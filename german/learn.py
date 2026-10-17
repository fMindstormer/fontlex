#!/usr/bin/env python3
"""Learn German noun-gender rules for Fontlex from gender-annotated treebanks.

Writes two TSV files for specs/german.yaml:

- suffixes.tsv: word endings and the gender they signal. In the font the
  longest listed ending of a capitalized word decides its color, so a rule is
  kept only where it changes what a shorter one would say (`none` stops a
  shorter rule where the ending is unreliable).
- words.tsv: whole words the endings get wrong: frequent nouns, and `none` for
  frequent capitalized words that aren't reliably one gender (names,
  sentence-initial words, nouns of two genders).

    python german/learn.py german/data/hdt/de_hdt-ud-train-*.conllu --out german/lexicon \
        [--dictionary german/data/german-nouns/nouns.csv]

With --dictionary (German Wiktionary's nouns, from github.com/gambolputty/
german-nouns), dictionary forms also vote on endings, and decide words the
treebank doesn't know or gets wrong. Word entries are then ranked by
frequency (needs the wordfreq package) and capped at --max-words.
"""

import argparse
import collections
import csv
import re
import sys
from pathlib import Path

GENDERS = {"Masc": "masc", "Fem": "fem", "Neut": "neut"}
NAME = "name"        # a proper noun
OTHER = "other"      # any other word that isn't a noun
# The letters specs/german.yaml puts in words; anything else ends a word.
LETTERS = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")


def tokens(path):
    """(form, upos, feats) for each syntactic word of a CoNLL-U file."""
    for line in open(path, encoding="utf-8"):
        if line[:1] in ("#", "\n", ""):
            continue
        cols = line.rstrip("\n").split("\t")
        if "-" in cols[0] or "." in cols[0]:
            continue
        feats = dict(f.split("=", 1) for f in cols[5].split("|")) if cols[5] != "_" else {}
        yield cols[1], cols[3], feats


def font_word(form):
    """The letter run the font colors for a token: its last one."""
    runs = LETTERS.findall(form)
    return runs[-1] if runs else None


def read_dictionary(path):
    """Word form -> genders of the nouns it is a form of; and forms with no
    gender of their own: plural-only nouns (Eltern, Leute) and adjectives
    used as nouns, whose gender follows the person meant (der/die
    Beschäftigte). Names and multi-word entries are left out."""
    short = {"m": "masc", "f": "fem", "n": "neut"}
    skip = {"Toponym", "Vorname", "Nachname", "Wortverbindung"}
    genders: dict[str, set[str]] = collections.defaultdict(set)
    genderless: set[str] = set()
    for row in csv.DictReader(open(path, encoding="utf-8")):
        pos = set(row["pos"].split(","))
        if "Substantiv" not in pos or pos & skip:
            continue
        gs = {short[v] for k, v in row.items() if k.startswith("genus") and v in short}
        if "adjektivische Deklination" in pos:
            gs = set()
        for k, v in row.items():
            if v and k not in ("lemma", "pos") and not k.startswith("genus") \
                    and LETTERS.fullmatch(v) and v[0].isupper():
                if gs:
                    genders[v] |= gs
                else:
                    genderless.add(v)
    # A form that is also a form of a noun with a gender (Daten, of Datum)
    # is decided by that noun, and by the treebank.
    return genders, genderless - set(genders)


