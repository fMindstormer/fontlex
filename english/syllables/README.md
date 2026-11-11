# English syllables for learning to read

A font that colors each word's syllables in turn, blue and red, as the German
syllable font does for German (`german/syllables/`): *lit-tle ti-ger*,
*rab-bit*, *ta-ble*, *el-e-phant*. It works as you type, in any app that
renders color fonts with OpenType features.

The font is compiled from `specs/english-syllables.yaml`, on Noto Sans. This
is a first version: no demo page yet, and no review by teachers.

## Where the syllables come from

The Moby Hyphenation List (Grady Ward, public domain) splits about 160,000
English words the way dictionaries do: a vowel that ends a syllable is long
(*ti-ger*), a short one keeps the consonant after it (*cab-in*), and a
consonant before *-le* starts the last syllable (*ta-ble*). `patgen.py` adds
what it lacks among the 30,000 most frequent words (`english/lexicon/`, with
CMUdict pronunciations):

- one-syllable words, unsplit: the list has no *is*, *to* or *of*, and splits
  a few from capitalized entries (*I-s*);
- inflected forms of listed words, split as the stem is, with or without a
  syllable for the ending (*start-ed*, *play-ing*, *chang-es*,
  *com-pa-nies*), where that gives as many syllables as the pronunciation.

That makes 167,316 words, 27,536 of them among the 30,000 most frequent.
`patgen.py` then trains Liang patterns on them, as TeX's patgen does: level
by level, odd levels adding breaks and even levels taking wrong ones back.
The patterns also guess at words they weren't trained on.

## Results

Splits counted against the word list (fidelity to the source, not a
teacher's judgment), through `fontlex.syllable_breaks`, which the font
follows exactly:

| Words | Split exactly right |
|---|---|
| Frequent words, patterns trained on all words (the font) | 27,444 of 27,536 (99.7%) |
| Frequent words held out of training (every tenth word) | 2,505 of 2,790 (89.8%) |
| All words held out of training | 14,126 of 16,833 (83.9%) |

So a frequent word comes out as the list splits it, and a word the list
lacks is right about five times in six. The font colors exactly what the
patterns say: 5,000 random lines and the spec's examples give no differences
in HarfBuzz and Core Text.

The font has 3,941 glyphs and 47,741 patterns, is 365 KB as WOFF2, and
compiles in about 45 seconds. Shaping takes about 220 ms per 1,000 words in
HarfBuzz and in Core Text (Noto Sans alone: 2–3 ms), about 22 ms for a
100-word paragraph: fine for typing, slow for long documents. Fewer patterns
would be faster; the trade against accuracy on unseen words is unmeasured.

## Limits

- Dictionary hyphenation isn't always the spoken syllable: the list has
  *eve-ry* (and *eve-ry-one*), where a reader says *ev-er-y* or *ev-ry*.
- The list's splits stand where the pronunciation has a different count of
  syllables (2% of frequent words); only one-syllable words are corrected.
- Words written with an apostrophe (*don't*) are split at it, like any
  character that isn't a letter.

## Reproducing

```sh
english/syllables/fetch_data.sh
python english/syllables/patgen.py english/syllables/data/mhyph.txt \
    --lexicon english/lexicon/words.tsv                  # the held-out numbers
python english/syllables/patgen.py english/syllables/data/mhyph.txt \
    --lexicon english/lexicon/words.tsv --all --out english/syllables/syllables.pat.txt
python fontlex.py specs/english-syllables.yaml --base fonts/NotoSans-Regular.ttf --out build
python test_fontlex.py specs/english-syllables.yaml build/Fontlex-English-Syllables.ttf \
    --base fonts/NotoSans-Regular.ttf --shaper harfbuzz --shaper coretext
```

## Licenses

The Moby Hyphenation List is in the public domain; the patterns trained on it
(`syllables.pat.txt`) are part of this project, under its MIT license. The
pronunciations come from CMUdict (`english/lexicon/CMUDICT-LICENSE.txt`). The
base font, Noto Sans, is under the SIL Open Font License.
