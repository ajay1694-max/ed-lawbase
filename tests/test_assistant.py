"""Meaningful source, privacy, budget and provider contract checks; no paid calls."""
import concurrent.futures
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import assistant

SOURCES = [{'id': 'S1', 'case_id': 'public', 'extracts': [{'passage': 1, 'text':
    'The grounds of arrest must be supplied in writing to the arrested person.'}]}]
ANSWER = {'points': [{'text': 'Written grounds are required in this extract.', 'sources': ['S1'],
    'quote': 'The grounds of arrest must be supplied in writing'}], 'limitations': 'Check later history.', 'questions': []}


class AssistantTests(unittest.TestCase):
    def setUp(self):
        assistant.CACHE.clear()

    def test_private_question_and_opt_in(self):
        with self.assertRaises(ValueError):
            assistant.validate_question({'question': 'When can officers arrest?'})
        with self.assertRaises(ValueError):
            assistant.validate_question({'question': 'Can arrest be made for ECIR/TEST/1/2026?', 'public_question': True})
        self.assertEqual(assistant.validate_question({'question': 'What does section 32A require?', 'public_question': True}), 'What does section 32A require?')

    def test_citations_and_quotes_must_exist(self):
        self.assertEqual(assistant.checked(ANSWER, SOURCES), ANSWER)
        for point in ({'text': 'x', 'sources': ['S99'], 'quote': 'This is an invented judgment passage'},
                      {'text': 'x', 'sources': ['S1'], 'quote': 'This is an invented judgment passage'},
                      {'text': 'x', 'sources': 'S1', 'quote': 'The grounds of arrest must be supplied'}):
            with self.assertRaises(ValueError):
                assistant.checked({**ANSWER, 'points': [point]}, SOURCES)
        with self.assertRaises(ValueError):
            assistant.checked([], SOURCES)

    def test_budget_is_atomic_and_cached_answers_are_free(self):
        with tempfile.TemporaryDirectory() as root:
            assistant.status(root)  # initialize the fixture ledger before racing
            with patch.dict(assistant.POLICY, monthly_budget_usd=0.001):
                def reserve(n):
                    try:
                        assistant.reserve(root, str(n), 700)
                        return True
                    except ValueError:
                        return False
                with concurrent.futures.ThreadPoolExecutor(4) as pool:
                    self.assertEqual(sum(pool.map(reserve, range(4))), 1)
            with patch.object(assistant, 'key', return_value='fixture-not-a-real-key'), patch.object(assistant, 'provider', return_value=ANSWER) as model:
                first = assistant.ask(root, 'alice', 'grounds of arrest', SOURCES, 1)
                second = assistant.ask(root, 'alice', 'grounds of arrest', SOURCES, 1)
                self.assertEqual(model.call_count, 1)
                self.assertTrue(second['cached'])
                self.assertEqual(first['model'], 'gpt-6-luna')

    def test_failures_do_not_retry_upgrade_or_reveal_keys(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.object(assistant, 'key', return_value='fixture-secret'), patch.object(assistant, 'provider', side_effect=ValueError('AI service unavailable.')) as model:
                result = assistant.ask(root, 'alice', 'grounds of arrest', SOURCES, 1)
                self.assertEqual(model.call_count, 1)
                self.assertNotIn('fixture-secret', json.dumps(result))
                self.assertTrue(result['sources'])

    def test_public_only_retrieval_even_with_attached_private_database(self):
        c = sqlite3.connect(':memory:'); c.row_factory = sqlite3.Row
        c.executescript('''CREATE TABLE cases(case_id,title,citation,court,decision_date,source_url,acts);
          CREATE TABLE chunks(rowid INTEGER PRIMARY KEY,case_id,chunk_index,text);
          CREATE VIRTUAL TABLE chunks_fts USING fts5(text);
          INSERT INTO cases VALUES ('public','Pankaj Bansal','Public citation','Court','2023','https://example.org','PMLA');
          INSERT INTO chunks VALUES(1,'public',0,'The grounds of arrest must be supplied in writing.');
          INSERT INTO chunks_fts(rowid,text) SELECT rowid,text FROM chunks;
          ATTACH DATABASE ':memory:' AS internal;
          CREATE TABLE internal.chunks(text); INSERT INTO internal.chunks VALUES('PRIVATE CANARY');''')
        try:
            result = assistant.retrieval(c, 'When must grounds of arrest be supplied in writing?')
            self.assertEqual(result[0]['case_id'], 'public')
            self.assertNotIn('PRIVATE CANARY', json.dumps(result))
        finally:
            c.close()

    def test_provider_request_is_cheap_bounded_and_stateless(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit):
                return json.dumps({'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(ANSWER)}]}]}).encode()
        with patch.object(assistant.urllib.request, 'urlopen', return_value=Response()) as request:
            self.assertEqual(assistant.provider('fixture-only', 'public question'), ANSWER)
            payload = json.loads(request.call_args.args[0].data)
            self.assertEqual(payload['model'], 'gpt-6-luna')
            self.assertFalse(payload['store'])
            self.assertEqual(payload['reasoning']['effort'], 'none')
            self.assertEqual(payload['max_output_tokens'], 1200)
            self.assertTrue(payload['text']['format']['strict'])


if __name__ == '__main__': unittest.main()
