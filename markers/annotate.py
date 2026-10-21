#!/usr/bin/env python3
"""Mark each noun/verb pair in a text with the reading a tagger picks.

    python markers/annotate.py en < text.txt > marked.txt
    python markers/annotate.py fr --model fr_core_news_lg < texte.txt > marque.txt
    python markers/annotate.py en --strip < marked.txt
    python markers/annotate.py en --score en_ewt-ud-test.conllu

The English and French hint fonts read an invisible character right after
a word of homographs.tsv: U+FE00 (variation selector 1) picks the noun
reading, U+FE01 (variation selector 2) the verb reading, whatever word comes
before. Other fonts draw nothing for them. This script puts them in with a
spaCy tagger (`pip install spacy`, then `python -m spacy download` the
model). Nouns, proper nouns and, in French, adjectives (*un homme
content*) take the noun reading; verbs and auxiliaries the verb reading.

English marks every pair word, since the tagger is right more often than
the cue words. French leaves a word alone when a cue word just before it
already decides (*le président*, *ils président*), since the cues there are
never wrong in the treebank, and marks the rest.

--score reads a Universal Dependencies treebank and prints how often the
cue rule, the tagger and this script's choice decide a pair word and how
often they're right, against the treebank's parts of speech.
"""

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKS = {"noun": "︀", "verb": "︁"}
LANGS = {"en": ("english", "en_core_web_sm", False), "fr": ("french", "fr_core_news_lg", True)}


def read_lexicon(lang):
    d = ROOT / LANGS[lang][0] / "lexicon"

    def rows(name):
        for line in open(d / name, encoding="utf-8"):
            if line.strip() and not line.startswith("#"):
                yield line.rstrip("\n").split("\t")
    return {r[0] for r in rows("homographs.tsv")}, {r[0]: r[1] for r in rows("cues.tsv")}


def kind_of(pos, lang):
    """The reading a part of speech (UD or spaCy tag) takes, or None."""
    kinds = {"NOUN": "noun", "PROPN": "noun", "VERB": "verb", "AUX": "verb"}
    if lang == "fr":
        kinds["ADJ"] = "noun"
    return kinds.get(pos)


class Annotator:
    def __init__(self, lang, model=None):
        import spacy
        self.lang = lang
        self.pairs, self.cues = read_lexicon(lang)
        self.keep_cues = LANGS[lang][2]
        # What continues a word in the font: a letter, or in English an
        # apostrophe and a letter (French ends a word at an apostrophe).
        self.joins = r"[^\W\d_]" if lang == "fr" else r"[^\W\d_]|['\u2019][^\W\d_]"
        self.nlp = spacy.load(model or LANGS[lang][1])

    def cue(self, words, spaces, i):
        """The reading the font's cue rule gives word i, or None: the word
        before it is a cue, with one space between."""
        if i and spaces[i - 1]:
            return self.cues.get(words[i - 1].lower().replace("’", "'"))
        return None

    def choose(self, words, spaces, pos, i):
        """The marker word i gets ("noun", "verb"), or None."""
        if words[i].lower() not in self.pairs:
            return None
        if self.keep_cues and self.cue(words, spaces, i):
            return None
        return kind_of(pos[i], self.lang)

    def annotate(self, text):
        text = strip(text)
        doc = self.nlp(text)
        words, spaces, pos = [t.text for t in doc], [t.whitespace_ == " " for t in doc], [t.pos_ for t in doc]
        out, at = [], 0
        for i, t in enumerate(doc):
            kind = self.choose(words, spaces, pos, i)
            end = t.idx + len(t.text)
            # Only where the font's word ends too: not inside "record's".
            if kind and not re.match(self.joins, text[end:end + 2]):
                out += [text[at:end], MARKS[kind]]
                at = end
        return "".join(out) + text[at:]

    def score(self, conllu):
        from spacy.tokens import Doc
        stats = Counter()
        for words, spaces, gold in read_conllu(conllu):
            hits = [i for i, w in enumerate(words) if w.lower() in self.pairs and kind_of(gold[i], self.lang)]
            if not hits:
                continue
            doc = self.nlp(Doc(self.nlp.vocab, words=words, spaces=spaces))
            pos = [t.pos_ for t in doc]
            for i in hits:
                want = kind_of(gold[i], self.lang)
                stats["words"] += 1
                cue = self.cue(words, spaces, i)
                mark = self.choose(words, spaces, pos, i)
                font = mark or cue          # what the font draws: a marker beats a cue
                for name, got in (("cue words", cue), ("tagger", kind_of(pos[i], self.lang)), ("this script", font)):
                    if got:
                        stats[name, "decides"] += 1
                        stats[name, "right"] += got == want
        n = stats["words"]
        print(f"{n} pair words with a noun or verb tag in {Path(conllu).name}")
        for name in ("cue words", "tagger", "this script"):
            d = stats[name, "decides"]
            print(f"  {name:12} decide {d} ({d / max(1, n):.1%}), right {stats[name, 'right']} "
                  f"({stats[name, 'right'] / max(1, d):.1%} of those)")


def read_conllu(path):
    """(words, space after each, UPOS) per sentence; multiword tokens are
    left out, so French "du" is "de" "le"."""
    words, spaces, tags = [], [], []
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if not line:
            if words:
                yield words, spaces, tags
            words, spaces, tags = [], [], []
        elif not line.startswith("#"):
            f = line.split("\t")
            if re.fullmatch(r"\d+", f[0]):
                words.append(f[1])
                spaces.append("SpaceAfter=No" not in f[9])
                tags.append(f[3])
    if words:
        yield words, spaces, tags


def strip(text):
    return re.sub("[︀︁]", "", text)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("lang", choices=sorted(LANGS))
    ap.add_argument("--model", help=f"a spaCy model (default {', '.join(f'{k}: {v[1]}' for k, v in LANGS.items())})")
    ap.add_argument("--strip", action="store_true", help="remove the markers instead")
    ap.add_argument("--score", metavar="CONLLU", help="score against a UD treebank instead")
    args = ap.parse_args()
    if args.strip:
        sys.stdout.write(strip(sys.stdin.read()))
        return 0
    annotator = Annotator(args.lang, args.model)
    if args.score:
        annotator.score(args.score)
        return 0
    sys.stdout.write(annotator.annotate(sys.stdin.read()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