def label(form, upos, feats):
    """A token's evidence: its gender, NAME, OTHER, or None to ignore it: a
    noun whose gender is missing, or a foreign word (X), which in HDT's tech
    news is often a noun German uses with a gender (Internet, Software)."""
    if upos == "NOUN":
        return GENDERS.get(feats.get("Gender"))
    if upos == "X":
        return None
    return NAME if upos == "PROPN" else OTHER


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("conllu", nargs="+", help="training treebank files")
    ap.add_argument("--out", required=True, help="directory for words.tsv and suffixes.tsv")
    # Defaults: the best coverage at the best accuracy on HDT dev (99.8%).
    ap.add_argument("--min-types", type=int, default=3, help="word types an ending needs to become a rule")
    ap.add_argument("--purity", type=float, default=0.95, help="share of an ending's types that must agree")
    ap.add_argument("--min-len", type=int, default=2)
    ap.add_argument("--max-len", type=int, default=14)
    ap.add_argument("--word-purity", type=float, default=0.9, help="share of a word's noun tokens that must agree")
    ap.add_argument("--noun-share", type=float, default=0.5, help="share of a word's tokens that must be nouns")
    ap.add_argument("--min-abstain", type=int, default=3, help="tokens before an unreliable word is listed as none")
    ap.add_argument("--dictionary", help="German Wiktionary nouns (german-nouns nouns.csv)")
    ap.add_argument("--max-words", type=int, default=20000, help="keep this many word entries, most frequent "
                    "first (0: all)")
    args = ap.parse_args()
    dict_genders, genderless = read_dictionary(args.dictionary) if args.dictionary else ({}, set())

    # Per capitalized word: token counts of each label.
    counts: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for path in args.conllu:
        for form, upos, feats in tokens(path):
            w = font_word(form)
            lab = label(form, upos, feats)
            if w and w[0].isupper() and lab:
                counts[w][lab] += 1

    # Endings, over word types (each type votes once, with its majority label).
    endings: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    votes = []
    for w, c in counts.items():
        lab, n = c.most_common(1)[0]
        if n * 2 > sum(c.values()):
            votes.append((w, lab))
    for w, gs in dict_genders.items():
        if len(gs) == 1:
            votes.append((w, next(iter(gs))))
    votes += [(w, OTHER) for w in genderless]
    for w, lab in votes:
        for k in range(args.min_len, min(args.max_len, len(w) - 1) + 1):
            x = w[-k:]
            if x.islower():
                endings[x][lab] += 1

    def own_label(x):
        c = endings[x]
        total = sum(c.values())
        if total < args.min_types:
            return None                     # too rare to say anything
        lab, n = c.most_common(1)[0]
        if lab in GENDERS.values() and n / total >= args.purity:
            return lab
        return "none"                       # unreliable, or mostly not nouns

    rules: dict[str, str] = {}

    def predicted(x):
        """What the listed rules say for a word ending in x (longest wins)."""
        for k in range(len(x), 0, -1):
            if x[-k:] in rules:
                return rules[x[-k:]]
        return "none"

    for x in sorted(endings, key=len):
        lab = own_label(x)
        if lab is not None and lab != predicted(x[1:]):
            rules[x] = lab

    def suffix_says(w):
        return predicted(w) if w else "none"

    def corpus_says(w):
        """The treebank's verdict: a gender, "none" if it saw the word often
        but not as nouns of one gender, or None if it barely saw it."""
        c = counts.get(w)
        if not c:
            return None
        total = sum(c.values())
        genders = collections.Counter({g: c[g] for g in GENDERS.values() if c[g]})
        nouns = sum(genders.values())
        lab, n = genders.most_common(1)[0] if genders else (None, 0)
        if nouns >= args.noun_share * total and n >= args.word_purity * nouns:
            return lab
        return "none" if total >= args.min_abstain else None

    def decide(w):
        if len(w) == 1:
            return "none"                   # a letter: "das A", or an initial in a name
        corpus = corpus_says(w)
        gs = dict_genders.get(w)
        if gs is None:
            return "none" if w in genderless else corpus
        c = counts.get(w, collections.Counter())
        total = sum(c.values())
        nouns = sum(c[g] for g in GENDERS.values())
        if total >= 10 and nouns < 0.2 * total:
            return "none"                   # a dictionary noun, but nearly always a name here
        if total >= 5 and c[OTHER] >= 0.3 * total:
            return "none"                   # often a capitalized function word: sentence-initial "Aus"
        if len(gs) == 1:
            g = next(iter(gs))
            return "none" if corpus in GENDERS.values() and corpus != g else g
        return corpus if corpus in GENDERS.values() else "none"

    words: dict[str, str] = {}
    for w in set(counts) | set(dict_genders) | genderless:
        want = decide(w)
        if want is not None and want != suffix_says(w):
            words[w] = want
    needed = len(words)
    if args.max_words and len(words) > args.max_words:
        from wordfreq import get_frequency_dict
        freq = get_frequency_dict("de")
        keep = sorted(words, key=lambda w: (-freq.get(w.lower(), 0), -sum(counts.get(w, {}).values()), w))
        words = {w: words[w] for w in keep[:args.max_words]}

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    header = ("# Generated by german/learn.py from " + ", ".join(Path(p).name for p in args.conllu)
              + f"\n# min-types {args.min_types}, purity {args.purity}, word-purity {args.word_purity},"
              f" noun-share {args.noun_share}, min-abstain {args.min_abstain}, max-words {args.max_words}\n"
              "# Derived from Universal Dependencies annotations (CC BY-SA 4.0)"
              + (" and German Wiktionary nouns via github.com/gambolputty/german-nouns (CC BY-SA 4.0)"
                 if args.dictionary else "") + ".\n")
    for name, table in (("suffixes.tsv", rules), ("words.tsv", words)):
        lines = [f"{k}\t{v}" for k, v in sorted(table.items())]
        (out / name).write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    by = lambda t: dict(collections.Counter(t.values()))  # noqa: E731
    print(f"{len(counts):,} capitalized word types, {len(dict_genders):,} dictionary forms; "
          f"{len(rules):,} ending rules {by(rules)}; {len(words):,} word entries {by(words)}"
          + (f" (of {needed:,} needed)" if needed != len(words) else ""), file=sys.stderr)


if __name__ == "__main__":
    main()
