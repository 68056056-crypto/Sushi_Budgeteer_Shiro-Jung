"""Production-matched food DP vs greedy/random; metrics distinguish both budget denominators."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import statistics
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sushi_budgeteer.optimizer import menu_records, score_item, dp_knapsack, matches_any_keyword
from sushi_budgeteer.tools import _run_filter
from sushi_budgeteer.database import cents, catalog_revision, budget_target_cents
from sushi_budgeteer.optimization_config import (FOOD_OBJECTIVE, DIVERSITY, NEAR_BUDGET_PERCENT,
                                                INITIAL_SPEND_RATIO, MAX_FOOD_ITEMS, MAX_REPEAT)

ROOT=Path(__file__).resolve().parents[1]


def greedy(items, budget, by_density):
    """Recompute diminishing marginal scores; no item can exceed the shared repeat cap."""
    counts=Counter()
    remaining=cents(budget)
    selected=[]
    while len(selected)<MAX_FOOD_ITEMS:
        available=[row for row in items if counts[row['item_id']]<MAX_REPEAT
                   and cents(row['price_baht'])<=remaining]
        if not available:
            break
        def key(row):
            marginal=row['score']*0.5**counts[row['item_id']]
            return (marginal/max(cents(row['price_baht']),1) if by_density else marginal,
                    marginal,row['item_id'])
        row=max(available,key=key)
        selected.append(row)
        counts[row['item_id']]+=1
        remaining-=cents(row['price_baht'])
    return selected


def random_set(items, budget, seed):
    pool=[row for row in items for _ in range(MAX_REPEAT)]
    random.Random(seed).shuffle(pool)
    selected=[]
    remaining=cents(budget)
    for row in pool:
        cost=cents(row['price_baht'])
        if cost<=remaining and len(selected)<MAX_FOOD_ITEMS:
            selected.append(row)
            remaining-=cost
    return selected


def metric(selected, items, budget, target, preferences, elapsed_ms):
    counts=Counter(row['item_id'] for row in selected)
    catalog={row['item_id']:row for row in items}
    score=sum(catalog[key]['score']*sum(0.5**repeat for repeat in range(qty))
              for key,qty in counts.items())
    spend=sum(cents(row['price_baht']) for row in selected)
    near=spend*100>=cents(target)*NEAR_BUDGET_PERCENT
    return {'diminishing_score':round(score,6),'spend_baht':spend/100,
            'share_of_full_budget':spend/cents(budget),
            'share_of_food_target':spend/cents(target),
            'full_budget_remaining_baht':(cents(budget)-spend)/100,
            'in_target_band':near,
            'distinct_dishes':len(counts),
            'distinct_categories':len({row['category'] for row in selected}),
            'preference_matching_plates':sum(matches_any_keyword(row,preferences) for row in selected),
            'item_count':len(selected),'elapsed_ms':round(elapsed_ms,3),
            'feasible':bool(selected) and spend<=cents(target) and len(selected)<=MAX_FOOD_ITEMS
                       and max(counts.values())<=MAX_REPEAT}


def objective_key(metric):
    if metric['in_target_band']:
        return (1,metric['diminishing_score'],metric['spend_baht'])
    return (0,metric['spend_baht'],metric['diminishing_score'])


def run_benchmark(random_seeds=100):
    menu=[row for row in menu_records() if row['category'] not in {'เครื่องดื่ม','ของหวาน'}]
    cases=[]
    for budget in (300,1000,3000,6000):
        for preferences,exclusions in (([],[]),(['แซลมอน'],[]),(['ปลา'],['ดิบ'])):
            safe,_,_=_run_filter(menu,hard_exclude_keywords=exclusions)
            items=[{**row,'score':score_item(row,preferences)} for row in safe]
            target=budget_target_cents(budget,INITIAL_SPEND_RATIO)/100
            algorithms={}
            for name,fn in (
                ('dp',lambda:dp_knapsack(items,target,max_items=MAX_FOOD_ITEMS,min_items=1,
                     max_repeat_per_item=MAX_REPEAT,objective=FOOD_OBJECTIVE,diversity=DIVERSITY)),
                ('greedy_density',lambda:greedy(items,target,True)),
                ('greedy_score',lambda:greedy(items,target,False))):
                start=time.perf_counter()
                chosen=fn()
                algorithms[name]=metric(chosen,items,budget,target,preferences,(time.perf_counter()-start)*1000)
            runs=[]
            for seed in range(random_seeds):
                start=time.perf_counter()
                chosen=random_set(items,target,seed)
                runs.append({'seed':seed,**metric(chosen,items,budget,target,preferences,(time.perf_counter()-start)*1000)})
            algorithms['random']={'runs':runs,'means':{
                key:statistics.mean(row[key] for row in runs) for key in (
                    'diminishing_score','share_of_full_budget','share_of_food_target',
                    'distinct_dishes','distinct_categories','preference_matching_plates','elapsed_ms')},
                'feasible_rate':statistics.mean(row['feasible'] for row in runs)}
            cases.append({'full_budget':budget,'food_target':target,'preferences':preferences,
                          'hard_exclusions':exclusions,'candidate_count':len(items),'algorithms':algorithms})
    failures=[]
    feasibility=0
    for index,case in enumerate(cases):
        alg=case['algorithms']
        comparisons=[alg['greedy_density'],alg['greedy_score'],*alg['random']['runs']]
        if any(objective_key(row)>objective_key(alg['dp']) for row in comparisons):
            failures.append(index)
        feasibility+=sum(not row['feasible'] for row in [alg['dp'],*comparisons])
    summaries={}
    for name in ('dp','greedy_density','greedy_score','random'):
        entries=[case['algorithms'][name]['means'] if name=='random' else case['algorithms'][name] for case in cases]
        summaries[name]={key:statistics.mean(row[key] for row in entries) for key in (
            'diminishing_score','share_of_full_budget','share_of_food_target','distinct_dishes',
            'distinct_categories','preference_matching_plates','elapsed_ms')}
    return {'created_at':datetime.now(timezone.utc).isoformat(),'catalog_revision':catalog_revision(),
            'scope':'food-only educational catalog, no allergy; no LLM quality or restaurant-safety claim',
            'config':{'objective':FOOD_OBJECTIVE,'diversity':DIVERSITY,'spend_ratio':INITIAL_SPEND_RATIO,
                      'target_band_percent':NEAR_BUDGET_PERCENT,'max_items':MAX_FOOD_ITEMS,'repeat_cap':MAX_REPEAT,
                      'random_seeds':random_seeds},
            'summary':{'cases':len(cases),'random_runs':len(cases)*random_seeds,
                       'objective_dominance_failures':failures,'feasibility_failures':feasibility,
                       'algorithms':summaries},'cases':cases}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts'/'benchmark-production.json')
    parser.add_argument('--seeds',type=int,default=100,choices=range(1,1001))
    args=parser.parse_args()
    report=run_benchmark(args.seeds)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report['summary'],ensure_ascii=False,indent=2))
    return int(bool(report['summary']['objective_dominance_failures'] or report['summary']['feasibility_failures']))

if __name__=='__main__':
    sys.exit(main())
