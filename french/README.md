# Fontlex French: pronunciation hints in a font

The English hint font's sibling, for learners of French. **Silent letters**
fade: the *t* of *petit*, the *s* of *temps*, the *ent* of *ils parlent*.
The letters of a **nasal vowel** are violet (*an*, *on*, *ain*, *un*), so
*bon* and *bonne*, *fin* and *fine* look different. A **schwa** that speakers
often drop (the "e caduc" of *samedi* and *petit*) is blue. A **liaison**, a
final consonant said before the next word's vowel, is bold and green, with a
green tie under the space or hyphen: *les‿amis*, *nous‿avons*, *un‿homme*,
*vont-ils*, *peut-être*. Where a verb reads differently from the noun or
adjective it is spelled like, the word before it decides: *le président*,
*ils président* (silent *ent*), or an invisible marker after the word does
([markers/](../markers/README.md)). French has no word stress to mark. The text
stays as typed; copy it and you get plain letters. `french/demo.html` is a
text box in the font.

It knows the 30,000 most frequent French words that Lexique 3.83 has, 94.3%
of running text by wordfreq's counts (proper nouns are mostly missing), and
129 compounds. Other words are drawn plain.

## Results

*Measured* with `verify.py`, which compares each letter's glyph with the
lexicon's hint for it, and each space's and hyphen's tie:

| Text | Checked | Right, HarfBuzz | Right, Core Text |
|---|---|---|---|
| Every listed word alone, capitalized, in capitals, in punctuation, in a sentence and after *l'*; every compound alone, capitalized, in a sentence, with a curly apostrophe and with a letter added (must fall back to its parts); every verb/noun pair after each cue word, after another word and after two spaces, and before each reading marker (also after a cue for the other reading); a marker after other words; every liaison trigger before vowels, h muet, h aspiré, *onze*, *oui*, *yeux* and consonants, after a hyphen and an apostrophe, and with two spaces; numbers ending a longer one (*vingt-trois ans*); 400 words ending in s, x, t, d or z before each inverted clitic; listed words inside longer words and made-up words (must stay plain) | 202,190 | 202,190 | 202,190 |
| Width with a marker: each pair as wide as after a cue for the same reading, every 50th other word as wide as without one | 1,262 | 1,262 | 1,262 |
| The demo's sample (`sample.txt`) | 16 lines | 16 | 16 |

The font has 6,248 glyphs (letters' first-letter variants, as in the English
font, plus "blocking" variants for the first letters of words that block
liaison) and 26,337 word and compound rules; 240 KB as WOFF2. On the
sample's lines it shapes in 0.27 ms a line in HarfBuzz and 0.19 ms in Core
Text, against 0.11 and 0.14 ms for plain Noto Sans (best of five; lines of
about 120 characters). In WebKit the hints and ties render in both palettes.

## Where the hints come from

`align.py` aligns each spelling with its Lexique pronunciation, like the
English aligner:

- **Units of spelling.** Single letters, plus listed groups: vowel teams
  (*eau*, *ou*, *ai*, *oi*, *eu*, *œu*), nasal vowels (*an*, *en*, *in*,
  *on*, *un*, *ain*, *ein*, with *m* too), consonant groups (*ch*, *ph*, *gn*,
  *qu*, *gu*, *ill*, doubled consonants). Each takes 0 to 3 phonemes (*oy* is
  "waj"), with costs learned by hard EM over the 30,000 words.
- **Ties.** Where two alignments cost the same, the silent letters go at the
  end of each part of the word, as in French spelling: *choses* says its
  first *s* and not its last, *ils content* says *con-t* and drops *ent*, and
  *sous-sol* drops the *s* of *sous*, not of *sol*. Without this rule, 367
  words had their silent letters on the wrong side of a sound they spell.
- **Hints from the alignment.** A group that spells nothing is silent. A
  group of vowel and *n* or *m* that spells a nasal vowel is nasal. One that
  spells Lexique's schwa (°), in a word of two or more vowels, is a schwa;
  so *le* and *de* stay plain, *petit* and *monsieur* don't.
