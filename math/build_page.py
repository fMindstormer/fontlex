#!/usr/bin/env python3
"""Build the math font's demo page: a text box in the font, with what it
typesets, how, and what was measured.

    python math/build_page.py --font build/Fontlex-Math.ttf --out math/demo.html

The accuracy numbers come from shaping the embedded font (verify.py) on
samples.EDGES and random lines, in HarfBuzz.
"""

import argparse
import base64
import html
import io
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import layout as L  # noqa: E402
import samples  # noqa: E402
import test_fontlex  # noqa: E402
import verify  # noqa: E402
from demo import pages  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402

SAMPLE = r"""e^{i\pi}+1=0
x=\frac{-b\pm\sqrt{D}}{2a}
\frac{a}{b}+\frac{c}{d}=\frac{ad+bc}{bd}
\sqrt{x^2+y^2}
x_{n+1}=\frac{x_n}{2}+\frac{a}{2x_n}
\sum_{k=1}^n k=\frac{n(n+1)}{2}
\frac{1}{1+\frac{1}{x}}
\alpha_1^2+\beta_1^2 \theta\to\infty"""

PAGE = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fontlex Math: formulas typeset by a font</title>
<style>
{{STYLE}}
main { max-width: 56rem; }
textarea#code { min-height: 39rem; white-space: pre; overflow-x: auto; font-size: 1.6rem; line-height: 2.7; }
.keys { display: flex; flex-wrap: wrap; gap: .35rem .9rem; padding: 0; list-style: none; font-size: .92rem; }
.keys code { white-space: nowrap; }
</style>
<main>
  <h1>Fontlex Math</h1>
  <p class="lede">The box below is a plain text box holding a little LaTeX. The font typesets it: fractions,
  roots, superscripts and subscripts, Greek letters and a few symbols, laid out by the text engine that lays out
  the letters, as you type. The characters stay exactly as typed. No script on this page lays anything out.</p>

  <div class="editor" id="editor">
    <div class="bar">
      <label for="hl"><input type="checkbox" id="hl" checked> Render math</label>
    </div>
    <textarea id="code" spellcheck="false" wrap="off" aria-label="LaTeX, typeset by the font">{{SAMPLE}}</textarea>
  </div>
  <p class="note">Each line is read on its own. A construct that isn't complete yet, or that breaks a rule
  below, stays as its characters until it is. Inside a fraction the caret stays at the fraction's start: the
  fraction's glyphs are drawn where they belong, but take no room of their own.</p>

  <h2>What it typesets</h2>
  <ul>
    <li><code>\\frac{a}{b}</code>, <code>\\sqrt{x}</code>, <code>x^2</code>, <code>x_1</code>,
    <code>x^{n+1}</code>, and both scripts at once, stacked (<code>x_1^2</code>, in either order).</li>
    <li>Braces as groups: <code>{a+b}^2</code>.</li>
    <li>Symbols: <ul class="keys">{{SYMBOLS}}</ul></li>
    <li>Constructs inside constructs, {{DEPTH}} deep, with at most {{FRACTIONS}} fractions inside one another,
    and at most {{CHARS}} characters in a construct that isn't inside another. Text inside a fraction or a
    script is set smaller, in three sizes.</li>
    <li>A space inside a construct leaves it as its characters (WebKit gives every glyph of a space a space's
    width, which would break the layout); spaces between formulas are fine.</li>
  </ul>

  <h2>How it works</h2>
  <p>Every character gets four empty glyphs after its own, and {{PASSES}} passes, compiled to OpenType
  substitutions, rewrite them: they match braces, check what is complete, give each character its role and
  size, add up widths (in two digits, so the rules stay few), and finally turn every glyph into something
  drawn or a mover. Positioning then does the layout. Outside fractions, text keeps its advance and is
  raised or lowered. Inside a fraction nothing advances: each glyph is a mark attached to the one before it,
  and movers between them carry the fraction's chain to the numerator, back over the bar and down to the
  denominator, with the bars and root signs' overbars drawn by pieces hung off the chain.</p>
  <p>The compiled font has {{GLYPHS}} glyphs and {{LOOKUPS}} lookups. OpenType's lookup list holds only a few
  thousand, so the compiler shares nested lookups between passes and splits any glyph that would need more
  than a few dozen outcomes in one pass into two steps.</p>

  <h2>Results</h2>
  <p>Each line is shaped with the font, what it draws is read back from the glyphs (characters by name and
  size, rules from their outlines), and compared with a separate Python model of the layout
  (<code>layout.py</code>), to the font unit. Core Text (Safari, macOS) gives the same results.</p>
  <table>
    <tr><th>Lines</th><th class="n">Count</th>{{HEADS}}</tr>
    {{ROWS}}
  </table>
  <p class="note">Checked by screenshot in Chrome 155 and Safari's WebKit (text against the outlines placed as
  HarfBuzz places them), and by typing into the box key by key in Chrome, which ends as the same text set at
  once does. A keystroke that completes a construct changes glyphs before the caret, and with a simpler test
  font Chrome kept their old shaping, so this page still makes it lay the box out again on every input (by
  switching <code>font-kerning</code>). Not yet checked in Firefox, or on Windows.</p>
  <p class="note">Base font: JetBrains Mono (SIL Open Font License).</p>
