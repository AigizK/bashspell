#!/usr/bin/env python3
"""Rebuild grammar-derived Hunspell rows without requiring a third suffix.

The hand-maintained rows in bash.aff remain the source. A marker after each
block records its number of generated additions. Inverse action-noun classes
V25--V29, V36--V37, V50--V53 are rebuilt from the corresponding forward verb
classes. See reports/grammar-audit-2026-09-05.md.
Run with --write after editing source rules, or --check in validation.
"""

from __future__ import annotations

import argparse
import re
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AFF = ROOT / "static/hunspell/28.01.2024/bash.aff"
BEGIN = "# BEGIN generated grammar completion"
END = "# END generated grammar completion"
GENERATED_COUNT = "# generated grammar completion rows: "
PREDICATE_FLAGS = {"ы": 339, "е": 340, "о": 341, "ө": 342}
VOWELS = "аәеёиоуыэюяөү"
Row = tuple[str, ...]


def read_blocks(text: str):
    preamble: list[str] = []
    blocks: OrderedDict[int, tuple[str, list[Row]]] = OrderedDict()
    current = None
    generated = False
    for line in text.splitlines():
        if line.startswith(GENERATED_COUNT):
            count = int(line[len(GENERATED_COUNT):])
            del blocks[current][1][-count:]
        elif line == BEGIN:
            generated = True
        elif line == END:
            generated = False
        elif generated:
            continue
        elif re.match(r"[SP]FX \d+ [YN] \d+", line):
            parts = line.split(maxsplit=4)
            if parts[2] != "Y":
                raise ValueError(f"Cannot rebuild a non-cross-product block: {line}")
            current = int(parts[1])
            blocks[current] = (parts[4] if len(parts) > 4 else "", [])
        elif line.startswith(("SFX ", "PFX ")):
            assert current == int(line.split()[1]), line
            blocks[current][1].append(tuple(line.split()))
        elif current is None:
            preamble.append(line)
        elif line.strip():
            # Never silently discard an unfamiliar directive or source comment.
            raise ValueError(f"Unexpected line inside SFX block: {line}")
    return preamble, blocks


def addition(row: Row) -> tuple[str, str]:
    word, slash, flags = row[3].partition("/")
    return ("" if word == "0" else word), (slash + flags)


def make_row(flag: int, strip: str, add: str, condition: str, tag: str) -> Row:
    return ("SFX", str(flag), strip or "0", add or "0", condition, tag)


def distinguish_verb_forms(row: Row) -> Row:
    """Different participles/converbs are not competing phonetic allomorphs.

    Preserve the traditional category names and add their canonical formative.
    This also makes the morphology useful when a single flag covers multiple
    consonant groups: барған/барасаҡ/барыр must remain distinguishable.
    """
    if len(row) != 6:
        return row
    add, _ = addition(row)
    tag = row[5]
    if re.search(r"\+Prc(?=\+|$)", tag):
        if re.search("[м][аә]ҫ", add):
            kind = "маҫ"
        elif re.search("[ғгҡк][аә]н", add):
            kind = "ған"
        elif re.search("[аяә]с[аә][ҡк]", add):
            kind = "асаҡ"
        elif re.match("[бгғ]?[ыоеө]?р", add):
            kind = "ыр"
        else:
            kind = "а"
        tag = re.sub(r"\+Prc(?=\+|$)", "+Prc/" + kind, tag)
    if re.search(r"\+GerPerf(?=\+|$)", tag):
        if re.search("[ғгҡк][аә]нс[аәые]", add):
            kind = "ғанса"
        elif re.search("м[аә]й[ые]нс[аә]", add):
            kind = "майынса"
        elif re.search("м[аә]йс[аә]", add):
            kind = "майса"
        else:
            kind = "п"
        tag = re.sub(r"\+GerPerf(?=\+|$)", "+GerPerf/" + kind, tag)
    if "+Fut" in tag and "+Neg" in tag and "ҫ" not in add and "+Short" not in tag:
        tag += "+Short"
    return (*row[:5], tag)


