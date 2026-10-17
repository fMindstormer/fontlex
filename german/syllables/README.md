# German syllables for learning to read

A font that colors each word's syllables in turn, blue and red, the way many
German primary schools teach reading (the syllable method, *Silbenmethode*).
It works as you type, in any app that renders color fonts with OpenType
features, and it prints: worksheets made in a word processor keep their
colors in PDFs and on paper. `german/syllables/demo.html` is a page with the
font and its measured accuracy.

The font is compiled from `specs/german-syllables.yaml`.

## Results

On words a first reader meets, syllabified by hand in reading syllables
(`words-*.txt`), shaped through the compiled font; HarfBuzz and Core Text
give identical results:

| Word list | Words split exactly right |
|---|---|
| 120 words, labeled before any testing (`words-heldout.txt`) | 117 (97.5%) |
| 198 words used while writing the reading rules (`words-dev.txt`) | 195 |

The held-out misses are *Ko-a-la*, *U-ni-form* and *A-pri-ko-se*, which the
font splits *Koa-la*, *Uni-form* and *Apri-ko-se*.

## How it decides

1. **TeX's German hyphenation patterns** (36,709 of them, by the
   Deutschsprachige Trennmustermannschaft), run with Liang's algorithm: each
   pattern gives levels to the gaps it covers, the highest level at a gap
   wins, and odd levels are breaks.
2. **No break after a word's first letter or before its last** (`min_left`
   and `min_right` of 2, as in TeX). Without these the patterns produce
   *Pfer-d* and *S-tern*.
3. **Reading syllables** (`reading.pat.txt`, written by
   `make_reading_patterns.py`), at a higher level so they win: a lone first
   vowel before a consonant and a vowel is its own syllable (*A-bend*, *O-ma*,
   *I-gel*), except where the start looks like a prefix (*An-ord-nung*);
   likewise before *ch*, *ck* and *sch* (*E-cke*); and vowels in hiatus at the
   end of a word are split (*Ra-di-o*, *Ka-ka-o*). Hyphenation never splits
   off single letters, so the patterns alone can't do this.

## How the font does it

- Mark each word's first and last letter.
- Give every other letter a variant that also records the letter before it.
  Pattern rules are filed under the letter they decide and the letter before
  it, and a shaper only tries the rules filed under its glyph, so each glyph
  tries about twenty rules instead of thousands.
- Run the patterns: one lookup of chaining contextual format 2 subtables
  (655 of them for 38,117 patterns), highest level first, so the first rule
  that applies at a gap is the one Liang's algorithm picks.
- Color: a word starts blue, and each break switches color.

The font has 12,801 glyphs, is 378 KB as WOFF2, and compiles in about 13
seconds. Shaping takes 67 ms per 1,000 words in HarfBuzz and 76 ms in Core
Text (the plain font: 1–2 ms), about 7 ms for a 100-word paragraph, which is
fine for typing.

## Limits

- Vowels next to each other inside a word stay together where they are two
  syllables (*Koa-la*, *Thea-ter*); splitting them would break English loan
  words like *Team*. Final *-ie* stays together (*Fa-mi-lie*), since it is
  usually a long *i* (*Bie-ne*, *Knie*).
- A first vowel before a consonant cluster stays attached (*Apri-ko-se*), as
  does one whose start looks like a prefix (*Uni-form*).
- Compounds the patterns don't know can miss a break (*Mit-tag-essen*).

## Reproducing

```sh
python german/syllables/make_reading_patterns.py > german/syllables/reading.pat.txt
python fontlex.py specs/german-syllables.yaml --base fonts/JetBrainsMono-Regular.ttf --out build
python test_fontlex.py specs/german-syllables.yaml build/Fontlex-German-Syllables.ttf
python german/syllables/evaluate.py build/Fontlex-German-Syllables.ttf german/syllables/words-heldout.txt
python german/syllables/build_page.py --out german/syllables/demo.html
```

## Licenses

`hyph-de-1996.pat.txt` is from the hyph-utf8 package, under the MIT license;
its notice is in `hyph-de-1996.LICENSE.txt`. The reading-syllable patterns and
the word lists were written for this project. The base font, JetBrains Mono,
is under the SIL Open Font License.
