#!/usr/bin/env python3
"""Check a math font in real browsers, by screenshot.

    python math/browsers.py pages OUT [--relaxed] [--n 300]
    node math/browsers.mjs OUT chromium|firefox
    python math/browsers.py compare OUT chromium|firefox

`pages` writes pages that draw each line twice in one place: as text in the
font, and as the font's outlines placed where HarfBuzz places them (an SVG).
browsers.mjs screenshots each page showing one, then the other, and types
lines into the demo page key by key and sets the same lines at once.
`compare` then finds, for each line, pixels that differ by more than 2 px (at
100 px per em; the layout's smallest step is 3 px), and whether typing ended
where setting the text did. It exits with status 1 on a difference, apart
from lines that mix Greek and Latin letters: Chrome shapes those in separate
runs, so a construct across them stays as its characters (a known limit).
The fonts come from build/; the outlines need only HarfBuzz, so the check
runs wherever a browser does.
"""

import argparse
import base64
import json
import sys
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import samples  # noqa: E402

PX, ROW, TOP = 100, 480, 280        # px per em, row height, baseline in a row
PER_PAGE = 25
R = 2                               # px of tolerance

TYPED = {
    False: ["x=\\frac{a+b}{c}", "\\sqrt{x^2+1}", "e^{i\\pi}+1=0", "\\frac{1}{1+\\frac{1}{x}}"],
    True: ["(a+b)/(c+d)", "x^2", "sqrt(x^2+1)", "x=(-b+-sqrt(b^2-4ac))/(2a)", "1/(1+1/x)"],
}


def lines(relaxed, n):
    if relaxed:
        extra = ["a b", "x^2 + y^2 = z^2", "(a+b)/(c+d)", "αβγ x", "1/2 c d", "e^(iπ) + 1 = 0",
                 "x=(-b+-sqrt(b^2-4ac))/(2a)", "sqrt(a b_x", "x_(a b)^2 c", "and/or w/o 10/23/2026"]
        return [x for x in samples.RELAXED_EDGES + samples.relaxed_lines(n, seed=21) + extra if x]
    extra = ["a b", "x^2 + y^2 = z^2", "\\alpha + \\beta", "αβγ x", "\\frac{a}{b} c d", "e^{i\\pi} + 1 = 0",
             "\\sqrt{a b_x", "x_{a b}^2 c"]
    return [x for x in samples.EDGES + samples.lines(n, seed=21) + extra if x]


def pages(args):
    name = "Fontlex-RelaxedMath" if args.relaxed else "Fontlex-Math"
    ttf = HERE.parent / "build" / f"{name}.ttf"
    data = ttf.read_bytes()
    font = TTFont(ttf)
    glyphs, order = font.getGlyphSet(), font.getGlyphOrder()
    shaper = hb.Font(hb.Face(hb.Blob(data)))
    woff2 = base64.b64encode(ttf.with_suffix(".woff2").read_bytes()).decode()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    todo = lines(args.relaxed, args.n)
    index = {"row": ROW, "px": PX, "pages": [], "typed": TYPED[args.relaxed],
             "demo": str(HERE / ("relaxed.html" if args.relaxed else "demo.html"))}
    for p in range(0, len(todo), PER_PAGE):
        rows, meta = [], []
        for i, line in enumerate(todo[p:p + PER_PAGE]):
            buf = hb.Buffer()
            buf.add_str(line)
            buf.guess_segment_properties()
            hb.shape(shaper, buf, {"calt": True})
            pen = SVGPathPen(glyphs)
            x = 0
            for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
                glyphs[order[info.codepoint]].draw(
                    TransformPen(pen, (1, 0, 0, -1, x + pos.x_offset, -pos.y_offset)))
                x += pos.x_advance
            y = i * ROW + TOP
            text = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            rows.append(f'<div class=t style="top:{y}px"><i class=b></i>{text}</div>'
                        f'<svg class=r style="top:{y - 1000}px" width="{x * PX / 1000 + 40}" height="2000">'
                        f'<path transform="translate(20 1000) scale({PX / 1000})" d="{pen.getCommands()}"/></svg>')
            meta.append({"line": line, "top": i * ROW, "width": x})
        page = out / f"page{len(index['pages'])}.html"
        page.write_text(f"""<!doctype html><meta charset=utf-8><style>
@font-face{{font-family:M;src:url(data:font/woff2;base64,{woff2})}}
body{{margin:0;background:#fff;position:relative;height:{len(meta) * ROW}px}}
.t{{position:absolute;left:20px;font:{PX}px M;white-space:pre;color:#000}}
.b{{display:inline-block;width:0;height:0}}
.r{{position:absolute;left:0;overflow:visible}}
body.text .r, body.ref .t{{visibility:hidden}}</style><body>{''.join(rows)}
<script>function align(){{const ts=document.querySelectorAll('.t'),rs=document.querySelectorAll('.r');
ts.forEach((t,i)=>{{const b=t.querySelector('.b').getBoundingClientRect().top+scrollY;rs[i].style.top=(b-1000)+'px'}})}}
</script></body>""", encoding="utf-8")
        index["pages"].append({"page": str(page.resolve()), "rows": meta})
    (out / "index.json").write_text(json.dumps(index), encoding="utf-8")
    print(f"{len(todo)} lines on {len(index['pages'])} pages in {out}")


