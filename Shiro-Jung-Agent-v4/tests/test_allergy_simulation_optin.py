"""Explicit per-meal educational planning; never silently downgrade strict evidence."""
import os
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
import test_system as fixtures
from test_system import ScriptedModel
from sushi_budgeteer.agent import BudgeteerAgent
from sushi_budgeteer.database import ROOT, records
from sushi_budgeteer.presentation import ALLERGY_WARNING
from sushi_budgeteer.optimizer import parse_allergen_tags


class AllergySimulationTest(unittest.TestCase):
    setUp=fixtures.CatalogTest.setUp
    tearDown=fixtures.CatalogTest.tearDown

    def blocked(self,allergens=None):
        allergens=allergens or ['milk']
        agent=BudgeteerAgent(llm=ScriptedModel([],{'budget':1000,'num_people':2,
            'allergens':allergens,'preferred_keywords':['แซลมอน'],'dislikes':['ปลาหมึก']}),consumer_flow=True)
        agent.chat('1000บาท 2คน แพ้ '+','.join(allergens)+' ชอบแซลมอน ไม่ชอบปลาหมึก')
        answer=agent.chat('ยืนยันข้อมูลและจัดชุด')
        return agent,answer

    def test_strict_still_blocks_and_requires_explicit_optin(self):
        agent,answer=self.blocked()
        self.assertEqual(agent.data_mode,'strict')
        self.assertFalse(agent.allergy_simulation_consent)
        self.assertTrue(agent.allergy_simulation_available)
        self.assertFalse(agent.last_options)
        self.assertIn('ดูชุดจำลองจากข้อมูลเมนู',answer)
        agent.chat('ดูชุดจำลองจากข้อมูลเมนู')
        self.assertEqual(agent.data_mode,'simulation')
        self.assertTrue(agent.allergy_simulation_consent)
        self.assertEqual(agent.state.allergens,['milk'])
        self.assertEqual(agent.state.budget,1000)
        self.assertEqual(agent.state.dislikes,['ปลาหมึก'])
        self.assertTrue(agent.last_options)
        self.assertTrue(all(row['allergen_status']=='unknown' for row in records()))

    def test_all_options_exclude_requested_tags_and_warn(self):
        agent,_=self.blocked(['milk','egg','crustacean'])
        answer=agent.chat('ดูชุดจำลองจากข้อมูลเมนู')
        self.assertIn(ALLERGY_WARNING,answer)
        self.assertIn('ชุดทดลอง',answer)
        self.assertIn('แพ้รุนแรง',answer)
        for option in agent.last_options:
            self.assertTrue(option['policy_decision']['allow'])
            for row in option['selected']:
                self.assertFalse(parse_allergen_tags(row['allergen_tags']) & set(agent.state.allergens))

    def test_unknown_allergen_never_offers_optin(self):
        agent,_=self.blocked(['unmapped spice'])
        self.assertFalse(agent.allergy_simulation_available)
        agent.chat('ดูชุดจำลองจากข้อมูลเมนู')
        self.assertEqual(agent.data_mode,'strict')
        self.assertFalse(agent.last_options)
        self.assertEqual(agent.state.allergens,['unmapped spice'])

    def test_reset_revokes_consent_and_restores_strict(self):
        agent,_=self.blocked()
        agent.chat('ดูชุดจำลองจากข้อมูลเมนู')
        agent.reset_order()
        self.assertEqual(agent.data_mode,'strict')
        self.assertFalse(agent.allergy_simulation_consent)
        self.assertFalse(agent.allergy_simulation_available)
        agent.chat('ดูชุดจำลองจากข้อมูลเมนู')
        self.assertEqual(agent.data_mode,'strict')

    def test_extras_keep_allergy_constraint_after_optin(self):
        agent,_=self.blocked()
        agent.chat('ดูชุดจำลองจากข้อมูลเมนู')
        agent.select_option(0)
        answer=agent.set_checkout_extras({'D001':1})
        self.assertNotIn('D001',agent.extras_plan)
        self.assertIn('ยังเพิ่มไม่ได้',answer)
        agent.set_checkout_extras({'B005':1})
        self.assertTrue(agent.checkout_result)
        agent.chat('ยืนยันรายการทั้งหมด')
        self.assertTrue(agent.order_closed)
        self.assertEqual(agent.state.allergens,['milk'])

    def test_ui_optin_survives_rerun_selection_and_confirmation(self):
        agent,_=self.blocked()
        with patch.dict(os.environ,{'OPENAI_API_KEY':'ui-optin-placeholder'}):
            page=AppTest.from_file(str(ROOT/'app.py'))
            page.session_state['agent']=agent
            page.session_state['_agent_key']=('ui-optin-placeholder','gpt-4o-mini','strict')
            page.session_state['chat_history']=[]
            page.run()
            page.button(key='allergy_simulation').click().run(timeout=30)
            self.assertFalse(page.exception)
            self.assertTrue(agent.allergy_simulation_consent)
            self.assertEqual(agent.data_mode,'simulation')
            page.button(key='choose_0').click().run()
            self.assertEqual(agent.data_mode,'simulation')
            page.button(key='final_confirm').click().run()
            self.assertFalse(page.exception)
            self.assertTrue(agent.order_closed)
            self.assertEqual(agent.state.allergens,['milk'])


if __name__=='__main__':unittest.main()
