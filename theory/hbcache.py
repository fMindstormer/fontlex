"""A test for HarfBuzz 12.3.1+'s context coverage cache: glyph ids 32512-32767,
and glyph ids 32768 apart.

    python theory/hbcache.py [--page OUT.html]

Each test font turns `a` into a helper glyph at a chosen glyph id, and a
format 2 chain context rule turns that glyph into `B`. A shaper that matches
the rule draws "BBB" for "aaa". HarfBuzz from 12.3.1 caches whether a glyph
is covered in an hb_cache_t<14, 1, 8>, whose empty slots read as "not
covered" for ids 32512 to 32767, so there it draws "aaa". HarfBuzz 15.0.0
fixed it (commit b98ffb1, harfbuzz/harfbuzz#6419).

The last fonts also turn `b` into a glyph 32768 above the helper, which the
rule doesn't cover, and shape "ba": "bB" is right. Before 14.6.0 the cache
stored that glyph's "not covered" in the helper's slot, under the helper's
tag (harfbuzz/harfbuzz#6320, fixed by #6321), so the helper then reads as not
covered: "ba". With --page, the fonts go into an HTML page, to see what a
browser does.
"""

import argparse
import base64
import io
import sys
from pathlib import Path

from fontTools.ttLib.tables import otTables as ot

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "markdown"))
import fontbuild as fb  # noqa: E402
import test_fontlex  # noqa: E402

BASE = HERE.parent / "fonts" / "JetBrainsMono-Regular.ttf"
IDS = (20000, 32511, 32512, 32600, 32767, 32768, 40000)
PAIRED = (7232, 20000)          # helper ids with a `b` glyph 32768 above


def build(gid, paired=False):
    """The test font with its helper glyph at `gid` (and, paired, `b`'s
    glyph at gid + 32768)."""
    b = fb.FontBuilder(str(BASE))
    cmap = b.font.getBestCmap()
    a, small_b, big_b = cmap[ord("a")], cmap[ord("b")], cmap[ord("B")]
    fb.BAD_WINDOW, fb.SPREAD = range(0), False     # this test wants the glyphs where it puts them
    for i in range(gid - len(b.order)):
        b.empty(f"_fill{i}")
    helper = b.composite("_helper", [(a, 0, 0)], b.advance(a))
    assert b.gid(helper) == gid
    first = {a: helper}
    if paired:
        for i in range(gid + fb.ALIAS - len(b.order)):
            b.empty(f"_fill{gid + 1 + i}")
        first[small_b] = b.composite("_other", [(small_b, 0, 0)], b.advance(small_b))
        assert b.gid(first[small_b]) == gid + fb.ALIAS
    st = ot.ChainContextSubst()
    st.Format = 2
    st.Coverage = ot.Coverage()
    st.Coverage.glyphs = [helper]
    for name in ("BacktrackClassDef", "InputClassDef", "LookAheadClassDef"):
        cd = ot.ClassDef()
        cd.classDefs = {}
        setattr(st, name, cd)
    st.InputClassDef.classDefs = {helper: 1}
    rule = ot.ChainSubClassRule()
    rule.Backtrack, rule.Input, rule.LookAhead = [], [], []
    rule.BacktrackGlyphCount, rule.InputGlyphCount, rule.LookAheadGlyphCount = 0, 1, 0
    rec = ot.SubstLookupRecord()
    rec.SequenceIndex, rec.LookupListIndex = 0, 2
    rule.SubstLookupRecord, rule.SubstCount = [rec], 1
    rules = ot.ChainSubClassSet()
    rules.ChainSubClassRule, rules.ChainSubClassRuleCount = [rule], 1
    st.ChainSubClassSet, st.ChainSubClassSetCount = [None, rules], 2
    lookups = [fb.lookup(1, [fb.single(first)]), fb.lookup(6, [st]), fb.lookup(1, [fb.single({helper: big_b})])]
    font = b.finish(fb.build_gsub(lookups, top=[0, 1]), family=f"HB Cache {gid}{' paired' if paired else ''}")
    buf = io.BytesIO()
    font.save(buf)
    return buf.getvalue(), font


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--page", help="write a page showing each font, for browsers")
    args = ap.parse_args()
    shapers = [n for n in ("harfbuzz", "coretext") if n == "harfbuzz" or sys.platform == "darwin"]
    faces, rows = [], []
    cases = [(gid, False, "aaa", "BBB") for gid in IDS] + [(gid, True, "ba", "bB") for gid in PAIRED]
    for gid, paired, text, right in cases:
        data, font = build(gid, paired)
        order = font.getGlyphOrder()
        seen = {}
        for name in shapers:
            gids = test_fontlex.SHAPERS[name](data).shape(text)[0]
            seen[name] = "".join({"B": "B", "_other": "b"}.get(order[g[0]], "a") for g in gids)
        what = f"helper glyph id {gid:5}" + (f", b at {gid + fb.ALIAS}" if paired else "")
        print(f"{what}: " + "  ".join(f"{n} {s}" for n, s in seen.items()) + f"  (right: {right})")
        if args.page:
            font.flavor = "woff2"
            buf = io.BytesIO()
            font.save(buf)
            face = f"T{gid}{'p' if paired else ''}"
            faces.append(f'@font-face {{ font-family: "{face}"; src: url(data:font/woff2;base64,'
                         f'{base64.b64encode(buf.getvalue()).decode()}) format("woff2"); }}')
            label = f"{gid}+{gid + fb.ALIAS}" if paired else f"{gid}"
            rows.append(f'<p><span class="id">{label}</span> <span style="font-family: {face}">{text}</span>'
                        f' <span class="id">{right}</span></p>')
    if args.page:
        Path(args.page).write_text(
            "<!doctype html><meta charset=utf-8><title>HarfBuzz coverage cache test</title><style>"
            + "\n".join(faces) + "\nbody { font: 28px system-ui; margin: 16px; } p { margin: 4px 0; }"
            ".id { display: inline-block; min-width: 5em; color: #666; }</style>"
            "<p>Each line should read as its last column.</p>" + "".join(rows), encoding="utf-8")
        print(f"wrote {args.page}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
