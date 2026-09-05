"""Regression checks for the fast spellcheck path and the legacy API."""
import importlib.util
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