</main>
<script>
(() => {
  const editor = document.getElementById('editor'), hl = document.getElementById('hl'),
        code = document.getElementById('code');
  hl.addEventListener('change', () => editor.classList.toggle('off', !hl.checked));
  // Chrome keeps the shaping of text before an edit: switch a setting that
  // makes it shape the box again.
  let flip = false;
  code.addEventListener('input', () => {
    flip = !flip;
    code.style.fontKerning = flip ? 'normal' : 'auto';
  });
})();
</script>
"""


def accuracy(path, lines, shaper):
    r = verify.Reader(path)
    sh = shaper(r.data)
    return sum(r.draw(sh.shape(line)) == L.layout(line) for line in lines) / len(lines)


def web_font(ttf):
    font = TTFont(io.BytesIO(ttf), recalcTimestamp=False)
    font["post"].formatType = 3.0    # no glyph names on the web
    return pages.woff2(font)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--font", required=True, help="the compiled font (TTF)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=5000, help="random lines to check")
    args = ap.parse_args()
    ttf = Path(args.font).read_bytes()
    sets = [("Edge cases (incomplete and broken input)", [l for l in samples.EDGES if l]),
            ("Random formulas, some mistyped", samples.lines(args.n, seed=2))]
    # HarfBuzz only, so the page rebuilds the same everywhere (Core Text's
    # results, the same, are in the README)
    shapers = [("HarfBuzz", test_fontlex.HarfBuzz)]
    rows = []
    for name, lines in sets:
        cells = "".join(f'<td class="n">{accuracy(args.font, lines, sh):.1%}</td>' for _, sh in shapers)
        rows.append(f'<tr><td>{html.escape(name)}</td><td class="n">{len(lines):,}</td>{cells}</tr>')
        print(name, cells)
    import program
    font = TTFont(io.BytesIO(ttf))
    symbols = "".join(f"<li><code>\\{html.escape(k)}</code> {html.escape(v)}</li>" for k, v in L.SYMBOLS.items())
    page = pages.fill(PAGE, {
        "STYLE": pages.fill(pages.STYLE, {"FAMILY": "Fontlex Math", "LIGHT": "", "DARK": "",
                                          "FONT": base64.b64encode(web_font(ttf)).decode()}),
        "SAMPLE": html.escape(SAMPLE),
        "SYMBOLS": symbols,
        "DEPTH": str(L.MAX_DEPTH), "FRACTIONS": str(L.MAX_FRACTIONS), "CHARS": str(L.MAX_CHARS),
        "PASSES": f"{len(program.program()):,}",
        "GLYPHS": f"{len(font.getGlyphOrder()):,}",
        "LOOKUPS": f"{len(font['GSUB'].table.LookupList.Lookup):,} substitution and "
                   f"{len(font['GPOS'].table.LookupList.Lookup):,} positioning",
        "HEADS": "".join(f'<th class="n">{name}</th>' for name, _ in shapers),
        "ROWS": "\n    ".join(rows),
    })
    pages.write(args.out, page)


if __name__ == "__main__":
    main()
