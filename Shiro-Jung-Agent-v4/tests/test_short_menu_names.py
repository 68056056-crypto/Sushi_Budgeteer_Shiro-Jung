"""Short names, omitted units, Unicode input and one-shot flavor clarification."""
import unittest
import os
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
import test_system as fixtures
from test_system import ScriptedModel
from sushi_budgeteer.database import records, ROOT
from sushi_budgeteer.extra_order import parse_order
from sushi_budgeteer.agent import BudgeteerAgent


class ShortNameParserTest(unittest.TestCase):
    setUp=fixtures.CatalogTest.setUp
    tearDown=fixtures.CatalogTest.tearDown

    def test_multiple_short_names_with_or_without_units(self):
        expected={'B004':2,'B001':1,'B005':2}
        for message in ('น้ำส้ม 2 ชาเขียว 1 น้ำเปล่า 2','น้ำส้ม2ชาเขียว1น้ำเปล่า2',
                        'น้ำส้ม 2 แก้ว ชาเขียว 1 แก้ว น้ำเปล่า 2 แก้ว',
                        'นํ้าส้ม ๒ ชาเขียว ๑ น้ำเปล่า ๒',
                        'น้ำส้ม\u200b 2, ชาเขียว 1 และ น้ำเปล่า 2 ครับ'):
            with self.subTest(message=message):
                result=parse_order(message,records())
                self.assertEqual(result['orders'],expected)
                self.assertFalse(result['ambiguous'])

    def test_multiple_short_dessert_names(self):
        for message in ('ชีสเค้ก 1 วาราบิ 1','ชีสเค้ก1วาราบิ1',
                        'ชีสเค้ก ๑ ชิ้น และ วาราบิ ๑ ชิ้น',
                        'ทาร์ตชีสเค้ก 1 วาราบิโมจิ 1'):
            with self.subTest(message=message):
                result=parse_order(message,records())
                self.assertEqual(result['orders'],{'D003':1,'D002':1})
                self.assertFalse(result['ambiguous'])

    def test_dessert_menu_context_and_warabi_spelling(self):
        for message in ('วาราบี 1 ชาเขียว 1','วาราบี 1 ชาเขียวไอศครีม 1'):
            result=parse_order(message,records(),category='ของหวาน')
            self.assertEqual(result['orders'],{'D002':1,'D001':1})
            self.assertFalse(result['ambiguous'])
        self.assertEqual(parse_order('ชาเขียว 1',records(),category='เครื่องดื่ม')['orders'],{'B001':1})

    def test_ice_cream_spellings_keep_quantity_without_guessing_flavor(self):
        for name in ('ไอศกรีม','ไอศครีม','ไอครีม','ไอติม'):
            for suffix in ('2',' 2 ชิ้น',' ๒ ถ้วย'):
                result=parse_order(name+suffix,records())
                self.assertEqual(result['ambiguous'][0]['quantity'],2)
                self.assertEqual(set(result['ambiguous'][0]['candidates']),{'D001','D005'})
        exact=parse_order('ไอศครีมชาเขียว 2',records())
        self.assertEqual(exact['orders'],{'D001':2})
        self.assertFalse(exact['ambiguous'])

    def test_no_partial_unknown_invalid_or_duplicate_orders(self):
        for message in ('น้ำส้ม2 แฟนต้า1','น้ำส้ม-2','น้ำส้ม2.5','น้ำส้ม0','น้ำส้ม61','น้ำส้ม1 น้ำส้ม2',
                        'ไอศครีม1 ไอครีม2'):
            self.assertIsNone(parse_order(message,records()),message)


