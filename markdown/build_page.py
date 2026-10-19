#!/usr/bin/env python3
"""Build the Markdown font's demo page: a text box in the font, with how it
works and what was measured.

    python markdown/build_page.py --font build/Fontlex-Markdown.ttf \
        --sans build/Fontlex-MarkdownSans.ttf --out markdown/demo.html

The accuracy numbers come from checking the embedded fonts (verify.py) on
CommonMark's single-line spec examples and random lines. With --sans the box
has an edition menu: the monospaced font or the proportional one.
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
<title>Fontlex Markdown: GitHub Flavored Markdown rendered by a font</title>
<style>
{{STYLE}}
main { max-width: 64rem; }
textarea#code { min-height: 33rem; white-space: pre; overflow-x: auto; font-size: 1rem; line-height: 1.75; }
{{SANS_FACE}}
#editor.sans textarea#code { font-family: "Fontlex Markdown Sans", system-ui, sans-serif; }
</style>
<main>
  <h1>Fontlex Markdown</h1>
  <p class="lede">The box below is a plain text box holding Markdown. The font renders it: the text engine
  that lays out the letters runs GitHub Flavored Markdown's rules, line by line, hides the markup and styles the
  text. The characters you type stay exactly as typed. No script on this page does any of it.{{EDITIONS}}</p>

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
    <li>GitHub's extensions: strikethrough with <code>~</code> or <code>~~</code>, bare URLs
    (<code>www.</code>, <code>http://</code>, <code>https://</code>, <code>ftp://</code>, with the trailing
    punctuation GitHub leaves out) and bare email addresses.</li>
    <li>Each line's block markup: headings, block quotes (a bar), list items (a bullet; numbers stay), task
    boxes, thematic breaks (a rule), and lines that are code, code fences, HTML or link reference definitions,
    which inline syntax leaves alone.</li>
  </ul>

  <h2>How exact it is</h2>
  <table>
    <tr><th>Text</th><th class="n">Lines</th>{{HEADS}}</tr>
    {{ROWS}}
  </table>
  <p class="note">Each character's glyph (hidden, or its style) is compared with what GitHub makes of the line
  read as a document, as computed by ports of the reference implementations: commonmark.js 0.31.2, and
  cmark-gfm 0.29.0.gfm.13 (github.com's parser) for the extensions. Lines past one of the font's bounds (below)
  are left out of the count; many of them still come out right.</p>

  <h2>How a font can parse Markdown</h2>
  <p>OpenType lets a font substitute glyphs by context, one lookup after another, each a pass over the line
  from left to right or from right to left. The font's 150 or so passes carry what they learn in glyph variants.
  The trick that makes Markdown possible is that most passes only see the characters they care about: a pass
  matching <code>*</code> and <code>_</code> skips every letter in between, so a pair of markers is next to each
  other however much text separates them.</p>
  <ol>
    <li><b>Right to left:</b> what lies ahead of each character. Whether a code span's closing backticks
    follow, whether a link destination <code>(…)</code> follows a <code>]</code>, whether a valid tag or
    autolink starts at a <code>&lt;</code>, and what the line's block markup needs to know.</li>
    <li><b>Left to right, after that:</b> the line's block markup, read from its start; a scan that settles code
    spans, link destinations and raw HTML; then brackets and emphasis are matched in rounds, where each round
    pairs every opener with the closer right after it and matched pairs drop out, so the next round sees the
    next level of nesting; then each glyph is drawn in its style.</li>
  </ol>
  <p>So CommonMark's inline syntax takes one change of direction. It can't take none: whether a run of backticks
  opens a code span depends on what follows, and whether it is inside one depends on what precedes. GitHub's
  extensions add a few right-to-left passes later on: where a bare URL's trailing punctuation starts, and
  email addresses, which GitHub only looks for once emphasis is settled. Markdown's nesting is unbounded,
  which no finite set of passes can follow, so the font has bounds: {{BOUNDS}}.</p>

  <h2>Limits</h2>
  <ul>
    <li>One line at a time: a line is read as if it were the whole document, so nothing that spans lines (a
    paragraph continued into a list, a fenced code block's content, reference links).</li>
    <li>Browsers break a line into pieces before the font sees it, and the font can't see across them: Safari at
    soft wraps (so this box doesn't wrap), Chrome where the script changes and at tabs, so <code>*мир*</code>
    after Latin text, a Latin URL after Cyrillic link text, or emphasis with a tab inside, stays as typed there
    (Safari renders all three).</li>
    <li>In Safari a space inside a hidden link destination (before a title) still takes a space's width.</li>
    <li>Needs a browser or app that applies OpenType features and color fonts: current Chrome, Firefox and Safari.</li>
  </ul>
  <p class="note">{{BASE}}</p>
</main>
{{SCRIPT}}{{EDITION_SCRIPT}}
"""

