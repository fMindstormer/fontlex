#!/usr/bin/env python3
"""Shape lines with the font and compare what it draws with layout.py.

    python math/verify.py FONT.ttf [--shaper harfbuzz] [--shaper coretext] [--n N] [LINE ...]
    python math/verify.py --simulate [--n N]

What a shaped line draws is read back from the glyphs: a character's glyph
(by name: its base glyph, scaled by style), a radical (by name), and rules
(the outline's box). Lines are samples.EDGES and N random ones unless
given; --simulate checks the passes in Python, before any font is built.
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

from fontTools.ttLib import TTFont

import layout as L
import samples


class Reader:
    def __init__(self, path):
        f = TTFont(path)
        self.order = f.getGlyphOrder()
        self.glyf = f["glyf"]
        self.char_of = {}
        for cp, name in f.getBestCmap().items():
            self.char_of.setdefault(name, chr(cp))
        self.data = open(path, "rb").read()

    def ink(self, name, x, y):
        """What the glyph draws at (x, y), as layout.py describes it."""
        m = re.fullmatch(r"(.+)\.s(\d)([bm])", name)
        if m and m.group(1) in self.char_of:
            return ("glyph", self.char_of[m.group(1)], int(m.group(2)), x, y)
        m = re.fullmatch(r"_radical(\d)(\d)([bm])", name)
        if m:
            return ("radical", int(m.group(1)), int(m.group(2)), x, y)
        if name.startswith("_ink"):
            g = self.glyf[name]
            if g.numberOfContours <= 0:
                return None
            g.recalcBounds(self.glyf)
            return ("rule", x + g.xMin, x + g.xMax, y + g.yMin, y + g.yMax)
        if name in self.char_of and self.char_of[name] != " ":
            return ("glyph", self.char_of[name], 0, x, y)
        return None

    def draw(self, shaped):
        glyphs, width = shaped
        ink = []
        for g, _, x, y in glyphs:
            if g is None:
                ink.append(("missing",))
                continue
            r = self.ink(self.order[g], round(x), round(y))
            if r is not None:
                ink.append(r)
        return sorted(L.merge(ink)), round(width)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("font", nargs="?")
    ap.add_argument("lines", nargs="*")
    ap.add_argument("--shaper", action="append", choices=("harfbuzz", "coretext"))
    ap.add_argument("--simulate", action="store_true",
                    help="check the passes in Python (program.py, assemble.py) instead of a font")
    ap.add_argument("--n", type=int, default=0, help="random lines, besides samples.EDGES")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--show", type=int, default=5, help="differences to print in full")
    args = ap.parse_args()
    lines = args.lines or (samples.EDGES + samples.lines(args.n, args.seed))
    if args.simulate:
        import assemble
        bad = [line for line in lines if not assemble.check(line)[0]]
        for line in bad[:args.show]:
            print("DIFF", repr(line))
        print(f"simulated: {len(lines)} lines, {len(bad)} differ")
        return 1 if bad else 0
    import test_fontlex as tf
    r = Reader(args.font)
    kinds = {"harfbuzz": tf.HarfBuzz, "coretext": tf.CoreText}
    shapers = {n: kinds[n](r.data) for n in (args.shaper or ["harfbuzz"])}
    bad = 0
    for line in lines:
        want = L.layout(line)
        for n, sh in shapers.items():
            got = r.draw(sh.shape(line))
            if got == want:
                continue
            bad += 1
            if bad <= args.show:
                print(f"DIFF {n} {line!r}")
                for x in sorted(set(got[0]) | set(want[0]), key=str):
                    if (x in got[0]) != (x in want[0]):
                        print("   ", "+" if x in got[0] else "-", x)
                print("    advance", got[1], "want", want[1])
            elif bad == args.show + 1:
                print("...")
    print(f"{len(lines)} lines, {', '.join(shapers)}: {bad} differ")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