def inverse_vowel(rows: list[Row], flag: int, ending: str) -> list[Row]:
    """уйнау -> уйна + V09, including vowel-final stems such as уҡыу."""
    result = [make_row(flag, ending[-1], "", ending, "+Imp")]
    for row in rows:
        strip = "" if row[2] == "0" else row[2]
        condition = ending if row[4] == "." else row[4] + ending[-1]
        result.append(("SFX", str(flag), strip + ending[-1], row[3], condition, *row[5:]))
    return result


def inverse_consonant(blocks, flag: int, ending: str, harmony: int) -> list[Row]:
    """Invert -(ы)у etc., restoring п/к/ҡ and using the right consonant class.

    Conditions apply to the *dictionary* spelling, before stripping. Retaining
    the preceding-character conditions is essential for ҡурҡ/ҡурҡыу vs. ҡаҡ/ҡағыу.
    The stem-vowel ambiguities (уҡыу, бейеү, etc.) use separate dictionary flags.
    """
    result = []
    for letter in "бвгғджзҙйкҡлмнңпрсҫтфхһцчшщуүи":
        root_letter = {"б": "п", "г": "к", "ғ": "ҡ"}.get(letter, letter)
        group = 215 if root_letter in "лмнңжз" else 219 if root_letter in "йрҙуүи" else 227
        result.append(make_row(flag, ending if letter == root_letter else letter + ending,
                               "" if letter == root_letter else root_letter,
                               letter + ending, "+Imp"))
        for row in blocks[group + harmony][1]:
            condition = row[4]
            atoms = re.findall(r"\[[^]]+\]|.", condition)
            if not re.fullmatch(atoms[-1], root_letter):
                continue
            before = "".join(atoms[:-1])
            strip = "" if row[2] == "0" else row[2]
            add, continuation = addition(row)
            if strip:
                assert strip == root_letter, row
                inverse_strip = letter + ending
            elif letter != root_letter:
                inverse_strip = letter + ending
                add = root_letter + add
            else:
                inverse_strip = ending
            result.append(("SFX", str(flag), inverse_strip, (add or "0") + continuation,
                           before + letter + ending, *row[5:]))
    # Merge equal rules that differ only in their final stem letter. This keeps
    # the generated dictionaries small without broadening any condition.
    merged: OrderedDict[tuple, list[str]] = OrderedDict()
    for row in result:
        prefix = row[4][:-len(ending)-1]
        letter = row[4][-len(ending)-1]
        key = (*row[:4], prefix, *row[5:])
        merged.setdefault(key, []).append(letter)
    return [(*key[:4], key[4] + (letters[0] if len(set(letters)) == 1 else
                               "[" + "".join(dict.fromkeys(letters)) + "]") + ending,
             *key[5:]) for key, letters in merged.items()]


def expand_nominal_derivation(row: Row, blocks) -> list[Row]:
    """Combine -лыҡ with the first nominal suffix, leaving a second stage free.

    In particular, combine the nominal zero transition into U22/U24 here:
    һүн + мәҫлек/U24 + ге works, whereas һүн + мәҫлек/N14 + 0/U24 + ге
    would require three suffixes and silently fail in Hunspell.
    """
    add, _ = addition(row)
    if len(row) != 6 or not row[5].endswith(("+Der/лыҡ", "+Der/ыш", "+Der/ғыс")):
        return []
    if row[5].endswith("+Der/лыҡ"):
        target = {"лыҡ": 107, "лек": 108, "лоҡ": 109, "лөк": 110}.get(add[-3:])
    else:
        target = int(row[3].partition("/")[2])
        target = {13: 107, 14: 108, 15: 109, 16: 110}.get(target, target)
    if target is None:
        return []
    result = []
    for nominal in blocks[target][1]:
        if not re.search(nominal[4] + "$", add):
            continue
        strip = "" if nominal[2] == "0" else nominal[2]
        suffix, continuation = addition(nominal)
        if strip and not add.endswith(strip):
            continue
        combined = (add[:-len(strip)] if strip else add) + suffix
        result.append(make_row(int(row[1]), row[2], combined + continuation,
                               row[4], row[5] + (nominal[5] if len(nominal) == 6 else "")))
    return result


