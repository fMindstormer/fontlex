#!/usr/bin/env python3
"""Shape lines with the font and compare what it draws with layout.py.

    python math/verify.py FONT.ttf [--shaper harfbuzz] [--shaper coretext] [--n N] [--relaxed] [LINE ...]
    python math/verify.py --simulate [--n N] [--relaxed]

What a shaped line draws is read back from the glyphs: a character's glyph
(by name: its base glyph, scaled by style), an accent (by name, and over
the character it sits on: where the font puts an accent over that
character, layout.accent_offset), a radical (by name), and rules (the
outline's box). Lines are samples.EDGES and N random ones unless
given; --simulate checks the passes in Python, before any font is built.
With --relaxed, the relaxed notation (relaxed.py: samples.RELAXED_EDGES
and random lines of it), against relaxed.layout.
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

from fontTools.pens.boundsPen import BoundsPen
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
        self.gs, self.cmap = f.getGlyphSet(), f.getBestCmap()
        self.tops = {}

    def top(self, ch):
        """How high the character's outline reaches."""
        if ch not in self.tops:
            bp = BoundsPen(self.gs)
            self.gs[self.cmap[ord(ch)]].draw(bp)
            self.tops[ch] = bp.bounds[3] if bp.bounds else L.HEIGHT[0]
        return self.tops[ch]

    def ink(self, name, x, y):
        """What the glyph draws at (x, y), as layout.py describes it."""
        m = re.fullmatch(r"(.+)\.s(\d)([bm])", name)
        if m and m.group(1) in self.char_of:
            return ("glyph", self.char_of[m.group(1)], int(m.group(2)), x, y)
        m = re.fullmatch(r"_acc([a-z])(\d)([bm])", name)
        if m:           # where its character is: draw() says
            return ("acc", m.group(1), int(m.group(2)), m.group(3), x, y)
        m = re.fullmatch(r"_radical(\d)(\d)([bm])", name)
        if m:
            return ("radical", int(m.group(1)), int(m.group(2)), x, y)
        m = re.fullmatch(r"_paren([LR])(\d)(\d)o(m?)(\d+)", name)
        if m:
            dx = int(m.group(5)) * (-1 if m.group(4) else 1) * L.UNIT
            return ("paren", m.group(1), int(m.group(2)), int(m.group(3)), x + dx, y)
        if name.startswith("_inka"):        # a rule's piece (if any) and a wide arrow's head, last
            g = self.glyf[name]
            coords, ends, _ = g.getCoordinates(self.glyf)
            boxes, first = [], 0
            for end in ends:
                xs = [p[0] for p in coords[first:end + 1]]
                ys = [p[1] for p in coords[first:end + 1]]
                boxes.append((x + min(xs), x + max(xs), y + min(ys), y + max(ys)))
                first = end + 1
            return [("rule",) + box for box in boxes[:-1]] + [("arrow",) + boxes[-1]]
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
            if isinstance(r, list):
                ink += r
            elif r is not None:
                ink.append(r)
        return sorted(L.merge(self.accents(ink))), round(width)

    def accents(self, ink):
        """Each accent glyph as the accent over the character it sits on: a
        character of its style, for which it is exactly where the font puts
        an accent (from the character's origin in a chain, from past its
        advance in flow). Any other is stray."""
        chars = {}
        for r in ink:
            if r[0] == "glyph":
                chars.setdefault((r[2], r[3]), []).append(r)
        out = []
        for r in ink:
            if r[0] != "acc":
                out.append(r)
                continue
            _, code, st, mode, ax, ay = r
            dx = L.WIDTH[st] if mode == "b" else L.accent_offset(0, st)[0]
            on = [c for c in chars.get((st, ax - dx), []) if c[4] + L.accent_offset(self.top(c[1]), st)[1] == ay]
            if on:
                chars[(st, ax - dx)].remove(on[0])
                out.append(("accent", code, st, on[0][3], on[0][4]))
            else:
                out.append(("stray accent", code, st, mode, ax, ay))
        return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("font", nargs="?")
    ap.add_argument("lines", nargs="*")
    ap.add_argument("--shaper", action="append", choices=("harfbuzz", "coretext", "directwrite"))
    ap.add_argument("--simulate", action="store_true",
                    help="check the passes in Python (program.py, assemble.py) instead of a font")
    ap.add_argument("--n", type=int, default=0, help="random lines, besides samples.EDGES")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--show", type=int, default=5, help="differences to print in full")
    ap.add_argument("--relaxed", action="store_true", help="the relaxed notation's font and lines")
    args = ap.parse_args()
    if args.relaxed:
        import front
        import relaxed
        lines = args.lines or (samples.RELAXED_EDGES + samples.relaxed_lines(args.n, args.seed))
        model, check = relaxed.layout, front.check
    else:
        import assemble
        lines = args.lines or (samples.EDGES + samples.lines(args.n, args.seed))
        model, check = L.layout, assemble.check
    if args.simulate:
        bad = [line for line in lines if not check(line)[0]]
        for line in bad[:args.show]:
            print("DIFF", repr(line))
        print(f"simulated: {len(lines)} lines, {len(bad)} differ")
        return 1 if bad else 0
    import test_fontlex as tf
    r = Reader(args.font)
    shapers = {n: tf.SHAPERS[n](r.data) for n in (args.shaper or ["harfbuzz"])}
    bad, differ = 0, []
    for line in lines:
        want = model(line)
        for n, sh in shapers.items():
            got = r.draw(sh.shape(line))
            if got == want:
                continue
            bad += 1
            differ.append((n, line))
            if bad <= args.show:
                print(f"DIFF {n} {line!r}")
                for x in sorted(set(got[0]) | set(want[0]), key=str):
                    if (x in got[0]) != (x in want[0]):
                        print("   ", "+" if x in got[0] else "-", x)
                print("    advance", got[1], "want", want[1])
            elif bad == args.show + 1:
                print("...")
    print(f"{len(lines)} lines, {', '.join(shapers)}: {bad} differ")
    if differ:      # as browsers.py sorts them: Chrome, Firefox and DirectWrite shape Greek runs apart
        other = [d for d in differ if not any("Ͱ" <= ch <= "Ͽ" for ch in d[1])]
        print(f"    {bad - len(other)} with a Greek letter, {len(other)} other{':' if other else ''}")
        for n, line in other[:20]:
            print(f"    {n} {line!r}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
