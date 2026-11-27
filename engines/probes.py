#!/usr/bin/env python3
"""Small fonts that each use one mechanism the Fontlex fonts rely on, to
find which one a shaping engine handles differently from HarfBuzz.

    python engines/probes.py directwrite        # or coretext, harfbuzz

Each probe is JetBrains Mono with one feature added; it shapes one text and
prints whether the engine gives the glyphs HarfBuzz gives.
"""

import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import test_fontlex as T  # noqa: E402
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402
from fontTools.ttLib.tables._g_l_y_f import Glyph  # noqa: E402

BASE = ROOT / "fonts" / "JetBrainsMono-Regular.ttf"

PROBES = {
    # one contextual rule that substitutes at two places
    "two substitutions in one rule": ("ab", """
        lookup UA { sub a by A; } UA;
        lookup UB { sub b by B; } UB;
        feature calt { sub a' lookup UA b' lookup UB; } calt;"""),
    # a rule that looks past base glyphs, seeing only one mark
    "mark filtering set": ("x\u0300z\u0300", """
        table GDEF { GlyphClassDef [x z], , [gravecomb acutecomb], ; } GDEF;
        lookup MF {
            lookupflag IgnoreBaseGlyphs UseMarkFilteringSet [gravecomb];
            sub gravecomb' gravecomb by acutecomb;
        } MF;
        feature calt { lookup MF; } calt;"""),
    "reverse chaining": ("abc", """
        feature calt { reversesub a b' by B; } calt;"""),
    # each application reads what the one after it (to its right) wrote
    "reverse chaining, applied at three places": ("bbbc", """
        feature calt { reversesub b' [c B] by B; } calt;"""),
    "reverse chaining over a mark filtering set, at three places": ("x\u0300q\u0300f\u0300h\u0301", """
        table GDEF { GlyphClassDef [x q f h], , [gravecomb acutecomb], ; } GDEF;
        lookup R {
            lookupflag IgnoreBaseGlyphs UseMarkFilteringSet [gravecomb acutecomb];
            reversesub gravecomb' acutecomb by acutecomb;
        } R;
        feature calt { lookup R; } calt;"""),
    "reverse chaining skipping bases, no filtering set, at three places": ("x\u0300q\u0300f\u0300h\u0301", """
        table GDEF { GlyphClassDef [x q f h], , [gravecomb acutecomb], ; } GDEF;
        lookup R {
            lookupflag IgnoreBaseGlyphs;
            reversesub gravecomb' acutecomb by acutecomb;
        } R;
        feature calt { lookup R; } calt;"""),
    # the right b matches the first subtable, the others the second
    "reverse chaining in two subtables, at three places": ("bbbc", """
        lookup R { reversesub b' c by B; subtable; reversesub b' B by B; } R;
        feature calt { lookup R; } calt;"""),
    "the same, as an extension lookup": ("bbbc", """
        lookup R useExtension { reversesub b' c by B; subtable; reversesub b' B by B; } R;
        feature calt { lookup R; } calt;"""),
    "reverse chaining, one subtable, as an extension lookup": ("bbbc", """
        lookup R useExtension { reversesub b' [c B] by B; } R;
        feature calt { lookup R; } calt;"""),
    "multiple substitution, then a context on its output": ("ab", """
        lookup M { sub a by a c; } M;
        lookup C { sub c' b by C; } C;
        feature calt { lookup M; lookup C; } calt;"""),
    "a contextual rule after 1,500 lookups": ("ab", "".join(f"lookup N{i} {{ sub x by x; }} N{i};\n" for i in range(1500))
                                              + "feature calt {" + "".join(f" lookup N{i};" for i in range(1500))
                                              + " sub a' b by A; } calt;"),
}

# Default features, each on its own letter, beside a stylistic set
DEFAULT_SUBS = """
    feature ccmp { sub a by A; } ccmp;
    feature locl { sub b by B; } locl;
    feature rlig { sub c by C; } rlig;
    feature liga { sub d by D; } liga;
    feature clig { sub e by E; } clig;
    feature calt { sub g by G; } calt;
    feature ss01 { sub h by H; } ss01;"""
DEFAULT_POS = """
    feature kern { pos T o -300; } kern;
    markClass acutecomb <anchor 0 0> @TOP;
    feature mark { pos base x <anchor 250 700> mark @TOP; } mark;
    markClass gravecomb <anchor 0 0> @TOP2;
    feature mkmk { pos mark acutecomb <anchor 0 300> mark @TOP2; } mkmk;
    feature ss01 { sub z by Z; } ss01;"""

