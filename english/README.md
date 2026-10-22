# Fontlex English: pronunciation hints in a font

A proof of concept: a font that hints at how English words are pronounced,
for learners. In words of two or more syllables the **stressed vowel** is
bold and red and **reduced vowels** (the schwa of *banana*) are blue. In any
word, **silent letters** fade: the *k* of *knife*, the *gh* of *night*, the
*b* of *debt*, the final *e* of *make*. Where the stress depends on whether a
word is a noun or a verb (*record*, *present*, *object*), the word before it
decides: *the record* is REcord, *to record* is reCORD. A tagger or an
editor can also pick the reading with an invisible marker after the word
([markers/](../markers/README.md)). The text stays as typed; copy it and you get plain letters. `english/demo.html` is a text box in the font.

It knows the 30,000 most frequent English words that the CMU Pronouncing
Dictionary has (American English). By wordfreq's counts they make up 96.4%
of running text (the first 5,000 make up 86.8%, 20,000 make up 95.1%).
Other words are drawn plain.

## Results

*Measured* with `verify.py`, which compares each letter's glyph with the
lexicon's hint for it. This measures the compiler, not the hints: the font
draws exactly what the lexicon says, and the lexicon is only as right as
CMUdict and the aligner. Whether the hints are right is a separate question.
Only spot checks have answered it so far; a review by fluent speakers is
the next step (*Check the alignments* below).

| Text | Checked | As the lexicon says, HarfBuzz | Core Text |
|---|---|---|---|
| Every listed word alone, capitalized, in capitals, in punctuation and in a sentence; with a curly apostrophe; inside longer words and made-up words (must stay plain); every noun/verb pair after each cue word, after another word and after two spaces, and before each reading marker (also after a cue for the other reading); a marker after other words | 170,817 | 170,817 | 170,817 |
| Width with a marker: each pair as wide as after a cue for the same reading, every 50th other word as wide as without one | 1,446 | 1,446 | 1,446 |
| Lines of this project's English READMEs (`README.md`, `markdown/`, `theory/`) | 901 | 901 | 901 |

The glyph count doesn't depend on the word list (3,412 glyphs, mostly the
letters' first-letter variants); the rules do. Before the two-letter keys and
homographs:

| Words | Rules (words with hints) | WOFF2 | ms a line, HarfBuzz | ms a line, Core Text |
|---|---|---|---|---|
| none (plain Noto Sans) | | | 0.05 | 0.07 |
| 5,000 | 3,736 | 83 KB | 0.12 | 0.09 |
| 20,000 | 16,659 | 168 KB | 0.23 | 0.13 |
| 30,000 | 25,649 | 226 KB | 0.20 | 0.15 |

The times are the best of five runs over this project's README lines, on a
heavily loaded machine, so only their ratios mean much: about four times a
plain font in HarfBuzz, twice in Core Text. A shaper tries a word against
the rules for its first letter one after another. Keying them on the first
two letters (the current font, 238 KB) cut the time by about a fifth in both
engines, to roughly 0.2 ms a line in HarfBuzz and 0.13 ms in Core Text; the
rest is spread over the passes. In WebKit the hints render in both palettes
and survive soft wrapping, because each hint depends only on its own word.

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
- **Ties.** Of equally cheap alignments, each phoneme goes to the earliest
  letter that can say it: *been* is b-e plus a silent *e*, and the first *z*
  of *pizza* says "ts". Before this rule, ties fell to floating-point noise,
  so *beer* and *peer* silenced different letters, and the vowel before a
  double *r* came out silent (*arrive*, *correct*, *hurry*) instead of
  reduced or stressed.
- **Hints from the alignment.**
  - A grapheme that spells nothing is silent.
  - A vowel grapheme spelling the primary-stressed vowel is stressed.
  - One spelling AH0, ER0, IH0 or UH0 is reduced.
  - Stress and reduction are only marked in words of two or more syllables.
- **Ambiguous words.** A word with several pronunciations keeps only the
  hints they all agree on. So *the* shows nothing, and *record* shows no
  stress unless the word before it decides (below).