- **Several pronunciations.** Lexique has one per part of speech. Those with
  under 5% of the word's uses are dropped (*est* as "east", *fils* as
  "threads"); the rest keep only the hints they agree on. Words whose final
  consonant comes and goes with use (*plus*, *tous*, *six*, *dix*, *huit*,
  *août*, *but*) keep no hint on it.
- **Verb/noun pairs** (`lexicon/homographs.tsv`, 32): words whose verb reading
  has different hints, mostly *-ent* (*président*, *content*, *excellent*,
  *couvent*) but also *sens*, *fier*, *bus*. Only where the noun or adjective
  reading is at least a fifth of the uses: otherwise *le*, a noun cue, would
  pick the rare noun in *je vais le porter*. Cues (`lexicon/cues.tsv`):
  determiners and *très*, *si*, *est* for the noun or adjective; subject
  pronouns, *qui*, *ne* and *se* for the verb.
- **Compounds** (`lexicon/compounds.tsv`): Lexique's hyphen and apostrophe
  compounds whose hints differ from their parts said alone, aligned with no
  letter group across the hyphen. A final consonant silent alone but said in
  the compound is a liaison: *peut-être*, *c'est-à-dire*, *avant-hier*,
  *quelques-uns*.

How the font decides liaison:

- **Triggers** (`lexicon/liaison.txt`, 42 words): only where liaison is
  obligatory. These are determiners (*les*, *des*, *mon*, *un*, *aucun*,
  *quelques*, *plusieurs*), pronouns before the verb (*nous*, *vous*, *ils*,
  *elles*, *on*, *en*), short prepositions and adverbs (*dans*, *chez*,
  *sans*, *sous*, *très*, *tout*, *quand*) and numbers (*deux*, *trois*,
  *six*, *dix*, *vingt*, *cent*). After a hyphen a trigger is an inverted
  subject, and there is no liaison (*ont-ils eu*), unless it is a number
  ending a longer one: *vingt-trois‿ans*, *quatre-vingts‿euros*.
- **Inversion**: a final s, x, t, d or z before a hyphen and *il(s)*,
  *elle(s)*, *on*, *en* or *y* (*vont-ils*, *prend-il*, *allons-y*).
- **What it links to**: a vowel or an h, except before the words in
  `lexicon/blockers.txt`, 196 of them:
  - words with an h aspiré, from French Wiktionary's category (*héros*,
    *haricot*, *haut*, *hasard*, *huit*), less 15 that are in it for another
    sense or variant but take an h muet (*hier*, *humeur*);
  - *onze*, *oui*;
  - words starting with y, but *y* and *yeux*.

## How the font does it

Eight GSUB passes, built by `frfont.py` on Noto Sans and Noto Sans Bold:

1. Right to left, each word's last letter becomes a "final" variant. A word
   is letters; an apostrophe or a hyphen ends one, so *l'homme* is *l* and
   *homme*.
2. Left to right, each word's first letter becomes an "initial" variant
   keyed on the second letter.
3. Cue words mark their last letter as a noun or verb cue; blockers turn
   their first letter into a "blocking" initial, which liaison doesn't link to.
4. A verb/noun pair right before a reading marker (U+FE00 noun or
   adjective, U+FE01 verb; [markers/](../markers/README.md)), or else right
   after a cue and one space, gets that reading's hints. A reading with no hints turns the first letter plain, so pass 7
   leaves the word alone.
5. A trigger, not after a hyphen unless it is a number, then one space and
   a vowel or h that isn't blocking: the trigger's last letter becomes its
   bold liaison glyph and the space a tie. The next word's first letter can be any variant, hinted or
   not; after a space it is always a first letter.
6. Inversion, the same for a final s, x, t, d or z, a hyphen and a clitic.
7. One context rule per compound (tried first) and per listed word with
   hints, from an initial letter to a final one, case ignored. The liaison
   glyph still counts as its word's final letter; hint lookups don't cover
   it, so a word's own "silent" hint doesn't undo the liaison.
