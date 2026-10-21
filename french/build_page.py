#!/usr/bin/env python3
"""Build the French font's demo page: a text box in the font, a legend and
what was checked.

    python french/build_page.py --font build/Fontlex-French.ttf --out french/demo.html
"""

import argparse
import html
import io
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import verify  # noqa: E402  (before frfont, which puts markdown/ and its verify.py on the path)
import frfont  # noqa: E402
import test_fontlex  # noqa: E402
from demo import pages  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402

SAMPLE = (HERE / "sample.txt").read_text(encoding="utf-8").strip()

PAGE = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fontlex French: pronunciation hints in a font</title>
<style>
{{STYLE}}
textarea#code { min-height: 22rem; font-family: "Fontlex French", system-ui, sans-serif; font-size: 1.2rem;
  line-height: 1.9; white-space: pre-wrap; }
.legend span { font-weight: 600; }
.legend .silent { color: var(--silent); } .legend .nasal { color: var(--nasal); }
.legend .reduced { color: var(--reduced); } .legend .liaison { color: var(--liaison); }
</style>
<main>
  <h1>Fontlex French</h1>
  <p class="lede">A font that hints at how French words are pronounced, for learners. The text box below holds
  plain text, in French; the font draws the hints, in any app that renders color fonts. Copy the text and you get
  the letters you typed.</p>
  {{EDITOR}}
  <p class="note legend"><span class="silent">Silent letters</span> fade: the <i>t</i> of <i>petit</i>, the
  <i>ent</i> of <i>ils parlent</i>. The letters of a <span class="nasal">nasal vowel</span> are violet:
  <i>an</i>, <i>on</i>, <i>ain</i>, <i>un</i>, so <i>bon</i> and <i>bonne</i> look different. A
  <span class="reduced">schwa</span> that speakers often drop (<i>samedi</i>, <i>petit</i>) is blue. A
  <span class="liaison">liaison</span>, a final consonant said before the next word's vowel, is bold and green,
  with a tie under the space: <i>les amis</i>, <i>nous avons</i>, <i>vont-ils</i>. French has no word stress
  to mark. The switches above the text turn one kind of hint off; in other apps they are the font's stylistic
  sets (ss01 silent letters, ss02 schwas, ss04 nasal vowels, ss05 liaisons).</p>

  <h2>Where the hints come from</h2>
  <p>The pronunciations are Lexique 3.83's. Each word's spelling is aligned with its sounds, letter groups such as
  <i>eau</i>, <i>ou</i>, <i>an</i>, <i>gn</i> and <i>ill</i> taken as one spelling of one sound, so a letter
  that spells no sound is silent. The font lists the {{WORDS}} most frequent words that Lexique has, about 94% of
  running French text, and {{COMPOUNDS}} compounds such as <i>peut-être</i>; any other word is drawn plain.
  Liaison is drawn only where it is obligatory: after {{TRIGGERS}} determiners, pronouns, short prepositions and
  numbers (<i>les</i>, <i>nous</i>, <i>dans</i>, <i>deux</i>), and in inversion; not before an h aspiré
  (<i>les héros</i>) or <i>onze</i>. A word whose verb reading differs (<i>le président</i>, <i>ils
  président</i>) takes its reading from the word before it, or from an invisible character right after it,
  which a tagger can add: U+FE00 for the noun or adjective, U+FE01 for the verb (in the sample, after <i>élèves
  excellent</i>).</p>

  <h2>How exact it is</h2>
  <table>
    <tr><th>Text</th><th class="n">Checked</th><th class="n">Drawn as listed</th></tr>
    {{ROWS}}
  </table>
  <p class="note">Each letter's glyph, and each space's or hyphen's tie, is compared with the lexicon's hint for
  it, in HarfBuzz (Chrome, Firefox); Core Text (Safari) gives the same results.</p>

  <h2>How a font does it</h2>
  <p>OpenType passes. Right to left, each word's last letter gets a variant that says so; left to right, its first
  letter. Then cue words and words that block liaison are marked; verb/noun pairs read their cue; liaison
  triggers look one space ahead for a vowel or an h muet. Last, one rule per listed word, matching from a first
  letter to a last one with case ignored, applies a hint to each marked letter.</p>
  <p class="note">Base font: Noto Sans and Noto Sans Bold (SIL Open Font License). Pronunciations: Lexique 3.83
  (CC BY-SA 4.0); h aspiré: Wiktionary (CC BY-SA 4.0); word frequencies: wordfreq.</p>
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
    lex = verify.index_compounds(verify.Lexicon(args.lexicon))
    view = verify.View(ttf, test_fontlex.SHAPERS["harfbuzz"](ttf))
    sets = [("Listed words and compounds, alone, capitalized, in capitals and in sentences; verb/noun pairs after "
             "cues; liaison triggers before vowels, h muet, h aspiré and consonants; inversions; unlisted words",
             list(verify.cases(lex, random.Random(1)))),
            ("This page's sample", SAMPLE.splitlines())]
    rows = []
    for name, texts in sets:
        ok = sum(verify.expected(t, lex) == view.hints(t) for t in texts)
        rows.append(f"<tr><td>{html.escape(name)}</td><td class=\"n\">{len(texts):,}</td>"
                    f"<td class=\"n\">{ok / len(texts):.1%}</td></tr>")
        print(f"{name}: {ok}/{len(texts)}")
    font = TTFont(io.BytesIO(ttf), recalcTimestamp=False)
    colors = {k: (frfont.PALETTES["light"][k], frfont.PALETTES["dark"][k]) for k in frfont.PALETTES["light"]}
    switches = pages.hint_switches([(frfont.HINT_SETS[k][0], k, label) for k, label in
                                    (("silent", "Silent letters"), ("nasal", "Nasal vowels"), ("reduced", "Schwas"),
                                     ("liaison", "Liaisons"))])
    box = ("Show hints", SAMPLE, 'lang="fr" aria-label="French text, with pronunciation hints"', switches)
    page = pages.page(PAGE, pages.woff2(font), "Fontlex French", colors, box, {
        "ROWS": "\n    ".join(rows),
        "WORDS": f"{len(lex.words):,}",
        "COMPOUNDS": f"{len(lex.compounds):,}",
        "TRIGGERS": f"{len(lex.triggers)}",
    })
    pages.write(args.out, page)


if __name__ == "__main__":
    main()
