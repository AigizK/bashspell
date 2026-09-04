from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLI = PROJECT_ROOT / "bashspell"
GRAMMAR_REGRESSIONS = (
    PROJECT_ROOT / "tests" / "data" / "grammar-regressions-28.01.2024.txt"
)
APERTIUM_REGRESSIONS = (
    PROJECT_ROOT / "tests" / "data" / "apertium-pr-4-5-regressions.txt"
)
HAS_HUNSPELL = shutil.which("hunspell") is not None


def run_cli(*arguments: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(CLI), *arguments],
        cwd=PROJECT_ROOT,
        input=input_text,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


@unittest.skipUnless(HAS_HUNSPELL, "requires the hunspell executable")
class BashspellCliTests(unittest.TestCase):
    def test_short_check_form_and_exit_status(self) -> None:
        completed = run_cli("башҡорт", "башкорд")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("✓ башҡорт", completed.stdout)
        self.assertIn("✗ башкорд", completed.stdout)

    def test_json_text_counts_repeated_misspellings(self) -> None:
        completed = run_cli("--json", "text", "башкорд башкорд башҡорт")
        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertEqual(
            payload["summary"],
            {"checked": 3, "correct": 1, "incorrect": 2},
        )

    def test_rule_expectations(self) -> None:
        completed = run_cli(
            "test",
            "--valid",
            "башҡорт",
            "башҡорттар",
            "--invalid",
            "башкорд",
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_dictionary_entry_and_affix_rule_lookup(self) -> None:
        entry = run_cli("entry", "башҡорт")
        self.assertEqual(entry.returncode, 0)
        self.assertIn("башҡорт/109", entry.stdout)
        self.assertIn("флаги: N15", entry.stdout)

        rule = run_cli("rule", "N15")
        self.assertEqual(rule.returncode, 0)
        self.assertIn("[N15 → 109]", rule.stdout)
        self.assertIn("SFX 109 Y 31", rule.stdout)
        self.assertIn("+Pl", rule.stdout)

    def test_validate_detects_a_missing_case_ending(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dictionary = Path(directory)
            (dictionary / "bash.aff").write_text(
                "SET UTF-8\n"
                "FLAG UTF-8\n"
                "SFX A Y 6\n"
                "SFX A 0 тар . +Pl\n"
                "SFX A 0 тар . +Pl+Acc\n"
                "SFX A 0 ымдыҡынан . +PxSg1+Poss+Acc\n"
                "SFX A 0 ыбыҙҙыңмылыр . +PxPl1+Q+Indf\n"
                "SFX A 0 лар [^н][^гк] +Pl\n"
                "SFX A 0 ылар [а][м][п] +Pl\n",
                encoding="utf-8",
            )
            (dictionary / "bash.dic").write_text(
                "1\nбашҡорт/A\n",
                encoding="utf-8",
            )

            completed = run_cli("--dict", directory, "--json", "validate")

        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["valid"])
        self.assertTrue(
            any(
                "пропущено окончание +Acc" in issue["message"]
                for issue in payload["issues"]
            )
        )
        self.assertTrue(
            any("вероятно, требуется +Abl" in issue["message"] for issue in payload["issues"])
        )
        self.assertTrue(
            any("пропущен тег +Gen" in issue["message"] for issue in payload["issues"])
        )
        self.assertTrue(
            any("условия `[^н][^гк]`" in issue["message"] for issue in payload["issues"])
        )

    def test_latest_dictionary_matches_grammar_regressions(self) -> None:
        completed = run_cli("test", "--file", str(GRAMMAR_REGRESSIONS))
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("Итого: 125; провалено: 0", completed.stdout)

    def test_latest_dictionary_matches_apertium_regressions(self) -> None:
        completed = run_cli("test", "--file", str(APERTIUM_REGRESSIONS))
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("Итого: 42; провалено: 0", completed.stdout)

    def test_apertium_homographs_are_not_noun_plural_analyses(self) -> None:
        for wrong_plural, correct_plural, noun, verb in (
            ("заказлар", "заказдар", "заказ", "заказла"),
            ("йыһазлар", "йыһаздар", "йыһаз", "йыһазла"),
        ):
            with self.subTest(word=wrong_plural):
                wrong = run_cli("analyze", wrong_plural)
                self.assertEqual(wrong.returncode, 0, wrong.stderr)
                self.assertIn(f"st:{verb} [Verb]", wrong.stdout)
                self.assertNotIn(f"st:{noun} [Noun] +Pl", wrong.stdout)

                correct = run_cli("analyze", correct_plural)
                self.assertEqual(correct.returncode, 0, correct.stderr)
                self.assertIn(f"st:{noun} [Noun] +Pl", correct.stdout)

    def test_latest_dictionary_morphology_regressions(self) -> None:
        plural = run_cli("analyze", "малымдар")
        self.assertEqual(plural.returncode, 0, plural.stderr)
        self.assertIn("+PxSg1+Pl", plural.stdout)
        self.assertNotIn("+PxSg1+Pl+Acc", plural.stdout)

        accusative = run_cli("analyze", "малымдарҙы")
        self.assertEqual(accusative.returncode, 0, accusative.stderr)
        self.assertIn("+PxSg1+Pl+Acc", accusative.stdout)

        ablative = run_cli("analyze", "малымдыҡынан")
        self.assertEqual(ablative.returncode, 0, ablative.stderr)
        self.assertIn("+PxSg1+Poss+Abl", ablative.stdout)
        self.assertNotIn("+PxSg1+Poss+Acc", ablative.stdout)

        genitive = run_cli("analyze", "малыбыҙҙыңмылыр")
        self.assertEqual(genitive.returncode, 0, genitive.stderr)
        self.assertIn("+PxPl1+Gen+Q+Indf", genitive.stdout)


if __name__ == "__main__":
    unittest.main()
