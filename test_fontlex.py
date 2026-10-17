#!/usr/bin/env python3
"""Check a compiled Fontlex font against the reference lexer.

Shapes text with HarfBuzz (the shaper Chrome, Firefox and Android use) and
compares, character by character, the state/word set encoded in each output
glyph with what the spec's DFA says it should be.

    python test_fontlex.py specs/python.yaml build/Fontlex-Python.ttf [--n 20000]
"""

import argparse
import random
import sys

import uharfbuzz as hb
from fontTools.ttLib import TTFont

from fontlex import SUFFIX, WORD_SUFFIX, Model, load_spec

HAND_CASES = [
    'def f(x): return x + 1',
    'define = 3; undef = 4; deff = 5',
    'if x is not None and isinstance(y, int): pass',
    'island is is_ok isinstance',
    'x1 = 12 + 0x1F + 3.14 + 1_000',
    's = "a # not a comment" # a comment with "quotes"',
    "t = 'it\\'s' + \"say \\\"hi\\\"\" + 'end'",
    'u = "back\\\\" + x',
    '@app.route("/")',
    'print(len(range(10)))',
    'π = 3.14159  # unicode ident-ish: π is "other"',
    'класс = "строка"  # кириллица',
    '"unterminated string here',
    '# whole line comment',
    'lambda: yield from self.items',
    'True False None',
    '',
    'a',
    '"',
    '\\',
]


def glyph_info(name: str, start: str):
    if WORD_SUFFIX in name:
        base, wset = name.split(WORD_SUFFIX)
        return "WORD", wset
    if SUFFIX in name:
        return name.split(SUFFIX)[1], None
    return start, None


def shape(hbfont, text):
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(hbfont, buf, {"calt": True})
    return buf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("font")
    ap.add_argument("--n", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    spec = load_spec(args.spec)
    tt = TTFont(args.font)
    order = tt.getGlyphOrder()
    model = Model(spec, TTFont(args.font).getBestCmap())
    blob = hb.Blob.from_file_path(args.font)
    hbfont = hb.Font(hb.Face(blob))

    def check(text):
        expect = model.lex(text)
        buf = shape(hbfont, text)
        infos = buf.glyph_infos
        if len(infos) != len(text):
            return f"glyph count {len(infos)} != {len(text)}"
        for i, info in enumerate(infos):
            if info.cluster != i:
                return f"cluster mismatch at {i}"
            name = order[info.codepoint]
            st, ws = glyph_info(name, spec.start)
            exp_state, exp_set = expect[i]
            if exp_state is None:          # char not in font
                continue
            if st == "WORD":
                got = (spec.word_state, ws)
            else:
                got = (st, None)
            if got != (exp_state, exp_set):
                return f"char {i} {text[i]!r}: font says {got}, spec says {(exp_state, exp_set)}"
        return None

    failures = 0
    for t in HAND_CASES:
        err = check(t)
        if err:
            failures += 1
            print(f"FAIL {t!r}: {err}")
    print(f"hand-written cases: {len(HAND_CASES) - failures}/{len(HAND_CASES)} pass")

    # Random programs over an alphabet that hits every class, plus words.
    rng = random.Random(args.seed)
    alphabet = list("abdefinstx_XZ0129.\"'\\#@ ()=+:,") + ["é", "π", "ж", "→"]
    words = [w for _, ws in spec.word_sets for w in ws]
    fuzz_fail = 0
    for _ in range(args.n):
        parts = []
        for _ in range(rng.randint(1, 12)):
            if rng.random() < 0.3:
                parts.append(rng.choice(words))
            else:
                parts.append("".join(rng.choice(alphabet) for _ in range(rng.randint(1, 4))))
        text = "".join(parts)
        err = check(text)
        if err:
            fuzz_fail += 1
            if fuzz_fail <= 10:
                print(f"FAIL {text!r}: {err}")
    print(f"random cases: {args.n - fuzz_fail}/{args.n} pass")
    return 1 if failures or fuzz_fail else 0


if __name__ == "__main__":
    sys.exit(main())
