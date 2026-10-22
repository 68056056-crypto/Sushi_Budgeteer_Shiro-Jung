"""Evaluate 40 offline gold scenarios over real MCP/SQLite/OPA; never call an LLM."""
from __future__ import annotations
import argparse
import asyncio
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
from sushi_budgeteer.database import records, catalog_revision
from sushi_budgeteer.telemetry import redact


def percentile(values,p):
    if not values:return None
    ordered=sorted(values);return ordered[min(len(ordered)-1,round((len(ordered)-1)*p))]

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

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',choices=['offline'],default='offline')
    p.add_argument('--limit',type=int,default=40)
    p.add_argument('--output',type=Path)
    args=p.parse_args()
    if not 1<=args.limit<=40:p.error('--limit must be 1–40')
    destination=args.output or ROOT/'artifacts'/f'{args.mode}-evaluation.json';destination.parent.mkdir(parents=True,exist_ok=True)
    base={'created_at':datetime.now(timezone.utc).isoformat(),'mode':args.mode,'catalog_revision':catalog_revision(),
        'model_source':'no model; real MCP/SQLite/OPA',
        'scope':'single-turn gold scenarios; multi-turn behavior is covered separately by regression tests'}
    cases=json.loads((ROOT/'evaluation'/'cases.json').read_text())[:args.limit]
    outcomes=asyncio.run(offline(cases))
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
