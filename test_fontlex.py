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

from fontlex import (DROPPED_TABLES, RULER_PREFIX, RULER_SUFFIX, START_SUFFIX, SUFFIX, SYLLABLE_INFIX,
                     WORD_SUFFIX, Model, _unify_gpos_scripts, load_spec, subset_font)

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
    'x = a / b // comment */ "not a string"',
    'f(/* block * with ** stars */ 1, `tpl ${x} \\` end`)',
    '/* unterminated block',
    '**/ */ /*/ x',
]

# Combining marks, and letters that have no precomposed form with them.
MARKS = ["́", "̣", "̈", "̱"]


def unruled(name: str) -> str:
    """The glyph a space past the ruler stands for."""
    return name[:-len(RULER_SUFFIX)] if name.endswith(RULER_SUFFIX) else name


def lexed(glyphs, order):
    """The shaped glyphs without the ruler's own (its slots and bars)."""
    return [g for g in glyphs if g[0] is None or not order[g[0]].startswith(RULER_PREFIX)]


def glyph_info(name: str, start: str):
    name = unruled(name)
    if WORD_SUFFIX in name:
        base, wset = name.split(WORD_SUFFIX)
        return "WORD", wset
    for infix in (SUFFIX, START_SUFFIX):
        if infix in name:
            return name.split(infix)[1], None
    return start, None


def base_name(name: str) -> str:
    name = unruled(name)
    for infix in (WORD_SUFFIX, START_SUFFIX, SYLLABLE_INFIX, SUFFIX):
        name = name.split(infix)[0]
    return name


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
    falls_back_clusters = False

    def __init__(self, data: bytes, variations: dict[str, float] | None = None, features=()):
        self.font = hb.Font(hb.Face(hb.Blob(data)))
        if variations:
            self.font.set_variations(variations)
        self.features = {"calt": True, **{tag: True for tag in features}}

    def shape(self, text):
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        # One cluster per character, so a combining mark keeps its own index.
        buf.cluster_level = hb.BufferClusterLevel.MONOTONE_CHARACTERS
        hb.shape(self.font, buf, self.features)
        glyphs, x, y = [], 0, 0
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions or []):
            glyphs.append((info.codepoint, info.cluster, x + pos.x_offset, y + pos.y_offset))
            x += pos.x_advance
            y += pos.y_advance
        return glyphs, x


