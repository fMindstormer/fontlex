#!/usr/bin/env python3
"""Check a compiled Fontlex font against the reference lexer.

Shapes text and compares, character by character, the state/word set encoded
in each output glyph with what the spec's DFA says it should be. Two shapers
are supported: HarfBuzz (Chrome, Firefox, Android) and, on macOS, Core Text
(Safari and native Mac apps; needs pyobjc-framework-CoreText).

With --base, it also checks positioning: the compiled font must place every
glyph exactly where the base font (minus the tables fontlex drops) places the
same base glyph, so kerning and mark anchors survive the lexer's substitutions.
One exception, Core Text only: where the base font has no anchor for a mark,
Core Text improvises a position for the original mark glyph but not for a
lexed variant, so those marks are skipped and counted.

    python test_fontlex.py specs/python.yaml build/Fontlex-Python.ttf \
        [--base fonts/JetBrainsMono-Regular.ttf] [--shaper harfbuzz] \
        [--shaper coretext] [--n 20000]
"""

import argparse
import io
import random
import sys
import unicodedata

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
    'q́ = "x̣" + j̈',   # marks with no precomposed glyph
    'a中1 + "😀s" # 中',                # chars the font lacks reset the lexer
]

# Combining marks, and letters that have no precomposed form with them.
MARKS = ["́", "̣", "̈", "̱"]


def glyph_info(name: str, start: str):
    if WORD_SUFFIX in name:
        base, wset = name.split(WORD_SUFFIX)
        return "WORD", wset
    if SUFFIX in name:
        return name.split(SUFFIX)[1], None
    return start, None


def base_name(name: str) -> str:
    return name.split(WORD_SUFFIX)[0].split(SUFFIX)[0]


def anchored_pairs(tt: TTFont) -> set[tuple[str, str]]:
    """(glyph, mark) pairs the font's GPOS attaches with an anchor."""
    pairs: set[tuple[str, str]] = set()
    if "GPOS" not in tt:
        return pairs
    for lookup in tt["GPOS"].table.LookupList.Lookup:
        for st in lookup.SubTable:
            kind = lookup.LookupType
            if kind == 9:
                kind, st = st.ExtensionLookupType, st.ExtSubTable
            if kind == 4:
                marks, bases = st.MarkCoverage.glyphs, st.BaseCoverage.glyphs
                anchors = [r.BaseAnchor for r in st.BaseArray.BaseRecord]
                classes = [r.Class for r in st.MarkArray.MarkRecord]
            elif kind == 6:
                marks, bases = st.Mark1Coverage.glyphs, st.Mark2Coverage.glyphs
                anchors = [r.Mark2Anchor for r in st.Mark2Array.Mark2Record]
                classes = [r.Class for r in st.Mark1Array.MarkRecord]
            else:
                continue
            for b, row in zip(bases, anchors):
                for m, c in zip(marks, classes):
                    if row[c] is not None:
                        pairs.add((b, m))
    return pairs


# Each shaper's shape(text) returns (glyphs, width). glyphs is a list of
# (glyph id, character index, x, y) with absolute pen positions in font units;
# the glyph id is None where the shaper fell back to another font.

class HarfBuzz:
    name = "harfbuzz"
    improvises_marks = False

    def __init__(self, data: bytes):
        self.font = hb.Font(hb.Face(hb.Blob(data)))

    def shape(self, text):
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        # One cluster per character, so a combining mark keeps its own index.
        buf.cluster_level = hb.BufferClusterLevel.MONOTONE_CHARACTERS
        hb.shape(self.font, buf, {"calt": True})
        glyphs, x, y = [], 0, 0
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions or []):
            glyphs.append((info.codepoint, info.cluster, x + pos.x_offset, y + pos.y_offset))
            x += pos.x_advance
            y += pos.y_advance
        return glyphs, x


