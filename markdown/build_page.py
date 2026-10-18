#!/usr/bin/env python3
"""Build the Markdown font's demo page: a text box in the font, with how it
works and what was measured.

    python markdown/build_page.py --font build/Fontlex-Markdown.ttf --out markdown/demo.html

The accuracy numbers come from checking the embedded font (verify.py) on
CommonMark's single-line spec examples and random lines.
"""

import argparse
import html
import io
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import bounds  # noqa: E402
import mdfont  # noqa: E402
import test_fontlex  # noqa: E402
import verify  # noqa: E402
from demo import pages  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402

PAGE = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fontlex Markdown: CommonMark rendered by a font</title>
<style>
{{STYLE}}
main { max-width: 64rem; }
textarea#code { min-height: 19rem; white-space: pre; overflow-x: auto; font-size: 1rem; line-height: 1.75; }
</style>
<main>
  <h1>Fontlex Markdown</h1>
  <p class="lede">The box below is a plain text box holding Markdown. The font renders it: the text engine
  that lays out the letters runs CommonMark's inline rules, hides the markup and styles the text. The
  characters you type stay exactly as typed. No script on this page does any of it.</p>

  {{EDITOR}}
  <p class="note">Turn off "Render Markdown" to see the characters. Each line is read on its own: the font sees
  one line at a time, as the browser lays it out.</p>

  <h2>What it renders</h2>
  <ul>
    <li>Emphasis and strong emphasis, by CommonMark's full rules (left- and right-flanking runs, the rule of
    three, <code>_</code> inside words, nesting), with Unicode punctuation and whitespace in any script.</li>
    <li>Code spans, with a background: any number of backticks, a space of padding kept visible.</li>
    <li>Inline links and images, shown as styled text, with destinations and titles hidden; links can't contain
    links, images can.</li>
    <li>Autolinks (URLs and email addresses), raw HTML (dimmed), entity and numeric character references (shown
    as their characters), and backslash escapes.</li>
  </ul>

  <h2>How exact it is</h2>
  <table>
    <tr><th>Text</th><th class="n">Lines</th><th class="n">Rendered as CommonMark</th></tr>
    {{ROWS}}
  </table>
  <p class="note">Each character's glyph (hidden, or its style) is compared with what CommonMark makes of it, as
  computed by a port of the reference implementation, commonmark.js 0.31.2. Lines past one of the font's bounds
  (below) are left out of the count; many of them still come out right.</p>

  <h2>How a font can parse Markdown</h2>
  <p>OpenType lets a font substitute glyphs by context, one lookup after another, each a pass over the line
  from left to right or from right to left. The font's 100 or so passes carry what they learn in glyph variants.
  The trick that makes Markdown possible is that most passes only see the characters they care about: a pass
  matching <code>*</code> and <code>_</code> skips every letter in between, so a pair of markers is next to each
  other however much text separates them.</p>
  <ol>
    <li><b>Right to left, once:</b> what lies ahead of each character. Whether a code span's closing backticks
    follow, whether a link destination <code>(…)</code> follows a <code>]</code>, and whether a valid tag or
    autolink starts at a <code>&lt;</code>.</li>
    <li><b>Left to right, after that:</b> a scan settles code spans, link destinations and raw HTML; then
    brackets and emphasis are matched in rounds, where each round pairs every opener with the closer right after
    it and matched pairs drop out, so the next round sees the next level of nesting; then each glyph is drawn in
    its style.</li>
  </ol>
  <p>So CommonMark's inline syntax takes one change of direction. It can't take none: whether a run of backticks
  opens a code span depends on what follows, and whether it is inside one depends on what precedes. Markdown's
  nesting is unbounded, which no finite set of passes can follow, so the font has bounds: {{BOUNDS}}.</p>

  <h2>Limits</h2>
  <ul>
    <li>Only inline syntax, one line at a time: no headings, lists, code blocks or reference links, and nothing
    that spans lines.</li>
    <li>Browsers break a line into pieces before the font sees it, and the font can't see across them: Safari at
    soft wraps (so this box doesn't wrap), Chrome where the script changes, so <code>*мир*</code> after Latin
    text, or a Latin URL after Cyrillic link text, stays as typed there (Safari renders both).</li>
    <li>In Safari a space inside a hidden link destination (before a title) still takes a space's width.</li>
    <li>Needs a browser or app that applies OpenType features and color fonts: current Chrome, Firefox and Safari.</li>
  </ul>
  <p class="note">Base font: JetBrains Mono with its bold and italic (SIL Open Font License).</p>
</main>
{{SCRIPT}}
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--font", required=True, help="the compiled font (TTF)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=5000, help="random lines to check")
    args = ap.parse_args()
    ttf = Path(args.font).read_bytes()
    view, shaper = verify.FontView(ttf), test_fontlex.SHAPERS["harfbuzz"](ttf)
    rows = []
    sets = [("CommonMark's single-line spec examples", [l for _, l in verify.spec_lines(HERE / "spec-0.31.2.json")]),
            ("Random lines of Markdown syntax", list(verify.random_lines(args.n, 1, verify.TOKENS)))]
    for name, lines in sets:
        within = [l for l in lines if not bounds.exceeds(l, view.cmap)]
        ok = sum(verify.check(view, shaper, l) is None for l in within)
        rows.append(f"<tr><td>{html.escape(name)}</td><td class=\"n\">{len(within):,}</td>"
                    f"<td class=\"n\">{ok / len(within):.1%}</td></tr>")
        print(f"{name}: {ok}/{len(within)} within the bounds")
    font = TTFont(io.BytesIO(ttf), recalcTimestamp=False)
    font["post"].formatType = 3.0    # no glyph names on the web
    bound_text = (f"emphasis runs of up to {mdfont.MAX_DELIMS} characters, nested {mdfont.ROUNDS} deep; "
                  f"{mdfont.MAX_BRACKETS} brackets open at once; backtick runs of up to {mdfont.MAX_TICKS}; "
                  f"parentheses {mdfont.PARENS} deep in a destination")
    sample = (HERE / "sample.md").read_text(encoding="utf-8").rstrip("\n")
    box = ("Render Markdown", sample, 'wrap="off" aria-label="Markdown, rendered by the font"')
    page = pages.page(PAGE, pages.woff2(font), "Fontlex Markdown", {}, box, {
        "ROWS": "\n    ".join(rows),
        "BOUNDS": html.escape(bound_text),
    })
    pages.write(args.out, page)


if __name__ == "__main__":
    main()
