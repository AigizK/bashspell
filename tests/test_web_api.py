"""Regression checks for the fast spellcheck path and the legacy API."""
import importlib.util
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

HAS_FASTAPI = importlib.util.find_spec('fastapi') is not None
if HAS_FASTAPI:
    from fastapi.testclient import TestClient
    import main


@unittest.skipUnless(HAS_FASTAPI, 'requires FastAPI and httpx')
class WebApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = Mock()
        self.engine.spell.side_effect = lambda word: word == 'башҡорт'
        self.engine.suggest.return_value = ['башҡорт']
        self.hunspell = patch.object(main, 'hobj', self.engine)
        self.db = patch.object(main, 'save_to_sqlite_db')
        self.hunspell.start()
        self.save = self.db.start()
        main.is_correct.cache_clear()
        main.suggestions.cache_clear()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        self.db.stop()
        self.hunspell.stop()
        main.is_correct.cache_clear()
        main.suggestions.cache_clear()

    def test_fast_check_preserves_order_and_does_not_generate_suggestions(self):
        response = self.client.post('/data_processing', json={
            'unverified_words': ['башкорд', 'башҡорт', 'башкорд'],
            'include_suggestions': False,
        })
        self.assertEqual(response.status_code, 200)
        items = response.json()['message']
        self.assertEqual([item['word'] for item in items], ['башкорд', 'башҡорт', 'башкорд'])
        self.assertEqual([item['correct'] for item in items], [False, True, False])
        self.assertEqual(self.engine.spell.call_count, 2)
        self.engine.suggest.assert_not_called()
        self.save.assert_not_called()

    def test_legacy_call_still_returns_suggestions_and_saves_counts(self):
        response = self.client.post('/data_processing', json={'unverified_words': ['башкорд', 'башҡорт']})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['variants'] for item in response.json()['message']], [['башҡорт'], []])
        self.save.assert_called_once()

    def test_click_suggestions_are_cached_across_requests(self):
        for _ in range(2):
            response = self.client.post('/suggestions', json={'word': 'башкорд'})
            self.assertEqual(response.json()['variants'], ['башҡорт'])
        self.engine.spell.assert_called_once_with('башкорд')
        self.engine.suggest.assert_called_once_with('башкорд')

    def test_unknown_word_without_suggestions_is_still_incorrect(self):
        self.engine.suggest.return_value = []
        response = self.client.post('/data_processing', json={'unverified_words': ['хххх']})
        self.assertEqual(response.json()['message'][0], {'word': 'хххх', 'correct': False, 'variants': []})

    def test_missing_hunspell_is_an_error_not_fake_success(self):
        with patch.object(main, 'hobj', None):
            for path, data in [('/data_processing', {'unverified_words': ['башҡорт']}), ('/suggestions', {'word': 'башҡорт'})]:
                self.assertEqual(self.client.post(path, json=data).status_code, 503)
        self.save.assert_not_called()

    def test_ignored_tokens_do_not_call_hunspell(self):
        response = self.client.post('/data_processing', json={
            'unverified_words': ['БР', 'респ', '1941-ҙән'], 'include_suggestions': False,
        })
        self.assertTrue(all(item['correct'] for item in response.json()['message']))
        self.engine.spell.assert_not_called()

    def test_full_text_returns_only_distinct_errors_in_first_occurrence_order(self):
        self.engine.suggest.side_effect = lambda word: ['башҡорт'] if word == 'башкорд' else ['һүҙ']
        response = self.client.post('/api/v1/spellcheck', json={
            'text': 'башҡорт, башкорд!\nһүҙҙ башкорд — башҡорт.',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'errors': [
                {'word': 'башкорд', 'suggestions': ['башҡорт']},
                {'word': 'һүҙҙ', 'suggestions': ['һүҙ']},
            ],
            'message': 'Найдены ошибки',
        })
        self.assertEqual(self.engine.spell.call_count, 3)
        self.assertEqual(self.engine.suggest.call_count, 2)
        self.save.assert_not_called()

    def test_full_text_no_errors_has_an_explicit_success_response(self):
        for text in ['башҡорт башҡорт.', '123! 🙂', 'БР респ. 1941-ҙән М.']:
            with self.subTest(text=text):
                response = self.client.post('/api/v1/spellcheck', json={'text': text})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {'errors': [], 'message': 'Ошибок нет'})
        self.engine.suggest.assert_not_called()
        self.save.assert_not_called()

    def test_full_text_error_without_suggestions_is_not_omitted(self):
        self.engine.suggest.return_value = []
        response = self.client.post('/api/v1/spellcheck', json={'text': 'хххх башҡорт хххх'})
        self.assertEqual(response.json(), {
            'errors': [{'word': 'хххх', 'suggestions': []}],
            'message': 'Найдены ошибки',
        })

    def test_full_text_preserves_case_and_normalizes_unicode(self):
        response = self.client.post('/api/v1/spellcheck', json={'text': 'ба\u0438\u0306рам Байрам байрам'})
        self.assertEqual([item['word'] for item in response.json()['errors']], ['байрам', 'Байрам'])
        self.assertEqual(self.engine.spell.call_count, 2)

    def test_full_text_handles_quoted_suffixes_numbers_and_initials(self):
        self.engine.spell.side_effect = lambda word: word in ['Данаяның', 'башҡорт', 'ике-өс']
        response = self.client.post('/api/v1/spellcheck', json={
            'text': '1941-ҙән 20-нән «Даная»ның респ. БР М. башҡорт ике-өс башкорд',
        })
        self.assertEqual(response.json()['errors'], [{'word': 'башкорд', 'suggestions': ['башҡорт']}])
        self.assertEqual([call.args[0] for call in self.engine.spell.call_args_list],
                         ['Данаяның', 'башҡорт', 'ике-өс', 'башкорд'])

    def test_full_text_accepts_5000_unicode_code_points_not_bytes(self):
        text = '🙂' * 4992 + ' башҡорт'
        self.assertEqual(len(text), 5000)
        self.assertGreater(len(text.encode('utf-8')), 5000)
        response = self.client.post('/api/v1/spellcheck', json={'text': text})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['errors'], [])
        self.engine.spell.assert_called_once_with('башҡорт')

    def test_full_text_rejects_overlong_input_before_normalizing_or_checking(self):
        with patch.object(main, 'extract_words') as tokenize:
            for text in ['башҡорт' + ' ' * 4994, '🙂' * 5001, 'и\u0306' * 2501]:
                with self.subTest(length=len(text)):
                    response = self.client.post('/api/v1/spellcheck', json={'text': text})
                    self.assertEqual(response.status_code, 422)
            tokenize.assert_not_called()
        self.engine.spell.assert_not_called()
        self.engine.suggest.assert_not_called()

    def test_full_text_rejects_blank_missing_non_string_and_invalid_json(self):
        for data in [{}, {'text': ''}, {'text': ' \n\t'}, {'text': None},
                     {'text': 123}, {'text': True}, {'text': ['башҡорт']}]:
            with self.subTest(data=data):
                self.assertEqual(self.client.post('/api/v1/spellcheck', json=data).status_code, 422)
        response = self.client.post('/api/v1/spellcheck', content='{"text":',
                                    headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 422)
        self.engine.spell.assert_not_called()
        self.save.assert_not_called()

    def test_full_text_reuses_suggestion_cache_between_requests(self):
        for text in ['башкорд башкорд', 'башҡорт! башкорд']:
            response = self.client.post('/api/v1/spellcheck', json={'text': text})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()['errors']), 1)
        self.engine.suggest.assert_called_once_with('башкорд')

    def test_full_text_unavailable_engine_never_claims_no_errors(self):
        with patch.object(main, 'hobj', None):
            for text in ['башҡорт', '123!']:
                response = self.client.post('/api/v1/spellcheck', json={'text': text})
                self.assertEqual(response.status_code, 503)
                self.assertNotIn('errors', response.json())

    def test_agent_instructions_are_available_as_plain_text_and_html_comment(self):
        response = self.client.get('/llms.txt')
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/plain', response.headers['content-type'])
        instructions = response.text
        self.assertIn('POST https://tiksher.eu/api/v1/spellcheck', instructions)
        self.assertIn('5000', instructions)
        self.assertIn('{"errors":[],"message":"Ошибок нет"}', instructions)
        self.assertNotIn('--', instructions)  # Must remain a valid HTML comment.
        home = self.client.get('/')
        self.assertEqual(home.status_code, 200)
        comments = re.findall(r'<!--(.*?)-->', home.text, flags=re.DOTALL)
        self.assertTrue(any(instructions in comment for comment in comments))
        self.assertIn('href="/llms.txt"', home.text)

    def test_full_text_openapi_exposes_input_limit_and_structured_response(self):
        schema = self.client.get('/openapi.json').json()
        operation = schema['paths']['/api/v1/spellcheck']['post']
        self.assertEqual(set(operation['responses']), {'200', '422', '503'})
        models = schema['components']['schemas']
        text_schema = models['TextCheckRequest']['properties']['text']
        self.assertEqual((text_schema['type'], text_schema['minLength'], text_schema['maxLength']),
                         ('string', 1, 5000))
        self.assertEqual(set(models['TextCheckResponse']['properties']), {'errors', 'message'})
        self.assertEqual(set(models['SpellingError']['properties']), {'word', 'suggestions'})

    def test_database_retains_variant_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            import sqlite3
            connect = sqlite3.connect
            with patch.object(main.sqlite3, 'connect', side_effect=lambda _: connect(Path(directory) / 'text.db')):
                # Call the original function, outside the persistence mock.
                self.db.stop()
                main.save_to_sqlite_db([{'word': 'башкорд', 'variants': ['башҡорт']}], 'test')
                with connect(Path(directory) / 'text.db') as connection:
                    self.assertEqual(connection.execute('SELECT word, count_of_variants FROM words').fetchall(), [('башкорд', 1)])
                self.db.start()


if __name__ == '__main__':
    unittest.main()
