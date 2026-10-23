"""Food → drinks → desserts → full-budget review → explicit final confirmation."""
import os
import sqlite3
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
import test_system as fixtures
from test_system import ScriptedModel
from sushi_budgeteer.agent import BudgeteerAgent
from sushi_budgeteer.database import ROOT


class CheckoutSequenceTest(unittest.TestCase):
    setUp=fixtures.CatalogTest.setUp
    tearDown=fixtures.CatalogTest.tearDown

    def ready(self):
        agent=BudgeteerAgent(llm=ScriptedModel([],{'budget':500,'num_people':2}),consumer_flow=True)
        agent.chat('500บาท 2คน')
        agent.chat('ยืนยันว่าไม่แพ้และจัดชุด')
        agent.select_option(0)
        return agent

    def test_extras_spend_reserved_budget_without_changing_chosen_food(self):
        agent=self.ready()
        self.assertEqual(agent.checkout_step,'review')
        self.assertFalse(agent.order_closed)
        food=[(x['item_id'],x['quantity']) for x in agent.food_choice['selected'] if x['category'] not in {'เครื่องดื่ม','ของหวาน'}]
        drink_menu=agent.checkout_action('รับเครื่องดื่ม')
        self.assertIn('โค้ก',drink_menu)
        self.assertEqual(agent.checkout_step,'drinks_menu')
        answer=agent.choose_extra('B002',1)
        self.assertIn('สรุปรายการทั้งหมด',answer)
        self.assertEqual(agent.checkout_step,'review')
        self.assertIn('วาราบิโมจิ',agent.checkout_action('รับของหวาน'))
        summary=agent.choose_extra('D002',1)
        self.assertEqual(agent.checkout_step,'review')
        result=agent.checkout_result
        self.assertEqual(result['total_price'],result['food_total_price']+75)
        self.assertGreater(result['total_price'],400)
        self.assertLessEqual(result['total_price'],500)
        self.assertEqual(food,[(x['item_id'],x['quantity']) for x in result['selected'] if x['category'] not in {'เครื่องดื่ม','ของหวาน'}])
        self.assertIn(f"เหลือ {500-result['total_price']:,.2f} บาท",summary)
        self.assertFalse(agent.order_closed)
        final=agent.checkout_action('ยืนยันรายการทั้งหมด')
        self.assertTrue(agent.order_closed)
        self.assertTrue(agent.last_policy['allow'])
        self.assertIn('ขอให้เป็นมื้ออาหารที่อร่อย',final)

    def test_skipping_both_categories_still_requires_final_confirmation(self):
        agent=self.ready()
        self.assertIn('สรุปรายการทั้งหมด',agent.checkout_action('ไม่รับเครื่องดื่ม'))
        summary=agent.checkout_action('ไม่รับของหวาน')
        self.assertIn('สรุปรายการทั้งหมด',summary)
        self.assertEqual(agent.checkout_step,'review')
        self.assertFalse(agent.order_closed)
        self.assertFalse(agent.state.drink_selection)
        self.assertFalse(agent.state.wants_dessert)
        agent.checkout_action('ยืนยันรายการทั้งหมด')
        self.assertTrue(agent.order_closed)
        agent.reset_order()
        self.assertIsNone(agent.checkout_step)
        self.assertIsNone(agent.food_choice)

    def test_over_budget_extras_cannot_be_confirmed(self):
        agent=self.ready()
        before=agent.checkout_result['total_price']
        agent.checkout_action('รับเครื่องดื่ม')
        error=agent.choose_extra('B002',20)
        self.assertIn('เกินงบ',error)
        self.assertIn('รายการครั้งนี้ยังไม่ถูกเพิ่ม',error)
        self.assertFalse(agent.extras_plan)
        self.assertEqual(agent.checkout_result['total_price'],before)
        agent.checkout_action('ไม่รับของหวาน')
        agent.checkout_action('ยืนยันรายการทั้งหมด')
        self.assertTrue(agent.order_closed)
        self.assertFalse(any(row['item_id']=='B002' for row in agent.checkout_result['selected']))

    def test_catalog_change_between_summary_and_confirm_is_blocked(self):
        agent=self.ready()
        agent.checkout_action('ไม่รับเครื่องดื่ม')
        agent.checkout_action('ไม่รับของหวาน')
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE menu SET price_baht=price_baht+1 WHERE item_id='B002'")
        error=agent.checkout_action('ยืนยันรายการทั้งหมด')
        self.assertIn('เปลี่ยนแล้ว',error)
        self.assertFalse(agent.order_closed)
        self.assertEqual(agent.checkout_step,'review_error')

    def test_typed_drink_with_per_item_quantity_advances_to_desserts(self):
        agent=self.ready()
        agent.checkout_action('รับเครื่องดื่ม')
        agent.llm.extraction={'drink_selection':['โค้ก'],'drink_quantities':{'โค้ก':1}}
        answer=agent.chat('โค้ก1แก้ว')
        self.assertIn('สรุปรายการทั้งหมด',answer)
        self.assertEqual(agent.checkout_step,'review')
        self.assertEqual(agent.state.drink_quantity,1)
        self.assertEqual(agent.state.drink_quantities,{'โค้ก':1})

    def test_multiple_extras_are_summed_exactly_and_repeating_updates_quantity(self):
        agent=self.ready()
        food=agent.food_choice['food_total_price']
        agent.chat('เครื่องดื่ม')
        agent.chat('น้ำส้ม 1 แก้ว โค้ก 1 แก้ว')
        self.assertEqual(agent.checkout_result['total_price'],food+80)
        agent.chat('น้ำส้ม 1 แก้ว')
        self.assertEqual(agent.checkout_result['total_price'],food+80)
        agent.chat('ยกเลิกโค้ก')
        self.assertEqual(agent.checkout_result['total_price'],food+45)
        agent.chat('ของหวาน')
        answer=agent.chat('โมจิ 1 พุดดิ้ง 1')
        self.assertIn('เกินงบ',answer)  # 125 extra > 100 reserve; neither new item added.
        self.assertEqual(agent.checkout_step,'review')
        self.assertEqual(agent.checkout_result['total_price'],food+45)
        self.assertEqual(agent.extras_plan,{'B004':1})
        agent.chat('โมจิ 1')
        self.assertEqual(agent.checkout_result['total_price'],food+85)
        agent.chat('ยืนยันรายการทั้งหมด')
        self.assertTrue(agent.order_closed)

    def test_full_60_food_items_can_add_drink_without_reoptimizing(self):
        agent=BudgeteerAgent(llm=ScriptedModel([],{'budget':5000,'num_people':2}),consumer_flow=True)
        agent.chat('5000บาท 2คน')
        agent.chat('ยืนยันว่าไม่แพ้และจัดชุด')
        agent.select_option(0)
        food=agent.food_choice['food_total_price']
        count=sum(row['quantity'] for row in agent.food_choice['selected'] if row['category'] not in {'เครื่องดื่ม','ของหวาน'})
        self.assertEqual(count,60)
        answer=agent.chat('น้ำส้ม 1 แก้ว')
        self.assertIn('สรุปรายการทั้งหมด',answer)
        self.assertEqual(agent.checkout_result['item_count'],61)
        self.assertEqual(agent.checkout_result['total_price'],food+45)
        self.assertTrue(agent.checkout_result['policy_decision']['allow'])

    def test_ui_navigates_categories_then_combined_summary(self):
        agent=self.ready()
        with patch.dict(os.environ,{'OPENAI_API_KEY':'checkout-ui-placeholder'}):
            page=AppTest.from_file(str(ROOT/'app.py'))
            page.session_state['agent']=agent
            page.session_state['_agent_key']=('checkout-ui-placeholder','gpt-4o-mini','strict')
            page.session_state['chat_history']=[]
            page.run(timeout=30)
            self.assertFalse(any(b.key=='choose_0' for b in page.button))
            page.chat_input[0].set_value('เครื่องดื่ม').run()
            self.assertEqual(len(page.selectbox),0)
            self.assertEqual(len(page.number_input),0)
            page.chat_input[0].set_value('โค้ก 1 แก้ว').run()
            page.chat_input[0].set_value('ของหวาน').run()
            page.chat_input[0].set_value('วาราบิโมจิ 1 ชิ้น').run()
            self.assertEqual(agent.checkout_step,'review')
            self.assertFalse(page.exception)
            self.assertFalse(agent.order_closed)
            page.button(key='final_confirm').click().run()
            self.assertTrue(agent.order_closed)
            self.assertFalse(page.exception)




    def test_rejected_paid_drink_does_not_poison_free_tea(self):
        agent=self.ready()
        # Build an exact 40-baht remainder using a legitimate fixed food set.
        from sushi_budgeteer.service import MenuService
        agent.state.budget=200;agent.state.num_people=2
        result=MenuService().build(**agent.build_arguments())['result']
        agent.last_options=[result];agent.select_option(0)
        self.assertEqual(200-agent.food_choice['food_total_price'],40)
        food=agent.food_choice.copy()
        self.assertIn('เกินงบ',agent.chat('ลาเต้ 1'))
        self.assertFalse(agent.extras_plan)
        answer=agent.chat('ชาเขียวร้อน 1')
        self.assertNotIn('ยอดรวมเกินงบ',answer)
        self.assertEqual(agent.extras_plan,{'B001':1})
        self.assertEqual(agent.checkout_result['total_price'],160)
        self.assertIn('เหลือ 40.00 บาท',answer)
        self.assertEqual(agent.food_choice,food)
        agent.chat('ชาเขียวร้อน 2')
        self.assertEqual(agent.checkout_result['total_price'],160)
        self.assertEqual(agent.extras_plan,{'B001':2})

    def test_legacy_invalid_basket_is_explained_and_repaired_before_free_tea(self):
        agent=self.ready();agent.state.budget=200
        from sushi_budgeteer.service import MenuService
        result=MenuService().build(**agent.build_arguments())['result']
        agent.last_options=[result];agent.select_option(0)
        agent.extras_plan={'B003':1};agent.sync_checkout_extras()
        self.assertIsNone(agent.compose_checkout()[0])
        answer=agent.chat('ชาเขียวร้อน 1')
        self.assertIn('ยกเลิกรายการเพิ่มเติมเดิม',answer)
        self.assertIn('มัทฉะ',answer)
        self.assertEqual(agent.extras_plan,{'B001':1})
        self.assertEqual(agent.checkout_result['total_price'],160)
        self.assertIn('เหลือ 40.00 บาท',answer)
        self.assertNotIn('ยอดรวมเกินงบ',answer)

    def test_bare_free_tea_names_price_and_preserves_valid_extras(self):
        agent=self.ready()
        agent.chat('น้ำเปล่า 1')
        before=agent.checkout_result['total_price']
        answer=agent.chat('ชาเขียวร้อน')
        self.assertIn('0.00 บาท',answer)
        self.assertIn('ชาเขียวร้อน 1',answer)
        self.assertEqual(agent.extras_plan,{'B005':1})
        answer=agent.chat('ชาเขียวร้อน 1')
        self.assertEqual(agent.extras_plan,{'B005':1,'B001':1})
        self.assertEqual(agent.checkout_result['total_price'],before)
