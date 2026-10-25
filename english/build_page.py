#!/usr/bin/env python3
"""Build the English font's demo page: a text box in the font, a legend and
what was checked.

    python english/build_page.py --font build/Fontlex-English.ttf --out english/demo.html
"""

import argparse
import html
import io
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import verify  # noqa: E402  (before enfont, which puts markdown/ and its verify.py on the path)
import enfont  # noqa: E402
import test_fontlex  # noqa: E402
from demo import pages  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402

SAMPLE = """English spelling often hides the sound of a word. Which letters are silent in knife, write, island, listen, castle and honest? Where does the stress fall in photograph and photography, or in comfortable, chocolate and different?

This font shows it as you read: the stressed vowel is bold and red, reduced vowels are blue, and silent letters fade. Where a word's stress depends on its use, the word before it decides: a present for you, to present to you. Where it doesn't, an invisible marker after the word can: keep a new record︀, then record︁ it again. It knows the 30,000 most common words; others stay as they are. Type anything in this box."""

PAGE = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fontlex English: pronunciation hints in a font</title>
<style>
{{STYLE}}
textarea#code { min-height: 16rem; font-family: "Fontlex English", system-ui, sans-serif; font-size: 1.2rem;
  line-height: 1.8; white-space: pre-wrap; }
.legend span { font-weight: 600; }
.legend .stress { color: var(--stress); } .legend .reduced { color: var(--reduced); }
.legend .silent { color: var(--silent); }
</style>
<main>
  <h1>Fontlex English</h1>
  <p class="lede">A font that hints at how English words are pronounced, for learners. The text box below holds
  plain text; the font draws the hints, in any app that renders color fonts. Copy the text and you get the letters
  you typed.</p>
  {{EDITOR}}
  <p class="note legend">In words of two or more syllables, the <span class="stress">stressed vowel</span> is
  bold and red and <span class="reduced">reduced vowels</span> (the schwa of <i>banana</i>) are blue. In any
  word, <span class="silent">silent letters</span> fade. A word whose stress moves between noun and verb
  (<i>record</i>, <i>present</i>, <i>object</i>) takes its reading from the word before it: <i>the</i>,
  <i>a</i>, <i>my</i> make it a noun, <i>to</i>, <i>will</i>, <i>we</i> a verb; with neither it shows only
  what both readings share. An invisible character right after the word, which a tagger can add, overrides
  that: U+FE00 for the noun, U+FE01 for the verb (in the sample, after <i>new record</i> and <i>then
  record</i>). The switches above the text turn one kind of hint off; in other apps they are the
  font's stylistic sets (ss01 silent letters, ss02 reduced vowels, ss03 stress).</p>

  <h2>Where the hints come from</h2>
  <p>The pronunciations are the CMU Pronouncing Dictionary's (American English). Each word's spelling is aligned
  with its sounds, letter groups such as <i>sh</i>, <i>ee</i> and <i>tion</i>'s <i>ti</i> taken as one
  spelling of one sound, so a letter that spells no sound is silent: the <i>k</i> of <i>knife</i>, the
  <i>gh</i> of <i>night</i>, the <i>b</i> of <i>debt</i>. The font lists the {{WORDS}} most frequent words
  that the dictionary has, about 96% of running English text; any other word is drawn plain.</p>

  <h2>How exact it is</h2>
  <table>
    <tr><th>Text</th><th class="n">Checked</th><th class="n">Drawn as listed</th></tr>
    {{ROWS}}
  </table>
  <p class="note">Each letter's glyph is compared with the lexicon's hint for it, in HarfBuzz (Chrome,
  Firefox); Core Text (Safari) gives the same results.</p>

  <h2>How a font does it</h2>
  <p>Three OpenType passes. Right to left, each word's last letter gets a variant that says so; left to right,
  its first letter. Then one rule per listed word, matching from a first letter to a last one with case
  ignored, applies a hint to each marked letter. Words are matched whole, so <i>often</i> inside
  <i>oftentimes</i> isn't. Hints depend only on the word, so they survive line wrapping, unlike constructs
  that span words.</p>
  <p class="note">Base font: Noto Sans and Noto Sans Bold (SIL Open Font License). Pronunciations: the CMU
  Pronouncing Dictionary (BSD-style license); word frequencies: wordfreq.</p>
</main>
{{SCRIPT}}
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--font", required=True)
    ap.add_argument("--lexicon", default=str(HERE / "lexicon"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    ttf = Path(args.font).read_bytes()
    lex = verify.Lexicon(args.lexicon)
    view = verify.View(ttf, test_fontlex.SHAPERS["harfbuzz"](ttf))
    sets = [("Listed words, alone, capitalized, in capitals and in sentences; unlisted words",
             list(verify.cases(lex, random.Random(1)))),
            ("Lines of this project's English documentation",
             [l for p in ("README.md", "specs/README.md", "markdown/README.md", "theory/README.md")
              for l in (HERE.parent / p).read_text(encoding="utf-8").splitlines() if l.strip()]),
            ("This page's sample", SAMPLE.splitlines())]
    rows = []
    for name, texts in sets:
        ok = sum(verify.expected(t, lex) == view.hints(t) for t in texts)
        rows.append(f"<tr><td>{html.escape(name)}</td><td class=\"n\">{len(texts):,}</td>"
                    f"<td class=\"n\">{ok / len(texts):.1%}</td></tr>")
        print(f"{name}: {ok}/{len(texts)}")
    font = TTFont(io.BytesIO(ttf), recalcTimestamp=False)
    colors = {k: (enfont.PALETTES["light"][k], enfont.PALETTES["dark"][k]) for k in enfont.PALETTES["light"]}
    switches = pages.hint_switches([(enfont.HINT_SETS[k][0], k, label) for k, label in
                                    (("stress", "Stress"), ("reduced", "Reduced vowels"), ("silent", "Silent letters"))])
    box = ("Show hints", SAMPLE, 'aria-label="English text, with pronunciation hints"', switches)
    page = pages.page(PAGE, pages.woff2(font), "Fontlex English", colors, box, {
        "ROWS": "\n    ".join(rows),
        "WORDS": f"{len(lex.words):,}",
    })
    pages.write(args.out, page)


if __name__ == "__main__":
    main()
