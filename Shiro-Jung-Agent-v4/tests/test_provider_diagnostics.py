"""Provider diagnostics use synthetic exceptions and never call a paid provider."""
import json
import unittest
from unittest.mock import patch
from langchain_core.messages import AIMessage
from sushi_budgeteer.agent import BudgeteerAgent
from sushi_budgeteer.telemetry import model_error
from test_system import ScriptedModel


class ProviderDiagnosticsTest(unittest.TestCase):
    def test_quota_is_separate_from_transient_rate_limit(self):
        error=RuntimeError('secret must never be exported')
        error.status_code=429;error.body={'error':{'code':'insufficient_quota','message':'secret'}}
        result=model_error(error,'extraction')
        self.assertEqual(result['category'],'quota_or_billing')
        self.assertNotIn('secret',json.dumps(result))
        error.body={'error':{'code':'rate_limit_exceeded'}}
        self.assertEqual(model_error(error,'extraction')['category'],'rate_limit')

    def test_authentication_status_and_unknown_body_are_safe(self):
        error=RuntimeError('secret')
        error.status_code=401;error.body={'code':'sk-not-safe-to-echo'}
        result=model_error(error,'extraction')
        self.assertEqual(result['category'],'authentication')
        self.assertIsNone(result['code'])
        self.assertNotIn('sk-',json.dumps(result))

    def test_exception_group_is_unwrapped_for_planning(self):
        error=RuntimeError('private');error.status_code=403
        result=model_error(ExceptionGroup('private',[error]),'planning')
        self.assertEqual(result['category'],'permission_denied')
        self.assertEqual(result['phase'],'planning')

    def test_failed_extraction_keeps_safe_error_and_zero_successful_calls(self):
        model=ScriptedModel([])
        error=RuntimeError('private key');error.status_code=401
        agent=BudgeteerAgent(llm=model,consumer_flow=True)
        with patch.object(model,'invoke',side_effect=error),self.assertLogs('shiro_jung.agent',level='ERROR'):
            agent.chat('งบ300 2คน')
        report=agent.run_report()
        self.assertEqual(report['model_calls'],0)
        self.assertEqual(report['model_errors'][0]['category'],'authentication')
        self.assertNotIn('private key',json.dumps(report))

    def test_bad_json_records_successful_response_but_validation_failure(self):
        model=ScriptedModel([]);agent=BudgeteerAgent(llm=model,consumer_flow=True)
        with patch.object(model,'invoke',return_value=AIMessage(content='not JSON')),self.assertLogs('shiro_jung.agent',level='ERROR'):
            agent.chat('งบ300 2คน')
        report=agent.run_report()
        self.assertEqual(report['model_calls'],1)
        self.assertEqual(report['model_errors'][0]['category'],'invalid_model_response')
