#!/usr/bin/env python3
"""Check the French font letter by letter against its lexicon.

    python french/verify.py build/Fontlex-French.ttf [--shaper harfbuzz --shaper coretext] [--corpus FILE ...]

Every listed word is shaped alone, capitalized, in capitals, between
punctuation and inside a sentence, and every compound alone and in a
sentence. Each letter must come out with its hint (silent, reduced, nasal,
liaison) or plain, and each space or hyphen with its tie or plain. Listed
words inside longer words, and words that aren't listed, must come out
plain. Verb/noun pairs are shaped after every cue word and after other words
or two spaces; liaison triggers before vowels, h muet, blockers and
consonants, and after hyphens and apostrophes; inverted verbs before each
clitic. Corpus files are checked line by line the same way.
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

sys.path.insert(0, str(HERE))
import frfont  # noqa: E402

LETTERS = frfont.LETTERS + frfont.LETTERS.upper() + "Ÿ"
WORD = re.compile(f"[{LETTERS}]+")
Lexicon = frfont.Lexicon


def expected(text, lex):
    """The hint of every character of `text`, as the font should draw it."""
    low = text.lower().replace("’", "'")
    toks = [(m.start(), m.end()) for m in WORD.finditer(low)]
    at = {s: i for i, (s, _) in enumerate(toks)}

    def word(i):
        return low[toks[i][0]:toks[i][1]]

    def before(i):
        return low[toks[i][0] - 1] if toks[i][0] else ""
    out = ["."] * len(text)
    claimed, links = set(), set()
    # 4. Verb/noun pairs after a cue and one space.
    for i, (s, e) in enumerate(toks):
        if word(i) in lex.homographs and i and toks[i - 1][1] == s - 1 and before(i) == " " \
                and word(i - 1) in lex.cues:
            out[s:e] = lex.homographs[word(i)][0 if lex.cues[word(i - 1)] == "noun" else 1]
            claimed.add(i)
    # 5. Liaison after a trigger and one space, not after a hyphen.
    for i, (s, e) in enumerate(toks):
        if word(i) in lex.triggers and before(i) != "-" and low[e:e + 1] == " " and e + 1 in at \
                and low[e + 1] in frfont.LINKS_TO and word(at[e + 1]) not in lex.blockers:
            links |= {e - 1, e}
    # 6. Liaison in inversion.
    for i, (s, e) in enumerate(toks):
        if e - s > 1 and low[e - 1] in frfont.INVERTED and low[e:e + 1] == "-" and e + 1 in at \
                and word(at[e + 1]) in frfont.CLITICS and not (i in claimed and out[e - 1] != "."):
            links |= {e - 1, e}
    # 7. Compounds first, then words.
    i = 0
    while i < len(toks):
        s, e = toks[i]
        if i in claimed:
            i += 1
            continue
        for c in lex.by_start.get(word(i), ()):
            end = s + len(c)
            if low[s:end] == c and end in {t[1] for t in toks}:
                out[s:end] = lex.compounds[c]
                i = next(k for k, t in enumerate(toks) if t[1] == end) + 1
                break
        else:
            if word(i) in lex.words:
                out[s:e] = lex.words[word(i)]
            i += 1
    for p in links:
        out[p] = "L" if low[p] in frfont.LETTERS else frfont.TIE
    return "".join(out)


class View:
    def __init__(self, data, shaper):
        self.order = TTFont(data if isinstance(data, str) else __import__("io").BytesIO(data)).getGlyphOrder()
        self.shaper = shaper

    def hints(self, text):
        """What the font draws for each character: a hint letter, `T` for a
        tie, `.` for plain, or `?` for a glyph that should never be drawn."""
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


def index_compounds(lex):
    lex.by_start = {}
    for c in sorted(lex.compounds, key=len, reverse=True):
        lex.by_start.setdefault(frfont.tokens(c)[0], []).append(c)
    return lex


def cases(lex, rng):
    words = list(lex.words)
    vowel_words = [w for w in words[:3000] if w[0] in frfont.LINKS_TO and w not in lex.blockers]
    blockers = sorted(lex.blockers)
    for w in lex.homographs:
        for c in lex.cues:
            yield f"{c} {w}"
            yield f"{c.capitalize()} {w.upper()}."
        yield f"le  {w}"           # two spaces: no cue
        yield f"alors {w}"
    for t in lex.triggers:
        for nxt in rng.sample(vowel_words, 8) + ["homme", "heures", "haricots", "onze", "oui", "yeux", "y",
                                                 "livres", "Anne", "été", "à"] + rng.sample(blockers, 4):
            yield f"{t} {nxt}"
            yield f"{t.capitalize()} {nxt.upper()}"
            yield f"Elles-{t} {nxt}"           # after a hyphen: none
            yield f"qu’{t} {nxt}"
            yield f"{t}  {nxt}"                # two spaces: none
            yield f"{t}x {nxt}"                # not the trigger
    inverted = [w for w in words[:5000] if w[-1] in frfont.INVERTED and len(w) > 1]
    for w in rng.sample(inverted, 400):
        for c in frfont.CLITICS:
            yield f"{w}-{c} ?"
        yield f"{w.capitalize()}-{rng.choice(frfont.CLITICS).upper()} ?"
        yield f"{w}-ilx"
    yield from ("a-t-il", "Va-t-on", "Y a-t-il", "vas-y", "Allons-y !", "prend-il", "ont-ils eu", "sont-elles arrivées")
    for c in lex.compounds:
        yield c
        yield c.capitalize()
        yield f"Il dit : {c}, puis rien."
        yield c + "s"
        yield c.replace("'", "’")
    for w in words:
        yield w
        yield w.capitalize()
        yield w.upper()
        yield f"({w}),"
        yield f"Je crois que {w} est là."
        yield f"l'{w}"
    for _ in range(2000):        # listed words inside longer ones, and made-up words
        w = rng.choice(words)
        yield rng.choice(["x", "in", "re"]) + w
        yield w + rng.choice(["x", "zz", "q"])
        yield "".join(rng.choice(frfont.LETTERS) for _ in range(rng.randint(2, 9)))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("font")
    ap.add_argument("--lexicon", default=str(HERE / "lexicon"), help="the directory of words.tsv and the rest")
    ap.add_argument("--shaper", action="append", choices=sorted(test_fontlex.SHAPERS))
    ap.add_argument("--corpus", nargs="*", default=[])
    ap.add_argument("--show", type=int, default=10)
    args = ap.parse_args()
    lex = index_compounds(Lexicon(args.lexicon))
    data = Path(args.font).read_bytes()
    failed = 0
    for name in args.shaper or ["harfbuzz"]:
        view = View(data, test_fontlex.SHAPERS[name](data))
        sets = [("lexicon words in context", list(cases(lex, random.Random(1))))]
        for path in args.corpus:
            sets.append((f"lines of {path}", [l for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]))
        for label, texts in sets:
            bad, shown, t = 0, 0, time.perf_counter()
            for text in texts:
                want, got = expected(text, lex), view.hints(text)
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
