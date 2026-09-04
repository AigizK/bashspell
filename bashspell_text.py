"""Shared tokenization and conservative abbreviation handling for Bashspell."""

from __future__ import annotations

import re
import unicodedata


LETTER = r"[^\W\d_]"
WORD_RE = re.compile(rf"{LETTER}+(?:[-'’]{LETTER}+)*", re.UNICODE)
QUOTED_SUFFIX_RE = re.compile(
    rf"[«“„\"](?P<base>{LETTER}+(?:[-'’]{LETTER}+)*)[»”\"]"
    rf"(?P<suffix>{LETTER}+)",
    re.UNICODE,
)

# These are editorial abbreviations seen repeatedly in the encyclopedia part
# of AigizK/bashkir-russian-parallel-corpora.  The list is deliberately exact:
# ordinary lowercase words and arbitrary all-caps tokens still reach Hunspell.
LOWERCASE_ABBREVIATIONS = frozenset(
    {
        "авг",
        "акад",
        "басс",
        "биол",
        "гәз",
        "геол",
        "гр",
        "ғин",
        "губерн",
        "диам",
        "див",
        "дир",
        "етәкс",
        "иҡт",
        "каф",
        "кг",
        "км",
        "ком",
        "лаб",
        "м",
        "мәҫ",
        "мед",
        "млн",
        "млрд",
        "мм",
        "муз",
        "нач",
        "нефтехим",
        "окт",
        "өлк",
        "орд",
        "респ",
        "реж",
        "сент",
        "см",
        "соц",
        "станц",
        "т",
        "терр",
        "февр",
        "проф",
        "ҡсб",
    }
)

UPPERCASE_ABBREVIATIONS = frozenset(
    {
        "ААЙ",
        "АССР",
        "БАССР",
        "БДУ",
        "БР",
        "БССР",
        "ВИЧ",
        "ҒПП",
        "КПСС",
        "ПОЛИЭФ",
        "РСФСР",
        "РФ",
        "СДПА",
        "СССР",
        "ФДУП",
        "ЭЭМ",
        "ЮНЕСКО",
        "ӨДАТУ",
    }
)

_COMPONENT_CHARS = frozenset("-'’‐‑‒–—―")


def normalize_text(text: str) -> str:
    """Normalize Unicode and rejoin a quoted name with its case suffix."""
    normalized = unicodedata.normalize("NFC", text)
    return QUOTED_SUFFIX_RE.sub(
        lambda match: match.group("base") + match.group("suffix"), normalized
    )


def _belongs_to_numeric_component(text: str, start: int, end: int) -> bool:
    """Return true for fragments extracted from forms such as ``1941-ҙән``."""
    left = start
    while left and (text[left - 1].isalnum() or text[left - 1] in _COMPONENT_CHARS):
        left -= 1
    right = end
    while right < len(text) and (
        text[right].isalnum() or text[right] in _COMPONENT_CHARS
    ):
        right += 1
    return any(character.isdigit() for character in text[left:right])


def extract_words(text: str) -> list[str]:
    """Extract spellcheckable words without manufacturing suffix fragments."""
    normalized = normalize_text(text)
    words: list[str] = []
    for match in WORD_RE.finditer(normalized):
        word = match.group(0)
        if _belongs_to_numeric_component(normalized, match.start(), match.end()):
            continue
        # A single letter followed by a full stop is an initial or an editorial
        # abbreviation.  Bare one-letter words still go through Hunspell.
        if len(word) == 1 and match.end() < len(normalized):
            if normalized[match.end()] == ".":
                continue
        words.append(word)
    return words


def should_ignore_word(word: str) -> bool:
    """Return whether an exact token belongs to the conservative whitelist."""
    normalized = unicodedata.normalize("NFC", word).strip()
    if not normalized:
        return True
    if any(character.isdigit() for character in normalized):
        return True
    if normalized.casefold() in LOWERCASE_ABBREVIATIONS:
        return True
    if normalized in UPPERCASE_ABBREVIATIONS:
        return True
    return False