class CoreText:
    name = "coretext"
    improvises_marks = True

    def __init__(self, data: bytes):
        try:
            import CoreText as CT
            from Foundation import NSAttributedString, NSData
        except ImportError:
            sys.exit("--shaper coretext needs macOS and pyobjc-framework-CoreText")
        self.CT, self.NSAttributedString = CT, NSAttributedString
        desc = CT.CTFontManagerCreateFontDescriptorFromData(NSData.dataWithBytes_length_(data, len(data)))
        if desc is None:
            sys.exit("Core Text could not load the font")
        # Size the font at one unit per em so positions come out in font units.
        upem = TTFont(io.BytesIO(data))["head"].unitsPerEm
        self.font = CT.CTFontCreateWithFontDescriptor(desc, upem, None)
        self.ps_name = CT.CTFontCopyPostScriptName(self.font)

    def shape(self, text):
        CT = self.CT
        # Core Text reports UTF-16 offsets; map them to character indices.
        char_at, u = {}, 0
        for i, ch in enumerate(text):
            char_at[u] = i
            u += 2 if ord(ch) > 0xFFFF else 1
        s = self.NSAttributedString.alloc().initWithString_attributes_(
            text, {CT.kCTFontAttributeName: self.font})
        line = CT.CTLineCreateWithAttributedString(s)
        glyphs = []
        for run in CT.CTLineGetGlyphRuns(line):
            run_font = CT.CTRunGetAttributes(run)[CT.kCTFontAttributeName]
            ours = CT.CTFontCopyPostScriptName(run_font) == self.ps_name
            r = (0, CT.CTRunGetGlyphCount(run))  # PyObjC can't size buffers for (0, 0)
            for g, u16, p in zip(CT.CTRunGetGlyphs(run, r, None),
                                 CT.CTRunGetStringIndices(run, r, None),
                                 CT.CTRunGetPositions(run, r, None)):
                glyphs.append((g if ours else None, char_at[u16], p.x, p.y))
        return glyphs, CT.CTLineGetTypographicBounds(line, None, None, None)[0]


SHAPERS = {s.name: s for s in (HarfBuzz, CoreText)}


