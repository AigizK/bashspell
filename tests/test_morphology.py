import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bashspell_morphology import AnalysisLimitError, Morphology
from bashspell_morphology_labels import LABELS, legend_for

ROOT = Path(__file__).resolve().parents[1]
HAS_FASTAPI = importlib.util.find_spec('fastapi') is not None
if HAS_FASTAPI:
    from fastapi.testclient import TestClient
    import main


class MorphologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analyzer = Morphology(ROOT / 'static/hunspell/28.01.2024')

    def noun(self, word, stem='халыҡ'):
        return next(item for item in self.analyzer.analyze(word)['analyses']
                    if item['stem'] == stem and item['pos'] == ['Noun'])

    def test_requested_words_split_every_suffix(self):
        for word, ending, tag in [('халыҡтарҙыңмы', 'мы', 'Q'), ('халыҡтарҙыңдыр', 'дыр', 'Indf')]:
            with self.subTest(word=word):
                item = self.noun(word)
                self.assertEqual([part['text'] for part in item['parts']], ['халыҡ', 'тар', 'ҙың', ending])
                self.assertEqual(item['tags'], ['Pl', 'Gen', tag])

    def test_all_ambiguous_dictionary_bases_are_returned_without_duplicates(self):
        items = self.analyzer.analyze('халыҡтарҙың')['analyses']
        self.assertEqual({(a['stem'], tuple(a['pos'])) for a in items},
                         {('халыҡ', ('Noun',)), ('халыҡ', ('A',)), ('халыҡтар', ('Noun',))})
        self.assertEqual(len(items), 3)

    def test_long_nominal_word_has_all_six_parts(self):
        item = self.noun('китапханаларыбыҙҙағыларҙың', 'китапхана')
        self.assertEqual([p['text'] for p in item['parts']], ['китапхана', 'лар', 'ыбыҙ', 'ҙағы', 'лар', 'ҙың'])
        self.assertEqual(item['tags'], ['Pl', 'PxPl1', 'Der/дағы', 'Pl', 'Gen'])

    def test_voicing_changes_the_previous_part_not_the_new_suffix(self):
        item = next(a for a in self.analyzer.analyze('һүнмәҫлеге')['analyses'] if a['stem'] == 'һүн')
        self.assertEqual([p['text'] for p in item['parts']], ['һүн', 'мә', 'ҫ', 'лег', 'е'])
        self.assertEqual(item['tags'], ['Neg', 'Prc', 'Der/лыҡ', 'PxSg3'])
        self.assertIn({'from': 'к', 'to': 'г'}, item['changes'])
        book = self.noun('китабы', 'китап')
        self.assertEqual([p['text'] for p in book['parts']], ['китаб', 'ы'])
        self.assertEqual(book['changes'], [{'from': 'п', 'to': 'б'}])

    def test_real_grammar_path_beyond_hunspells_two_stages(self):
        word = 'китапханаланмағандарҙыңмы'
        item = self.noun(word, 'китапхана')
        self.assertGreater(len(item['steps']), 2)
        self.assertEqual(item['tags'], ['Der/ла', 'Pass', 'Neg', 'Prc/ған', 'Pl', 'Gen', 'Q'])
        self.assertEqual(''.join(p['text'] for p in item['parts']), word)
        if shutil.which('hunspell'):
            native = subprocess.run(['hunspell', '-d', str(ROOT / 'static/hunspell/28.01.2024/bash'), '-m'],
                                    input=word+'\n', text=True, capture_output=True, check=True)
            self.assertNotIn('st:', native.stdout)

    def test_forty_continuations_have_no_two_stage_or_short_depth_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            rows = ['SET UTF-8', 'FLAG num']
            for flag in range(1, 41):
                continuation = f'/{flag + 1}' if flag < 40 else ''
                rows += [f'SFX {flag} Y 1', f'SFX {flag} 0 а{continuation} . +T{flag}']
            (path / 'bash.aff').write_text('\n'.join(rows)+'\n')
            (path / 'bash.dic').write_text('1\nтамыр/1\t[Noun]\n')
            item = Morphology(path).analyze('тамыр' + 'а'*40)['analyses'][0]
            self.assertEqual(len(item['steps']), 40)
            self.assertEqual(len(item['tags']), 40)
            self.assertEqual(''.join(p['text'] for p in item['parts']), 'тамыр' + 'а'*40)

    def test_continuation_flags_and_conditions_cannot_be_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'bash.aff').write_text('SET UTF-8\nFLAG num\nSFX 1 Y 1\nSFX 1 0 а/2 р +A\nSFX 2 Y 1\nSFX 2 0 б . +B\nSFX 3 Y 1\nSFX 3 0 в . +C\n')
            (path / 'bash.dic').write_text('2\nтамыр/1\nташ/1\n')
            analyzer = Morphology(path)
            self.assertTrue(analyzer.analyze('тамыраб')['analyses'])
            for word in ['ташаб', 'тамырб', 'тамырав', 'билдәһеҙаб']:
                self.assertEqual(analyzer.analyze(word)['analyses'], [], word)

    def test_zero_transition_cycle_finishes_without_inventing_suffixes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'bash.aff').write_text('SET UTF-8\nFLAG num\nSFX 1 Y 1\nSFX 1 0 0/2\nSFX 2 Y 2\nSFX 2 0 0/1 .\nSFX 2 0 а . +Q\n')
            (path / 'bash.dic').write_text('1\nтамыр/1\n')
            items = Morphology(path).analyze('тамыра')['analyses']
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]['tags'], ['Q'])

    def test_budget_failure_never_returns_a_partial_analysis(self):
        with self.assertRaises(AnalysisLimitError):
            self.analyzer.paths('халыҡтарҙыңмы', max_states=1)

    def test_every_used_tag_has_a_bashkir_legend(self):
        used = {tag for rule in self.analyzer.rules for tag in rule.tags}
        used.update(tag for entries in self.analyzer.entries.values() for entry in entries for tag in entry.pos)
        self.assertFalse(used - LABELS.keys())
        legend = {item['tag']: item for item in legend_for(self.analyzer.analyze('халыҡтарҙыңмы')['analyses'])}
        self.assertEqual(legend['Pl']['label'], 'Күплек һан')
        self.assertEqual(legend['Gen']['label'], 'Эйәлек килеш')
        self.assertEqual(legend['Q']['label'], 'Һорау киҫәксәһе')

    def test_unknown_or_incomplete_words_have_no_guessed_result(self):
        for word in ['уйнған', 'эшлгән', 'тороуо', 'йцукенһығыҙҙыр', 'халыҡтарҙыңм']:
            self.assertEqual(self.analyzer.analyze(word)['analyses'], [], word)

    def test_all_parts_reconstruct_the_whole_word_including_capitals(self):
        words = ['Халыҡтарҙыңмы', 'ХАЛЫҠТАРҘЫҢДЫР', 'халыҡтарыбыҙҙыңмы', 'һүнмәҫлеге',
                 'өйҙәһегеҙ', 'уйнаған', 'йөрәк', 'йөрәгем', 'конькиҙәр', 'ағайыңмын',
                 'һүнмәҫлекләнмәгәндәрҙеңме']
        for word in words:
            items = self.analyzer.analyze(word)['analyses']
            self.assertTrue(items, word)
            for item in items:
                self.assertEqual(''.join(p['text'] for p in item['parts']), word)
                self.assertEqual([tag for p in item['parts'] for tag in p['tags']], item['tags'])

    def test_existing_grammar_regressions_also_hold_for_extended_analysis(self):
        for name in ['grammar-regressions-28.01.2024.txt', 'apertium-pr-4-5-regressions.txt', 'grammar-audit-2026-09-05.txt']:
            for line in (ROOT / 'tests/data' / name).read_text().splitlines():
                if not line.startswith(('+ ', '- ')):
                    continue
                marker, word = line.split(' ', 1)
                word = word.strip()
                with self.subTest(word=word):
                    items = self.analyzer.analyze(word)['analyses']
                    self.assertEqual(bool(items), marker == '+')
                    for item in items:
                        self.assertEqual(''.join(part['text'] for part in item['parts']), word)
                        self.assertEqual([tag for part in item['parts'] for tag in part['tags']], item['tags'])


