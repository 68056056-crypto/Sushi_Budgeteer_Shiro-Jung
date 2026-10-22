"""Consumer intake rejects implausibly low budgets before planning, preserving state."""
import asyncio
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock,patch
from streamlit.testing.v1 import AppTest
import test_system as fixtures
from test_system import ScriptedModel
from sushi_budgeteer.agent import BudgeteerAgent
from sushi_budgeteer.database import ROOT
from scripts import live_sessions


class IntakeBudgetTest(unittest.TestCase):
    setUp=fixtures.CatalogTest.setUp
    tearDown=fixtures.CatalogTest.tearDown

    def agent(self,extraction=None):
        model=ScriptedModel([],extraction or {'budget':50,'num_people':3})
        return BudgeteerAgent(llm=model,consumer_flow=True),model

    def test_low_budget_warns_before_confirmation_or_tools_and_preserves_preferences(self):
        agent,_=self.agent({'budget':50,'num_people':3,'allergens':['milk'],
                           'preferred_keywords':['แซลมอน'],'dislikes':['ปลาหมึก']})
        with patch.object(agent,'_run',new_callable=AsyncMock) as planning:
            answer=agent.chat('งบ 50 บาท 3 คน แพ้นม ชอบแซลมอน ไม่ชอบปลาหมึก')
        planning.assert_not_awaited()
        self.assertIn('16.67',answer);self.assertIn('300.00',answer)
        self.assertEqual((agent.state.budget,agent.state.num_people),(50,3))
        self.assertEqual(agent.state.allergens,['milk'])
        self.assertEqual(agent.state.preferred_keywords,['แซลมอน'])
        self.assertEqual(agent.state.dislikes,['ปลาหมึก'])
        self.assertFalse(agent.pending_confirmation);self.assertFalse(agent.details_confirmed)
        self.assertFalse(agent.last_options);self.assertFalse(agent.last_trace)
        self.assertEqual(agent.last_run['intake_check']['status'],'needs_budget_revision')
        self.assertNotIn('80%',answer)

    def test_confirm_cannot_bypass_gate_or_apply_pending_allergy_removal(self):
        agent,_=self.agent();agent.state.budget=50;agent.state.num_people=3
        agent.state.allergens=['milk'];agent.pending_allergy_removals=['milk']
        with patch.object(agent,'_run',new_callable=AsyncMock) as planning:
            answer=agent._confirm_order()
        planning.assert_not_awaited();self.assertIn('300.00',answer)
        self.assertEqual(agent.state.allergens,['milk'])
        self.assertEqual(agent.pending_allergy_removals,['milk'])
        with patch.object(agent,'_run_turn',new_callable=AsyncMock) as planning:
            self.assertIn('300.00',asyncio.run(agent._run('จัดเลย')))
        planning.assert_not_awaited()

    def test_amount_only_correction_reaches_summary_without_reasking_preferences(self):
        agent,_=self.agent({'budget':50,'num_people':3,'allergens':['milk'],
                           'preferred_keywords':['แซลมอน'],'hard_exclude_keywords':['หมู']})
        agent.chat('50 บาท 3 คน แพ้นม ชอบแซลมอน ไม่กินหมู')
        answer=agent.chat('300')
        self.assertEqual(agent.state.budget,300);self.assertEqual(agent.state.num_people,3)
        self.assertEqual(agent.state.allergens,['milk'])
        self.assertEqual(agent.state.hard_exclude_keywords,['หมู'])
        self.assertEqual(agent.state.preferred_keywords,['แซลมอน'])
        self.assertTrue(agent.pending_confirmation);self.assertIn('ขอเช็กมื้อ',answer)
        self.assertEqual(agent.last_run['model_calls'],0)

    def test_floor_boundary_and_changed_people(self):
        for budget,warning in ((299.99,True),(300,False),(300.01,False)):
            with self.subTest(budget=budget):
                agent,_=self.agent({'budget':budget,'num_people':3})
                agent.chat(f'{budget} บาท 3 คน')
                self.assertEqual(bool(agent.last_run.get('intake_check')),warning)
                self.assertEqual(agent.pending_confirmation,not warning)
        agent,model=self.agent({'budget':100,'num_people':3});agent.chat('100 บาท 3 คน')
        model.extraction={'num_people':1}
        agent.chat('เปลี่ยนเป็น 1 คน')
        self.assertEqual((agent.state.budget,agent.state.num_people),(100,1))
        self.assertTrue(agent.pending_confirmation)

    def test_partial_intake_and_replan_are_checked_once_people_are_known(self):
        agent,model=self.agent({'budget':50})
        self.assertIn('ทานกี่คน',agent.chat('งบ50'))
        model.extraction={'num_people':3}
        self.assertIn('300.00',agent.chat('3 คน'))
        agent.state.budget=300;agent.details_confirmed=True
        agent.state.last_result={'previous':'result'};agent._has_recommended=True
        model.extraction={'budget':50}
        with patch.object(agent,'_run',new_callable=AsyncMock) as planning:
            agent.chat('ลดงบเหลือ50บาท')
        planning.assert_not_awaited();self.assertIsNone(agent.state.last_result)
        self.assertFalse(agent.details_confirmed);self.assertFalse(agent.pending_confirmation)

    def test_ui_hides_confirmation_until_budget_is_revised(self):
        agent,_=self.agent();answer=agent.chat('50 บาท 3 คน')
        with patch.dict(os.environ,{'OPENAI_API_KEY':'ui-fixture-only'}):
            page=AppTest.from_file(str(ROOT/'app.py'))
            page.session_state['agent']=agent
            page.session_state['_agent_key']=('ui-fixture-only','gpt-4o-mini','strict')
            page.session_state['chat_history']=[{'role':'assistant','content':answer}]
            page.run(timeout=30)
            self.assertFalse(page.exception)
            self.assertFalse(any(button.key=='confirm_order' for button in page.button))
            agent.chat('300');page.run(timeout=30)
            self.assertTrue(any(button.key=='confirm_order' for button in page.button))

    def test_live_runner_checks_early_revision_then_restored_recommendation_offline(self):
        source=Path(self.tmp.name)/'session.json';output=Path(self.tmp.name)/'report.json'
        source.write_text(json.dumps([{'id':'low-budget-fixture','mode':'strict','turns':[
            {'message':'50บาท3คน ไม่กินหมู','expected':'budget_revision','budget':50,'num_people':3,'hard_exclude_keywords':['หมู']},
            {'message':'300','expected':'recommendation','budget':300,'num_people':3,'hard_exclude_keywords':['หมู']}]}]))
        def factory(**kwargs):
            return BudgeteerAgent(llm=ScriptedModel([],{'budget':50,'num_people':3,'dislikes':['หมู']}),**kwargs)
        with patch.dict(os.environ,{'OPENAI_API_KEY':'fixture-only'}),patch.object(live_sessions,'BudgeteerAgent',side_effect=factory),patch.object(sys,'argv',['live_sessions','--scenarios',str(source),'--output',str(output)]):
            self.assertEqual(live_sessions.main(),0)
        report=json.loads(output.read_text())
        self.assertEqual(report['success_rate'],1);self.assertFalse(report['live_llm_tested'])
        self.assertEqual(len(report['sessions'][0]['turns'][0]['runs']),1)
