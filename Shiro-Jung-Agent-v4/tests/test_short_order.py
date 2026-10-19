"""Short, user-confirmed consumer intake, with real backend menu validation."""
import os
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
import test_system as fixtures
from test_system import ScriptedModel
from sushi_budgeteer.agent import BudgeteerAgent
from sushi_budgeteer.database import ROOT
from sushi_budgeteer.extraction import _sanitize_extraction


class ShortOrderTest(unittest.TestCase):
    setUp=fixtures.CatalogTest.setUp
    tearDown=fixtures.CatalogTest.tearDown

    def agent(self, extracted):
        model=ScriptedModel([],extracted)
        return BudgeteerAgent(llm=model,consumer_flow=True),model

    def test_dislike_is_not_allergy_and_one_confirmation_builds_without_extra_questions(self):
        agent,model=self.agent({'budget':300,'num_people':2,'allergens':['molluscs'],
                               'dislikes':['ปลาหมึก'],'wants_dessert':False})
        answer=agent.chat('งบ300 2คน ไม่ชอบปลาหมึก ไม่รับของหวาน')
        self.assertEqual(agent.state.allergens,[])
        self.assertEqual(agent.state.dislikes,['ปลาหมึก'])
        self.assertFalse(agent.state.wants_dessert)
        self.assertTrue(agent.pending_confirmation)
        self.assertIn('ของหวาน: ไม่รับ',answer)
        self.assertNotIn('รับของหวานด้วยไหม',answer)
        answer=agent.chat('ยืนยันว่าไม่แพ้และจัดชุด')
        self.assertEqual(agent.last_run['model_calls'],0)
        self.assertEqual(len(agent.last_options),2)
        self.assertIsNone(agent.state.last_asked_field)
        self.assertFalse(agent.pending_confirmation)
        for option in agent.last_options:
            self.assertFalse(option['dessert_included'])
            self.assertFalse(option['constraints']['allergens'])

    def test_combined_missing_details_then_single_summary(self):
        agent,model=self.agent({})
        answer=agent.chat('ช่วยจัดมื้อหน่อย')
        self.assertIn('งบรวมกี่บาท',answer)
        self.assertIn('ทานกี่คน',answer)
        model.extraction={'budget':500,'num_people':3,'preferred_keywords':['แซลมอน']}
        answer=agent.chat('500 บาท 3 คน ชอบแซลมอน')
        self.assertTrue(agent.pending_confirmation)
        self.assertIn('เครื่องดื่ม: ไม่เพิ่มในชุด',answer)
        self.assertIn('ของหวาน: ไม่รับ',answer)
        agent.chat('ยืนยันว่าไม่แพ้และจัดชุด')
        self.assertEqual(agent.missing_fields(),[])
        self.assertTrue(agent.last_options)
        model.extraction={'preferred_keywords':['ไข่'],'intent':'search','wants_dessert':True}
        answer=agent.chat('อยากกินไข่ด้วย')
        self.assertTrue(agent.last_options)
        self.assertFalse(agent.pending_confirmation)
        self.assertFalse(agent.state.wants_dessert)
        self.assertEqual(agent.state.budget,500)
        self.assertIn('แซลมอน',agent.state.preferred_keywords)
        self.assertIn('ไข่',agent.state.preferred_keywords)

    def test_explicit_correction_needs_confirmation_and_keeps_other_allergies(self):
        agent,model=self.agent({'budget':300,'num_people':2,'dislikes':[]})
        agent.state.allergens=['molluscs','egg']
        answer=agent.chat('ปลาหมึกเป็นแค่ไม่ชอบ ไม่ได้แพ้')
        self.assertEqual(agent.state.allergens,['molluscs','egg'])
        self.assertEqual(agent.pending_allergy_removals,['molluscs'])
        self.assertIn('ปลาหมึก',agent.state.dislikes)
        self.assertIn('กดยืนยัน',answer)
        agent.chat('ยืนยันข้อมูลและจัดชุด')
        self.assertEqual(agent.state.allergens,['egg'])
        self.assertFalse(agent.last_options)  # unknown ingredients stay blocked in strict mode

    def test_declined_dessert_clears_old_question_even_if_strict_cannot_build(self):
        agent=BudgeteerAgent(llm=ScriptedModel([('build_set',{})]))
        agent.state.update_from_extraction({**fixtures.READY,'allergens':['egg'],'wants_dessert':None})
        agent.state.last_asked_field='dessert'
        answer=agent.chat('ไม่รับของหวาน')
        self.assertFalse(agent.state.wants_dessert)
        self.assertIsNone(agent.state.last_asked_field)
        self.assertIn('ข้อมูลส่วนผสม',answer)
        self.assertEqual(agent.last_run['model_calls'],1)  # no extraction call; build selection only

    def test_explicit_refusal_works_after_summary_without_model_call(self):
        agent,model=self.agent({'budget':300,'num_people':2,'wants_dessert':True,
                               'dessert_selection':['โมจิ']})
        agent.chat('300บาท 2คน เอาโมจิ')
        agent.chat('ไม่รับของหวาน')
        self.assertFalse(agent.state.wants_dessert)
        self.assertEqual(agent.last_run['model_calls'],0)
        self.assertIn('ของหวาน: ไม่รับ',agent.order_summary())

    def test_ui_one_confirmation_no_mode_or_stale_dessert_buttons(self):
        agent,_=self.agent({'budget':300,'num_people':2,'wants_dessert':False})
        answer=agent.chat('300บาท 2คน ไม่รับของหวาน')
        with patch.dict(os.environ,{'OPENAI_API_KEY':'ui-short-flow-placeholder'}):
            page=AppTest.from_file(str(ROOT/'app.py'))
            page.session_state['agent']=agent
            page.session_state['_agent_key']=('ui-short-flow-placeholder','gpt-4o-mini','strict')
            page.session_state['chat_history']=[{'role':'assistant','content':answer}]
            page.run(timeout=30)
            self.assertFalse(page.exception)
            self.assertEqual(len(page.selectbox),0)
            self.assertEqual(len([b for b in page.button if 'ยืนยัน' in b.label]),1)
            self.assertFalse(any('รับของหวาน' in b.label for b in page.button))
            page.button(key='confirm_order').click().run(timeout=30)
            self.assertFalse(page.exception)
            self.assertFalse(agent.pending_confirmation)
            self.assertEqual(len(agent.last_options),2)
            self.assertFalse(any('ยืนยันว่าไม่แพ้' in b.label or 'รับของหวาน' in b.label for b in page.button))

    def test_browsing_does_not_force_order_intake(self):
        model=ScriptedModel([('search_menu',{'keyword':'แซลมอน'}),('final',{})],{'intent':'search'})
        agent=BudgeteerAgent(llm=model,consumer_flow=True)
        answer=agent.chat('ดูเมนูแซลมอน')
        self.assertIn('แซลมอน',answer)
        self.assertNotIn('ขอทราบงบ',answer)
        self.assertFalse(agent.pending_confirmation)
        self.assertIsNone(agent.state.budget)

    def test_negation_does_not_remove_existing_allergy_without_confirmation(self):
        extracted=_sanitize_extraction({'allergens':['molluscs']},None,'ไม่ชอบปลาหมึก ไม่ได้แพ้')
        self.assertEqual(extracted['allergens'],[])
        self.assertIn('ปลาหมึก',extracted['dislikes'])
        actual=_sanitize_extraction({'allergens':['crustacean']},None,'ไม่ชอบปลาหมึก แต่แพ้กุ้ง')
        self.assertEqual(actual['allergens'],['crustacean'])


if __name__=='__main__':
    unittest.main()
