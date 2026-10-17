#!/usr/bin/env python3
"""Check a compiled Fontlex font against the reference lexer.

Shapes text with HarfBuzz (the shaper Chrome, Firefox and Android use) and
compares, character by character, the state/word set encoded in each output
glyph with what the spec's DFA says it should be.

With --base, it also checks positioning: the compiled font must place every
glyph exactly where the base font (minus the tables fontlex drops) places the same base glyph,
so kerning and mark anchors survive the lexer's substitutions.

    python test_fontlex.py specs/python.yaml build/Fontlex-Python.ttf \
        [--base fonts/JetBrainsMono-Regular.ttf] [--n 20000]
"""

import argparse
import io
import random
import sys

import uharfbuzz as hb
from fontTools.ttLib import TTFont

from fontlex import DROPPED_TABLES, SUFFIX, WORD_SUFFIX, Model, load_spec

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
    'q\u0301 = "x\u0323" + j\u0308',   # marks with no precomposed glyph
]

# Combining marks, and letters that have no precomposed form with them.
MARKS = ["\u0301", "\u0323", "\u0308", "\u0331"]


def glyph_info(name: str, start: str):
    if WORD_SUFFIX in name:
        base, wset = name.split(WORD_SUFFIX)
        return "WORD", wset
    if SUFFIX in name:
        return name.split(SUFFIX)[1], None
    return start, None


def base_name(name: str) -> str:
    return name.split(WORD_SUFFIX)[0].split(SUFFIX)[0]


def hb_font(data: bytes):
    return hb.Font(hb.Face(hb.Blob(data)))


def shape(hbfont, text):
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    # One cluster per character, so a combining mark keeps its own index.
    buf.cluster_level = hb.BufferClusterLevel.MONOTONE_CHARACTERS
    hb.shape(hbfont, buf, {"calt": True})
    return buf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("font")
    ap.add_argument("--base", help="base font the spec was compiled from")
    ap.add_argument("--n", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    spec = load_spec(args.spec)
    tt = TTFont(args.font)
    order = tt.getGlyphOrder()
    model = Model(spec, TTFont(args.font).getBestCmap())
    hbfont = hb_font(open(args.font, "rb").read())
    if args.base:
        ref = TTFont(args.base)
        for tag in DROPPED_TABLES:
            if tag in ref:
                del ref[tag]
        data = io.BytesIO()
        ref.save(data)
        ref_order = ref.getGlyphOrder()
        ref_font = hb_font(data.getvalue())

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

    def check_positions(text):
        got, want = shape(hbfont, text), shape(ref_font, text)
        got_g = [base_name(order[i.codepoint]) for i in got.glyph_infos]
        want_g = [ref_order[i.codepoint] for i in want.glyph_infos]
        if got_g != want_g:
            return f"glyphs {got_g} != base font's {want_g}"
        for i, (a, b) in enumerate(zip(got.glyph_positions or [], want.glyph_positions or [])):
            pa = (a.x_advance, a.y_advance, a.x_offset, a.y_offset)
            pb = (b.x_advance, b.y_advance, b.x_offset, b.y_offset)
            if pa != pb:
                return f"glyph {i} {got_g[i]!r}: position {pa} != base font's {pb}"
        return None

    def run(label, texts, fn):
        fails = 0
        for t in texts:
            err = fn(t)
            if err:
                fails += 1
                if fails <= 10:
                    print(f"FAIL {t!r}: {err}")
        print(f"{label}: {len(texts) - fails}/{len(texts)} pass")
        return fails

    # Random programs over an alphabet that hits every class, plus words.
    rng = random.Random(args.seed)
    alphabet = list("abdefinstx_XZ0129.\"'\\#@ ()=+:,") + ["é", "π", "ж", "→"]
    words = [w for _, ws in spec.word_sets for w in ws]

    def random_text(alpha):
        parts = []
        for _ in range(rng.randint(1, 12)):
            if rng.random() < 0.3:
                parts.append(rng.choice(words))
            else:
                parts.append("".join(rng.choice(alpha) for _ in range(rng.randint(1, 4))))
        return "".join(parts)

    fuzz = [random_text(alphabet) for _ in range(args.n)]
    fails = run("hand-written cases", HAND_CASES, check)
    fails += run("random cases", fuzz, check)
    if args.base:
        marked = [random_text(alphabet + list("qjxy") + MARKS) for _ in range(args.n)]
        fails += run("positioning, hand-written", HAND_CASES, check_positions)
        fails += run("positioning, random", fuzz + marked, check_positions)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