8. The variants that no rule claimed go back to plain letters.

Each kind of hint has a stylistic set that turns it off, numbered as in the
English font: `ss01` silent letters, `ss02` schwas, `ss04` nasal vowels,
`ss05` liaisons with their ties. Each set is one lookup after the eight
passes, so the other hints don't change. The demo page and the browser
extension have a switch for each. *Measured*: every tenth `verify.py` text
(19,889), with each set and with all four, comes out right in HarfBuzz and
Core Text, and `demo/check_switches.py` sees each switch remove its color,
and only its color, in WebKit.

Word hints depend only on their word, so they survive soft wrapping, as in
the English font. A liaison looks one space ahead, and *measured* in WebKit
it doesn't survive a soft line break between its two words: WebKit shapes
each line on its own, so *les* at a line's end shows a silent *s*.

## Limits

- **Optional liaison isn't shown**: *c'est‿un*, *ils sont‿arrivés*,
  *pas‿encore* are left to the reader, as are adjective and noun (*petit‿ami*,
  *grand‿homme*). The font can't tell *grand homme* from *grand et fort*.
  **Enchaînement**, a pronounced consonant gliding into the next vowel
  (*avec‿elle*), isn't marked either.
- **An h the lexicon lacks** counts as an h muet, so an unlisted word with an
  h aspiré gets a wrong liaison. So does a letter's name (*un h*).
- **Cue words are a guess.** *le* and *la* are also object pronouns: *je le
  sens* gets the noun reading of *sens*. *les*, which is as often a pronoun,
  is no cue. A marker overrides the cue, and `markers/annotate.py` adds
  markers with a tagger where no cue decides (98.6% right on the French GSD
  treebank, with fr_core_news_lg).
- **Lexique's pronunciation** is one standard French one, and has errors:
  *diocèses* with a said final s.
- **Proper nouns**: Lexique has few. *France* is drawn plain, and
  *États-Unis* gets no liaison.

## Reproducing

```sh
pip install -r english/requirements.txt
french/fetch_data.sh french/data                         # Lexique 3.83 and Wiktionary's h aspiré list
python french/align.py french/data/Lexique383.tsv --h-aspire french/data/h_aspire.txt --out french/lexicon    # checked in
python french/frfont.py --base fonts/NotoSans-Regular.ttf --bold fonts/NotoSans-Bold.ttf --out build
python french/verify.py build/Fontlex-French.ttf --shaper harfbuzz --shaper coretext --corpus french/sample.txt
python french/build_page.py --font build/Fontlex-French.ttf --out french/demo.html
python french/review_sheet.py french/data/Lexique383.tsv --font build/Fontlex-French.woff2 --out review.html
```

`./check.sh french` runs the font, test and page steps, and checks the
page's hint switches in WebKit.

## Review

The hints have been checked against Lexique, not yet by a fluent speaker.
`review_sheet.py` builds a page for that: the 500 most frequent words, the
verb/noun pairs (each after a cue the font reads: *le président*, *ils
président*), every liaison trigger in a phrase (*quatre-vingts‿ans*) and
every blocker, and the compounds. Each is drawn in the font with its
pronunciation in IPA, to be marked right or wrong with a note. The
published page keeps the verdicts, with what was judged, to read back and
turn into fixes. Building it already found two: the tie rule above, and
liaison after numbers that end a longer one.

## Licenses

The lexicon (`lexicon/words.tsv`, `homographs.tsv`, `compounds.tsv`) is
derived from Lexique 3.83 (New, Pallier et al., www.lexique.org) under CC
BY-SA 4.0, and `lexicon/blockers.txt` in part from French Wiktionary's h
aspiré category (CC BY-SA 4.0). So the lexicon files and the font built from
them are shared under CC BY-SA 4.0 too, with attribution. The words' choice
and order follow wordfreq's ranking (data CC BY-SA 4.0). `cues.tsv`,
`liaison.txt` and `sample.txt` are this project's. The base fonts are Noto
Sans under the SIL Open Font License (`../fonts/OFL-NotoSans.txt`).