def supplemental_rows(flag: int, rows: list[Row], blocks) -> list[Row]:
    generated = []
    if 215 <= flag <= 230 or flag in (328, 329, 330, 331, 238, 239):
        soft = flag % 2 == 0 if 215 <= flag <= 230 else flag in (330, 331, 239)
        for add, tag in (("һәнә" if soft else "һана", "+Imp+Clt/һана"),
                         ("сәле", "+Imp+Clt/сәле")):
            generated.append(make_row(flag, "", add, ".", tag))
        # The modern -маҡ/-мәк action form is frozen: no nominal continuation.
        if flag not in (238, 239, 330, 331):
            generated.append(make_row(flag, "", "мәк" if soft else "маҡ", ".", "+ActArch"))
    if 215 <= flag <= 230 or flag in (328, 329):
        harmony = (flag - 215) % 4 if flag <= 230 else 0
        high = ("ы", "е", "о", "ө")[harmony]
        consonant = ("ҡ" if flag >= 227 else "ғ") if harmony in (0, 2) else ("к" if flag >= 227 else "г")
        generated.append(make_row(flag, "", consonant + high + "с/" + str(13 + harmony),
                                  ".", "+Der/ғыс"))
        for row in rows:
            if len(row) == 6 and row[5] == "+Act":
                add, _ = addition(row)
                assert add.endswith(("у", "ү")), row
                generated.append(make_row(flag, row[2], add[:-1] + "ш/" + str(107 + harmony),
                                          row[4], "+Der/ыш"))
    for row in rows:
        if len(row) != 6:
            continue
        add, continuation = addition(row)
        if not continuation and re.search(r"\+Pred[12](Sg|Pl)$", row[5]):
            last = next(c for c in reversed(add) if c in VOWELS)
            question = "м" + last
            indf = ("ҙ" if add.endswith("ҙ") else "д") + last + "р"
            for tail, tag in ((question, "+Q"), (indf, "+Indf"),
                              (question + "л" + last + "р", "+Q+Indf"),
                              ("с" + last, "+Clt/сы")):
                generated.append(make_row(flag, row[2], add + tail, row[4], row[5] + tag))
        if row[5] == "+Prc/маҫ" and add.endswith(("маҫ", "мәҫ")):
            soft = add.endswith("мәҫ")
            generated.append(make_row(flag, row[2], add + ("лек/14" if soft else "лыҡ/13"),
                                      row[4], "+Neg+Prc+Der/лыҡ"))
    generated += [new for row in rows + generated for new in expand_nominal_derivation(row, blocks)]
    return generated


def predicates(row: Row) -> list[Row]:
    if len(row) != 6 or row[0] != "SFX":
        return []
    tag = row[5]
    if any(t in tag for t in ("+Past", "+Pres", "+Fut", "+Cond", "+Opt", "+Imp",
                              "+Ger", "+Inf", "+Pred")):
        return []
    if not tag.endswith(("+Loc", "+Abl", "+Poss", "+PxSg1", "+PxSg2", "+PxSg3",
                         "+PxPl1", "+PxPl2")):
        return []
    add, _ = addition(row)
    vowels = [c for c in add if c in VOWELS]
    if not vowels:
        inherited = {199: "ы", 200: "е", 201: "о", 202: "ө"}.get(int(row[1]))
        if inherited is None:
            return []
        vowels = [inherited]
    vowel = vowels[-1]
    high = "ө" if vowel == "ө" else "о" if vowel == "о" else "е" if vowel in "әеиү" else "ы"
    question = "м" + high
    result = []
    for person, suffix, indf in (
        ("1Sg", "м" + high + "н", "д" + high + "р"),
        ("2Sg", "һ" + high + "ң", "д" + high + "р"),
        ("1Pl", "б" + high + "ҙ", "ҙ" + high + "р"),
        ("2Pl", "һ" + high + "ғ" + high + "ҙ" if high in "ыо" else
         "һ" + high + "г" + high + "ҙ", "ҙ" + high + "р"),
    ):
        for tail, tags in (("", ""), (question, "+Q"), (indf, "+Indf"),
                           (question + "л" + high + "р", "+Q+Indf"),
                           ("с" + high, "+Clt/сы")):
            result.append(make_row(int(row[1]), row[2], add + suffix + tail, row[4],
                                   tag + "+Pred" + person + tags))
    return result


