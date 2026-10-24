#!/usr/bin/env python3
"""Build the math font's demo page: a text box in the font, with what it
typesets, how, and what was measured.

    python math/build_page.py --font build/Fontlex-Math.ttf --out math/demo.html
    python math/build_page.py --relaxed --font build/Fontlex-RelaxedMath.ttf --out math/relaxed.html

The accuracy numbers come from shaping the embedded font (verify.py) on
samples.EDGES (or RELAXED_EDGES) and random lines, in HarfBuzz.
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


RELAXED_SAMPLE = """(a+b)/(c+d)
x=(-b+-sqrt(b^2-4ac))/(2a)
e^(-x^2/2)
1/2 + 1/3 = 5/6
sqrt(x^2+y^2) <= x+y
x_(n+1) = x_n/2 + a/(2x_n)
f(x) = 1/(1+e^-x)
H_2O, 2^10 = 1024, a_1^2 + a_2^2
and/or, w/o, km/h, C/C++, 10/23/2026"""

RELAXED_PAGE = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fontlex Relaxed Math: plain-text math typeset by a font</title>
<style>
{{STYLE}}
main { max-width: 56rem; }
textarea#code { min-height: 42rem; white-space: pre; overflow-x: auto; font-size: 1.6rem; line-height: 2.7; }
</style>
<main>
  <h1>Fontlex Relaxed Math</h1>
  <p class="lede">The box below is a plain text box holding math the way people type it in plain text:
  <code>(a+b)/(c+d)</code>, <code>x^2</code>, <code>sqrt(x)</code>. The font typesets it as you type: fractions,
  roots, superscripts and subscripts, laid out by the text engine that lays out the letters. Ordinary text stays
  ordinary, so <code>and/or</code>, <code>w/o</code>, dates and paths are left alone. The characters stay exactly
  as typed. No script on this page lays anything out.</p>

  <div class="editor" id="editor">
    <div class="bar">
      <label for="hl"><input type="checkbox" id="hl" checked> Render math</label>
    </div>
    <textarea id="code" spellcheck="false" wrap="off" aria-label="Plain-text math, typeset by the font">{{SAMPLE}}</textarea>
  </div>
  <p class="note">Each line is read on its own. A construct that isn't complete yet, or that breaks a rule
  below, stays as its characters until it is. Inside a fraction the caret stays at the fraction's start: the
  fraction's glyphs are drawn where they belong, but take no room of their own.</p>

  <h2>What it typesets</h2>
  <ul>
    <li>Fractions: <code>1/2</code>, <code>x/2</code>, <code>2a/3</code>, <code>(a+b)/(c+d)</code>,
    <code>f(x)/2</code>, <code>1/(1+1/x)</code>. Parentheses around a whole part go; with a script after them they
    stay: <code>(a+b)^2/c</code>.</li>
    <li>Scripts: <code>x^2</code>, <code>x^(n+1)</code>, <code>x^-1</code>, <code>x_1</code>, <code>H_2O</code>,
    and both at once, stacked: <code>x_i^2</code>.</li>
    <li>Roots: <code>sqrt(x^2+1)</code>.</li>
    <li>Symbols: <code>&lt;=</code> <code>&gt;=</code> <code>!=</code> <code>-&gt;</code> <code>=&gt;</code>
    <code>+-</code> become ≤ ≥ ≠ → ⇒ ±. Greek letters and other symbols can be typed as themselves, but
    Chrome shapes Greek and Latin letters apart, so there a construct that mixes them (<code>e^(iπ)</code>) stays
    as its characters.</li>
    <li>Constructs inside constructs, {{DEPTH}} deep, with at most {{FRACTIONS}} fractions inside one another,
    and at most {{CHARS}} characters in a construct that isn't inside another.</li>
  </ul>

  <h2>What stays text</h2>
  <ul>
    <li>A fraction's parts are numbers (<code>12</code>, <code>3.5</code>), a number and a letter
    (<code>2a</code>), one letter, a group in parentheses, a call like <code>f(x)</code> or <code>sin(x)</code>, or
    a root, each with its scripts. Longer words make no fraction: <code>and/or</code>, <code>km/h</code>,
    <code>page/2</code>.</li>
    <li>Two lone letters make a fraction only in an expression (<code>a+b/c</code>, <code>x = a/b</code>), so
    <code>w/o</code>, <code>n/a</code> and <code>I/O</code> stay as they are.</li>
    <li>Slashes in a row (<code>a/b/c</code>, <code>10/23/2026</code>, <code>//</code>) make none, nor does any
    slash in a run of characters where one touches a longer word (<code>tr/a-z/A-Z/</code>).</li>
    <li>No script touches another underscore, and a number has no subscript: <code>file_1_2</code>,
    <code>1_000</code> stay text.</li>
    <li>A space inside a construct leaves it as its characters: write <code>(a+b)/2</code>, not
    <code>(a + b)/2</code>.</li>
  </ul>

  <h2>How it works</h2>
  <p>{{FRONT}} passes read each line the way the rules above say, and rewrite it as the LaTeX that lays out the
  same: <code>(a+b)/(c+d)</code> as <code>\\frac{a+b}{c+d}</code>, with the parentheses as its braces and a
  <code>\\frac</code> and braces that the line doesn't have inserted as glyphs that draw nothing. Then Fontlex
  Math's own passes lay it out. The font has {{GLYPHS}} glyphs and {{LOOKUPS}} lookups.</p>

  <h2>Results</h2>
  <p>Each line is shaped with the font, what it draws is read back from the glyphs (characters by name and
  size, rules from their outlines), and compared with a separate Python model of the notation
  (<code>relaxed.py</code>), to the font unit.</p>
  <table>
    <tr><th>Lines</th><th class="n">Count</th>{{HEADS}}</tr>
    {{ROWS}}
  </table>
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


def accuracy(path, lines, shaper, model=L.layout):
    r = verify.Reader(path)
    sh = shaper(r.data)
    return sum(r.draw(sh.shape(line)) == model(line) for line in lines) / len(lines)


def web_font(ttf):
    font = TTFont(io.BytesIO(ttf), recalcTimestamp=False)
    font["post"].formatType = 3.0    # no glyph names on the web
    return pages.woff2(font)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--font", required=True, help="the compiled font (TTF)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=5000, help="random lines to check")
    ap.add_argument("--relaxed", action="store_true", help="the relaxed notation's font and page")
    args = ap.parse_args()
    ttf = Path(args.font).read_bytes()
    if args.relaxed:
        import front
        import relaxed
        sets = [("Edge cases (incomplete and broken input, and prose)", [l for l in samples.RELAXED_EDGES if l]),
                ("Random formulas and words, some mistyped", samples.relaxed_lines(args.n, seed=2))]
        model, page, sample, family = relaxed.layout, RELAXED_PAGE, RELAXED_SAMPLE, "Fontlex Relaxed Math"
    else:
        sets = [("Edge cases (incomplete and broken input)", [l for l in samples.EDGES if l]),
                ("Random formulas, some mistyped", samples.lines(args.n, seed=2))]
        model, page, sample, family = L.layout, PAGE, SAMPLE, "Fontlex Math"
    # HarfBuzz only, so the page rebuilds the same everywhere (Core Text's
    # results, the same, are in the README)
    shapers = [("HarfBuzz", test_fontlex.HarfBuzz)]
    rows = []
    for name, lines in sets:
        cells = "".join(f'<td class="n">{accuracy(args.font, lines, sh, model):.1%}</td>' for _, sh in shapers)
        rows.append(f'<tr><td>{html.escape(name)}</td><td class="n">{len(lines):,}</td>{cells}</tr>')
        print(name, cells)
    import program
    font = TTFont(io.BytesIO(ttf))
    symbols = "".join(f"<li><code>\\{html.escape(k)}</code> {html.escape(v)}</li>" for k, v in L.SYMBOLS.items())
    page = pages.fill(page, {
        "STYLE": pages.fill(pages.STYLE, {"FAMILY": family, "LIGHT": "", "DARK": "",
                                          "FONT": base64.b64encode(web_font(ttf)).decode()}),
        "SAMPLE": html.escape(sample),
        "FRONT": f"{len(front.front()) if args.relaxed else 0:,}",
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
