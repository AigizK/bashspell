#!/usr/bin/env python3
"""Check italicized examples from every archived grammar page with libhunspell.

This produces candidates for linguistic review, NOT automatically valid test
cases. The reference also italicizes translations, phonetic transcriptions,
suffixes, historical forms, and explicitly incorrect spellings.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import ctypes.util
import hashlib
import json
import re
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "docs/grammar-reference"
WORD = re.compile(r"[А-Яа-яЁёӘәӨөҮүҒғҠҡҘҙҪҫҺһҢң]+(?:-[А-Яа-яЁёӘәӨөҮүҒғҠҡҘҙҪҫҺһҢң]+)*")


class ReferenceText(HTMLParser):
    """Preserve words split by inline Word markup, and exclude head/CSS text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.body = False
        self.italic = 0
        self.parts: list[str] = []
        self.styles: list[str] = []

    def boundary(self):
        self.parts.append("\n")
        self.styles.append("0")

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.body = True
        if self.body:
            if tag in ("p", "tr", "h1", "h2", "h3", "br"):
                self.boundary()
            if tag == "i":
                self.italic += 1

    def handle_endtag(self, tag):
        if tag == "body":
            self.body = False
        if tag == "i":
            self.italic = max(0, self.italic - 1)
        if tag in ("p", "tr", "h1", "h2", "h3"):
            self.boundary()

    def handle_data(self, data):
        if self.body:
            data = re.sub(r"\s+", " ", data)
            self.parts.append(data)
            self.styles.append(("1" if self.italic else "0") * len(data))

    def extract(self) -> tuple[str, list[str]]:
        body = "".join(self.parts)
        styles = "".join(self.styles)
        words = sorted({m[0] for m in WORD.finditer(body)
                        if len(m[0]) > 2 and m[0][0].islower()
                        and "1" in styles[m.start():m.end()]})
        paragraphs = [line.strip() for line in body.splitlines() if line.strip()]
        return "\n".join(paragraphs), words


class Hunspell:
    def __init__(self, stem: Path):
        name = next((found for candidate in ("hunspell-1.7", "hunspell")
                     if (found := ctypes.util.find_library(candidate))), None)
        if name is None:
            # macOS's dyld search path does not include Homebrew by default.
            name = next((str(path) for prefix in ("/opt/homebrew", "/usr/local")
                         if (path := Path(prefix) / "lib/libhunspell-1.7.dylib").is_file()), None)
        if name is None:
            raise RuntimeError("libhunspell not found; install Hunspell (brew install hunspell / libhunspell-dev)")
        self.lib = ctypes.CDLL(name)
        self.lib.Hunspell_create.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        self.lib.Hunspell_create.restype = ctypes.c_void_p
        self.lib.Hunspell_spell.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        self.lib.Hunspell_spell.restype = ctypes.c_int
        self.lib.Hunspell_destroy.argtypes = [ctypes.c_void_p]
        self.lib.Hunspell_destroy.restype = None
        aff, dic = stem.with_suffix(".aff"), stem.with_suffix(".dic")
        if not aff.is_file() or not dic.is_file():
            raise FileNotFoundError(f"Expected {aff} and {dic}")
        self.handle = self.lib.Hunspell_create(str(aff).encode(), str(dic).encode())
        if not self.handle:
            raise RuntimeError("Hunspell could not load the dictionary")

    def spell(self, word: str) -> bool:
        return bool(self.lib.Hunspell_spell(self.handle, word.encode("utf-8")))

    def close(self):
        self.lib.Hunspell_destroy(self.handle)


def audit(stem: Path) -> dict:
    checker = Hunspell(stem)
    checked = {}
    pages = []
    rejected = defaultdict(list)
    try:
        for path in sorted(REFERENCE.rglob("*")):
            if path.suffix not in (".htm", ".html"):
                continue
            raw = path.read_bytes()
            charset = re.search(rb"charset\s*=\s*([\w-]+)", raw[:8192], re.I)
            parser = ReferenceText()
            parser.feed(raw.decode(charset[1].decode() if charset else "cp1251"))
            text, words = parser.extract()
            relative = path.relative_to(REFERENCE).as_posix()
            failed = []
            for word in words:
                if word not in checked:
                    checked[word] = checker.spell(word)
                if not checked[word]:
                    rejected[word].append(relative)
                    failed.append(word)
            pages.append({"path": relative, "title": text.splitlines()[0] if text else "",
                          "sha256": hashlib.sha256(raw).hexdigest(),
                          "examples": len(words), "rejected": failed})
    finally:
        checker.close()
    return {"dictionary_sha256": {suffix: hashlib.sha256(stem.with_suffix(suffix).read_bytes()).hexdigest()
                                  for suffix in (".aff", ".dic")},
            "pages": pages, "checked": checked, "rejected": dict(rejected)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dict", type=Path, default=ROOT / "static/hunspell/28.01.2024/bash",
                        help="Dictionary stem, without .aff/.dic")
    parser.add_argument("--output", type=Path, required=True, help="Directory for the audit artifacts")
    args = parser.parse_args()
    result = audit(args.dict.resolve())
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "scan.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    with (args.output / "pages.tsv").open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output, delimiter="\t", lineterminator="\n")
        writer.writerow(("page", "title", "examples", "accepted", "rejected", "sha256"))
        for page in result["pages"]:
            writer.writerow((page["path"], page["title"], page["examples"],
                             page["examples"] - len(page["rejected"]),
                             len(page["rejected"]), page["sha256"]))
    with (args.output / "review-candidates.tsv").open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output, delimiter="\t", lineterminator="\n")
        writer.writerow(("word", "source_pages"))
        writer.writerows((word, ";".join(pages)) for word, pages in sorted(result["rejected"].items()))
    print(f"Pages: {len(result['pages'])}; unique examples: {len(result['checked'])}; "
          f"review candidates: {len(result['rejected'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
