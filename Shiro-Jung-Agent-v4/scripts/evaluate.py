"""Evaluate 40 gold scenarios over real MCP; optional live LLM mode never fakes results."""
from __future__ import annotations
import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from sushi_budgeteer.agent import BudgeteerAgent
from sushi_budgeteer.database import records, catalog_revision
from sushi_budgeteer.policy import validate_result
from sushi_budgeteer.telemetry import redact


def percentile(values,p):
    if not values:return None
    ordered=sorted(values);return ordered[min(len(ordered)-1,round((len(ordered)-1)*p))]

def expected_constraints(args):
    return {'budget':300,'allergens':[],'dislikes':[],'preferred_keywords':[],
        'hard_exclude_keywords':[],'must_include_keywords':[], 'min_items':1,'max_items':20,
        'num_people':1,'drink_selection':[],'drink_quantity':None,
        'drinks_separate_from_budget':False,'include_dessert':False,
        'dessert_selection':[],'dessert_quantity':None,**args}

async def offline(cases):
    outcomes=[]
    for mode in ['strict','simulation']:
        subset=[x for x in cases if x['data_mode']==mode]
        if not subset:continue
        env={'SUSHI_DATA_MODE':mode}
        for name in ['SUSHI_DB_PATH','SUSHI_OPA_BINARY']:
            if os.getenv(name):env[name]=os.environ[name]
        params=StdioServerParameters(command=sys.executable,args=[str(ROOT/'mcp_server.py')],cwd=str(ROOT),env=env)
        async with stdio_client(params) as (r,w):
            async with ClientSession(r,w) as session:
                await session.initialize()
                for case in subset:
                    start=time.perf_counter();calls=0;safety=False;decision=None
                    try:
                        if case['expected']=='clarification':
                            result=await session.call_tool('clarify',{'missing':[case['missing_field']]});calls+=1
                            payload=json.loads(result.content[0].text)
                            actual='clarification' if not result.isError and payload.get('questions') else 'error'
                        else:
                            result=await session.call_tool('build_set',case['arguments']);calls+=1
                            if result.isError:
                                # Expected rejections must be explicit input errors, not missing infrastructure.
                                actual='rejected' if any(x in result.content[0].text for x in ['จำนวน','งบ','ไม่พบตัวเลือก','validation error']) else 'error'
                            else:
                                payload=json.loads(result.content[0].text);decision=payload.get('policy_decision')
                                if payload.get('status')=='candidate':
                                    verify=await session.call_tool('verify_set',{'result_id':payload['result_id']});calls+=1
                                    checked=json.loads(verify.content[0].text);decision=checked.get('policy_decision')
                                    actual='recommendation' if not verify.isError and checked.get('passed') else 'blocked'
                                    safety=actual=='recommendation' and not decision.get('allow',False)
                                else: actual='blocked'
                        success=actual==case['expected'] and not safety
                        # OPA failures never count as successful handling of a business constraint.
                        if decision and 'opa_unavailable_or_invalid' in decision.get('deny_reasons',[]):success=False
                        outcomes.append({'id':case['id'],'expected':case['expected'],'actual':actual,
                            'success':success,'safety_violation':safety,'tool_calls':calls,
                            'elapsed_ms':round((time.perf_counter()-start)*1000,3),'policy_decision':decision})
                    except Exception as exc:
                        outcomes.append({'id':case['id'],'success':False,'actual':'error','error_type':type(exc).__name__,
                            'tool_calls':calls,'elapsed_ms':round((time.perf_counter()-start)*1000,3),'safety_violation':False})
    return outcomes

