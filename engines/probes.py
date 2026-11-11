#!/usr/bin/env python3
"""Small fonts that each use one mechanism the Fontlex fonts rely on, to
find which one a shaping engine handles differently from HarfBuzz.

    python engines/probes.py directwrite        # or coretext, harfbuzz

Each probe is JetBrains Mono with one feature added; it shapes one text and
prints whether the engine gives the glyphs HarfBuzz gives.
"""

import io
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
    "multiple substitution, then a context on its output": ("ab", """
        lookup M { sub a by a c; } M;
        lookup C { sub c' b by C; } C;
        feature calt { lookup M; lookup C; } calt;"""),
    "a contextual rule after 1,500 lookups": ("ab", "".join(f"lookup N{i} {{ sub x by x; }} N{i};\n" for i in range(1500))
                                              + "feature calt {" + "".join(f" lookup N{i};" for i in range(1500))
                                              + " sub a' b by A; } calt;"),
}


def build(fea, extra_glyphs=0):
    f = TTFont(BASE)
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
    for name, (text, fea, *extra) in probes.items():
        data = build(fea, *extra)
        order = TTFont(io.BytesIO(data)).getGlyphOrder()
        want = [order[g] for g, *_ in T.HarfBuzz(data).shape(text)[0]]
        got = [order[g] if g is not None else None for g, *_ in T.SHAPERS[other](data).shape(text)[0]]
        print(f"{'same' if got == want else 'DIFFERS'}: {name}: harfbuzz {' '.join(want)}"
              + ("" if got == want else f"; {other} {' '.join(map(str, got))}"))


if __name__ == "__main__":
    main()