class ShortNameCheckoutTest(unittest.TestCase):
    setUp=fixtures.CatalogTest.setUp
    tearDown=fixtures.CatalogTest.tearDown

    def ready(self):
        agent=BudgeteerAgent(llm=ScriptedModel([],{'budget':1000,'num_people':2}),consumer_flow=True)
        agent.chat('1000บาท 2คน')
        agent.chat('ยืนยันว่าไม่แพ้และจัดชุด')
        agent.select_option(0)
        return agent

    def test_screenshot_drinks_are_added_and_can_finish_without_model(self):
        agent=self.ready()
        food=agent.food_choice['food_total_price']
        answer=agent.chat('น้ำส้ม 2 ชาเขียว 1 น้ำเปล่า 2')
        self.assertIn('สรุปรายการทั้งหมด',answer)
        self.assertEqual(agent.checkout_result['total_price'],food+130)
        self.assertEqual(agent.last_run['model_calls'],0)
        agent.chat('ยืนยันรายการทั้งหมด')
        self.assertTrue(agent.order_closed)

    def test_screenshot_desserts_preserve_food_and_finish_without_model(self):
        agent=self.ready()
        food_choice=agent.food_choice.copy()
        agent.chat('ของหวาน')
        answer=agent.chat('ชีสเค้ก 1 วาราบิ 1')
        self.assertIn('สรุปรายการทั้งหมด',answer)
        self.assertEqual(agent.extras_plan,{'D003':1,'D002':1})
        self.assertEqual(agent.food_choice,food_choice)
        self.assertEqual(agent.checkout_result['total_price'],food_choice['food_total_price']+100)
        self.assertEqual(agent.last_run['model_calls'],0)
        agent.chat('ยืนยันรายการทั้งหมด')
        self.assertTrue(agent.order_closed)

    def test_screenshot_warabi_and_green_tea_desserts_finish(self):
        for message in ('วาราบี 1 ชาเขียว 1','วาราบี 1 ชาเขียวไอศครีม 1'):
            with self.subTest(message=message):
                agent=self.ready()
                food=agent.food_choice.copy()
                agent.chat('ของหวาน')
                answer=agent.chat(message)
                self.assertIn('สรุปรายการทั้งหมด',answer)
                self.assertEqual(agent.extras_plan,{'D002':1,'D001':1})
                self.assertEqual(agent.food_choice,food)
                self.assertEqual(agent.checkout_result['total_price'],food['food_total_price']+80)
                self.assertEqual(agent.last_run['model_calls'],0)
                agent.chat('ชาเขียว 2')
                self.assertEqual(agent.extras_plan,{'D002':1,'D001':2})
                self.assertEqual(agent.checkout_result['total_price'],food['food_total_price']+120)
                agent.chat('ยืนยันรายการทั้งหมด')
                self.assertTrue(agent.order_closed)

    def test_one_ice_cream_clarification_preserves_quantity_and_other_orders(self):
        agent=self.ready()
        food=agent.food_choice['food_total_price']
        answer=agent.chat('ไอศครีม 2 น้ำส้ม 1')
        self.assertIn('2 ชิ้น',answer)
        self.assertTrue(agent.pending_extra_order)
        self.assertEqual(agent.extras_plan,{})
        agent.checkout_action('ยืนยันรายการทั้งหมด')
        self.assertFalse(agent.order_closed)
        answer=agent.chat('ชาเขียว 2')
        self.assertIn('สรุปรายการทั้งหมด',answer)
        self.assertIsNone(agent.pending_extra_order)
        self.assertEqual(agent.extras_plan,{'D001':2,'B004':1})
        self.assertEqual(agent.checkout_result['total_price'],food+125)
        agent.chat('ยืนยันรายการทั้งหมด')
        self.assertTrue(agent.order_closed)

    def test_explicit_split_flavors_replaces_ambiguous_quantity(self):
        agent=self.ready()
        agent.chat('ไอศครีม2')
        agent.chat('ชาเขียวไอศกรีม1 ไอศกรีมซอร์เบต์องุ่น1')
        self.assertIsNone(agent.pending_extra_order)
        self.assertEqual(agent.extras_plan,{'D001':1,'D005':1})
        agent.reset_order()
        self.assertIsNone(agent.pending_extra_order)

    def test_ui_short_orders_and_ambiguity_can_finish(self):
        agent=self.ready()
        with patch.dict(os.environ,{'OPENAI_API_KEY':'short-name-ui-placeholder'}):
            page=AppTest.from_file(str(ROOT/'app.py'))
            page.session_state['agent']=agent
            page.session_state['_agent_key']=('short-name-ui-placeholder','gpt-4o-mini','strict')
            page.session_state['chat_history']=[]
            page.run()
            page.chat_input[0].set_value('ไอศครีม 2').run()
            self.assertTrue(page.button(key='final_confirm').disabled)
            page.chat_input[0].set_value('2').run()
            self.assertFalse(page.exception)
            self.assertEqual(agent.extras_plan,{'D005':2})
            self.assertFalse(page.button(key='final_confirm').disabled)
            page.button(key='final_confirm').click().run()
            self.assertTrue(agent.order_closed)
            self.assertFalse(page.exception)


if __name__=='__main__': unittest.main()
