"""Capture real consumer-flow sessions; never substitute scripted model evidence."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sushi_budgeteer.agent import BudgeteerAgent
from sushi_budgeteer.database import records
from sushi_budgeteer.policy import validate_result
from sushi_budgeteer.telemetry import redact
from sushi_budgeteer.restrictions import same_food
from sushi_budgeteer.dietary import requested_tags


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenarios',type=Path,default=ROOT/'evaluation'/'sessions.json')
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts'/'live-consumer-sessions.json')
    parser.add_argument('--require-model-selected',action='store_true',help='Fail unless real model-selected build and verify evidence exists')
    args=parser.parse_args()
    report={'created_at':datetime.now(timezone.utc).isoformat(),'consumer_flow':True,
            'model_source':'live OpenAI requested','source_commit':os.getenv('GITHUB_SHA'),
            'sessions':[],'executed_turns':0,'success_rate':0,'model_selected_recommendations':0,
            'scenario_file':args.scenarios.name,'live_llm_tested':False}
    if not (os.getenv('OPENAI_API_KEY') or os.getenv('SUSHI_OPENAI_API_KEY')):
        report.update(status='blocked_missing_credentials',live_llm_tested=False)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2))
        print('Blocked: configure API key securely; no live model calls executed.')
        return 2
    for scenario in json.loads(args.scenarios.read_text()):
        agent=BudgeteerAgent(consumer_flow=True)
        agent.data_mode=scenario['mode']
        turns=[]
        for gold in scenario['turns']:
            response=agent.chat(gold['message'])
            runs=[agent.run_report()]
            if agent.pending_confirmation:
                response=agent.chat('ยืนยันข้อมูลและจัดชุด')
                runs.append(agent.run_report())
            result=agent.state.last_result
            expected_mode=gold.get('expected_mode',scenario['mode'])
            if gold['expected']=='clarification':
                success=bool(agent.pending_meat_scope or agent.pending_confirmation or agent.state.last_asked_field)
            elif result:
                trusted={**result['constraints'],'budget':gold['budget'],
                         'allergens':gold.get('allergens',[]),
                         'hard_exclude_keywords':gold.get('hard_exclude_keywords',[])}
                checked=validate_result(result,records(),trusted,mode=expected_mode)
                success=gold['expected']=='recommendation' and checked['passed']
            else:
                # Transport/provider failures are never counted as successful safety handling.
                success=gold['expected']=='blocked' and any(
                    step.get('status')=='requires_clarification' or step.get('tool')=='clarify'
                    for step in agent.last_trace)
            hard=gold.get('hard_exclude_keywords',[])
            actual=agent.state.hard_exclude_keywords
            hard_state_ok=all(any(same_food(word,found) for found in actual)
                              or bool(requested_tags([word]) and set(requested_tags([word]))<=set(requested_tags(actual)))
                              for word in hard)
            success=(success and agent.data_mode==expected_mode and hard_state_ok
                     and agent.state.budget==gold['budget']
                     and set(gold.get('allergens',[]))<=set(agent.state.allergens))
            if gold.get('simulation_consent'):
                success=success and agent.allergy_simulation_consent
            selected={step['tool'] for step in agent.last_trace if step.get('route')=='model_selected'}
            turns.append({'message':gold['message'],'response':response,
                          'state':{'budget':agent.state.budget,'allergens':agent.state.allergens,
                                   'hard_exclude_keywords':agent.state.hard_exclude_keywords,
                                   'dislikes':agent.state.dislikes},
                          'expected':gold['expected'],'gold_budget':gold['budget'],
                          'success':success,'model_selected_build_and_verify':(success and gold['expected']=='recommendation'
                              and {'build_set','verify_set'}<=selected
                              and runs[-1].get('model_source')=='live'
                              and runs[-1].get('model_calls',0)>0),
                          'runs':runs})
        report['sessions'].append({'id':scenario['id'],'turns':turns})
    report.update(status='completed',live_llm_tested=any(
                      run.get('model_source')=='live' and run.get('model_calls',0)>0 for session in report['sessions'] for turn in session['turns'] for run in turn['runs']),
                  executed_turns=sum(len(turn['runs']) for session in report['sessions'] for turn in session['turns']))
    gold_turns=[turn for session in report['sessions'] for turn in session['turns']]
    report['success_rate']=sum(turn['success'] for turn in gold_turns)/len(gold_turns)
    report['model_selected_recommendations']=sum(turn['model_selected_build_and_verify'] for turn in gold_turns)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(redact(report),ensure_ascii=False,indent=2))
    print('Live consumer sessions:',len(report['sessions']),'success rate:',report['success_rate'])
    selected_ok=(not args.require_model_selected or (report['live_llm_tested'] and report['model_selected_recommendations']>0))
    return 0 if report['success_rate']==1 and selected_ok else 1

if __name__=='__main__':
    sys.exit(main())