- **Noun/verb pairs.** For the 128 listed words and plurals that
  linguists list as stress-shifting verb/noun pairs (`lexicon/noun_verb_pairs.txt`,
  from Wikipedia's list of initial-stress-derived nouns), the pronunciations
  with the earliest stress make the noun reading and those with the latest
  make the verb reading (`lexicon/homographs.tsv`). Other words with several
  stress patterns (*museum*, *emergency*, *into*) are variants, not noun/verb
  pairs, and keep only their shared hints.

How *kn* and *wr* are cut matters for teaching: *knife* has a silent *k*
rather than a *kn* that spells "n". The choices follow how phonics usually
names them, but they are choices:
- *igh* in *night* is *i* plus a silent *gh*;
- *ue* in *guess* and *ui* in *build* are vowel teams;
- *eo* in *people* is *e* plus a silent *o*.

271 of the most frequent forms don't align and are left out: nearly all
letters, abbreviations and initialisms (*mr*, *tv*, *bbc*, *usb*).

## How the font does it

Six GSUB passes, built by `enfont.py` on Noto Sans and Noto Sans Bold:

1. Right to left, each word's last letter becomes a "final" variant. A word
   is letters, with apostrophes between letters.
2. Left to right, each word's first letter becomes an "initial" variant
   that also records the second letter, so a word is only tried against the
   rules for its first two letters.
3. Cue words (`lexicon/cues.tsv`: *the*, *a*, *my*, ... for nouns; *to*,
   *will*, *we*, ... for verbs) mark their last letter as a noun or verb cue.
4. A noun/verb pair right before a reading marker (U+FE00 noun, U+FE01
   verb; [markers/](../markers/README.md)), or else right after a cue and
   one space, gets that reading's hints.
5. Then one context rule per listed word that has hints (25,643 of the
   30,000). Each rule is class-based, so case is ignored, and runs from an
   initial letter to a final one, so it matches whole words only. It applies
   the stress, reduced or silent lookup at each hinted letter. The colors are
   COLR layers with light and dark palettes.
6. The variants that no rule claimed go back to plain letters.

This is the "lexicon as table bytes, not glyphs" design from
[../theory/README.md](../theory/README.md). The word rules cost bytes per
letter, and the glyph count doesn't grow with the word list.

### Turning a kind of hint off

Each kind of hint has a stylistic set that turns it off: `ss01` silent
letters, `ss02` reduced vowels, `ss03` stress. The French font uses the same
numbers, plus `ss04` and `ss05` for its own hints. Each set is one lookup
after the six passes that maps its hint's glyphs back to plain letters, so
the other hints don't change. In CSS it's `font-feature-settings: "ss03"`.
The font names each set ("No stress hints") for apps that list stylistic
sets by name. The demo page has a switch for each, and so does the browser
extension. *Measured*: every tenth `verify.py` text (16,736), with each set
and with all three, comes out right in HarfBuzz and Core Text, and
`demo/check_switches.py` sees each switch remove its color, and only its
color, in WebKit.

## Next steps

- **Faster matching.** Profile which pass costs most now that the word
  rules are keyed on two letters.
- **Words not in the 30,000**: the next 20,000 would add about 1.6% of
  running text (CMUdict lists fewer of them; many are names).
- **Check the alignments.** `review_sheet.py` builds a review page: the 500
  most frequent words and the noun/verb pairs drawn in the font, with their
  pronunciations in IPA, each to be marked right or wrong with a note. The
  published page keeps the verdicts (with the hints judged) for reading back
  and turning into alignment rules or per-word fixes. The alignment was only
  spot-checked so far.
- **More context for noun/verb pairs.** The font itself sees only the word
  right before, so *then record it* and *rose to record levels* (an
  adjective after *to*) aren't decided right, and adjectives in between
  (*the new record*) block the cue. Markers from a tagger fix this:
  `markers/annotate.py` decides 99.6% of pair words in the English EWT
  treebank, 98.7% of them right, where the cues decide 37.5%. The font
  could also learn longer cues (*the new*, *rose to*) from a treebank.
- **Design.** Reduced vowels are now blue rather than gray, so the three
  hints differ in hue. Further options: vowel colors by sound behind a
  stylistic set, like ESL color-vowel charts.
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
