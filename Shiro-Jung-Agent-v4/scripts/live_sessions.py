"""Capture real model traces across turns. Exits blocked without configured credentials."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from sushi_budgeteer.agent import BudgeteerAgent
from sushi_budgeteer.database import records
from sushi_budgeteer.policy import validate_result
from sushi_budgeteer.telemetry import redact
from evaluate import expected_constraints

def main():
    destination=ROOT/'artifacts'/'live-sessions.json';destination.parent.mkdir(exist_ok=True)
    report={'created_at':datetime.now(timezone.utc).isoformat(),'model_source':'live OpenAI','sessions':[]}
    if not (os.getenv('OPENAI_API_KEY') or os.getenv('SUSHI_OPENAI_API_KEY')):
        report.update(status='blocked_missing_credentials',executed_turns=0)
        destination.write_text(json.dumps(report,indent=2));print('Blocked: configure API key securely; no live model calls executed.');return 2
    for scenario in json.loads((ROOT/'evaluation'/'sessions.json').read_text()):
        agent=BudgeteerAgent();agent.data_mode=scenario['mode'];turns=[]
        for gold in scenario['turns']:
            agent.chat(gold['message']);result=agent.state.last_result
            run=agent.run_report()
            constraints=expected_constraints({'budget':gold['budget'],
                'allergens':gold.get('allergens',[]),'hard_exclude_keywords':gold.get('hard_exclude_keywords',[])})
            # Gold checks only constraints explicitly stipulated by this multi-turn scenario.
            if result:
                trusted={**result['constraints'],**{key:constraints[key] for key in ['budget','allergens','hard_exclude_keywords']}}
                checked=validate_result(result,records(),trusted)
                success=gold['expected']=='recommendation' and checked['passed']
            else:
                # A provider failure is not successful constraint handling.
                success=gold['expected']=='blocked' and any(x.get('status')=='requires_clarification' or x.get('tool')=='clarify' for x in agent.last_trace)
            turns.append({'expected':gold['expected'],'gold_budget':gold['budget'],'success':success,'run':run})
        report['sessions'].append({'id':scenario['id'],'turns':turns})
    report['status']='completed';report['executed_turns']=sum(len(x['turns']) for x in report['sessions'])
    report['success_rate']=sum(t['success'] for s in report['sessions'] for t in s['turns'])/report['executed_turns']
    destination.write_text(json.dumps(redact(report),ensure_ascii=False,indent=2))
    print('Live sessions:',report['executed_turns'],'success rate:',report['success_rate'])
    return 0 if report['success_rate']==1 else 1
if __name__=='__main__':sys.exit(main())
