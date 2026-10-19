# Fontlex English: pronunciation hints in a font

A proof of concept: a font that hints at how English words are pronounced,
for learners. In words of two or more syllables the **stressed vowel** is
bold and red and **reduced vowels** (the schwa of *banana*) are gray. In any
word, **silent letters** fade: the *k* of *knife*, the *gh* of *night*, the
*b* of *debt*, the final *e* of *make*. The text stays as typed; copy it and
you get plain letters. `english/demo.html` is a text box in the font.

It knows the 30,000 most frequent English words that the CMU Pronouncing
Dictionary has (American English). By wordfreq's counts they make up 96.4%
of running text (the first 5,000 make up 86.8%, 20,000 make up 95.1%).
Other words are drawn plain.

## Results

*Measured* with `verify.py`, which compares each letter's glyph with the
lexicon's hint for it:

| Text | Checked | Right, HarfBuzz | Right, Core Text |
|---|---|---|---|
| Every listed word alone, capitalized, in capitals, in punctuation and in a sentence; with a curly apostrophe; inside longer words and made-up words (must stay plain) | 156,553 | 156,553 | 156,553 |
| Lines of this project's English READMEs (`README.md`, `markdown/`, `theory/`) | 743 | 743 | 743 |

The glyph count doesn't depend on the word list: 1,850 glyphs for any size.
The rules do:

| Words | Rules (words with hints) | WOFF2 | ms a line, HarfBuzz | ms a line, Core Text |
|---|---|---|---|---|
| none (plain Noto Sans) | | | 0.05 | 0.07 |
| 5,000 | 3,736 | 83 KB | 0.12 | 0.09 |
| 20,000 | 16,659 | 168 KB | 0.23 | 0.13 |
| 30,000 | 25,649 | 226 KB | 0.20 | 0.15 |

The times are the best of five runs over this project's README lines, on a
heavily loaded machine, so only their ratios mean much: about four times a
plain font in HarfBuzz, twice in Core Text. A shaper tries a word's rules
one after another among those for its first letter, which is most of the
cost; keying the rules on the first two letters would cut it. In WebKit the hints render in both palettes and survive soft wrapping,
because each hint depends only on its own word.

## Where the hints come from

`align.py` aligns each spelling with its CMUdict pronunciation:

- **Units of spelling.** The word is cut into graphemes: single letters, plus
  listed letter groups that spell one sound. These are consonant digraphs
  (*sh*, *ph*, *ck*), doubled consonants, vowel teams (*ee*, *ou*, *ai*),
  r-colored vowels (*er*, *ir*, *ear*; *ur* also for the "yer" of *figure*)
  and *ti*/*ci*/*si* for "sh" in *nation*.
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

271 of the most frequent forms don't align and are left out: nearly all
letters, abbreviations and initialisms (*mr*, *tv*, *bbc*, *usb*).

## How the font does it

Four GSUB passes, built by `enfont.py` on Noto Sans and Noto Sans Bold:

1. Right to left, each word's last letter becomes a "final" variant. A word
   is letters, with apostrophes between letters.
2. Left to right, each word's first letter becomes an "initial" variant.
3. Then one context rule per listed word that has hints (25,649 of the
   30,000). Each rule is class-based, so case is ignored, and runs from an
   initial letter to a final one, so it matches whole words only. It applies
   the stress, reduced or silent lookup at each hinted letter. The colors are
   COLR layers with light and dark palettes.
4. Initial and final variants that no rule claimed go back to plain letters.

This is the "lexicon as table bytes, not glyphs" design from
[../theory/README.md](../theory/README.md). The word rules cost bytes per
letter, and the glyph count doesn't grow with the word list.

## Next steps

- **Faster matching.** Mark each word's first letter with a variant that
  also records the second letter, so a word is tried only against the rules
  for its first two letters.
- **Words not in the 30,000**: the next 20,000 would add about 1.6% of
  running text (CMUdict lists fewer of them; many are names).
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
python english/align.py cmudict.dict --words 30000 --out english/lexicon    # the lexicon is checked in
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
