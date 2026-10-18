#!/usr/bin/env python3
"""Build the Markdown font's demo page: a text box in the font, with how it
works and what was measured.

    python markdown/build_page.py --font build/Fontlex-Markdown.ttf --out markdown/demo.html

The accuracy numbers come from checking the embedded font (verify.py) on
CommonMark's single-line spec examples and random lines.
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
import fontbuild  # noqa: E402
import verify  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402

PAGE = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fontlex Markdown: CommonMark rendered by a font</title>
<style>
@font-face { font-family: "Fontlex Markdown"; src: url(data:font/woff2;base64,{{FONT}}) format("woff2"); }
:root { --bg: #F4F5F7; --surface: #FFFFFF; --ink: #1B2130; --muted: #5B6476; --rule: #D8DCE3;
        --fp: light; --link: {{LINK_LIGHT}}; color-scheme: light; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #11141B; --surface: #181C25; --ink: #E4E7EE; --muted: #98A0B1; --rule: #2A303D;
  --fp: dark; --link: {{LINK_DARK}}; color-scheme: dark; } }
:root[data-theme="dark"] { --bg: #11141B; --surface: #181C25; --ink: #E4E7EE; --muted: #98A0B1;
  --rule: #2A303D; --fp: dark; --link: {{LINK_DARK}}; color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 64rem; margin: 0 auto; padding: 2.5rem 1.25rem 4rem; }
h1 { font-size: 2rem; margin: 0 0 .25rem; }
h2 { font-size: 1.15rem; margin: 2.25rem 0 .5rem; }
.lede { color: var(--muted); margin: 0 0 1.5rem; }
.editor { background: var(--surface); border: 1px solid var(--rule); border-radius: 10px; overflow: hidden; }
.bar { display: flex; gap: 1.25rem; align-items: center; padding: .6rem 1rem; border-bottom: 1px solid var(--rule);
       font-size: .875rem; color: var(--muted); flex-wrap: wrap; }
.bar label { display: inline-flex; gap: .4rem; align-items: center; }
select { font: inherit; color: var(--ink); background: var(--bg); border: 1px solid var(--rule); border-radius: 6px; }
textarea#code { display: block; width: 100%; min-height: 19rem; border: 0; outline: none; resize: vertical;
  padding: 1rem 1.1rem; background: transparent; color: var(--ink); white-space: pre; overflow-x: auto;
  font: 400 1rem/1.75 "Fontlex Markdown", ui-monospace, monospace; font-palette: var(--fp); }
#editor.off textarea#code { font-feature-settings: "calt" 0; }
table { border-collapse: collapse; width: 100%; font-size: .92rem; }
th, td { text-align: left; padding: .45rem .6rem; border-bottom: 1px solid var(--rule); vertical-align: top; }
td.n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.note { color: var(--muted); font-size: .9rem; }
code { font: .92em ui-monospace, monospace; }
ul, ol { padding-left: 1.2rem; } li { margin: .25rem 0; }
</style>
<main>
  <h1>Fontlex Markdown</h1>
  <p class="lede">The box below is a plain text box holding Markdown. The font renders it: the text engine
  that lays out the letters runs CommonMark's inline rules, hides the markup and styles the text. The
  characters you type stay exactly as typed. No script on this page does any of it.</p>

  <div class="editor" id="editor">
    <div class="bar">
      <label for="hl"><input type="checkbox" id="hl" checked> Render Markdown</label>
      <label for="pal">Palette
        <select id="pal"><option value="auto">Match page</option><option value="light">Light</option>
        <option value="dark">Dark</option></select></label>
    </div>
    <textarea id="code" spellcheck="false" wrap="off" aria-label="Markdown, rendered by the font">{{SAMPLE}}</textarea>
  </div>
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
  <p class="note">Each character's glyph (hidden, or its style) is compared with what the reference
  implementation, commonmark.js 0.31.2, makes of it. Lines past one of the font's bounds (below) are left out of
  the count; most of them still come out right.</p>

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
<script>
(() => {
  const editor = document.getElementById('editor'), hl = document.getElementById('hl'), pal = document.getElementById('pal');
  const style = document.createElement('style');
  document.head.appendChild(style);
  function apply() {
    editor.classList.toggle('off', !hl.checked);
    const value = pal.value === 'auto' ? 'var(--fp)' : pal.value;
    style.textContent = 'textarea#code { font-palette: ' + value + '; }';
  }
  hl.addEventListener('change', apply);
  pal.addEventListener('change', apply);
  apply();
})();
</script>
"""


def main():
    import mdfont
    import test_fontlex as T
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--font", required=True, help="the compiled font (TTF)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=5000, help="random lines to check")
    args = ap.parse_args()
    ttf = Path(args.font).read_bytes()
    view, shaper = verify.FontView(ttf), T.SHAPERS["harfbuzz"](ttf)
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
    font["post"].formatType = 3.0
    font.flavor = "woff2"
    buf = io.BytesIO()
    font.save(buf)
    bound_text = (f"emphasis runs of up to {mdfont.MAX_DELIMS} characters, nested {mdfont.ROUNDS} deep; "
                  f"{mdfont.MAX_BRACKETS} brackets open at once; backtick runs of up to {mdfont.MAX_TICKS}; "
                  f"parentheses {mdfont.PARENS} deep in a destination")
    repl = {
        "{{FONT}}": base64.b64encode(buf.getvalue()).decode(),
        "{{SAMPLE}}": html.escape((HERE / "sample.md").read_text(encoding="utf-8").rstrip("\n")),
        "{{ROWS}}": "\n    ".join(rows),
        "{{BOUNDS}}": html.escape(bound_text),
        "{{LINK_LIGHT}}": fontbuild.PALETTES["light"]["link"],
        "{{LINK_DARK}}": fontbuild.PALETTES["dark"]["link"],
    }
    page = PAGE
    for k, v in repl.items():
        page = page.replace(k, v)
    assert "{{" not in page, "unfilled placeholder"
    Path(args.out).write_text(page, encoding="utf-8")
    print(f"wrote {args.out} ({len(page) // 1024} KB)")


if __name__ == "__main__":
    main()
