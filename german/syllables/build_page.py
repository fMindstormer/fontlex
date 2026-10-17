#!/usr/bin/env python3
"""Build german/syllables/demo.html: a text box in the syllable font, with
its accuracy on the hand-labeled word lists, measured with the embedded font.

    python german/syllables/build_page.py --out german/syllables/demo.html
"""

import argparse
import base64
import html
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fontTools.ttLib import TTFont  # noqa: E402

import fontlex  # noqa: E402
import test_fontlex  # noqa: E402
from evaluate import syllables  # noqa: E402

SAMPLE = """Die kleine Katze Mimi wohnt bei Oma und Opa. Am Abend spielt sie im Garten mit einem \
roten Ball. Dann kommt der Igel Paul und sagt: Hallo, Mimi! Zusammen schauen sie den Schmetterlingen \
zu. Später trinkt Mimi Milch aus ihrer Lieblingsschüssel, und Opa liest ihr eine Geschichte vor."""

PAGE = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fontlex Silben: syllables in color for learning to read</title>
<style>
@font-face { font-family: "Fontlex German Syllables"; src: url(data:font/woff2;base64,{{FONT}}) format("woff2"); }
:root { --bg: #F4F5F7; --surface: #FFFFFF; --ink: #1B2130; --muted: #5B6476; --rule: #D8DCE3;
        --fp: light; --s1: {{S1_LIGHT}}; --s2: {{S2_LIGHT}}; color-scheme: light; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #11141B; --surface: #181C25; --ink: #E4E7EE; --muted: #98A0B1; --rule: #2A303D;
  --fp: dark; --s1: {{S1_DARK}}; --s2: {{S2_DARK}}; color-scheme: dark; } }
:root[data-theme="dark"] { --bg: #11141B; --surface: #181C25; --ink: #E4E7EE; --muted: #98A0B1;
  --rule: #2A303D; --fp: dark; --s1: {{S1_DARK}}; --s2: {{S2_DARK}}; color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 52rem; margin: 0 auto; padding: 2.5rem 1.25rem 4rem; }
h1 { font-size: 2rem; margin: 0 0 .25rem; } h2 { font-size: 1.15rem; margin: 2.25rem 0 .5rem; }
.lede { color: var(--muted); margin: 0 0 1.5rem; }
.editor { background: var(--surface); border: 1px solid var(--rule); border-radius: 10px; overflow: hidden; }
.bar { display: flex; gap: 1.25rem; align-items: center; padding: .6rem 1rem; border-bottom: 1px solid var(--rule);
       font-size: .875rem; color: var(--muted); flex-wrap: wrap; }
.bar label { display: inline-flex; gap: .4rem; align-items: center; }
select { font: inherit; color: var(--ink); background: var(--bg); border: 1px solid var(--rule); border-radius: 6px; }
textarea#code { display: block; width: 100%; min-height: 14rem; border: 0; outline: none; resize: vertical;
  padding: 1rem 1.1rem; background: transparent; color: var(--ink);
  font: 400 1.35rem/1.75 "Fontlex German Syllables", ui-monospace, monospace; font-palette: var(--fp); }
