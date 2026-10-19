# Fontlex English: pronunciation hints in a font

A proof of concept: a font that hints at how English words are pronounced,
for learners. In words of two or more syllables the **stressed vowel** is
bold and red and **reduced vowels** (the schwa of *banana*) are gray. In any
word, **silent letters** fade: the *k* of *knife*, the *gh* of *night*, the
*b* of *debt*, the final *e* of *make*. The text stays as typed; copy it and
you get plain letters. `english/demo.html` is a text box in the font.

It knows the 5,000 most frequent English words that the CMU Pronouncing
Dictionary has (American English). By wordfreq's counts they make up about
87% of running text. Other words are drawn plain.

## Results

*Measured* with `verify.py`, which compares each letter's glyph with the
lexicon's hint for it:

| Text | Checked | Right, HarfBuzz | Right, Core Text |
|---|---|---|---|
| Every listed word alone, capitalized, in capitals, in punctuation and in a sentence; with a curly apostrophe; inside longer words and made-up words (must stay plain) | 31,060 | 31,060 | 31,060 |
| Lines of this project's English READMEs (`README.md`, `markdown/`, `theory/`) | 743 | 743 | 743 |

The font has 1,850 glyphs and is 84 KB as WOFF2. It shapes a line in about
0.08 ms in HarfBuzz, twice a plain Noto Sans, and as fast as Noto Sans in Core
Text. In WebKit the hints render in both palettes and survive soft wrapping,
because each hint depends only on its own word.

## Where the hints come from

`align.py` aligns each spelling with its CMUdict pronunciation:

- **Units of spelling.** The word is cut into graphemes: single letters, plus
  listed letter groups that spell one sound. These are consonant digraphs
  (*sh*, *ph*, *ck*), doubled consonants, vowel teams (*ee*, *ou*, *ai*),
  r-colored vowels (*er*, *ir*, *ear*) and *ti*/*ci*/*si* for "sh" in
  *nation*.
- **Learned costs.** Each grapheme gets 0, 1 or 2 phonemes, with costs learned
  by hard EM over the 30,000 most frequent words. The search starts from
  which letters plausibly spell which sounds.
- **Hints from the alignment.**
  - A grapheme that spells nothing is silent.
  - A vowel grapheme spelling the primary-stressed vowel is stressed.
  - One spelling AH0, ER0, IH0 or UH0 is reduced.
  - Stress and reduction are only marked in words of two or more syllables.
- **Ambiguous words.** A word with several pronunciations keeps only the
  hints they all agree on. So *record* and *present* show no stress, and *the*
  shows nothing.

How *kn* and *wr* are cut matters for teaching: *knife* has a silent *k*
rather than a *kn* that spells "n". The choices follow how phonics usually
names them, but they are choices:
- *igh* in *night* is *i* plus a silent *gh*;
- *ue* in *guess* and *ui* in *build* are vowel teams;
- *eo* in *people* is *e* plus a silent *o*.

71 of the most frequent forms don't align and are left out. They are mostly
letters and abbreviations (*mr*, *tv*, *uk*).

## How the font does it

Four GSUB passes, built by `enfont.py` on Noto Sans and Noto Sans Bold:

1. Right to left, each word's last letter becomes a "final" variant. A word
   is letters, with apostrophes between letters.
2. Left to right, each word's first letter becomes an "initial" variant.
3. Then one context rule per listed word that has hints (3,736 of the
   5,000). Each rule is class-based, so case is ignored, and runs from an
   initial letter to a final one, so it matches whole words only. It applies
   the stress, reduced or silent lookup at each hinted letter. The colors are
   COLR layers with light and dark palettes.
4. Initial and final variants that no rule claimed go back to plain letters.

This is the "lexicon as table bytes, not glyphs" design from
[../theory/README.md](../theory/README.md). The word rules cost bytes per
letter, and the glyph count doesn't grow with the word list.

## Next steps

- **More words.** 20,000 words cover about 96% of running text and 30,000
  about 97%. The rule tables should grow about linearly: roughly 0.5 MB of
  rules for 30,000 words, to be measured.
- **Check the alignments.** Have a teacher or a phonics word list go over
  the hints for the most frequent words. The alignment was only spot-checked.
- **Homographs from context.** *a record* vs *to record*: the previous word
  is often enough, and a font can read it.
- **Design.** Gray for reduced vowels and pale for silent letters are close
  in the dark palette. Alternatives are dotted or outlined silent letters,
  or vowel colors by sound behind a stylistic set, like ESL color-vowel
  charts.
- **British English**, from other pronunciation data (e.g. Wiktionary).
- **Words not listed**, from letter-to-sound rules or a suffix list, as
  the German font uses for gender.

## Reproducing

```sh
pip install -r english/requirements.txt
curl -LO https://raw.githubusercontent.com/cmusphinx/cmudict/master/cmudict.dict
python english/align.py cmudict.dict --words 5000 --out english/lexicon    # the lexicon is checked in
python english/enfont.py --base fonts/NotoSans-Regular.ttf --bold fonts/NotoSans-Bold.ttf --out build
python english/verify.py build/Fontlex-English.ttf --shaper harfbuzz --shaper coretext --corpus README.md
python english/build_page.py --font build/Fontlex-English.ttf --out english/demo.html
```

`./check.sh english` runs the last three.

## Licenses

`lexicon/words.tsv` is derived from the CMU Pronouncing Dictionary
(BSD-style license, `lexicon/CMUDICT-LICENSE.txt`). Its choice and order of
words follow `wordfreq`'s frequency ranking; wordfreq's data is under CC
BY-SA 4.0, used here for ranking only. The base fonts are Noto Sans under the
SIL Open Font License (`../fonts/OFL-NotoSans.txt`).
