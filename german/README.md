# German noun genders: a learner prototype

A font that colors German nouns by grammatical gender in any text box:
**der** blue, **die** red, **das** green. Words it isn't sure about stay in
the text color. `german/demo.html` is a self-contained page with the font and
its measured accuracy; open it in Chrome, Firefox or Safari.

The font is compiled from `specs/german.yaml`, whose word and ending lists
are learned by `german/learn.py` from a gender-annotated treebank and German
Wiktionary.

## Results

Scored by shaping text through the compiled font (HarfBuzz and Core Text give
identical results), reading the color of each noun's last letter, and
comparing it with the dataset's gender label.

| Text | Nouns colored | Colored nouns right | All colored words right |
|---|---|---|---|
| 199 everyday nouns, labeled by hand (`core_nouns.tsv`) | 97.5% | 100% | 100% |
| HDT test: tech news 1996–2001, same source as training (64,819 nouns) | 97.1% | 99.5% | 95.2% |
| PUD: Wikipedia (4,080 nouns) | 90.1% | 98.5% | 93.9% |

The last column also counts words that aren't nouns in the dataset but were
colored; most of those are nouns the dataset tags as foreign words
(*Internet*, *Software*, *Cookies*) or names that are also nouns (*Sommer*).

The labels have errors of their own, especially on plurals, whose articles
don't show gender. Checking every wrong color on PUD by hand (55):

| | Count |
|---|---|
| Font right, label wrong or given the compound's gender (*Polonium* das, *Display* das, *Routine* in *Routine-Ultraschall*) | 35 |
| Both genders accepted (*der/das Liter*, *Fakten* of *der Fakt* or *das Faktum*) | 3 |
| Font wrong | 17 |

So on Wikipedia text the font is wrong about 1 in 200 nouns it colors, not 1
in 70. The 17: adjectives and participles used as nouns that the dictionary
doesn't list (*Lebenden*, *Reichen*), forms shared by two nouns (*Steuern* of
*die Steuer* or *das Steuer*, *an Bord*, *zu Rate*, *Teilen*), names,
abbreviations and English words (*Ms*, *Medal*), two endings learned from
noisy labels (*Geschäftspraktiken*), and a typo in the text (*Anworten*).

## How it decides

- **Only capitalized words.** German capitalizes nouns, so the DFA has three
  states: between words, in a capitalized word, in another word.
- **Whole words, then endings.** A listed word decides first. Otherwise the
  longest listed ending does: *-ung* makes *Zeitung* feminine, and a compound
  takes the gender of its last part (*der Haustürschlüssel*). The font builds
  this from three lookups: one marks the first letter of every word, one rule
  per word or ending marks the word's last letter (a word's rule starts at
  the marked first letter, so *Sprung* can't match inside *AbSprung*), and a
  reverse chaining lookup, which runs right to left, spreads the color back
  to the start of the word.
- **Abstaining.** Words of two genders (*der/die See*), plural-only nouns
  (*Großeltern*), adjectives used as nouns (*der/die Vorsitzende*), single
  letters, and capitalized function words that often start sentences (*Aus*)
  are listed as `none`, which leaves them uncolored.

The font has 12,292 ending rules and 20,000 words (the most frequent of
49,910 the endings get wrong), in 2,483 glyphs and 239 KB of WOFF2. It
compiles in about 3 seconds.

## How the lists are learned

`learn.py` reads the treebank's training split (HDT parts A and B, 3.7M
tokens) and, with `--dictionary`, German Wiktionary's nouns:

- **Evidence per capitalized word:** noun tokens with a gender, proper-noun
  tokens, and other tokens. Nouns without a gender label and foreign words
  (UPOS X) are ignored: in HDT's tech news, X is often a German noun.
- **Dictionary:** each form's genders from all nouns it is a form of.
  Plural-only nouns and adjectives used as nouns have no gender of their own;
  forms only those have are listed as `none`.
- **Endings:** every word type and dictionary form votes for its gender on
  each of its endings; an ending becomes a rule if at least 3 types end in it
  and 95% of them agree, and only if it changes what a shorter rule says.
- **Words:** a word is decided by the dictionary if it lists one gender
  (unless the treebank clearly says another, or nearly always sees it as a
  name or as a non-noun), otherwise by the treebank (90% of its noun tokens
  must agree, and at least half its tokens must be nouns). Only words the
  endings get wrong are kept, ranked by frequency (`wordfreq`) and capped at
  20,000.

The thresholds were chosen on HDT's dev split (best coverage at the best
accuracy). The test sets were scored at the end; the adjective rule above was
narrowed after looking at PUD's errors, and checked on dev.

## Reproducing

```sh
pip install -r requirements.txt -r german/requirements.txt
german/fetch_ud.sh german/data
curl -fsSL -o german/data/nouns.csv \
    https://raw.githubusercontent.com/gambolputty/german-nouns/main/german_nouns/nouns.csv
python german/learn.py german/data/hdt/de_hdt-ud-train-*.conllu --dictionary german/data/nouns.csv \
    --out german/lexicon
python fontlex.py specs/german.yaml --base fonts/JetBrainsMono-Regular.ttf --out build
python german/evaluate.py specs/german.yaml build/Fontlex-German.ttf german/data/hdt/de_hdt-ud-test.conllu
python german/build_page.py --out german/demo.html \
    --test german/data/hdt/de_hdt-ud-test.conllu --test german/data/pud/de_pud-ud-test.conllu
```

`german/lexicon/` is checked in, so the font builds without downloading
anything; `evaluate.py` also takes word lists like `core_nouns.tsv`.

## Data and licenses

- Universal Dependencies German HDT (annotations CC BY-SA 4.0; text for
  academic use) and PUD (CC BY-SA 3.0). Only the word lists derived from them
  are in this repository.
- German Wiktionary nouns via github.com/gambolputty/german-nouns (CC BY-SA 4.0).
- Word frequencies from `wordfreq` (data CC BY-SA 4.0), used for ranking only.

The lists in `german/lexicon/` are derived from CC BY-SA 4.0 data, so they,
and fonts built from them, need attribution and the same license when shared;
the base font, JetBrains Mono, is under the SIL Open Font License.