@unittest.skipUnless(HAS_FASTAPI, 'requires FastAPI and httpx')
class MorphologyApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_api_returns_all_analyses_with_bashkir_legend(self):
        response = self.client.post('/analyze', json={'word': ' халыҡтарҙыңмы '})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['word'], 'халыҡтарҙыңмы')
        self.assertEqual(len(data['analyses']), 3)
        self.assertIn('Һорау киҫәксәһе', [item['label'] for item in data['legend']])

    def test_unknown_word_is_successful_empty_result_not_a_guess(self):
        response = self.client.post('/analyze', json={'word': 'йцукенһығыҙҙыр'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['analyses'], [])
        self.assertEqual(response.json()['legend'], [])

    def test_multiple_words_digits_markup_and_excessive_input_are_rejected(self):
        for word in ['', '   ', 'ике һүҙ', '<script>', '123', 'һүҙ\nһүҙ', 'а'*257]:
            self.assertEqual(self.client.post('/analyze', json={'word': word}).status_code, 422, word)

    def test_resource_limit_is_an_error_not_an_incomplete_result(self):
        with patch.object(main.Morphology, 'analyze', side_effect=AnalysisLimitError):
            response = self.client.post('/analyze', json={'word': 'халыҡтарҙың'})
            self.assertEqual(response.status_code, 503)

    def test_analysis_works_independently_of_native_hunspell_availability(self):
        with patch.object(main, 'hobj', None):
            response = self.client.post('/analyze', json={'word': 'халыҡтарҙыңдыр'})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()['analyses'])


if __name__ == '__main__':
    unittest.main()
