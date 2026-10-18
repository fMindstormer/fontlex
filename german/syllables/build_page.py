#!/usr/bin/env python3
"""Build german/syllables/demo.html: a text box in the syllable font, with
its accuracy on the hand-labeled word lists, measured with the embedded font.

    python german/syllables/build_page.py --out german/syllables/demo.html
"""

import argparse
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
from demo import pages  # noqa: E402
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
{{STYLE}}
textarea#code { min-height: 14rem; font-size: 1.35rem; line-height: 1.75; }
.s1 { color: var(--s1); } .s2 { color: var(--s2); }
</style>
<main>
  <h1>Fontlex Silben</h1>
  <p class="lede">A plain text box, in a font that colors each word's syllables in turn, <b class="s1">blue</b>
  and <b class="s2">red</b>, the way many German primary schools teach reading (the syllable method). Edit the text,
  type your own, or use the font in a word processor to make worksheets.</p>

  {{EDITOR}}

  <h2>How it decides</h2>
  <ul>
    <li>Syllables come from the German hyphenation patterns TeX uses ({{N_PATTERNS}} patterns), run by the text
    engine as you type, with a few rules for the reading syllables hyphenation never splits off:
    <i>A-bend</i>, <i>O-ma</i>, <i>Ra-di-o</i>.</li>
    <li>Every word starts blue. Compounds split at their parts: <i>Lieb-lings-schüs-sel</i>.</li>
    <li>Everything happens inside the font. There is no script on this page doing the coloring.</li>
  </ul>

  <h2>How accurate it is</h2>
  <p>On {{N_HELDOUT}} words from first readers, labeled by hand before any testing, the font splits
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
{{SCRIPT}}
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

    order = TTFont(io.BytesIO(ttf)).getGlyphOrder()
    shaper = test_fontlex.SHAPERS["harfbuzz"](ttf)
    gold = (Path(__file__).resolve().parent / "words-heldout.txt").read_text(encoding="utf-8").split()
    wrong = [g for g in gold if syllables(ttf, order, shaper, g.replace("-", "")) != g]
    right = len(gold) - len(wrong)
    print(f"held-out words: {right}/{len(gold)}")

    themes = dict(spec.themes)
    colors = {f"s{i}": (themes["light"][f"syllable{i}"], themes["dark"][f"syllable{i}"]) for i in (1, 2)}
    box = ("Syllable colors", SAMPLE, 'lang="de" aria-label="German text with syllables in alternating colors"')
    page = pages.page(PAGE, pages.woff2(res.font), spec.name, colors, box, {
        "N_PATTERNS": f"{len(spec.syllables.patterns):,}",
        "N_HELDOUT": str(len(gold)),
        "HELDOUT_RIGHT": str(right),
        "HELDOUT_PCT": f"{right / len(gold):.1%}",
        "HELDOUT_WRONG": ", ".join(f"<i>{html.escape(w)}</i>" for w in wrong) or "none",
    })
    pages.write(args.out, page)


if __name__ == "__main__":
    main()