# Probes with options: the features asked for; `only`, to pass DirectWrite
# just those, not the defaults with them (dwshape --only); `layout`, to lay
# the text out with IDWriteTextLayout (dwshape --layout); `positions`, to
# compare positions too; `selector`, U+FE00 (variation selector 1, the
# Fontlex noun marker) mapped to an empty glyph; `uvs`, b + U+FE00 mapped to
# B in a cmap format 14 subtable.
OPTION_PROBES = {
    "default substitutions, beside a stylistic set": (
        "abcdegh", DEFAULT_SUBS, {"features": ("ss01",), "only": True}),
    "default substitutions, with the defaults passed too": ("abcdegh", DEFAULT_SUBS, {"features": ("ss01",)}),
    "default substitutions, beside a stylistic set, in a text layout": (
        "abcdegh", DEFAULT_SUBS, {"features": ("ss01",), "only": True, "layout": True}),
    "default positioning, beside a stylistic set": (
        "Tox\u0301\u0300", DEFAULT_POS, {"features": ("ss01",), "positions": True, "only": True}),
    "default positioning, with the defaults passed too": (
        "Tox\u0301\u0300", DEFAULT_POS, {"features": ("ss01",), "positions": True}),
    "default positioning, beside a stylistic set, in a text layout": (
        "Tox\u0301\u0300", DEFAULT_POS, {"features": ("ss01",), "positions": True, "only": True, "layout": True}),
    "the same, no features, in a text layout": (
        "Tox\u0301\u0300", DEFAULT_POS, {"positions": True, "layout": True}),
    "a variation selector in a context rule": ("ab\uFE00", """
        feature calt { sub b' uniFE00 by B; } calt;""", {"selector": True}),
    "a variation selector as lookahead, past a letter": ("ab\uFE00", """
        feature calt { sub a' b uniFE00 by A; } calt;""", {"selector": True}),
    "a variation sequence in cmap 14": ("ab\uFE00", "", {"selector": True, "uvs": True}),
    "a variation sequence in cmap 14, then a multiple substitution back": ("ab\uFE00", """
        feature calt { sub B by b uniFE00; } calt;""", {"selector": True, "uvs": True}),
    "the same, then a context rule on the selector": ("ab\uFE00", """
        lookup M { sub B by b uniFE00; } M;
        lookup C { sub a' b uniFE00 by A; } C;
        feature calt { lookup M; lookup C; } calt;""", {"selector": True, "uvs": True}),
}


def add_selector(f, uvs):
    """U+FE00 as an empty glyph; with `uvs`, b + U+FE00 as B in cmap 14."""
    order = list(f.getGlyphOrder())
    g = Glyph()
    g.numberOfContours = 0
    f["glyf"].glyphs["uniFE00"] = g
    f["hmtx"]["uniFE00"] = (0, 0)
    order.append("uniFE00")
    f.setGlyphOrder(order)
    f["glyf"].glyphOrder = order
    for t in f["cmap"].tables:
        if t.isUnicode():
            t.cmap[0xFE00] = "uniFE00"
    if uvs:
        from fontTools.ttLib.tables._c_m_a_p import CmapSubtable
        t = CmapSubtable.newSubtable(14)
        t.platformID, t.platEncID, t.language = 0, 5, 0xFF
        t.cmap, t.uvsDict = {}, {0xFE00: [(ord("b"), "B")]}
        f["cmap"].tables.append(t)


def build(fea, extra_glyphs=0, selector=False, uvs=False):
    f = TTFont(BASE)
    if selector:
        add_selector(f, uvs)
    if extra_glyphs:
        order = list(f.getGlyphOrder())
        for i in range(extra_glyphs):
            name = f"_pad{i}"
            g = Glyph()
            g.numberOfContours = 0
            f["glyf"].glyphs[name] = g
            f["hmtx"][name] = (0, 0)
            order.append(name)
        f.setGlyphOrder(order)
        f["glyf"].glyphOrder = order
    if fea:
        addOpenTypeFeaturesFromString(f, fea)
    out = io.BytesIO()
    f.save(out)
    return out.getvalue()


def main():
    other = sys.argv[1] if len(sys.argv) > 1 else "harfbuzz"
    probes = dict(PROBES)
    # the same two-substitution rule, with glyph ids past 32,767 and 40,000
    probes["a rule on glyphs past id 40,000"] = ("ab", """
        lookup UA { sub a by _pad40500; } UA;
        lookup UB { sub _pad40500 by A; } UB;
        feature calt { lookup UA; lookup UB; } calt;""", 41000)
    probes.update({name: (text, fea, 0, opts) for name, (text, fea, opts) in OPTION_PROBES.items()})
    for name, (text, fea, *extra) in probes.items():
        extra_glyphs, opts = (extra[0] if extra else 0), (extra[1] if len(extra) > 1 else {})
        text = re.sub(r"\\u([0-9A-Fa-f]{4})", lambda m: chr(int(m[1], 16)), text)
        data = build(fea, extra_glyphs, opts.get("selector", False), opts.get("uvs", False))
        order = TTFont(io.BytesIO(data)).getGlyphOrder()
        features = opts.get("features", ())

        def glyphs(shaper):
            out = []
            only = {k: True for k in ("only", "layout") if opts.get(k)} if shaper is T.DirectWrite else {}
            for g, _, x, y in shaper(data, features=features, **only).shape(text)[0]:
                name = order[g] if g is not None else "None"
                out.append(f"{name}@{x:.0f},{y:.0f}" if opts.get("positions") else name)
            return out
        want, got = glyphs(T.HarfBuzz), glyphs(T.SHAPERS[other])
        print(f"{'same' if got == want else 'DIFFERS'}: {name}: harfbuzz {' '.join(want)}"
              + ("" if got == want else f"; {other} {' '.join(got)}"))


if __name__ == "__main__":
    main()