def live(cases,args):
    outcomes=[]
    for case in cases:
        if case['expected']=='rejected':continue # Input API rejection cases belong to the offline layer.
        agent=BudgeteerAgent();agent.data_mode=case['data_mode']
        start=time.perf_counter()
        for message in case['messages']:answer=agent.chat(message)
        result=agent.state.last_result;report=agent.run_report()
        actual='recommendation' if result else 'no_recommendation'
        safety=False
        if result:
            # Use GOLD constraints, not just model-extracted state, to catch extraction omissions.
            previous=os.environ.get('SUSHI_DATA_MODE')
            os.environ['SUSHI_DATA_MODE']=case['data_mode']
            try: safety=not validate_result(result,records(),expected_constraints(case['arguments']))['passed']
            finally:
                if previous is None:os.environ.pop('SUSHI_DATA_MODE',None)
                else:os.environ['SUSHI_DATA_MODE']=previous
        elif any(x.get('tool')=='clarify' and not x.get('error') for x in agent.last_trace):actual='clarification'
        elif any(x.get('status')=='requires_clarification' for x in agent.last_trace):actual='blocked'
        success=actual==case['expected'] and not safety
        if case['expected']=='clarification':
            success=success and any(x.get('arguments',{}).get('missing')==[case['missing_field']] for x in agent.last_trace)
        usage=report['usage'];complete=report['token_usage_complete']
        cost=None
        if complete and args.input_usd_per_million is not None and args.output_usd_per_million is not None:
            cost=(usage['input_tokens']*args.input_usd_per_million+usage['output_tokens']*args.output_usd_per_million)/1e6
        outcomes.append({'id':case['id'],'expected':case['expected'],'actual':actual,'success':success,
            'safety_violation':safety,'elapsed_ms':round((time.perf_counter()-start)*1000,3),
            'tool_calls':report['tool_calls'],'estimated_cost_usd':cost,'run':report})
    return outcomes

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',choices=['offline','live'],default='offline')
    p.add_argument('--limit',type=int,default=40)
    p.add_argument('--input-usd-per-million',type=float)
    p.add_argument('--output-usd-per-million',type=float)
    args=p.parse_args()
    if not 1<=args.limit<=40:p.error('--limit must be 1–40')
    destination=ROOT/'artifacts'/f'{args.mode}-evaluation.json';destination.parent.mkdir(exist_ok=True)
    base={'created_at':datetime.now(timezone.utc).isoformat(),'mode':args.mode,'catalog_revision':catalog_revision(),
        'model_source':'live OpenAI' if args.mode=='live' else 'no model; real MCP/SQLite/OPA',
        'scope':'single-turn gold scenarios; multi-turn behavior is covered separately by regression tests'}
    if args.mode=='live' and not (os.getenv('OPENAI_API_KEY') or os.getenv('SUSHI_OPENAI_API_KEY')):
        report={**base,'status':'blocked_missing_credentials','executed_cases':0,'metrics':None,
            'action':'Set SUSHI_OPENAI_API_KEY securely in environment settings or OPENAI_API_KEY in local .env.'}
        destination.write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2));return 2
    cases=json.loads((ROOT/'evaluation'/'cases.json').read_text())[:args.limit]
    outcomes=asyncio.run(offline(cases)) if args.mode=='offline' else live(cases,args)
    latencies=[x['elapsed_ms'] for x in outcomes]
    recommendations=[x for x in outcomes if x['actual']=='recommendation']
    clarification=[x for x in outcomes if x['expected']=='clarification']
    report={**base,'status':'completed','executed_cases':len(outcomes),
        'metrics':{'success_rate':sum(x['success'] for x in outcomes)/len(outcomes),
         'safety_violation_rate_among_recommendations':sum(x['safety_violation'] for x in recommendations)/len(recommendations) if recommendations else None,
         'expected_clarification_success_rate':sum(x['success'] for x in clarification)/len(clarification) if clarification else None,
         'latency_ms_p50':percentile(latencies,.5),'latency_ms_p95':percentile(latencies,.95),
         'mean_tool_calls':statistics.mean(x['tool_calls'] for x in outcomes)},'cases':outcomes}
    destination.write_text(json.dumps(redact(report),ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='cases'},ensure_ascii=False,indent=2))
    return 0 if all(x['success'] for x in outcomes) else 1

if __name__=='__main__':sys.exit(main())