def compare(args):
    from PIL import Image, ImageChops
    Image.MAX_IMAGE_PIXELS = None
    out = Path(args.out)
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))

    def spread(im, pick):
        """Each pixel's lightest (pick = lighter) or darkest (darker) within R px, by shifting."""
        for dx, dy in ((1, 0), (0, 1)):
            base = im
            for d in range(1, R + 1):
                im = pick(pick(im, ImageChops.offset(base, d * dx, d * dy)),
                          ImageChops.offset(base, -d * dx, -d * dy))
        return im

    def missing(a, b):
        """Pixels of a with no pixel of b within R px that is within 128 levels of it. For a
        light pixel that means none as light as a - 128, for a dark one none as dark as a + 128."""
        too_dark = ImageChops.subtract(a, spread(b, ImageChops.lighter), 1.0, -128)
        too_light = ImageChops.subtract(spread(b, ImageChops.darker), a, 1.0, -128)
        return ImageChops.lighter(too_dark, too_light).point(lambda v: 255 if v else 0)

    total, bad = 0, []
    for pg in index["pages"]:
        text, ref = (Image.open(pg["page"].replace(".html", f".{args.browser}.{c}.png")).convert("L")
                     for c in ("text", "ref"))
        w, h = min(text.width, ref.width), min(text.height, ref.height)
        text, ref = text.crop((0, 0, w, h)), ref.crop((0, 0, w, h))
        diff = ImageChops.lighter(missing(text, ref), missing(ref, text))
        for row in pg["rows"]:
            box = (0, row["top"], min(w, int(row["width"] * index["px"] / 1000) + 80), row["top"] + index["row"])
            n = diff.crop(box).histogram()[255]
            total += 1
            if n:
                bad.append((n, row["line"]))
                # the text above HarfBuzz's outlines, for a look at what went wrong
                pair = Image.new("L", (box[2], 2 * index["row"]), 255)
                pair.paste(text.crop(box), (0, 0))
                pair.paste(ref.crop(box), (0, index["row"]))
                (out / "diffs").mkdir(exist_ok=True)
                pair.save(out / "diffs" / f"{args.browser}-{len(bad)}.png")
    known = [b for b in bad if any("Ͱ" <= ch <= "Ͽ" for ch in b[1])]
    unknown = [b for b in bad if b not in known]
    print(f"{args.browser}: {total} lines, {total - len(bad)} the same as HarfBuzz's layout; "
          f"{len(known)} differ that mix Greek and Latin (a known limit in Chrome), {len(unknown)} other")
    for diff, line in sorted(bad, reverse=True)[:15]:
        print(f"   {diff:7} px  {line!r}")
    typed, fresh = (Image.open(out / f"type.{args.browser}.{m}.png").convert("RGB") for m in ("typed", "fresh"))
    same = typed.size == fresh.size and not ImageChops.difference(typed, fresh).getbbox()
    print(f"{args.browser}: typing key by key {'ends with the same pixels as' if same else 'DIFFERS from'} "
          "setting the text at once")
    sys.exit(0 if same and not unknown else 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pages")
    p.add_argument("out")
    p.add_argument("--relaxed", action="store_true")
    p.add_argument("--n", type=int, default=300, help="random lines besides the edge cases")
    c = sub.add_parser("compare")
    c.add_argument("out")
    c.add_argument("browser")
    args = ap.parse_args()
    pages(args) if args.cmd == "pages" else compare(args)


if __name__ == "__main__":
    main()
