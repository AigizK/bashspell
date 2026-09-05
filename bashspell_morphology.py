"""Explain complete suffix paths in the project's numeric-flag Hunspell grammar.

This reader deliberately supports the format used by this dictionary, rather
than claiming to implement every Hunspell option. Unlike Hunspell's two-stage
matcher, it follows continuation flags until it reaches a dictionary entry.
Every returned analysis consumes the complete input and reconstructs it exactly.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
import unicodedata


class AnalysisLimitError(Exception):
    """The search could not finish; do not present a partial list as complete."""


@dataclass(frozen=True, slots=True)
class Entry:
    word: str
    flags: frozenset[int]
    pos: tuple[str, ...]
    form: str


@dataclass(frozen=True, slots=True)
class Rule:
    flag: int
    strip: str
    add: str
    following: frozenset[int]
    condition: re.Pattern
    tags: tuple[str, ...]
    line: int

    def apply(self, word: str) -> str | None:
        if not word.endswith(self.strip) or len(word) <= len(self.strip):
            return None
        if not self.condition.search(word):
            return None
        return (word[:-len(self.strip)] if self.strip else word) + self.add


@dataclass(frozen=True, slots=True)
class Analysis:
    entry: Entry
    rules: tuple[Rule, ...]

    @property
    def tags(self):
        return tuple(tag for rule in self.rules for tag in rule.tags)


def canonical_tag(tag: str) -> str:
    # Two spelling inconsistencies in the source grammar, not extra categories.
    return {'PL': 'Pl', 'Locl': 'Loc'}.get(tag, tag)


VOICING = {'ҡ': 'ғ', 'к': 'г', 'п': 'б', 'т': 'д'}


def is_surface_prefix(prefix: str, word: str) -> bool:
    if word.startswith(prefix):
        return True
    # An intermediate -лек can become -лег- before a vowel. Its boundary stays
    # at the same position; the changed sound is explained separately below.
    return bool(prefix and prefix[-1] in VOICING and
                word.startswith(prefix[:-1] + VOICING[prefix[-1]]))


class Morphology:
    def __init__(self, directory: Path):
        self.entries: dict[str, list[Entry]] = defaultdict(list)
        self.endings: dict[str, list[Rule]] = defaultdict(list)
        self.tag_prefixes: dict[tuple[int, tuple[str, ...]], list[Rule]] = defaultdict(list)
        self.rules: list[Rule] = []
        text = (directory / 'bash.aff').read_text(encoding='utf-8')
        patterns = {}
        flag_sets = {}
        case_prefixes = []

        def flags(value):
            if value not in flag_sets:
                flag_sets[value] = frozenset(int(flag) for flag in value.split(',') if flag)
            return flag_sets[value]

        directives = set()
        for line_number, line in enumerate(text.splitlines(), 1):
            fields = line.split()
            if not fields or fields[0].startswith('#'):
                continue
            if fields[0] == 'PFX':
                if fields[2] in ('Y', 'N'):
                    continue
                # The project's only prefix class changes the initial case of
                # proper names. Preserve its flag restriction on dictionary entries.
                if (len(fields) != 5 or len(fields[2]) != 1 or len(fields[3]) != 1
                        or fields[2].lower() != fields[3].lower()):
                    raise ValueError('Unsupported non-casing prefix rule')
                case_prefixes.append((int(fields[1]), fields[2], fields[3], re.compile('^(?:' + fields[4] + ')')))
                continue
            if fields[0] != 'SFX':
                directives.add(fields[0])
                if fields[0] == 'FLAG' and fields[1] != 'num':
                    raise ValueError('Morphology requires numeric Hunspell flags')
                continue
            if fields[2] in ('Y', 'N'):
                continue
            flag, stripped, addition = fields[1:4]
            # Hunspell treats an omitted condition as '.', including four
            # existing zero transitions in this dictionary (native probe tested).
            condition = fields[4] if len(fields) > 4 else '.'
            added, _, continuation = addition.partition('/')
            if condition not in patterns:
                patterns[condition] = re.compile('(?:' + condition + ')$')
            rule = Rule(int(flag), '' if stripped == '0' else stripped,
                        '' if added == '0' else added, flags(continuation),
                        patterns[condition], tuple(canonical_tag(tag) for tag in
                        re.findall(r'\+([^+\s]+)', ''.join(fields[5:]))), line_number)
            self.rules.append(rule)
            self.endings[rule.add].append(rule)
            self.tag_prefixes[rule.flag, rule.tags].append(rule)
            # The source's negative future participle also supplies a proven
            # boundary inside generated +Neg+Prc+Der/лыҡ rules (-мә + ҫ + лек).
            if rule.tags == ('Prc/маҫ',):
                self.tag_prefixes[rule.flag, ('Neg', 'Prc')].append(rule)
        unsupported = directives - {'SET', 'FLAG', 'TRY', 'REP', 'WORDCHARS'}
        if unsupported:
            raise ValueError('Unsupported morphology directives: ' + ', '.join(sorted(unsupported)))
        for line in (directory / 'bash.dic').read_text(encoding='utf-8').splitlines()[1:]:
            fields = line.split()
            if not fields:
                continue
            word, _, entry_flags = fields[0].partition('/')
            entry = Entry(word, flags(entry_flags), tuple(re.findall(r'\[([^\]]+)\]', ' '.join(fields[1:]))), word)
            self.entries[word].append(entry)
            for flag, stripped, added, condition in case_prefixes:
                if flag in entry.flags and word.startswith(stripped) and condition.search(word):
                    form = added + word[len(stripped):]
                    self.entries[form].append(Entry(word, entry.flags, entry.pos, form))

    def paths(self, word: str, *, max_states=30000, max_paths=5000) -> tuple[Analysis, ...]:
        active = set()
        states = 0

        @lru_cache(maxsize=None)
        def visit(form: str, following: int | None) -> tuple[Analysis, ...]:
            nonlocal states
            states += 1
            if states > max_states:
                raise AnalysisLimitError('Morphology search exceeded its work budget')
            state = (form, following)
            active.add(state)
            found = {}

            def remember(analysis):
                key = (analysis.entry.word, analysis.entry.pos, analysis.tags)
                previous = found.get(key)
                # Prefer the path with more explicit grammatical steps when
                # compiled and uncompiled paths express the same analysis.
                if previous is None or sum(bool(r.tags) for r in analysis.rules) > sum(bool(r.tags) for r in previous.rules):
                    found[key] = analysis
                if len(found) > max_paths:
                    raise AnalysisLimitError('Too many distinct analyses to return completely')

            for entry in self.entries.get(form, ()):
                if following is None or following in entry.flags:
                    remember(Analysis(entry, ()))
            for width in range(len(form) + 1):
                for rule in self.endings.get(form[-width:] if width else '', ()):
                    if following is not None and following not in rule.following:
                        continue
                    parent = (form[:-width] if width else form) + rule.strip
                    if (parent, rule.flag) in active or rule.apply(parent) != form:
                        continue
                    for prefix in visit(parent, rule.flag):
                        remember(Analysis(prefix.entry, prefix.rules + (rule,)))
            active.remove(state)
            return tuple(found.values())

        return visit(word, None)

    def split_addition(self, before: str, rule: Rule, start: int) -> list[dict]:
        """Split a bundled addition only at boundaries proven by prefix rules."""
        after = rule.apply(before)
        boundaries = [(0, start)]
        for index in range(1, len(rule.tags)):
            lengths = set()
            for prefix in self.tag_prefixes.get((rule.flag, rule.tags[:index]), ()):
                intermediate = prefix.apply(before)
                if intermediate and len(intermediate) >= start and is_surface_prefix(intermediate, after):
                    lengths.add(len(intermediate))
            # Ambiguous boundaries stay grouped instead of inventing morphemes.
            if len(lengths) == 1:
                end = lengths.pop()
                if boundaries[-1][1] <= end <= len(after):
                    boundaries.append((index, end))
        boundaries.append((len(rule.tags), len(after)))
        return [{'text': after[left:right], 'tags': list(rule.tags[begin:end]), 'kind': 'suffix'}
                for (begin, left), (end, right) in zip(boundaries, boundaries[1:])
                if left != right or begin != end]

    def explain(self, analysis: Analysis, surface: str) -> dict:
        entry = analysis.entry
        pieces = [{'text': entry.form, 'tags': [], 'kind': 'stem'}]
        current = entry.form
        changes = []
        steps = []
        for rule in analysis.rules:
            after = rule.apply(current)
            assert after is not None
            stripped, added = rule.strip, rule.add
            # Strip/add often repeat the whole final syllable (ыҡ -> ыҡтар).
            # Cancel that unchanged prefix to expose the actual -тар suffix.
            shared = 0
            while shared < min(len(stripped), len(added)) and stripped[shared] == added[shared]:
                shared += 1
            stripped, added = stripped[shared:], added[shared:]
            removed = len(stripped)
            # A voiced stem-final consonant belongs to the preceding morpheme,
            # not to the new suffix: китап + ы -> китаб + ы.
            voiced = len(stripped) == 1 and added and VOICING.get(stripped) == added[0]
            if voiced:
                for piece in reversed(pieces):
                    if piece['text']:
                        piece['text'] = piece['text'][:-1] + added[0]
                        break
                changes.append({'from': stripped, 'to': added[0]})
                removed = 0
                added = added[1:]
            elif stripped:
                changes.append({'from': stripped, 'to': ''})
            for piece in reversed(pieces):
                if not removed:
                    break
                take = min(removed, len(piece['text']))
                piece['text'] = piece['text'][:-take] if take else piece['text']
                removed -= take
            assert not removed
            start = len(after) - len(added)
            pieces.extend(self.split_addition(current, rule, start))
            steps.append({'before': current, 'after': after, 'tags': list(rule.tags), 'line': rule.line})
            current = after
        assert current == surface
        assert ''.join(piece['text'] for piece in pieces) == surface
        pieces = [piece for piece in pieces if piece['text'] or piece['tags']]
        return {'stem': entry.word, 'pos': list(entry.pos), 'tags': list(analysis.tags),
                'parts': pieces, 'changes': changes, 'steps': steps}

    @lru_cache(maxsize=256)
    def analyze(self, word: str) -> dict:
        word = unicodedata.normalize('NFC', word.strip())
        spellings = [word]
        if word.isupper() or word[:1].isupper() and word[1:].islower():
            if word.lower() != word:
                spellings.append(word.lower())
        analyses = {}
        for spelling in spellings:
            for path in self.paths(spelling):
                explanation = self.explain(path, spelling)
                key = (explanation['stem'], tuple(explanation['pos']), tuple(explanation['tags']))
                if spelling != word:
                    offset = 0
                    for part in explanation['parts']:
                        width = len(part['text'])
                        part['text'] = word[offset:offset + width]
                        offset += width
                analyses.setdefault(key, explanation)
        order = {'Noun': 0, 'Verb': 1, 'A': 2}
        values = sorted(analyses.values(), key=lambda item: (len(item['stem']), item['stem'],
                        min((order.get(pos, 3) for pos in item['pos']), default=4), tuple(item['tags'])))
        return {'word': word, 'analyses': values}
