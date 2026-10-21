# Reading markers

A hint font can't know whether *record* is a noun or a verb. It only sees
the word before it, so *the record* and *to record* work but *a new
record* doesn't. Something that reads the whole sentence can decide, such
as a tagger, an editor or a teacher. That tool puts an invisible character
right after the word, and the English and French fonts turn it into that
reading's hints:

| Character | Reading | Example |
|---|---|---|
| U+FE00 (variation selector 1) | noun (in French, also adjective) | *a new record*`U+FE00` is REcord |
| U+FE01 (variation selector 2) | verb | *they record*`U+FE01` is reCORD |

- **A marker beats a cue.** *the record*`U+FE01` is reCORD.
- **Put one only right after a pair word,** as `annotate.py` does. After
  another word that ends a word, it does nothing. Elsewhere the engines
  differ: HarfBuzz (Chrome, Firefox) looks past a marker it doesn't match,
  and Core Text (Safari) treats it as a break. So *les*`U+FE00` *amis*
  keeps its liaison in HarfBuzz and loses it in Core Text.
- **Other fonts don't show them.** Variation selectors are
  default-ignorable characters: they have no width and draw nothing.
  They survive copy and paste.
- **How the font reads them.** The fonts map both characters to empty,
  zero-width glyphs, and pass 4 (pairs) tries a rule for the marker before
  the rules for cue words.

The meaning of the first and second selector is this project's own
convention, not a Unicode standard. Unicode registers variation sequences
only for particular base characters, and a letter followed by U+FE00 isn't
one of them. Text marked this way is meant for these fonts.

## Marking text with a tagger

`annotate.py` marks a text with spaCy's tagger:

```sh
pip install spacy
python -m spacy download en_core_web_sm      # French: fr_core_news_lg
python markers/annotate.py en < text.txt > marked.txt
python markers/annotate.py en --strip < marked.txt    # remove the markers
```

Nouns and proper nouns take the noun reading, and so do adjectives in
French (*un homme content*). Verbs and auxiliaries take the verb reading.

## How often it's right

`annotate.py --score` compares the font's cue rule, the tagger and the
script's choice with the gold parts of speech of two Universal Dependencies
treebanks: English EWT and French GSD, train and test files together. spaCy's
models were trained on other corpora (OntoNotes 5; UD French Sequoia and
WikiNER).

| | Pair words | Cue words decide | right | Tagger decides | right | `annotate.py` decides | right |
|---|---|---|---|---|---|---|---|
| English (en_core_web_sm) | 528 | 37.5% | 96.5% | 99.2% | 98.7% | 99.6% | 98.7% |
| French (fr_core_news_lg) | 296 | 59.5% | 100% | 100% | 97.0% | 100% | 98.6% |

So the script uses the two sources differently:
- **English:** the tagger is right more often than the cue words, so the
  script marks every pair word, and a marker beats a cue.
- **French:** the cue words are never wrong in GSD, so the script leaves a
  word with a cue before it unmarked and tags only the rest.

French's small model (fr_core_news_sm) is right only 93.3% of the time. It
reads adjectives such as *violent* and *influent* as verbs.

The treebanks have few verb readings: 113 in English, 7 in French. GSD is
mostly encyclopedia text, so the French verb scores rest on very few words.
