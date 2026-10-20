"""Consumer catalog browsing, extras selection and end-of-conversation behavior."""
import os
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
import test_system as fixtures
from test_system import ScriptedModel
from sushi_budgeteer.agent import BudgeteerAgent
from sushi_budgeteer.database import ROOT
from sushi_budgeteer.presentation import CLOSING_MESSAGE


class ExtrasCheckoutTest(unittest.TestCase):
    setUp=fixtures.CatalogTest.setUp
    tearDown=fixtures.CatalogTest.tearDown

    def ready(self):
        agent=BudgeteerAgent(llm=ScriptedModel([],{'budget':500,'num_people':2,'wants_dessert':False}),consumer_flow=True)
        summary=agent.chat('500บาท 2คน ไม่รับของหวาน')
        self.assertNotIn('80%',summary)
        answer=agent.chat('ยืนยันว่าไม่แพ้และจัดชุด')
        self.assertNotIn('%',answer)
        self.assertEqual(agent.last_options[0]['constraints']['spend_ratio'],.8)
        return agent

    def test_repeated_dessert_or_drink_requests_show_real_menu_without_model(self):
        agent=BudgeteerAgent(llm=ScriptedModel([],{}),consumer_flow=True)
        for message, name in [('รับของหวาน','วาราบิโมจิ'),('เมนูของหวาน','วาราบิโมจิ'),
                              ('เมนูน้ำ','โค้ก'),('รับน้ำครับ','น้ำเปล่า')]:
            answer=agent.chat(message)
            self.assertIn(name,answer)
            self.assertIn('บาท',answer)
            self.assertEqual(agent.last_run['model_calls'],0)

    def test_extra_selection_replans_with_original_memory_and_prices(self):
        agent=self.ready()
        agent.open_extras('ของหวาน')
        answer=agent.choose_extra('D002',2)
        self.assertIn('วาราบิโมจิ',answer)
        self.assertEqual(agent.state.dessert_selection,['วาราบิโมจิ'])
        self.assertEqual(agent.state.dessert_quantity,2)
        self.assertEqual(agent.state.budget,500)
        self.assertTrue(agent.last_options)
        self.assertEqual(agent.last_run['model_calls'],0)
        agent.open_extras('เครื่องดื่ม')
        answer=agent.choose_extra('B002',1)
        self.assertIn('โค้ก',answer)
        self.assertIn('วาราบิโมจิ',answer)
        self.assertEqual(agent.state.drink_quantities,{'โค้ก':1})
        self.assertTrue(all(r['total_price']<=400 for r in agent.last_options))

    def test_final_confirmation_closes_until_reset(self):
        agent=self.ready()
        answer=agent.chat('1')
        self.assertTrue(agent.order_closed)
        self.assertIn(CLOSING_MESSAGE,answer)
        self.assertEqual(agent.chat('เมนูน้ำ'),CLOSING_MESSAGE)
        self.assertEqual(agent.last_run['model_calls'],0)
        agent.reset_order()
        self.assertFalse(agent.order_closed)
        self.assertIsNone(agent.state.budget)
        self.assertEqual(agent.last_options,[])
        self.assertIn('น้ำเปล่า',agent.chat('เมนูน้ำ'))

    def test_catalog_respects_medical_allergies_and_current_mode(self):
        agent=BudgeteerAgent(llm=ScriptedModel([],{}),consumer_flow=True)
        agent.state.allergens=['milk']
        self.assertEqual(agent.extra_items('ของหวาน'),[])
        agent.data_mode='simulation'
        safe=agent.extra_items('ของหวาน')
        self.assertTrue(safe)
        self.assertTrue(all('milk' not in r['allergens_verified'].split(';') for r in safe))
        agent.extra_category='ของหวาน'
        agent.data_mode='strict'
        self.assertIn('เลือกไม่ได้',agent.choose_extra(safe[0]['item_id'],1))
        self.assertFalse(agent.state.wants_dessert)

    def test_ui_picker_price_quantity_and_final_reset(self):
        agent=self.ready()
        with patch.dict(os.environ,{'OPENAI_API_KEY':'extras-ui-placeholder'}):
            page=AppTest.from_file(str(ROOT/'app.py'))
            page.session_state['agent']=agent
            page.session_state['_agent_key']=('extras-ui-placeholder','gpt-4o-mini','strict')
            page.session_state['chat_history']=[]
            page.run(timeout=30)
            page.button(key='browse_ของหวาน').click().run()
            self.assertFalse(page.exception)
            self.assertEqual(len(page.selectbox),1)
            self.assertIn('40.00 บาท',str(page.selectbox[0].options))
            page.selectbox[0].select('D002')
            page.number_input[0].set_value(2)
            next(b for b in page.button if b.label=='เลือกเมนูนี้').click().run(timeout=30)
            self.assertFalse(page.exception)
            self.assertEqual(agent.state.dessert_quantity,2)
            page.button(key='choose_0').click().run()
            self.assertFalse(page.exception)
            self.assertTrue(agent.order_closed)
            self.assertTrue(page.chat_input[0].disabled)
            self.assertFalse(any(b.key=='choose_0' for b in page.button))
            page.button(key='new_order').click().run()
            self.assertFalse(page.exception)
            self.assertFalse(agent.order_closed)
            self.assertFalse(page.chat_input[0].disabled)


if __name__=='__main__': unittest.main()
