"""Offline checks of the live-runner harness, never live-provider evidence."""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import test_system as fixtures
from test_system import ScriptedModel
from sushi_budgeteer.agent import BudgeteerAgent
from scripts import live_sessions


class LiveHarnessTest(unittest.TestCase):
    setUp=fixtures.CatalogTest.setUp
    tearDown=fixtures.CatalogTest.tearDown

    def test_missing_credentials_records_zero_live_turns(self):
        output=Path(self.tmp.name)/'blocked.json'
        with patch.dict(os.environ,{'OPENAI_API_KEY':'','SUSHI_OPENAI_API_KEY':''}), patch.object(sys,'argv',['live_sessions','--output',str(output)]):
            self.assertEqual(live_sessions.main(),2)
        report=json.loads(output.read_text())
        self.assertFalse(report['live_llm_tested'])
        self.assertEqual(report['executed_turns'],0)
        self.assertEqual(report['status'],'blocked_missing_credentials')

    def test_runner_meat_clarification_and_optin_without_claiming_scripted_as_live(self):
        scenarios=[
            {'id':'hard','mode':'strict','turns':[
                {'message':'1000 บาท 2คน ไม่กินเนื้อ','expected':'clarification','budget':1000},
                {'message':'สัตว์บกทั้งหมด','expected':'recommendation','budget':1000,'hard_exclude_keywords':['หมู','เนื้อวัว','ไก่']}]},
            {'id':'allergy','mode':'strict','turns':[
                {'message':'1000 บาท 2คน แพ้เนื้อ','expected':'clarification','budget':1000},
                {'message':'ไก่','expected':'blocked','budget':1000,'allergens':['chicken']},
                {'message':'ดูชุดจำลองจากข้อมูลเมนู','expected':'recommendation','budget':1000,
                 'allergens':['chicken'],'expected_mode':'simulation','simulation_consent':True}]}]
        source=Path(self.tmp.name)/'fixtures.json';source.write_text(json.dumps(scenarios,ensure_ascii=False))
        output=Path(self.tmp.name)/'scripted-harness-only.json'
        models=iter([ScriptedModel([],{'budget':1000,'num_people':2,'hard_exclude_keywords':['เนื้อวัว']}),
                     ScriptedModel([],{'budget':1000,'num_people':2,'allergens':['beef']})])
        def factory(**kwargs):
            return BudgeteerAgent(llm=next(models),**kwargs)
        with patch.dict(os.environ,{'OPENAI_API_KEY':'harness-fixture-only'}),patch.object(live_sessions,'BudgeteerAgent',side_effect=factory),patch.object(sys,'argv',['live_sessions','--scenarios',str(source),'--output',str(output)]):
            self.assertEqual(live_sessions.main(),0)
        report=json.loads(output.read_text())
        self.assertEqual(report['success_rate'],1)
        self.assertEqual(report['sessions'][0]['turns'][0]['state']['hard_exclude_keywords'],[])
        self.assertEqual(report['sessions'][1]['turns'][0]['state']['allergens'],[])
        self.assertFalse(report['live_llm_tested'])
        self.assertTrue(all(turn['success'] for session in report['sessions'] for turn in session['turns']))


if __name__=='__main__':unittest.main()
