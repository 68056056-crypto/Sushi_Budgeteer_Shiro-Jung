"""Consumer interactions with real MCP/SQLite/OPA; no live model calls."""
import copy
import os
import sqlite3
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from test_system import ScriptedModel, READY
import test_system as fixtures
from sushi_budgeteer.agent import BudgeteerAgent
from sushi_budgeteer.database import ROOT, records
from sushi_budgeteer.extraction import contextual_answer
from sushi_budgeteer.optimizer import parse_allergen_tags
from sushi_budgeteer.policy import validate_result
from sushi_budgeteer.presentation import ALLERGY_WARNING
from sushi_budgeteer.service import MenuService


class ConsumerFlowTest(unittest.TestCase):
    setUp=fixtures.CatalogTest.setUp
    tearDown=fixtures.CatalogTest.tearDown

    def recommend(self, **changes):
        model=ScriptedModel([('build_set',{}),('verify_current',{})],{**READY,**changes})
        agent=BudgeteerAgent(llm=model)
        answer=agent.chat('จัดชุดให้หน่อย')
        return agent,model,answer

    def test_two_distinct_options_keep_constraints_and_hide_diagnostics(self):
        agent,_,answer=self.recommend()
        self.assertEqual(len(agent.last_options),2)
        first,second=agent.last_options
        self.assertNotEqual({x['item_id'] for x in first['selected']},
                            {x['item_id'] for x in second['selected']})
        for result in agent.last_options:
            self.assertTrue(result['policy_decision']['allow'])
            self.assertLessEqual(result['total_price'],READY['budget'])
            for key in ('budget','allergens','dislikes','preferred_keywords','drink_selection','drink_quantity'):
                self.assertEqual(first['constraints'][key],result['constraints'][key])
        for internal in ('OPA','Python','DP:','allergen_status','ฐานข้อมูล'):
            self.assertNotIn(internal,answer)
        self.assertIn('\n\n**รวม ',answer)

    def test_followup_salmon_keeps_memory_and_skips_model_tool_loop(self):
        agent,model,_=self.recommend(dislikes=['หมึก'])
        model.extraction={'preferred_keywords':['แซลมอน'],'intent':'search'}
        model.steps=[('search_menu',{'keyword':'เซลมอน'})]
        answer=agent.chat('อยากกินเซลมอน')
        self.assertIn('แซลมอน',answer)
        self.assertEqual(agent.state.budget,READY['budget'])
        self.assertEqual(agent.state.num_people,READY['num_people'])
        self.assertEqual(agent.state.dislikes,['หมึก'])
        self.assertEqual(agent.state.drink_selection,READY['drink_selection'])
        self.assertEqual(agent.missing_fields(),[])
        self.assertEqual(agent.last_run['model_calls'],1)
        self.assertEqual(model.steps,[('search_menu',{'keyword':'เซลมอน'})])

    def test_simulated_allergy_filters_both_options_and_survives_replan(self):
        with patch.dict(os.environ,{'SUSHI_DATA_MODE':'simulation'}):
            agent,model,answer=self.recommend(allergens=['crustacean'],preferred_keywords=['แซลมอน'])
            self.assertEqual(len(agent.last_options),2)
            self.assertIn(ALLERGY_WARNING,answer)
            model.extraction={'preferred_keywords':['ไข่'],'intent':'optimize'}
            answer=agent.chat('อยากกินไข่ ใช้งบเดิม')
            self.assertEqual(agent.state.allergens,['crustacean'])
            self.assertIn(ALLERGY_WARNING,answer)
            for option in agent.last_options:
                for row in option['selected']:
                    self.assertNotIn('crustacean',parse_allergen_tags(row['allergens_verified']))

    def test_strict_allergy_does_not_recommend_unknown_ingredients(self):
        agent,_,answer=self.recommend(allergens=['crustacean'])
        self.assertIsNone(agent.state.last_result)
        self.assertEqual(agent.last_options,[])
        self.assertIn('ข้อมูลส่วนผสม',answer)
        self.assertIn(ALLERGY_WARNING,answer)

    def test_number_selects_without_model_and_can_replan_after_confirmation(self):
        agent,model,_=self.recommend()
        selected=agent.last_options[1]['result_id']
        answer=agent.chat('2')
        self.assertEqual(agent.confirmed_option,1)
        self.assertEqual(agent.state.last_result['result_id'],selected)
        self.assertEqual(agent.last_run['model_calls'],0)
        self.assertIn('ยังไม่ได้ส่งคำสั่งซื้อ',answer)
        model.extraction={'preferred_keywords':['แซลมอน'],'intent':'optimize'}
        agent.chat('เปลี่ยนเป็นแซลมอน')
        self.assertIsNone(agent.confirmed_option)
        self.assertEqual(agent.state.budget,READY['budget'])
        self.assertIn('แซลมอน',agent.state.preferred_keywords)

    def test_confirmation_rejects_catalog_or_mode_change(self):
        agent,_,_=self.recommend()
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE menu SET price_baht=price_baht+5 WHERE item_id='S001'")
        self.assertIn('เปลี่ยนแล้ว',agent.select_option(0))
        self.assertEqual(agent.last_options,[])
        agent,_,_=self.recommend()
        agent.data_mode='simulation'
        self.assertIn('เปลี่ยนแล้ว',agent.select_option(0))
        self.assertIsNone(agent.confirmed_option)

    def test_one_feasible_food_does_not_invent_second_option(self):
        service=MenuService()
        with sqlite3.connect(self.db) as conn:
            conn.execute("DELETE FROM menu WHERE item_id!='S001'")
        built=service.build(budget=300)
        self.assertEqual(built['status'],'candidate')
        self.assertEqual(service.alternative(built['result_id'])['status'],'unavailable')
        self.assertTrue(service.verify(built['result_id'])['passed'])

    def test_consumer_ui_selection_reset_and_mode_change(self):
        agent,_,answer=self.recommend()
        with patch.dict(os.environ,{'OPENAI_API_KEY':'ui-test-placeholder'}):
            page=AppTest.from_file(str(ROOT/'app.py'))
            page.session_state['agent']=agent
            page.session_state['_agent_key']=('ui-test-placeholder','gpt-4o-mini','strict')
            page.session_state['chat_history']=[{'role':'assistant','content':answer}]
            page.run(timeout=30)
            self.assertFalse(page.exception)
            self.assertEqual(len(page.dataframe),0)
            self.assertEqual(len(page.json),0)
            self.assertEqual(len(page.toggle),0)
            page.button(key='choose_1').click().run()
            self.assertFalse(page.exception)
            self.assertEqual(agent.confirmed_option,1)
            page.selectbox[0].select('simulation').run()
            self.assertFalse(page.exception)
            self.assertEqual(agent.last_options,[])
            self.assertEqual(agent.state.budget,READY['budget'])
            next(b for b in page.button if b.label=='รีเซ็ตบทสนทนา').click().run()
            self.assertIsNone(agent.state.budget)
            self.assertEqual(agent.state.preferred_keywords,[])

    def test_excluded_food_is_checked_against_trusted_constraints(self):
        service=MenuService()
        built=service.build(budget=300)
        result=copy.deepcopy(service.results[built['result_id']])
        result['constraints']['excluded_item_ids']=[result['selected'][0]['item_id']]
        self.assertFalse(validate_result(result,records())['passed'])

    def test_short_answers_do_not_erase_memory_or_swallow_extra_allergy(self):
        self.assertEqual(contextual_answer('dessert','ไม่รับของหวาน'),{'wants_dessert':False})
        self.assertEqual(contextual_answer('drink_quantity','2'),{'drink_quantity':2})
        self.assertEqual(contextual_answer('drinks_budget_mode','รวมในงบ'),{'drinks_budget_mode':'within'})
        self.assertIsNone(contextual_answer('dessert','ไม่รับของหวาน แพ้กุ้งด้วย'))


if __name__=='__main__':
    unittest.main()
