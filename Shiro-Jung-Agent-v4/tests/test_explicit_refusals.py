"""Model-independent refusal parsing and genuinely different verified options."""
import math
import unittest
from unittest.mock import patch
import test_system as fixtures
from test_system import ScriptedModel
from sushi_budgeteer.agent import BudgeteerAgent
from sushi_budgeteer.extraction import _sanitize_extraction
from sushi_budgeteer.state import BudgeteerState
from sushi_budgeteer.service import MenuService
from sushi_budgeteer.database import records
from sushi_budgeteer.tools import _run_filter
from sushi_budgeteer.dietary import hard_excluded


class ExplicitRefusalTest(unittest.TestCase):
    setUp=fixtures.CatalogTest.setUp
    tearDown=fixtures.CatalogTest.tearDown

    def test_refusals_override_wrong_model_dislikes_in_every_question_context(self):
        for message,target in [('ไม่กินหมู','หมู'),('ไม่ทานของดิบ','ดิบ'),('งดไก่','ไก่'),
                               ('ห้ามมีเนื้อหมู','หมู'),('ไม่กินเกี๊ยวซ่าหมู','เกี๊ยวซ่าหมู')]:
            for context in (None,'drinks','dessert_selection'):
                with self.subTest(message=message,context=context):
                    result=_sanitize_extraction({'dislikes':[target],'hard_exclude_keywords':[]},context,message)
                    self.assertIn(target,result['hard_exclude_keywords'])
                    self.assertNotIn(target,result['dislikes'])

    def test_soft_wording_does_not_create_hard_exclusion(self):
        for message in ('ไม่ค่อยชอบหมู','ไม่ชอบหมู','ไม่ค่อยชอบกินหมู'):
            result=_sanitize_extraction({'dislikes':[],'hard_exclude_keywords':['pork']},None,message)
            self.assertIn('หมู',result['dislikes'])
            self.assertEqual(result['hard_exclude_keywords'],[])

    def test_multiple_refusals_preserve_allergy_and_positive_preferences(self):
        result=_sanitize_extraction({'allergens':['crustacean'],'dislikes':['หมู','ไก่'],
                                    'preferred_keywords':['แซลมอน']},None,
                                   'งบ 1500 บาท 2 คน แพ้กุ้ง ชอบแซลมอน ไม่กินหมูและไก่ ไม่ทานของดิบ')
        self.assertEqual(set(result['hard_exclude_keywords']),{'หมู','ไก่','ดิบ'})
        self.assertEqual(result['allergens'],['crustacean'])
        self.assertEqual(result['preferred_keywords'],['แซลมอน'])
        self.assertFalse(result['dislikes'])

    def test_hard_upgrade_removes_previous_soft_alias_without_relaxing_old_restrictions(self):
        state=BudgeteerState(dislikes=['pork','ปลาหมึก'],hard_exclude_keywords=['ดิบ'])
        state.update_from_extraction(_sanitize_extraction({'dislikes':['หมู']},None,'ไม่กินหมู'))
        self.assertEqual(state.dislikes,['ปลาหมึก'])
        self.assertEqual(set(state.hard_exclude_keywords),{'ดิบ','หมู'})

    def test_soft_wording_does_not_undo_an_existing_hard_constraint(self):
        state=BudgeteerState(hard_exclude_keywords=['หมู'])
        state.update_from_extraction(_sanitize_extraction({},None,'ไม่ค่อยชอบหมู'))
        self.assertEqual(state.hard_exclude_keywords,['หมู'])
        self.assertEqual(state.dislikes,[])

    def test_end_to_end_incorrect_extraction_still_removes_pork_from_both_sets(self):
        agent=BudgeteerAgent(llm=ScriptedModel([],{'budget':1500,'num_people':2,
            'allergens':['crustacean'],'preferred_keywords':['แซลมอน'],'dislikes':['หมู']}),consumer_flow=True)
        answer=agent.chat('งบ 1500 บาท 2 คน แพ้กุ้ง ชอบแซลมอน ไม่กินหมู')
        self.assertIn('- ไม่กิน: หมู',answer)
        self.assertEqual(agent.state.hard_exclude_keywords,['หมู'])
        self.assertNotIn('หมู',agent.state.dislikes)
        agent.chat('ยืนยันข้อมูลและจัดชุด')
        self.assertFalse(agent.last_options)
        agent.chat('ดูชุดจำลองจากข้อมูลเมนู')
        self.assertTrue(agent.last_options)
        catalog={row['item_id']:row for row in records()}
        for option in agent.last_options:
            self.assertLessEqual(option['total_price'],1500)
            self.assertTrue(all(not hard_excluded(catalog[row['item_id']],['หมู']) for row in option['selected']))

    def test_raw_and_chicken_refusals_filter_actual_catalog(self):
        for phrase,target in [('ไม่ทานของดิบ','ดิบ'),('งดไก่','ไก่')]:
            constraints=_sanitize_extraction({'dislikes':[target]},None,phrase)['hard_exclude_keywords']
            safe,blocked,_=_run_filter(records(),hard_exclude_keywords=constraints)
            self.assertTrue(blocked)
            self.assertTrue(all(not hard_excluded(row,constraints) for row in safe))

    def test_unknown_food_refusal_is_preserved_and_negated_refusal_is_not_added(self):
        self.assertEqual(_sanitize_extraction({},None,'ห้ามซอสพิเศษ')['hard_exclude_keywords'],['ซอสพิเศษ'])
        self.assertFalse(_sanitize_extraction({},None,'ไม่ได้งดไก่')['hard_exclude_keywords'])
        self.assertEqual(_sanitize_extraction({},None,'ไม่กินหมู ไม่แพ้อาหาร')['hard_exclude_keywords'],['หมู'])

    def test_alternative_changes_thirty_percent_food_names_and_keeps_fixed_extras(self):
        service=MenuService()
        first=service.build(budget=1500,max_items=60,spend_ratio=.8,
                            hard_exclude_keywords=['หมู'],drink_selection=['น้ำส้ม'],drink_quantity=2)
        self.assertEqual(first['status'],'candidate')
        other=service.alternative(first['result_id'])
        self.assertEqual(other['status'],'candidate')
        a,b=first['result'],other['result']
        food=lambda r:{row['item_id'] for row in r['selected'] if row['category'] not in {'เครื่องดื่ม','ของหวาน'}}
        self.assertGreaterEqual(len(food(a)-food(b)),math.ceil(.3*len(food(a))))
        self.assertGreaterEqual(b['alternative_comparison']['changed_ratio'],.3)
        self.assertEqual(a['constraints']['hard_exclude_keywords'],b['constraints']['hard_exclude_keywords'])
        extras=lambda r:[row for row in r['selected'] if row['category']=='เครื่องดื่ม']
        self.assertEqual(extras(a),extras(b))
        self.assertTrue(service.verify(other['result_id'])['passed'])

    def test_alternative_returns_unavailable_when_no_different_safe_menu_exists(self):
        service=MenuService()
        ids=[row['item_id'] for row in records() if row['item_id']!='S001']
        first=service.build(budget=80,max_items=1,excluded_item_ids=ids)
        self.assertEqual(first['status'],'candidate')
        self.assertEqual(service.alternative(first['result_id'])['status'],'unavailable')
