"""Compare exact DP, two greedy algorithms, and seeded random on identical feasible pools."""
from __future__ import annotations
from collections import Counter
from datetime import datetime,timezone
import json
from pathlib import Path
import random
import statistics
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sushi_budgeteer.optimizer import menu_records, score_item, dp_knapsack, random_baseline
from sushi_budgeteer.tools import _run_filter
from sushi_budgeteer.database import cents,catalog_revision

ROOT=Path(__file__).resolve().parents[1]

def greedy(items,budget,by_density):
    ordered=sorted(items,key=lambda x:((x['score']/max(cents(x['price_baht']),1)) if by_density else x['score'],x['score'],x['item_id']),reverse=True)
    selected=[];remaining=cents(budget)
    for item in ordered:
        cost=cents(item['price_baht'])
        if cost<=remaining and len(selected)<20:selected.append(item);remaining-=cost
    return selected

def metric(selected,budget,elapsed_ms):
    counts=Counter(x['item_id'] for x in selected)
    return {'score':round(sum(x['score'] for x in selected),3),
        'spend':sum(cents(x['price_baht']) for x in selected)/100,
        'budget_utilization':sum(cents(x['price_baht']) for x in selected)/cents(budget),
        'distinct_dishes':len(counts),'distinct_categories':len({x['category'] for x in selected}),
        'item_count':len(selected),'elapsed_ms':round(elapsed_ms,3),
        'feasible':bool(selected) and sum(cents(x['price_baht']) for x in selected)<=cents(budget) and len(selected)<=20 and max(counts.values())<=3}

def main():
    menu=[x for x in menu_records() if x['category'] not in {'เครื่องดื่ม','ของหวาน'}]
    cases=[]
    for budget in [100,180,300,500]:
        for preference,exclude in [([],[]),(['แซลมอน'],[]),(['ปลา'],['ดิบ'])]:
            safe,_,_=_run_filter(menu,hard_exclude_keywords=exclude)
            items=[{**x,'score':score_item(x,preference)} for x in safe]
            pool=[x for x in items for _ in range(3)]
            algorithms={}
            for name,fn in [('dp',lambda:dp_knapsack(items,budget,max_items=20,min_items=1)),
                ('greedy_density',lambda:greedy(pool,budget,True)),('greedy_score',lambda:greedy(pool,budget,False))]:
                start=time.perf_counter();selected=fn();algorithms[name]=metric(selected,budget,(time.perf_counter()-start)*1000)
            random_runs=[]
            for seed in range(100):
                start=time.perf_counter();selected=random_baseline(pool,budget,max_items=20,seed=seed)
                random_runs.append({'seed':seed,**metric(selected,budget,(time.perf_counter()-start)*1000)})
            values=[x['score'] for x in random_runs]
            algorithms['random']={'runs':random_runs,'score_mean':statistics.mean(values),
                'score_stdev':statistics.stdev(values),'score_standard_error':statistics.stdev(values)/10,
                'feasible_rate':sum(x['feasible'] for x in random_runs)/100}
            cases.append({'budget':budget,'preferences':preference,'hard_excludes':exclude,
                'candidate_count':len(items),'algorithms':algorithms})
    violations=[]
    for i,case in enumerate(cases):
        scores=case['algorithms'];dp=scores['dp']['score']
        if dp+1e-8<max(scores['greedy_density']['score'],scores['greedy_score']['score'],max(x['score'] for x in scores['random']['runs'])):
            violations.append(i)
    feasibility_failures=sum(not c['algorithms'][a]['feasible'] for c in cases for a in ['dp','greedy_density','greedy_score']) + sum(not r['feasible'] for c in cases for r in c['algorithms']['random']['runs'])
    report={'created_at':datetime.now(timezone.utc).isoformat(),'catalog_revision':catalog_revision(),
        'data':'unverified educational dataset; food only; no allergy constraint',
        'objective':'maximize score then actual spend; diversity is measured, not optimized',
        'shared_constraints':{'max_items':20,'min_items':1,'repeat_cap':3,'random_seeds':list(range(100))},
        'summary':{'cases':len(cases),'random_runs':len(cases)*100,'dp_score_dominance_failures':violations,'feasibility_failures':feasibility_failures,
            'mean_dp_score':statistics.mean(x['algorithms']['dp']['score'] for x in cases),
            'mean_random_score':statistics.mean(x['algorithms']['random']['score_mean'] for x in cases)},'cases':cases}
    output=ROOT/'artifacts'/'benchmark.json';output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report['summary'],indent=2))
    return 1 if violations or feasibility_failures else 0

if __name__=='__main__':sys.exit(main())
