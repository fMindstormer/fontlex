#!/usr/bin/env python3
"""Check the English font letter by letter against its lexicon.

    python english/verify.py build/Fontlex-English.ttf [--shaper harfbuzz --shaper coretext] [--corpus FILE ...]

Every listed word is shaped alone, capitalized, in capitals, between
punctuation and inside a sentence; a word with an apostrophe also with a
curly one. Each letter must come out with its hint (stress, reduced, silent)
or plain. Listed words inside longer words, and words that aren't listed,
must come out plain. Corpus files are checked line by line the same way.
"""

import argparse
import random
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import test_fontlex  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402

WORD = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")


def read_lexicon(path):
    words = {}
    for line in open(path, encoding="utf-8"):
        word, hints, _ = line.rstrip("\n").split("\t")
        words[word] = hints
    return words


def expected(text, words):
    """The hint of every character of `text`, as the font should draw it."""
    out = ["."] * len(text)
    for m in WORD.finditer(text):
        hints = words.get(m.group().lower().replace("’", "'"))
        if hints:
            out[m.start():m.end()] = hints
    return "".join(out)


class View:
    def __init__(self, data, shaper):
        self.order = TTFont(data if isinstance(data, str) else __import__("io").BytesIO(data)).getGlyphOrder()
        self.shaper = shaper

    def hints(self, text):
        """What the font draws for each character: a hint letter, `.` for
        plain, or `?` for a glyph that should never be drawn."""
        out = ["?"] * len(text)
        for gid, cluster, *_ in self.shaper.shape(text)[0]:
            name = self.order[gid] if gid is not None else ""    # None: drawn by a fallback font
            if ".h" in name:
                out[cluster] = name[name.index(".h") + 2]
            elif ".w" in name:
                out[cluster] = "?"
            else:
                out[cluster] = "."
        return "".join(out)


def cases(words, rng):
    for w in words:
        yield w
        yield w.capitalize()
        yield w.upper()
        yield f"({w}),"
        yield f"I think {w} is here."
        if "'" in w:
            yield w.replace("'", "’")
    listed = list(words)
    for _ in range(2000):        # listed words inside longer ones, and made-up words
        w = rng.choice(listed)
        yield rng.choice(["x", "un", "re"]) + w
        yield w + rng.choice(["x", "zz", "q"])
        yield "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(rng.randint(2, 9)))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("font")
    ap.add_argument("--lexicon", default=str(HERE / "lexicon" / "words.tsv"))
    ap.add_argument("--shaper", action="append", choices=sorted(test_fontlex.SHAPERS))
    ap.add_argument("--corpus", nargs="*", default=[])
    ap.add_argument("--show", type=int, default=10)
    args = ap.parse_args()
    words = read_lexicon(args.lexicon)
    data = Path(args.font).read_bytes()
    failed = 0
    for name in args.shaper or ["harfbuzz"]:
        view = View(data, test_fontlex.SHAPERS[name](data))
        sets = [("lexicon words in context", list(cases(words, random.Random(1))))]
        for path in args.corpus:
            sets.append((f"lines of {path}", [l for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]))
        for label, texts in sets:
            bad, shown, t = 0, 0, time.perf_counter()
            for text in texts:
                want, got = expected(text, words), view.hints(text)
                if want != got:
                    bad += 1
                    if shown < args.show:
                        shown += 1
                        print(f"  {text!r}\n    expected {want}\n    drawn    {got}")
            ms = (time.perf_counter() - t) * 1000 / max(1, len(texts))
            print(f"{label}: {len(texts) - bad}/{len(texts)} right ({name}, {ms:.3f} ms each)")
            failed += bad
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