def verify(spec, font_data: bytes, base=None, shapers=("harfbuzz",), n=20000, seed=1,
           log=print) -> dict[str, tuple[int, int]]:
    """Run every check on a compiled font. Returns {label: (passed, total)}.

    `base` is the path of the base font; without it, positioning isn't checked.
    """
    tt = TTFont(io.BytesIO(font_data))
    order = tt.getGlyphOrder()
    model = Model(spec, tt.getBestCmap())
    if base:
        ref = TTFont(base)
        for tag in DROPPED_TABLES:
            if tag in ref:
                del ref[tag]
        data = io.BytesIO()
        ref.save(data)
        ref_order = ref.getGlyphOrder()
        ref_data = data.getvalue()
        anchored = anchored_pairs(ref)
        ref_gdef = ref["GDEF"].table if "GDEF" in ref else None
        ref_classes = ref_gdef.GlyphClassDef.classDefs if ref_gdef and ref_gdef.GlyphClassDef else None
    skipped_marks = 0

    def is_mark(text, glyphs, names, i):
        # Like the shapers: GDEF glyph classes if the font has them, else the
        # character's Unicode category.
        if ref_classes is not None:
            return ref_classes.get(names[i]) == 3
        return unicodedata.category(text[glyphs[i][1]]).startswith("M")

    def unanchored(text, glyphs, names, i):
        """Is glyph i a mark with no anchor on the glyph it attaches to?"""
        if names[i] is None or not is_mark(text, glyphs, names, i):
            return False
        j = i - 1
        while j >= 0 and names[j] is not None and is_mark(text, glyphs, names, j):
            j -= 1
        attach = {names[i - 1]} if i else set()
        if j >= 0:
            attach.add(names[j])
        return not any((g, names[i]) in anchored for g in attach)

    def name_in(names, gid):
        return None if gid is None else names[gid]

    def check(shaper, text):
        expect = model.lex(text)
        glyphs, _ = shaper.shape(text)
        if len(glyphs) != len(text):
            return f"glyph count {len(glyphs)} != {len(text)}"
        for i, (gid, cluster, _, _) in enumerate(glyphs):
            if cluster != i:
                return f"cluster mismatch at {i}"
            exp_state, exp_set = expect[i]
            if exp_state is None:          # char not in font
                continue
            if gid is None:
                return f"char {i} {text[i]!r} is in the font but was drawn from a fallback font"
            st, ws = glyph_info(order[gid], spec.start)
            if st == "WORD":
                got = (spec.word_state, ws)
            else:
                got = (st, None)
            if got != (exp_state, exp_set):
                return f"char {i} {text[i]!r}: font says {got}, spec says {(exp_state, exp_set)}"
        return None

    def check_positions(shaper, ref_shaper, text):
        nonlocal skipped_marks
        (got, got_w), (want, want_w) = shaper.shape(text), ref_shaper.shape(text)
        got_g = [name_in(order, g) for g, *_ in got]
        got_g = [None if g is None else base_name(g) for g in got_g]
        want_g = [name_in(ref_order, g) for g, *_ in want]
        if got_g != want_g:
            return f"glyphs {got_g} != base font's {want_g}"
        skipped_last = False
        for i, (a, b) in enumerate(zip(got, want)):
            pa, pb = (round(a[2], 3), round(a[3], 3)), (round(b[2], 3), round(b[3], 3))
            if pa != pb and shaper.improvises_marks and unanchored(text, want, want_g, i):
                skipped_marks += 1
                skipped_last = i == len(want) - 1
                continue
            if pa != pb:
                return f"glyph {i} {got_g[i]!r}: position {pa} != base font's {pb}"
        # An improvised trailing mark can also change the line's width.
        if round(got_w, 3) != round(want_w, 3) and not skipped_last:
            return f"line width {got_w} != base font's {want_w}"
        return None

    results: dict[str, tuple[int, int]] = {}

    def run(label, texts, fn):
        fails = 0
        for t in texts:
            err = fn(t)
            if err:
                fails += 1
                if fails <= 10:
                    log(f"FAIL {t!r}: {err}")
        log(f"{label}: {len(texts) - fails}/{len(texts)} pass")
        results[label] = (len(texts) - fails, len(texts))

    # Random programs over an alphabet that hits every class, plus words.
    rng = random.Random(seed)
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

    fuzz = [random_text(alphabet) for _ in range(n)]
    marked = [random_text(alphabet + list("qjxy") + MARKS) for _ in range(n)]
    for sname in shapers:
        shaper = SHAPERS[sname](font_data)
        run(f"{sname}: hand-written cases", HAND_CASES, lambda t: check(shaper, t))
        run(f"{sname}: random cases", fuzz, lambda t: check(shaper, t))
        if base:
            ref_shaper = SHAPERS[sname](ref_data)
            pos = lambda t: check_positions(shaper, ref_shaper, t)  # noqa: E731
            run(f"{sname}: positioning, hand-written", HAND_CASES, pos)
            skipped_marks = 0
            run(f"{sname}: positioning, random", fuzz + marked, pos)
            if skipped_marks:
                log(f"{sname}: skipped {skipped_marks} improvised positions of marks "
                    "the base font has no anchor for")
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("font")
    ap.add_argument("--base", help="base font the spec was compiled from")
    ap.add_argument("--shaper", action="append", choices=SHAPERS,
                    help="shaper to test with; repeat for several (default: harfbuzz)")
    ap.add_argument("--n", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    results = verify(load_spec(args.spec), open(args.font, "rb").read(), args.base,
                     args.shaper or ["harfbuzz"], args.n, args.seed)
    return 0 if all(passed == total for passed, total in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
