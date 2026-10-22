"""OPA enforcement, evidence, token accounting and export safety."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from langchain_core.messages import AIMessage
from sushi_budgeteer.opa import evaluate,binary_path,ROOT
from sushi_budgeteer.service import MenuService
from sushi_budgeteer.policy import validate_result
from sushi_budgeteer.database import records
from sushi_budgeteer.agent import BudgeteerAgent
from sushi_budgeteer.telemetry import redact
from test_system import ScriptedModel
import test_system as fixtures

class OPATest(unittest.TestCase):
    setUp=fixtures.CatalogTest.setUp
    tearDown=fixtures.CatalogTest.tearDown
    def test_rego_suite(self):
        completed=subprocess.run([str(binary_path()),'test',str(ROOT/'policies')],capture_output=True,text=True)
        self.assertEqual(completed.returncode,0,completed.stderr)
        self.assertIn('25/25',completed.stdout)
    def test_opa_allow_is_required(self):
        s=MenuService();r=s.build(budget=300)
        self.assertTrue(s.verify(r['result_id'])['policy_decision']['allow'])
        with patch.dict(os.environ,{'SUSHI_OPA_BINARY':str(Path(self.tmp.name)/'missing-opa')}):
            self.assertFalse(s.verify(r['result_id'])['passed'])
            self.assertEqual(s.verify(r['result_id'])['policy_decision']['deny_reasons'],['opa_unavailable_or_invalid'])
    def test_opa_rejects_over_budget_without_python_errors(self):
        s=MenuService();r=s.build(budget=300)
        facts=s.verify(r['result_id'])['policy_input']
        facts['python_issues']=[];facts['budget_cents']=1
        decision=evaluate(facts)
        self.assertFalse(decision['allow']);self.assertIn('over_budget',decision['deny_reasons'])
    def test_undefined_or_invalid_input_denies(self):
        self.assertFalse(evaluate({})['allow'])
        self.assertFalse(evaluate({'lines':[{}]})['allow'])
    def test_explanation_uses_shared_scores_and_db(self):
        s=MenuService();r=s.build(budget=300,preferred_keywords=['แซลมอน'])
        explanation=r['result']['explanation']
        self.assertEqual(explanation['food_score_total'],sum(x['score']*x['quantity'] for x in r['result']['selected']))
        self.assertTrue(all(x['price_status']=='unverified' for x in explanation['items']))
        self.assertTrue(all(x['source_url']=='' for x in explanation['items']))
        self.assertEqual(explanation['catalog_revision'],r['result']['catalog_revision'])
    def test_agent_trace_records_real_opa(self):
        agent=BudgeteerAgent(llm=ScriptedModel([('build_set',{}),('verify_current',{}),('final',{})]))
        answer=agent.chat('จัดชุด')
        report=agent.run_report()
        self.assertEqual(report['outcome'],'recommendation')
        self.assertTrue(report['final_recheck']['passed'])
        self.assertEqual(report['policy_decision']['engine'],'OPA')
        self.assertFalse(report['token_usage_complete'])
        self.assertGreater(report['elapsed_ms'],0)
        self.assertNotIn('prompt',report)
    def test_token_accounting_from_provider_metadata(self):
        agent=BudgeteerAgent(llm=ScriptedModel([],{}));agent.last_run={}
        agent._record_usage(AIMessage(content='',usage_metadata={'input_tokens':10,'output_tokens':5,'total_tokens':15}),'test')
        self.assertEqual(agent.last_run['usage']['total_tokens'],15)
        self.assertEqual(agent.last_run['usage_responses'],1)
    def test_export_redaction(self):
        # Synthetic marker is a local fixture, never used as an authentication credential.
        marker='sensitive-fixture-value'
        with patch.dict(os.environ,{'SUSHI_OPENAI_API_KEY':marker}):
            safe=redact({'api_key':marker,'trace':[{'text':marker}],'input_tokens':12})
        self.assertNotIn(marker,json.dumps(safe));self.assertEqual(safe['input_tokens'],12)
    def test_agent_denies_if_opa_subprocess_missing(self):
        agent=BudgeteerAgent(llm=ScriptedModel([('build_set',{}),('final',{})]))
        with patch.dict(os.environ,{'SUSHI_OPA_BINARY':str(Path(self.tmp.name)/'missing-opa')}):
            answer=agent.chat('จัดชุด')
        self.assertIsNone(agent.state.last_result)
        self.assertIn('ไม่พร้อมชั่วคราว',answer)
        self.assertNotIn('opa_unavailable',answer)
        self.assertFalse(agent.last_policy['allow'])
    def test_multi_turn_budget_and_hard_constraints(self):
        from test_system import READY
        model=ScriptedModel([('build_set',{}),('verify_current',{}),('final',{})],
            {**READY,'hard_exclude_keywords':['ดิบ']})
        agent=BudgeteerAgent(llm=model)
        agent.chat('งบ300 ห้ามของดิบ')
        self.assertEqual(agent.state.last_result['budget'],300)
        first_turn=agent.run_report()['turn_id']
        model.extraction={'budget_delta':100}
        model.steps=[('build_set',{}),('verify_current',{}),('final',{})]
        agent.chat('เพิ่มงบ100')
        self.assertEqual(agent.state.last_result['budget'],400)
        self.assertEqual(agent.state.hard_exclude_keywords,['ดิบ'])
        self.assertNotEqual(first_turn,agent.run_report()['turn_id'])
        self.assertTrue(agent.last_policy['allow'])
    def test_infeasible_then_user_replans_budget(self):
        from test_system import READY
        model=ScriptedModel([('build_set',{}),('final',{})],{**READY,'budget':1})
        agent=BudgeteerAgent(llm=model);agent.chat('งบ1')
        self.assertIsNone(agent.state.last_result)
        model.extraction={'budget':300}
        model.steps=[('build_set',{}),('verify_current',{}),('final',{})]
        agent.chat('เปลี่ยนงบ300')
        self.assertIsNotNone(agent.state.last_result)
    def test_unsupported_provider_usage_does_not_claim_zero_cost(self):
        agent=BudgeteerAgent(llm=ScriptedModel([('clarify',{'missing':['budget']}),('final',{})],{}))
        agent.chat('จัดชุด')
        report=agent.run_report()
        self.assertFalse(report['token_usage_complete'])
        self.assertEqual(report['model_source'],'scripted')
    def test_evidence_ui(self):
        from streamlit.testing.v1 import AppTest
        agent=BudgeteerAgent(llm=ScriptedModel([],{}))
        s=MenuService();r=s.build(budget=300)
        agent.state.last_result=s.verify(r['result_id'])['checked_result']
        agent.last_policy=agent.state.last_result['policy_decision']
        with patch.dict(os.environ,{'OPENAI_API_KEY':'','SUSHI_OPENAI_API_KEY':''}):
            page=AppTest.from_file(str(ROOT/'app.py'))
            page.session_state['agent']=agent
            page.run(timeout=30)
            self.assertFalse(page.exception)
            self.assertEqual(len(page.dataframe),0)
            self.assertEqual(len(page.json),0)
            self.assertEqual(len(page.toggle),0)
            self.assertFalse(any('OPA' in e.label or 'ที่มา' in e.label for e in page.expander))
            self.assertIn('explanation',agent.state.last_result)


if __name__=='__main__':unittest.main()