EDITION = """
      <label for="edition">Edition
        <select id="edition"><option value="mono">Monospace</option>
        <option value="sans">Proportional</option></select></label>"""

EDITION_SCRIPT = """
<script>
(() => {
  const editor = document.getElementById('editor'), edition = document.getElementById('edition');
  const apply = () => editor.classList.toggle('sans', edition.value === 'sans');
  edition.addEventListener('change', apply);
  apply();
})();
</script>"""


def accuracy(ttf, sets):
    """For each set of lines: those within the font's bounds, and the share
    of them the font renders as GitHub does."""
    view, shaper = verify.FontView(ttf), test_fontlex.SHAPERS["harfbuzz"](ttf)
    out = []
    for name, lines in sets:
        within = [l for l in lines if not bounds.exceeds(l, view.cmap)]
        ok = sum(verify.check(view, shaper, l) is None for l in within)
        print(f"{name}: {ok}/{len(within)} within the bounds")
        out.append((len(within), ok / len(within)))
    return out


def web_font(ttf):
    font = TTFont(io.BytesIO(ttf), recalcTimestamp=False)
    font["post"].formatType = 3.0    # no glyph names on the web
    return pages.woff2(font)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--font", required=True, help="the compiled font (TTF)")
    ap.add_argument("--sans", help="the proportional edition (TTF)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=5000, help="random lines to check")
    args = ap.parse_args()
    fonts = [Path(args.font).read_bytes()] + ([Path(args.sans).read_bytes()] if args.sans else [])
    sets = [("CommonMark's one-line spec examples", [l for _, l in verify.spec_lines(HERE / "spec-0.31.2.json")]),
            ("GitHub's one-line extension examples", [l for _, l in verify.spec_lines(HERE / "gfm-spec-0.29-extensions.json")]),
            ("Random lines of Markdown syntax", list(verify.random_lines(args.n, 1, verify.TOKENS))),
            ("Random lines behind block markup", list(verify.block_lines(args.n // 4, 1, verify.TOKENS)))]
    results = [accuracy(ttf, sets) for ttf in fonts]
    rows = []
    for i, (name, _) in enumerate(sets):
        counts = sorted({r[i][0] for r in results})
        cells = "".join(f"<td class=\"n\">{r[i][1]:.1%}</td>" for r in results)
        rows.append(f"<tr><td>{html.escape(name)}</td><td class=\"n\">{' / '.join(f'{c:,}' for c in counts)}</td>"
                    f"{cells}</tr>")
    bound_text = (f"emphasis runs of up to {mdfont.MAX_DELIMS} characters, nested {mdfont.ROUNDS} deep; "
                  f"{mdfont.MAX_BRACKETS} brackets open at once; backtick runs of up to {mdfont.MAX_TICKS}; "
                  f"parentheses {mdfont.PARENS} deep in a destination")
    sample = (HERE / "sample.md").read_text(encoding="utf-8").rstrip("\n")
    sans = len(fonts) > 1
    box = ("Render Markdown", sample, 'wrap="off" aria-label="Markdown, rendered by the font"',
           EDITION if sans else "")
    face = (f'@font-face {{ font-family: "Fontlex Markdown Sans"; '
            f'src: url(data:font/woff2;base64,{base64.b64encode(web_font(fonts[1])).decode()}) format("woff2"); }}'
            if sans else "")
    page = pages.page(PAGE, web_font(fonts[0]), "Fontlex Markdown", {}, box, {
        "ROWS": "\n    ".join(rows),
        "BOUNDS": html.escape(bound_text),
        "SANS_FACE": face,
        "EDITIONS": (" It comes in two editions: monospaced, and proportional with code in a monospaced font, "
                     "so the box looks like the rendered page." if sans else ""),
        "HEADS": ('<th class="n">Monospace</th><th class="n">Proportional</th>' if sans
                  else '<th class="n">Rendered as CommonMark</th>'),
        "BASE": ("Base fonts: JetBrains Mono, and Noto Sans with code in JetBrains Mono, each with its bold and "
                 "italic (SIL Open Font License)." if sans else
                 "Base font: JetBrains Mono with its bold and italic (SIL Open Font License)."),
        "EDITION_SCRIPT": EDITION_SCRIPT if sans else "",
    })
    pages.write(args.out, page)


if __name__ == "__main__":
    main()
