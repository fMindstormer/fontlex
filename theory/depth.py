"""How deep can a font count? Bracket matching by peeling, measured.

    python theory/depth.py --rounds 10 100 1000 4000 [--shaper harfbuzz --shaper coretext]

No finite set of passes decides whether brackets balance, but R passes match
them to depth R. Each round is one lookup that sees only unmatched brackets
(a mark filtering set) and matches every `(` directly followed, in that view,
by a `)`; matched brackets leave the view, so the next round matches the next
level out. The font needs eight extra glyphs whatever R is: the cost of depth
is lookups, not glyphs, and the ceiling is the shaping engine's work budget.

For each R the script builds the font, then finds the deepest `((...a...))`
each shaper matches completely, and the time to shape it. Identical rounds
are stored once; with --distinct each round's coverage also lists a
different base glyph (which never reaches it, base glyphs being skipped), so
every round is a lookup of its own, as in a real font.
"""

import argparse
import io
import sys
import time
from pathlib import Path

from fontTools.ttLib.tables import otTables as ot

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "markdown"))
import fontbuild as fb  # noqa: E402
import test_fontlex  # noqa: E402

BASE = HERE.parent / "fonts" / "JetBrainsMono-Regular.ttf"
MARK, BASE_GLYPHS, LIGATURES = 0x0008, 0x0002, 0x0004


def coverage(glyphs):
    cov = ot.Coverage()
    cov.glyphs = list(glyphs)
    return cov


def build(rounds, distinct=False, show=False):
    """The font as bytes: `(` and `)` become unmatched brackets, then
    `rounds` peeling rounds turn matched pairs into matched glyphs (drawn as
    `[` and `]` with `show`, to see the matching in a browser)."""
    b = fb.FontBuilder(str(BASE))
    cmap = b.font.getBestCmap()
    left, right = cmap[ord("(")], cmap[ord(")")]
    shown = (cmap[ord("[")], cmap[ord("]")]) if show else (left, right)
    po, pc, mo, mc = (b.composite(n, [(src, 0, 0)], b.advance(src), gdef_class=3)
                      for n, src in (("_po", left), ("_pc", right), ("_mo", shown[0]), ("_mc", shown[1])))
    gdef = b.font["GDEF"].table
    first_set = len(gdef.MarkGlyphSetsDef.Coverage) if getattr(gdef, "MarkGlyphSetsDef", None) else 0
    lookups = [fb.lookup(1, [fb.single({left: po, right: pc})]),     # 0: the brackets, unmatched
               fb.lookup(1, [fb.single({po: mo, pc: mc})])]          # 1: matched (called by the rounds)
    spare = [g for g in b.base_names if g not in (left, right)]
    for k in range(rounds):
        first = sorted({po, spare[k % len(spare)]}, key=b.gid) if distinct else [po]
        second = sorted({pc, spare[k // len(spare)]}, key=b.gid) if distinct else [pc]
        st = ot.ChainContextSubst()
        st.Format = 3
        st.BacktrackCoverage, st.InputCoverage, st.LookAheadCoverage = [], [coverage(first), coverage(second)], []
        st.BacktrackGlyphCount, st.InputGlyphCount, st.LookAheadGlyphCount = 0, 2, 0
        st.SubstLookupRecord = []
        for i in (0, 1):
            r = ot.SubstLookupRecord()
            r.SequenceIndex, r.LookupListIndex = i, 1
            st.SubstLookupRecord.append(r)
        st.SubstCount = 2
        lookups.append(fb.lookup(6, [st], BASE_GLYPHS | LIGATURES, mark_set=first_set))
    # The rounds' glyphs are marks, so a filtering set can pick them out;
    # shapers give marks no width, so a last pass draws them as base glyphs.
    final = {g: b.composite(g[1:], [(g, 0, 0)], b.advance(g)) for g in (po, pc, mo, mc)}
    lookups.append(fb.lookup(1, [fb.single(final)]))
    gsub = fb.build_gsub(lookups, top=[0] + list(range(2, len(lookups))))
    font = b.finish(gsub, [{po, pc}], family="Fontlex Depth")
    buf = io.BytesIO()
    font.save(buf)
    return buf.getvalue(), font.getGlyphOrder(), len(font.getGlyphOrder()) - len(b.base_names)


def matched(shaper, order, depth, pad=0):
    try:
        gids = shaper.shape("(" * depth + "a" * (1 + pad) + ")" * depth)[0]
    except MemoryError:      # uharfbuzz: HarfBuzz ran out of its work budget and gave up
        return False
    names = [order[g[0]] for g in gids]
    return names.count("mo") == names.count("mc") == depth


def deepest(shaper, order, limit):
    """The deepest nesting matched completely, by doubling then bisection
    (matching is monotone in depth)."""
    lo, hi = 0, 1
    while hi <= limit and matched(shaper, order, hi):
        lo, hi = hi, hi * 2
    hi = min(hi, limit + 1)
    while hi - lo > 1:
        mid = (lo + hi) // 2
        lo, hi = (mid, hi) if matched(shaper, order, mid) else (lo, mid)
    return lo


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rounds", type=int, nargs="+", default=[10, 100, 1000])
    ap.add_argument("--shaper", action="append", choices=sorted(test_fontlex.SHAPERS))
    ap.add_argument("--distinct", action="store_true", help="make every round a different lookup")
    args = ap.parse_args()
    short = 0
    print("rounds  extra glyphs  shaper     deepest matched  ms to shape it")
    for rounds in args.rounds:
        try:
            data, order, extra = build(rounds, args.distinct)
        except Exception as e:      # the lookup list's 16-bit offsets overflow
            print(f"{rounds:6}  does not compile: {type(e).__name__}")
            continue
        for name in args.shaper or ["harfbuzz"]:
            shaper = test_fontlex.SHAPERS[name](data)
            d = deepest(shaper, order, 2 * rounds + 8)
            t = time.perf_counter()
            shaper.shape("(" * d + "a" + ")" * d)
            ms = (time.perf_counter() - t) * 1000
            print(f"{rounds:6}  {extra:12}  {name:9}  {d:15}  {ms:14.1f}")
            short += d < rounds
    return 1 if short else 0


if __name__ == "__main__":
    sys.exit(main())
