"""Evidence exporter tests use synthetic fixtures, not live-provider results."""
import copy
import unittest
from unittest.mock import patch
from scripts.export_live_trace import render_trace


class LiveTraceExportTest(unittest.TestCase):
    def fixture(self):
        return {'live_llm_tested':True,'sessions':[{'id':'synthetic-unit-fixture','turns':[
            {'success':True,'model_selected_build_and_verify':True,'message':'fixture only',
             'runs':[{'model_source':'live','model_calls':2,'model':'fixture-model',
                      'trace':[{'tool':'build_set','route':'model_selected','status':'candidate','result_id':'fixture-id','arguments':{'hard_exclude_keywords':['หมู']}},
                               {'tool':'verify_set','route':'model_selected','passed':True,'result_id':'fixture-id'}]}]}]}]}

    def test_rejects_scripted_even_when_top_level_flag_is_true(self):
        report=self.fixture()
        report['sessions'][0]['turns'][0]['runs'][0]['model_source']='scripted'
        self.assertIn('unavailable',render_trace(report))

    def test_rejects_failed_turn_and_backend_fallback(self):
        report=self.fixture();report['sessions'][0]['turns'][0]['success']=False
        self.assertIn('unavailable',render_trace(report))
        report=self.fixture()
        for event in report['sessions'][0]['turns'][0]['runs'][0]['trace']:
            event.pop('route');event['fallback']='after_stall'
        self.assertIn('unavailable',render_trace(report))

    def test_valid_synthetic_fixture_exports_tool_events_with_secret_redaction(self):
        report=self.fixture();report['sessions'][0]['turns'][0]['message']='secret-example-for-unit-test'
        with patch.dict('os.environ',{'OPENAI_API_KEY':'secret-example-for-unit-test'}):
            text=render_trace(report)
        self.assertIn('build_set',text);self.assertIn('verify_set',text)
        self.assertNotIn('secret-example-for-unit-test',text)
        self.assertIn('[REDACTED]',text)
        self.assertIn('arguments of this run',text)
        report['sessions'][0]['turns'][0]['runs'][0]['trace'][1]['result_id']='different-id'
        self.assertIn('unavailable',render_trace(report))