#editor.off textarea#code { font-feature-settings: "calt" 0; }
.s1 { color: var(--s1); } .s2 { color: var(--s2); }
.note { color: var(--muted); font-size: .9rem; }
ul { padding-left: 1.2rem; } li { margin: .25rem 0; }
</style>
<main>
  <h1>Fontlex Silben</h1>
  <p class="lede">A plain text box, in a font that colors each word's syllables in turn, <b class="s1">blue</b>
  and <b class="s2">red</b>, the way many German primary schools teach reading (the syllable method). Edit the text,
  type your own, or use the font in a word processor to make worksheets.</p>

  <div class="editor" id="editor">
    <div class="bar">
      <label for="hl"><input type="checkbox" id="hl" checked> Syllable colors</label>
      <label for="pal">Palette
        <select id="pal"><option value="auto">Match page</option><option value="light">Light</option>
        <option value="dark">Dark</option></select></label>
    </div>
    <textarea id="code" spellcheck="false" lang="de" aria-label="German text with syllables in alternating colors">{{SAMPLE}}</textarea>
  </div>

  <h2>How it decides</h2>
  <ul>
    <li>Syllables come from the German hyphenation patterns TeX uses ({{N_PATTERNS}} patterns), run by the text
    engine as you type, with a few rules for the reading syllables hyphenation never splits off:
    <i>A-bend</i>, <i>O-ma</i>, <i>Ra-di-o</i>.</li>
    <li>Every word starts blue. Compounds split at their parts: <i>Lieb-lings-schüs-sel</i>.</li>
    <li>Everything happens inside the font. There is no script on this page doing the coloring.</li>
  </ul>

  <h2>How accurate it is</h2>
  <p>On {{N_HELDOUT}} words from first readers that I labeled by hand before testing, the font splits
  {{HELDOUT_RIGHT}} exactly as the syllable method does ({{HELDOUT_PCT}}). The misses: {{HELDOUT_WRONG}}.
  Measured with the font embedded in this page.</p>

  <h2>Limits</h2>
  <ul>
    <li>Vowels next to each other inside a word stay together when they're separate syllables:
    <i>Koa-la</i>, <i>Thea-ter</i>.</li>
    <li>A word starting with a single vowel and a consonant cluster, or with a prefix-like start, keeps the
    vowel attached: <i>Apri-ko-se</i>, <i>Uni-form</i>.</li>
    <li>Needs an app that renders color fonts with OpenType features: current Chrome, Firefox and Safari do,
    and so do Pages and TextEdit on a Mac.</li>
  </ul>
  <p class="note">Patterns: German hyphenation patterns by the Deutschsprachige Trennmustermannschaft (MIT
  license). Base font: JetBrains Mono (SIL Open Font License).</p>
</main>
<script>
(() => {
  const editor = document.getElementById('editor'), hl = document.getElementById('hl'), pal = document.getElementById('pal');
  const style = document.createElement('style');
  document.head.appendChild(style);
  function apply() {
    editor.classList.toggle('off', !hl.checked);
    style.textContent = 'textarea#code { font-palette: ' + (pal.value === 'auto' ? 'var(--fp)' : pal.value) + '; }';
  }
  hl.addEventListener('change', apply);
  pal.addEventListener('change', apply);
  apply();
})();
</script>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--spec", default=str(ROOT / "specs" / "german-syllables.yaml"))
    ap.add_argument("--base", default=str(ROOT / "fonts" / "JetBrainsMono-Regular.ttf"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    spec = fontlex.load_spec(args.spec)
    res = fontlex.compile_font(spec, args.base)
    buf = io.BytesIO()
    res.font.save(buf)
    ttf = buf.getvalue()
    res.font.flavor = "woff2"
    buf = io.BytesIO()
    res.font.save(buf)

    order = TTFont(io.BytesIO(ttf)).getGlyphOrder()
    shaper = test_fontlex.SHAPERS["harfbuzz"](ttf)
    gold = (Path(__file__).resolve().parent / "words-heldout.txt").read_text(encoding="utf-8").split()
    wrong = [g for g in gold if syllables(ttf, order, shaper, g.replace("-", "")) != g]
    right = len(gold) - len(wrong)
    print(f"held-out words: {right}/{len(gold)}")

    themes = dict(spec.themes)
    repl = {
        "{{FONT}}": base64.b64encode(buf.getvalue()).decode(),
        "{{SAMPLE}}": html.escape(SAMPLE),
        "{{N_PATTERNS}}": f"{len(spec.syllables.patterns):,}",
        "{{N_HELDOUT}}": str(len(gold)),
        "{{HELDOUT_RIGHT}}": str(right),
        "{{HELDOUT_PCT}}": f"{right / len(gold):.1%}",
        "{{HELDOUT_WRONG}}": ", ".join(f"<i>{html.escape(w)}</i>" for w in wrong) or "none",
        "{{S1_LIGHT}}": themes["light"]["syllable1"], "{{S2_LIGHT}}": themes["light"]["syllable2"],
        "{{S1_DARK}}": themes["dark"]["syllable1"], "{{S2_DARK}}": themes["dark"]["syllable2"],
    }
    page = PAGE
    for k, v in repl.items():
        page = page.replace(k, v)
    assert "{{" not in page, "unfilled placeholder"
    Path(args.out).write_text(page, encoding="utf-8")
    print(f"wrote {args.out} ({len(page) // 1024} KB)")


if __name__ == "__main__":
    main()
