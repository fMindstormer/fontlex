#!/usr/bin/env python3
"""Check the English font letter by letter against its lexicon.

    python english/verify.py build/Fontlex-English.ttf [--shaper harfbuzz --shaper coretext] [--corpus FILE ...]

Every listed word is shaped alone, capitalized, in capitals, between
punctuation and inside a sentence; a word with an apostrophe also with a
curly one. Each letter must come out with its hint (stress, reduced, silent)
or plain. Listed words inside longer words, and words that aren't listed,
must come out plain. Noun/verb pairs are shaped after every cue word (their
noun or verb reading), after other words or two spaces (the hints both
readings share), and before each reading marker, which beats a cue; a
marker after any other word does nothing, and markers add no width. Corpus files are checked line by line the same way. Every
tenth text is then shaped again with each stylistic set, and with all of
them, where that set's hints must come out plain.
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
from enfont import HINT_SETS, HINTS, MARKERS  # noqa: E402

WORD = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")
READING = {ch: kind for kind, ch in MARKERS.items()}


class Lexicon:
    """lexicon/: words.tsv (word, hints), homographs.tsv (word, noun hints,
    verb hints) and cues.tsv (word, noun or verb)."""

    def __init__(self, directory):
        def rows(name):
            for line in open(Path(directory) / name, encoding="utf-8"):
                if line.strip() and not line.startswith("#"):
                    yield line.rstrip("\n").split("\t")
        self.words = {r[0]: r[1] for r in rows("words.tsv")}
        self.homographs = {r[0]: (r[1], r[2]) for r in rows("homographs.tsv")}
        self.cues = {r[0]: r[1] for r in rows("cues.tsv")}


def expected(text, lex):
    """The hint of every character of `text`, as the font should draw it."""
    out = ["."] * len(text)
    prev = None
    for m in WORD.finditer(text):
        word = m.group().lower().replace("\u2019", "'")
        hints = lex.words.get(word)
        marker = READING.get(text[m.end():m.end() + 1])
        if word in lex.homographs and marker:
            hints = lex.homographs[word][0 if marker == "noun" else 1]
        elif word in lex.homographs and prev and prev.end() == m.start() - 1 and text[prev.end()] == " ":
            cue = lex.cues.get(prev.group().lower().replace("\u2019", "'"))
            if cue:
                hints = lex.homographs[word][0 if cue == "noun" else 1]
        if hints:
            out[m.start():m.end()] = hints
        prev = m
    return "".join(out)


class View:
    def __init__(self, data, shaper):
        self.order = TTFont(data if isinstance(data, str) else __import__("io").BytesIO(data)).getGlyphOrder()
        self.shaper = shaper

    def hints(self, text):
        """What the font draws for each character: a hint letter, `.` for
        plain, or `?` for a glyph that should never be drawn."""
        out = ["." if c in READING else "?" for c in text]       # a marker draws nothing
        for gid, cluster, *_ in self.shaper.shape(text)[0]:
            name = self.order[gid] if gid is not None else ""    # None: drawn by a fallback font
            if text[cluster] in READING:
                continue
            if ".h" in name:
                out[cluster] = name[name.index(".h") + 2]
            elif ".w" in name:
                out[cluster] = "?"
            else:
                out[cluster] = "."
        return "".join(out)


def cases(lex, rng):
    words = lex.words
    for w in lex.homographs:
        for c in lex.cues:
            yield f"{c} {w}"
            yield f"{c.capitalize()} {w.upper()}."
        yield f"the  {w}"          # two spaces: no cue
        yield f"then {w}"
        for kind, mark in MARKERS.items():
            other = next(c for c, k in sorted(lex.cues.items()) if k != kind)
            yield f"{w}{mark}"
            yield f"{w.capitalize()}{mark}, then"
            yield f"{other} {w}{mark}."       # the marker beats the cue
            yield f"a new {w}{mark} {w}"
            yield f"{other} {w} {mark}"       # a marker after a space does nothing
    for i, w in enumerate(words):
        yield w
        if i % 10 == 0:
            yield f"{w}{MARKERS['noun' if i % 20 else 'verb']} x"   # a marker after any other word does nothing
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
    ap.add_argument("--lexicon", default=str(HERE / "lexicon"), help="the directory of words.tsv and the rest")
    ap.add_argument("--shaper", action="append", choices=sorted(test_fontlex.SHAPERS))
    ap.add_argument("--corpus", nargs="*", default=[])
    ap.add_argument("--show", type=int, default=10)
    args = ap.parse_args()
    lex = Lexicon(args.lexicon)
    data = Path(args.font).read_bytes()
    failed = 0
    for name in args.shaper or ["harfbuzz"]:
        view = View(data, test_fontlex.SHAPERS[name](data))
        sets = [("lexicon words in context", list(cases(lex, random.Random(1))))]
        for path in args.corpus:
            sets.append((f"lines of {path}", [l for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]))
        for label, texts in sets:
            failed += report(label, texts, view, lambda text: expected(text, lex), name, args.show)
        failed += widths(view, lex, name)
        sample = [text for _, texts in sets for text in texts[::10]]
        for tags, off in hint_sets():
            view = View(data, test_fontlex.SHAPERS[name](data, features=tags))
            failed += report(f"every tenth text with {'+'.join(tags)}", sample, view,
                             lambda text: "".join("." if c in off else c for c in expected(text, lex)),
                             name, args.show)
    return 1 if failed else 0


def hint_sets():
    """Each stylistic set with the hints it turns off, then all of them at once."""
    sets = sorted((HINT_SETS[entry][0], h + ("T" if h == "L" else "")) for h, entry in HINTS.items())
    return [((tag,), off) for tag, off in sets] + [(tuple(t for t, _ in sets), "".join(o for _, o in sets))]


def widths(view, lex, name):
    """A marker adds no width: a pair with a marker is as wide as after a cue
    that picks the same reading, and any other word as wide as without one."""
    cue = {kind: next(c for c, k in sorted(lex.cues.items()) if k == kind) for kind in MARKERS}
    texts = [(f"{cue[kind]} {w}{mark}", f"{cue[kind]} {w}") for w in lex.homographs for kind, mark in MARKERS.items()]
    texts += [(w + mark, w) for w in list(lex.words)[::50] if w not in lex.homographs for mark in MARKERS.values()]
    bad = [a for a, b in texts if view.shaper.shape(a)[1] != view.shaper.shape(b)[1]]
    print(f"width with a marker: {len(texts) - len(bad)}/{len(texts)} the same ({name})"
          + (f"; e.g. {bad[:5]}" if bad else ""))
    return len(bad)


def report(label, texts, view, want_of, name, show):
    """Shapes each text and compares it with want_of(text); returns the misses."""
    bad, shown, t = 0, 0, time.perf_counter()
    for text in texts:
        want, got = want_of(text), view.hints(text)
        if want != got:
            bad += 1
            if shown < show:
                shown += 1
                print(f"  {text!r}\n    expected {want}\n    drawn    {got}")
    ms = (time.perf_counter() - t) * 1000 / max(1, len(texts))
    print(f"{label}: {len(texts) - bad}/{len(texts)} right ({name}, {ms:.3f} ms each)")
    return bad


if __name__ == "__main__":
    sys.exit(main())