class CoreText:
    name = "coretext"
    improvises_marks = True
    # A character followed by a mark the font lacks is drawn, with the mark,
    # from a fallback font.
    falls_back_clusters = True

    def __init__(self, data: bytes, variations: dict[str, float] | None = None, features=()):
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
        if variations:
            # Core Text keys variation axes by the tag read as a 32-bit integer.
            axes = {int.from_bytes(tag.encode(), "big"): value for tag, value in variations.items()}
            desc = CT.CTFontDescriptorCreateCopyWithAttributes(desc, {CT.kCTFontVariationAttribute: axes})
        if features:
            settings = [{CT.kCTFontOpenTypeFeatureTag: tag, CT.kCTFontOpenTypeFeatureValue: 1} for tag in features]
            desc = CT.CTFontDescriptorCreateCopyWithAttributes(desc, {CT.kCTFontFeatureSettingsAttribute: settings})
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
           log=print, unify_scripts=False) -> dict[str, tuple[int, int]]:
    """Run every check on a compiled font. Returns {label: (passed, total)}.

    `base` is the path of the base font; without it, positioning isn't checked.
    Pass `unify_scripts` if the font was compiled with it, so the base font
    gets the same GPOS changes before positions are compared. A font compiled
    with --unicodes is detected from its cmap, and the base font is subset to
    match.
    """
    tt = TTFont(io.BytesIO(font_data))
    order = tt.getGlyphOrder()
    model = Model(spec, tt.getBestCmap())
    if base:
        ref = TTFont(base)
        for tag in DROPPED_TABLES:
            if tag in ref:
                del ref[tag]
        kept = sorted(tt.getBestCmap())
        if kept != sorted(ref.getBestCmap()):
            subset_font(ref, kept)
        if unify_scripts:
            _unify_gpos_scripts(ref)
        data = io.BytesIO()
        ref.save(data)
        ref_order = ref.getGlyphOrder()
        ref_data = data.getvalue()
        anchored = anchored_pairs(ref)
        ref_gdef = ref["GDEF"].table if "GDEF" in ref else None
        ref_classes = ref_gdef.GlyphClassDef.classDefs if ref_gdef and ref_gdef.GlyphClassDef else None
    skipped_marks = 0
    skipped_fallback = 0

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

    def cluster_fallback(text):
        """Indices of characters whose cluster has a mark the font lacks."""
        out = set()
        for i, ch in enumerate(text):
            j = i + 1
            while j < len(text) and unicodedata.category(text[j]).startswith("M"):
                if ord(text[j]) not in model.cmap:
                    out.add(i)
                j += 1
        return frozenset(out)

    def check(shaper, text):
        expect = model.lex(text, cluster_fallback(text) if shaper.falls_back_clusters else frozenset())
        glyphs = lexed(shaper.shape(text)[0], order)
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
                got = (spec.word_state or spec.suffix_state or spec.start, ws)
            else:
                got = (st, None)
            if got != (exp_state, exp_set):
                return f"char {i} {text[i]!r}: font says {got}, spec says {(exp_state, exp_set)}"
        return None

    def check_positions(shaper, ref_shaper, text):
        nonlocal skipped_marks, skipped_fallback
        (got, got_w), (want, want_w) = shaper.shape(text), ref_shaper.shape(text)
        got = lexed(got, order)
        got_g = [name_in(order, g) for g, *_ in got]
        got_g = [None if g is None else base_name(g) for g in got_g]
        want_g = [name_in(ref_order, g) for g, *_ in want]
        if got_g != want_g:
            if shaper.falls_back_clusters:
                # Core Text may fall back differently for a cluster with a
                # mark the font lacks; then later positions shift by the
                # fallback font's widths and can't be compared.
                affected = set()
                for i in cluster_fallback(text):
                    affected.add(i)
                    j = i + 1
                    while j < len(text) and unicodedata.category(text[j]).startswith("M"):
                        affected.add(j)
                        j += 1
                rest = lambda gl, names: [(names[k], g[1]) for k, g in enumerate(gl) if g[1] not in affected]  # noqa: E731
                if rest(got, got_g) == rest(want, want_g):
                    skipped_fallback += 1
                    return None
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
                    log(f"FAIL {(t[0] if isinstance(t, tuple) else t)!r}: {err}")
        log(f"{label}: {len(texts) - fails}/{len(texts)} pass")
        results[label] = (len(texts) - fails, len(texts))

    # Random programs over an alphabet that hits every class, plus words.
    rng = random.Random(seed)
    alphabet = list("abdefinstx_XZ0129.\"'\\#@ ()=+:,") + ["é", "π", "ж", "→"]
    for _, chars in spec.classes:      # hit every class of whatever spec this is
        if chars and not any(c in alphabet for c in chars):
            alphabet.append(chars[0])
    words = [w for _, ws in spec.word_sets for w in ws]
    if spec.syllables:
        # Pseudo-words glued from the patterns' own letters, in either case,
        # so the patterns' contexts actually occur.
        frags = [p.strip(".") for p in sorted(spec.syllables.patterns) if p.strip(".")]
        words += ["".join(rng.choice(frags) for _ in range(rng.randint(1, 3))).capitalize()
                  if rng.random() < 0.5 else "".join(rng.choice(frags) for _ in range(rng.randint(1, 3)))
                  for _ in range(400)]
    if spec.suffix_sets:
        # Runs that end in listed suffixes: a start letter, a few letters, a suffix.
        starts = [c for _, cs in spec.classes for c in cs[:3]]
        suffixes = [x for _, xs in spec.suffix_sets for x in xs]
        words += [rng.choice(starts) + "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 3)))
                  + rng.choice(suffixes) for _ in range(max(len(words), 200))]

    def random_text(alpha):
        parts = []
        for _ in range(rng.randint(1, 12)):
            if rng.random() < 0.3:
                parts.append(rng.choice(words))
            else:
                parts.append("".join(rng.choice(alpha) for _ in range(rng.randint(1, 4))))
        return "".join(parts)

    # The spec's own examples: does the lexer color the language as intended?
    def check_example(case):
        text, expected = case
        got = model.tokens(text)
        if got != expected:
            i = next(k for k, (a, b) in enumerate(zip(got, expected)) if a != b)
            return f"char {i} {text[i]!r}: lexes as {got[i]}, example expects {expected[i]}"
        return None

    if spec.examples:
        run("spec examples", spec.examples, check_example)

    # Every glyph the font draws as a colored token needs a color record, or
    # renderers draw it in the text color (shaping alone can't tell).
    colored = {t for _, theme in spec.themes for t in theme}
    layers = tt["COLR"].ColorLayers if "COLR" in tt else {}

    def token_of(name):
        if WORD_SUFFIX in name:
            return name.split(WORD_SUFFIX)[1]
        if SUFFIX in name:
            return spec.token(name.split(SUFFIX)[1]) if name.split(SUFFIX)[1] in spec.states else None
        return None
    needed = [g for g in order if token_of(g) in colored]
    run("color records", needed, lambda g: None if g in layers else "no COLR record")
    hand = HAND_CASES + [text for text, _ in spec.examples]

    fuzz = [random_text(alphabet) for _ in range(n)]
    marked = [random_text(alphabet + list("qjxy") + MARKS) for _ in range(n)]

    # Every transition of the DFA, which random text rarely reaches when it
    # takes several characters (`*/`): the shortest text that reaches each
    # state, then a character of each class, then a random tail.
    reps: dict[str, list[str]] = {k: [] for k in spec.class_names}
    for ch in [c for _, cs in spec.classes for c in cs[:5]] + alphabet:
        g = model.cmap.get(ord(ch))
        k = model.glyph_class.get(g) if g else None
        if k and ch not in reps[k]:
            reps[k].append(ch)
    delta = spec.table()
    path = {spec.start: ""}
    queue = [spec.start]
    for s in queue:
        for k in spec.class_names:
            if reps[k] and delta[s][k] not in path:
                path[delta[s][k]] = path[s] + reps[k][0]
                queue.append(delta[s][k])
    transitions = [path[s] + rng.choice(reps[k]) + random_text(alphabet)[:rng.randint(0, 8)]
                   for s in path for k in spec.class_names if reps[k] for _ in range(20)]
    # The ruler: a bar under every character from column spec.ruler on,
    # counting every character but combining marks.
    gdef = tt["GDEF"].table.GlyphClassDef.classDefs if "GDEF" in tt else {}

    def is_mark_char(ch):
        g = model.cmap.get(ord(ch))
        return gdef.get(g) == 3 if g else unicodedata.category(ch).startswith("M")

    def check_ruler(shaper, text):
        barred = set()
        for gid, cluster, _, _ in shaper.shape(text)[0]:
            name = order[gid] if gid is not None else ""
            if name == RULER_PREFIX + "_bar" or name.endswith(RULER_SUFFIX):
                barred.add(cluster)
        col, want = 0, set()
        for i, ch in enumerate(text):
            if is_mark_char(ch):
                continue
            if col >= spec.ruler:
                want.add(i)
            col += 1
        if barred != want:
            first = min(barred ^ want)
            return f"char {first} {text[first]!r}: bar {'missing' if first in want else 'not wanted'}"
        return None
    if spec.ruler:
        ruled_alphabet = alphabet + [" "] * 8 + ["\u00a0", "q" + MARKS[0], "x" + MARKS[1] + MARKS[2]]
        ruled = ["".join(rng.choice(ruled_alphabet) for _ in range(rng.randint(0, 2 * spec.ruler + 20)))
                 for _ in range(max(n // 10, 200))]
        ruled += ["x" * k for k in range(spec.ruler - 2, spec.ruler + 3)]
        ruled += [" " * spec.ruler + "x", "\u00a0" * (spec.ruler + 1)]

    for sname in shapers:
        shaper = SHAPERS[sname](font_data)
        if spec.ruler:
            run(f"{sname}: ruler at column {spec.ruler}", ruled, lambda t: check_ruler(shaper, t))
        run(f"{sname}: hand-written cases", hand, lambda t: check(shaper, t))
        run(f"{sname}: random cases", fuzz, lambda t: check(shaper, t))
        run(f"{sname}: transition cases", transitions, lambda t: check(shaper, t))
        if base:
            ref_shaper = SHAPERS[sname](ref_data)
            pos = lambda t: check_positions(shaper, ref_shaper, t)  # noqa: E731
            run(f"{sname}: positioning, hand-written", hand, pos)
            skipped_marks = skipped_fallback = 0
            run(f"{sname}: positioning, random", fuzz + marked + transitions, pos)
            if skipped_marks:
                log(f"{sname}: skipped {skipped_marks} improvised positions of marks "
                    "the base font has no anchor for")
            if skipped_fallback:
                log(f"{sname}: skipped {skipped_fallback} strings that fall back differently "
                    "around marks the font lacks")
            # Variable fonts: variants must vary like their base glyphs too.
            if "fvar" in tt:
                sample = (fuzz + marked)[::8]
                for axis in tt["fvar"].axes:
                    for value in (axis.minValue, axis.maxValue):
                        loc = {axis.axisTag: value}
                        a, b = SHAPERS[sname](font_data, loc), SHAPERS[sname](ref_data, loc)
                        run(f"{sname}: positioning at {axis.axisTag}={value:g}", sample,
                            lambda t, a=a, b=b: check_positions(a, b, t))
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("font")
    ap.add_argument("--base", help="base font the spec was compiled from")
    ap.add_argument("--shaper", action="append", choices=SHAPERS,
                    help="shaper to test with; repeat for several (default: harfbuzz)")
    ap.add_argument("--unify-scripts", action="store_true",
                    help="the font was compiled with --unify-scripts")
    ap.add_argument("--n", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    results = verify(load_spec(args.spec), open(args.font, "rb").read(), args.base,
                     args.shaper or ["harfbuzz"], args.n, args.seed,
                     unify_scripts=args.unify_scripts)
    return 0 if all(passed == total for passed, total in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
