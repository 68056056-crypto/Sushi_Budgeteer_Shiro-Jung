"""Secret shape tests never use real credentials or make network requests."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from sushi_budgeteer.credentials import clean_api_key, InvalidAPIKeyFormat
from sushi_budgeteer.agent import BudgeteerAgent
from sushi_budgeteer.telemetry import redact
from scripts import live_sessions


class CredentialFormatTest(unittest.TestCase):
    def test_outer_whitespace_is_trimmed_but_not_exposed(self):
        self.assertEqual(clean_api_key(' \nfixture-key\r\n'),'fixture-key')
        self.assertIsNone(clean_api_key(' \n'))
        with patch.dict(os.environ,{'OPENAI_API_KEY':' \nfixture-key\n'}):
            self.assertEqual(redact('fixture-key'),'[REDACTED]')

    def test_internal_newlines_hidden_characters_and_config_syntax_are_rejected(self):
        for key in ('fixture\nkey','fixture\rkey','fixture key','fixture\x00key',
                    '\ufefffixture-key','OPENAI_API_KEY=fixture-key','"fixture-key"',"'fixture-key'",'Bearer fixture-key'):
            with self.subTest(key=repr(key)),self.assertRaises(InvalidAPIKeyFormat) as caught:
                clean_api_key(key)
            self.assertNotIn(key,str(caught.exception))

    def test_agent_passes_trimmed_key_to_provider_constructor(self):
        with patch('sushi_budgeteer.agent.ChatOpenAI') as provider:
            BudgeteerAgent(api_key=' \nfixture-key\r\n')
        self.assertEqual(provider.call_args.kwargs['api_key'],'fixture-key')
        with patch.dict(os.environ,{'OPENAI_API_KEY':' \n','SUSHI_OPENAI_API_KEY':''}),patch('sushi_budgeteer.agent.ChatOpenAI') as provider:
            with self.assertRaises(InvalidAPIKeyFormat):BudgeteerAgent()
            provider.assert_not_called()

    def test_runner_blocks_malformed_key_before_agent_or_network_call(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'report.json'
            with patch.dict(os.environ,{'OPENAI_API_KEY':'fixture\nkey'}),patch.object(sys,'argv',['live_sessions','--output',str(path)]),patch.object(live_sessions,'BudgeteerAgent') as constructor:
                self.assertEqual(live_sessions.main(),2)
            constructor.assert_not_called()
            text=path.read_text();report=json.loads(text)
            self.assertEqual(report['status'],'blocked_invalid_credential_format')
            self.assertEqual(report['executed_turns'],0)
            self.assertFalse(report['live_llm_tested'])
            self.assertNotIn('fixture',text)
