#!/usr/bin/env python3
"""Build english/syllables/demo.html: a text box in the English syllable
font, with what the patterns are trained on and how often they're right.

    python english/syllables/build_page.py --out english/syllables/demo.html

The accuracy figures are patgen.py's (README.md, Results): they need the
Moby Hyphenation List, which isn't in the repository. What this script
checks itself is that the embedded font colors the sample text exactly as
the patterns split it.
"""

import argparse
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from fontTools.ttLib import TTFont  # noqa: E402

import fontlex  # noqa: E402
import test_fontlex  # noqa: E402
from demo import pages  # noqa: E402

SAMPLE = """A little tiger named Tilly lives with her grandmother. In the evening she plays in the garden \
with a yellow ball. Then Peter the hedgehog comes along and says: Hello, Tilly! Together they watch the \
butterflies. Later Tilly drinks warm milk from her favorite bowl, and Grandmother reads her a story about \
a rabbit."""

# patgen.py's results (README.md): (right, of) for each set of words.
FREQUENT = (27_444, 27_536)          # the 30,000 most frequent words in the list, patterns trained on all
HELDOUT_FREQUENT = (2_505, 2_790)    # frequent words held out of training
HELDOUT_ALL = (14_126, 16_833)       # every word held out of training

PAGE = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fontlex English Syllables: syllables in color for learning to read</title>
<style>
{{STYLE}}
textarea#code { min-height: 14rem; font-family: "Fontlex English Syllables", system-ui, sans-serif;
  font-size: 1.35rem; line-height: 1.75; }
.s1 { color: var(--s1); } .s2 { color: var(--s2); }
</style>
<main>
  <p class="note nav"><a href="https://github.com/fMindstormer/fontlex">Fontlex</a> ·
  <a href="https://fmindstormer.github.io/fontlex/">All demos</a> ·
  <a href="https://github.com/fMindstormer/fontlex/releases/latest">Download</a></p>
  <h1>Fontlex English Syllables</h1>
  <p class="lede">A plain text box, in a font that colors each word's syllables in turn, <b class="s1">blue</b>
  and <b class="s2">red</b>, so a child learning to read sees where to break a long word: <i>lit-tle</i>,
  <i>ti-ger</i>, <i>but-ter-flies</i>. Edit the text, type your own, or use the font in a word processor to make
  worksheets.</p>

  {{EDITOR}}

  <h2>How it decides</h2>
  <ul>
    <li>Words split as dictionaries split them: a vowel that ends a syllable is long (<i>ti-ger</i>), a short one
    keeps the consonant after it (<i>rab-bit</i>), and a consonant before <i>-le</i> starts the last syllable
    (<i>ta-ble</i>).</li>
    <li>The splits come from {{N_PATTERNS}} hyphenation patterns, trained the way TeX's are, on the Moby
    Hyphenation List (about 160,000 words) with the frequent words it lacks added: one-syllable words, unsplit,
    and inflected forms like <i>start-ed</i> and <i>play-ing</i>. The text engine runs them as you type, so the
    font also guesses at words it was never shown.</li>
    <li>Every word starts blue. Everything happens inside the font; no script on this page does the
    coloring.</li>
  </ul>

  <h2>How often it's right</h2>
  <p>Counted against the word list, so this measures how faithfully the font follows a dictionary, not a
  teacher's judgment:</p>
  <table>
    <tr><th>Words</th><th>Split exactly as the list does</th></tr>
    <tr><td>Frequent words: those of the 30,000 most frequent that the list has</td><td class="n">{{FREQUENT}}</td></tr>
    <tr><td>Frequent words held out of training</td><td class="n">{{HELDOUT_FREQUENT}}</td></tr>
    <tr><td>All words held out of training</td><td class="n">{{HELDOUT_ALL}}</td></tr>
  </table>
  <p>So a common word comes out as the dictionary splits it, and a word the list lacks is right about five times
  in six. Teachers haven't reviewed it yet.</p>

  <h2>Limits</h2>
  <ul>
    <li>Dictionary hyphenation isn't always how a word is taught or said: the list has <i>lat-er</i> where phonics
    teaches <i>la-ter</i>, and <i>eve-ry</i> where a reader says <i>ev-ry</i>.</li>
    <li>Words with an apostrophe (<i>don't</i>) are split at it.</li>
    <li>It is slower to lay out than a plain font, about 22 ms for a 100-word paragraph: fine for typing, slow
    for a long document.</li>
    <li>Needs an app that renders color fonts with OpenType features: current Chrome, Firefox and Safari do,
    and so do Pages and TextEdit on a Mac.</li>
  </ul>
  <p class="note">Word list: the Moby Hyphenation List by Grady Ward (public domain). Pronunciations used to
  check syllable counts: CMUdict. Base font: Noto Sans (SIL Open Font License). How it's made and measured:
  <a href="https://github.com/fMindstormer/fontlex/blob/main/english/syllables/README.md">english/syllables/README.md</a>.</p>
</main>
{{SCRIPT}}
"""


def colored(order, shaper, text):
    """The text with a hyphen wherever the font's color changes inside a word."""
    glyphs, _ = shaper.shape(text)
    out, prev = "", None
    for (gid, *_), ch in zip(glyphs, text):
        name = order[gid] if gid is not None else ""
        color = name.split(fontlex.WORD_SUFFIX)[1] if fontlex.WORD_SUFFIX in name else None
        if prev and color and color != prev:
            out += "-"
        out += ch
        prev = color
    return out


def expected(spec, text):
    s = spec.syllables
    def split(m):
        breaks = fontlex.syllable_breaks(m.group().lower(), s.patterns, s.longest)
        return "".join(("-" if i in breaks else "") + c for i, c in enumerate(m.group()))
    return re.sub(r"[A-Za-z]+", split, text)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--spec", default=str(ROOT / "specs" / "english-syllables.yaml"))
    ap.add_argument("--base", default=str(ROOT / "fonts" / "NotoSans-Regular.ttf"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    spec = fontlex.load_spec(args.spec)
    res = fontlex.compile_font(spec, args.base)
    buf = io.BytesIO()
    res.font.save(buf)
    ttf = buf.getvalue()

    order = TTFont(io.BytesIO(ttf)).getGlyphOrder()
    got = colored(order, test_fontlex.SHAPERS["harfbuzz"](ttf), SAMPLE)
    want = expected(spec, SAMPLE)
    assert got == want, f"the font colors the sample differently from the patterns:\n{got}\n{want}"
    print(f"sample: {want}")

    themes = dict(spec.themes)
    colors = {f"s{i}": (themes["light"][f"syllable{i}"], themes["dark"][f"syllable{i}"]) for i in (1, 2)}
    box = ("Syllable colors", SAMPLE, 'lang="en" aria-label="English text with syllables in alternating colors"')
    pct = lambda right, of: f"{right:,} of {of:,} ({right / of:.1%})"  # noqa: E731
    page = pages.page(PAGE, pages.woff2(res.font), spec.name, colors, box, {
        "N_PATTERNS": f"{len(spec.syllables.patterns):,}",
        "FREQUENT": pct(*FREQUENT),
        "HELDOUT_FREQUENT": pct(*HELDOUT_FREQUENT),
        "HELDOUT_ALL": pct(*HELDOUT_ALL),
    })
    pages.write(args.out, page)


if __name__ == "__main__":
    main()
