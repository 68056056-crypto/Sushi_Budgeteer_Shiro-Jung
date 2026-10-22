"""Regressions from instructor review; real catalog/MCP/OPA, explicitly scripted model."""
import copy
import csv
import io
import sqlite3
import unittest
from pathlib import Path
import test_system as fixtures
from test_system import ScriptedModel
from sushi_budgeteer.agent import BudgeteerAgent
from sushi_budgeteer.database import ROOT, records, import_csv, catalog_revision
from sushi_budgeteer.dietary import hard_excluded
from sushi_budgeteer.tools import _run_filter
from sushi_budgeteer.opa import evaluate
from sushi_budgeteer.service import MenuService
from sushi_budgeteer.optimizer import dp_knapsack, score_item
from scripts.benchmark import metric, objective_key


class ReviewTest(unittest.TestCase):
    setUp=fixtures.CatalogTest.setUp
    tearDown=fixtures.CatalogTest.tearDown

    def test_pork_does_not_exclude_squid_or_octopus(self):
        menu={row['item_id']:row for row in records()}
        self.assertTrue(hard_excluded(menu['F001'],['หมู']))
        self.assertFalse(hard_excluded(menu['S004'],['หมู']))
        self.assertFalse(hard_excluded(menu['S020'],['หมู']))
        safe,_,_=_run_filter(list(menu.values()),hard_exclude_keywords=['หมู'])
        self.assertIn('S004',{row['item_id'] for row in safe})
        self.assertNotIn('F001',{row['item_id'] for row in safe})

    def test_raw_does_not_exclude_pudding_or_cooked_eel_and_octopus(self):
        menu={row['item_id']:row for row in records()}
        for word in ('ดิบ','ของดิบ','raw'):
            for key in ('D004','S003','S020'):
                self.assertFalse(hard_excluded(menu[key],[word]),(word,key))
            self.assertTrue(hard_excluded(menu['S001'],[word]))

    def test_unreviewed_dietary_tags_fail_closed(self):
        row={**records()[0],'dietary_status':'unknown','dietary_tags':''}
        self.assertTrue(hard_excluded(row,['ดิบ']))
        self.assertTrue(hard_excluded(row,['หมู']))

    def test_uni_is_echinoderm_not_mollusc_and_still_unknown(self):
        row=next(row for row in records() if row['item_id']=='S007')
        self.assertEqual(set(row['allergen_tags'].split(';')),{'echinoderm','seafood'})
        self.assertEqual(row['allergen_status'],'unknown')
        self.assertEqual(row['allergen_source_url'],'')
        safe,_,_=_run_filter([row],allergens=['seafood'])
        self.assertEqual(safe,[])

    def test_legacy_schema_migration_preserves_prices_and_provenance(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE menu SET price_baht=77.25,allergen_status='confirmed',allergen_source_url='https://example.org/fixture',checked_at='2026-10-01' WHERE item_id='S001'")
            conn.execute('ALTER TABLE menu RENAME COLUMN allergen_tags TO allergens_verified')
            conn.execute('ALTER TABLE menu DROP COLUMN dietary_tags')
            conn.execute('ALTER TABLE menu DROP COLUMN dietary_status')
        row=records()[0]
        self.assertEqual(row['price_baht'],77.25)
        self.assertEqual(row['allergen_status'],'confirmed')
        self.assertEqual(row['allergen_source_url'],'https://example.org/fixture')
        self.assertIn('raw',row['dietary_tags'].split(';'))
        self.assertNotIn('allergens_verified',row)

    def test_partial_schema_migration_recovers_without_losing_menu(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute('ALTER TABLE menu DROP COLUMN dietary_status')
        self.assertEqual(len(records()),42)
        self.assertEqual(records()[0]['dietary_status'],'reviewed_dataset')

    def test_custom_menu_is_not_assumed_to_have_reviewed_dietary_tags(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE menu SET description_th='custom recipe' WHERE item_id='S001'")
            conn.execute('ALTER TABLE menu DROP COLUMN dietary_tags')
            conn.execute('ALTER TABLE menu DROP COLUMN dietary_status')
        row=records()[0]
        self.assertEqual(row['dietary_status'],'')
        self.assertTrue(hard_excluded(row,['ดิบ']))

    def test_legacy_csv_column_is_read_without_claiming_confirmation(self):
        path=Path(self.tmp.name)/'legacy.csv'
        path.write_text('item_id,name_th,category,price_baht,allergens_verified\nx,fixture,food,1,egg\n')
        import_csv(path)
        self.assertEqual(records()[0]['allergen_tags'],'egg')
        self.assertEqual(records()[0]['allergen_status'],'unknown')

    def test_consumer_confirmation_and_replan_are_model_selected(self):
        model=ScriptedModel([('filter_menu',{}),('build_set',{'budget':99999,'allergens':['egg']}),('verify_current',{})],
                            {'budget':1000,'num_people':2,'preferred_keywords':['แซลมอน']})
        agent=BudgeteerAgent(llm=model,consumer_flow=True)
        agent.chat('1000 บาท 2 คน ชอบแซลมอน ไม่แพ้')
        self.assertTrue(agent.pending_confirmation)
        self.assertEqual(len(model.steps),3)
        agent.chat('ยืนยันข้อมูลและจัดชุด')
        self.assertEqual(agent.last_run['model_calls_by_phase']['tool_selection'],3)
        build=next(step for step in agent.last_trace if step['tool']=='build_set')
        self.assertEqual(build['route'],'model_selected')
        self.assertEqual(build['arguments']['budget'],1000)
        self.assertEqual(build['arguments']['allergens'],[])
        self.assertFalse(any(step.get('fallback') for step in agent.last_trace))
        self.assertEqual(len(agent.last_options),2)
        model.extraction={'budget_delta':100}
        model.steps=[('build_set',{}),('verify_current',{})]
        agent.chat('เพิ่มงบ 100 บาท')
        self.assertEqual(agent.state.budget,1100)
        self.assertIn('แซลมอน',agent.state.preferred_keywords)
        self.assertEqual(agent.last_run['model_calls_by_phase']['tool_selection'],2)
        self.assertTrue(all(step.get('route')=='model_selected' for step in agent.last_trace))
        self.assertTrue(agent.last_run['final_recheck']['passed'])

    def test_rego_intersects_raw_allergens_even_with_false_python_flag(self):
        service=MenuService()
        built=service.build(budget=300)
        facts=service.verify(built['result_id'])['policy_input']
        facts.update(python_issues=[],data_mode='simulation',user_allergens=['egg'])
        facts['lines'][0].update(allergen_tags=['egg'],allergen_blocked=False)
        decision=evaluate(facts)
        self.assertIn('allergen_conflict',decision['deny_reasons'])

    def test_rego_intersects_raw_dietary_tags_even_with_false_python_flag(self):
        service=MenuService()
        built=service.build(budget=300)
        facts=service.verify(built['result_id'])['policy_input']
        facts.update(python_issues=[],excluded_dietary_tags=['raw'])
        facts['lines'][0].update(dietary_tags=['raw'],hard_excluded=False)
        self.assertIn('hard_exclusion',evaluate(facts)['deny_reasons'])

    def test_benchmark_reports_full_budget_and_target_separately(self):
        items=[{'item_id':'A','price_baht':40,'score':5,'category':'food','name_th':'fixture'}]
        chosen=dp_knapsack(items,80,max_items=60,min_items=1,objective='budget',diversity=True)
        result=metric(chosen,items,100,80,[],0)
        self.assertEqual(result['share_of_full_budget'],0.8)
        self.assertEqual(result['share_of_food_target'],1)
        self.assertEqual(result['diminishing_score'],7.5)
        self.assertEqual(result['full_budget_remaining_baht'],20)
        self.assertEqual(objective_key(result),(1,7.5,80))


if __name__=='__main__':
    unittest.main()