def build(text: str) -> str:
    preamble, blocks = read_blocks(text)
    # Continuations added by a previous run are derived data too.
    for _, rows in blocks.values():
        for i, row in enumerate(rows):
            add, slash, flags = row[3].partition("/")
            if slash:
                flags = ",".join(f for f in flags.split(",") if int(f) not in PREDICATE_FLAGS.values())
                rows[i] = (*row[:3], add + ("/" + flags if flags else ""), *row[4:])
    blocks = OrderedDict((flag, (note, [distinguish_verb_forms(r) for r in rows]))
                         for flag, (note, rows) in blocks.items())
    extra = {flag: supplemental_rows(flag, rows, blocks) for flag, (_, rows) in blocks.items()}
    # Build from the complete source verb paradigm, before nominal expansion.
    sources = {flag: (note, rows + extra[flag]) for flag, (note, rows) in blocks.items()}
    for flag, source, ending in ((231, 223, "ау"), (236, 224, "әү"), (237, 223, "яу"),
                                 (335, 223, "ыу"), (336, 224, "еү"),
                                 (337, 225, "оу"), (338, 226, "өү")):
        blocks[flag] = (f"# inverse action noun {ending}: vowel-final V{source - 214:02}",
                        inverse_vowel(sources[source][1], flag, ending))
        extra[flag] = []
    for flag, ending, harmony in ((235, "ыу", 0), (232, "еү", 1),
                                  (233, "оу", 2), (234, "өү", 3)):
        blocks[flag] = (f"# inverse action noun {ending}: consonant agreement and voicing",
                        inverse_consonant(sources, flag, ending, harmony))
        extra[flag] = []
    incoming = {int(f) for _, rows in blocks.values() for row in rows
                for f in row[3].partition("/")[2].split(",") if f}
    for high, flag in PREDICATE_FLAGS.items():
        dummy = make_row(flag, "", high, ".", "+Loc")
        rows = [("SFX", str(flag), "0", row[3][1:], ".", row[5][4:])
                for row in predicates(dummy)]
        blocks[flag] = (f"# nominal predicate continuation, harmony {high}", rows)
        extra[flag] = []
    output = preamble
    for flag, (note, rows) in blocks.items():
        generated = list(extra[flag])
        updated_rows = []
        for row in rows:
            forms = predicates(row)
            if forms and flag not in incoming:
                # This class is only used on dictionary entries, so a shared
                # second suffix is sufficient. Classes used as continuations
                # need the explicit products below (Hunspell has two stages).
                add, _ = addition(row)
                high = forms[0][3][len(add) + 1]
                join = "," if "/" in row[3] else "/"
                row = (*row[:3], row[3] + join + str(PREDICATE_FLAGS[high]), *row[4:])
            else:
                generated.extend(forms)
            updated_rows.append(row)
        rows = updated_rows
        existing = set(rows)
        generated = list(dict.fromkeys(r for r in generated if r not in existing))
        output.append(f"{rows[0][0]} {flag} Y {len(rows) + len(generated)} {note}".rstrip())
        output.extend(" ".join(row) for row in rows)
        if generated:
            # Hunspell counts physical lines inside an affix block. A comment
            # between rows can silently truncate the block, so put it after.
            output.extend(" ".join(row) for row in generated)
            output.append(GENERATED_COUNT + str(len(generated)))
        output.append("")
    return "\n".join(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    before = AFF.read_text(encoding="utf-8")
    after = build(before)
    if args.write:
        AFF.write_text(after, encoding="utf-8")
    elif before != after:
        print("Generated grammar rules are stale; run with --write")
        return 1
    print(f"Grammar completion: {after.count(chr(10))} lines; {'updated' if args.write else 'up to date'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
