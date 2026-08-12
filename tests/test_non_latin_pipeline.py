"""The whole path has to work in the language the session is written in.

Four separate places were Latin-only, each found after the previous one was
patched: the topic slug, the retrieval tokenizer, the decision floor, and the
secret-word redaction cue. Naming one more alphabet each time only moves the
blind spot to the next language, so the tokenizer is now a Unicode class and the
word lists carry the languages the fleet actually speaks. These tests fail
against the version before this commit.
"""

import unittest

from claimkeep.config import Config
from claimkeep.harvesters import retraction as R
from claimkeep.harvesters.regex_floor import RegexFloorHarvester
from claimkeep.redact import redact
from claimkeep.retrieve import TOKEN_RE


class TokenizerCoversEveryScript(unittest.TestCase):
    """A latin-only tokenizer made a whole corpus invisible to search."""

    CASES = [
        ("русский", "ночной бэкап памяти флота"),
        ("greek", "το αρχείο βρίσκεται εδώ"),
        ("chinese", "服务器在四点重启"),
        ("hebrew", "השרת מופעל מחדש"),
        ("latin", "the retry ceiling is 5"),
    ]

    def test_every_script_produces_tokens(self):
        for label, text in self.CASES:
            with self.subTest(script=label):
                self.assertTrue(TOKEN_RE.findall(text.casefold()))

    def test_underscore_does_not_glue_words(self):
        self.assertEqual(TOKEN_RE.findall("db_password"), ["db", "password"])


class FloorCatchesRussianDecisions(unittest.TestCase):
    """The floor exists to catch lines nobody marked; it caught none in Russian."""

    def _hit(self, line):
        return bool(RegexFloorHarvester().harvest([line], Config()))

    def test_russian_decision_markers(self):
        for line in (
            "РЕШЕНИЕ: поправить порядок EnvironmentFile",
            "Решение: не трогать инлайн-переменные юнита",
            "ВЫВОД: гейтвей читает токен не оттуда",
            "Решили оставить порог ретраев на четырёх",
            "Выбрали Vertex вместо AI Studio",
            "Договорились не трогать телефонию",
        ):
            with self.subTest(line=line):
                self.assertTrue(self._hit(line))

    def test_english_still_works(self):
        self.assertTrue(self._hit("DECISION: fix the EnvironmentFile order"))

    def test_ordinary_russian_prose_is_not_a_decision(self):
        self.assertFalse(self._hit("Проверяю логи гейтвея"))


class RetractionCatchesRussianCorrections(unittest.TestCase):
    """A missed retraction leaves the refuted claim alive — the worst outcome."""

    def test_russian_correction_cues(self):
        for line in (
            "Исправление: дело в пути к токену",
            "Уточнение: порт ни при чём",
            "Поправка: привязка порта в порядке",
            "Не подтвердилось, причина в другом",
        ):
            with self.subTest(line=line):
                self.assertTrue(R._is_retraction(line))

    def test_plain_work_is_not_a_retraction(self):
        self.assertFalse(R._is_retraction("Проверяю логи гейтвея"))


class RedactionCueIsNotEnglishOnly(unittest.TestCase):
    """A secret leaked in Russian while the identical English sentence was masked."""

    def test_russian_cue_words_mask_the_blob(self):
        for line in (
            "секрет wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY лежит там",
            "токен AbCdEf1234567890AbCdEf1234 в конфиге",
            "пароль QwErTy1234567890QwErTy1234 от базы",
        ):
            with self.subTest(line=line):
                out = redact(line)
                self.assertIn("[REDACTED:secret]", out)

    def test_english_cue_still_works(self):
        self.assertIn(
            "[REDACTED:secret]", redact("secret wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLE")
        )

    def test_prose_is_left_alone_in_both_languages(self):
        for line in (
            "секрет успеха в простоте",
            "ключ к решению найден",
            "the secret sauce is simplicity",
        ):
            with self.subTest(line=line):
                self.assertEqual(redact(line), line)


if __name__ == "__main__":
    unittest.main()
