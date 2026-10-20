#!/usr/bin/env python3
"""Align French spellings with their Lexique pronunciations, letter by letter.

    python french/align.py french/data/Lexique383.tsv --h-aspire french/data/h_aspire.txt --out french/lexicon

Lexique 3.83 gives each spelling one pronunciation per part of speech, in its
own one-character phoneme alphabet (`°` schwa, `@ 5 § 1` the nasal vowels).
Each word is cut into graphemes (a letter, or a listed group such as `eau`,
`ou`, `an`, `ch`, `gn`, `ill`) and each grapheme is given 0 to 3 phonemes;
the costs are learned by hard EM, as for English. From the alignment each
letter gets a hint: `x` silent, `n` part of a nasal vowel (`an`, `on`,
`ain`), `r` a schwa (the "e caduc" of `petit`, which speakers often drop) in
a word of two or more vowels, `.` none.

- **Several pronunciations.** Pronunciations with under 5% of a word's
  frequency are dropped (`est` as "east"); the rest keep only the hints they
  agree on (`fils` keeps none of its `l` and `s`). Words whose final consonant
  is said in some uses and not in others (`plus`, `tous`, `six`) keep no hint
  on it (VARIABLE).
- **Verbs.** A word whose verb reading differs from its noun or adjective one
  (`président`: "ils président", "le président") gets both in
  `homographs.tsv`, for the font to pick from the word before it, if the
  noun reading is at least a fifth of the word's uses (else "le" in "je vais
  le porter" would pick the rare noun "porter").
- **Compounds.** Hyphen and apostrophe compounds Lexique lists, where they
  differ from their parts said alone (`peut-être`, whose `t` is said), go in
  `compounds.tsv`. A final consonant silent alone but said in the compound
  is a liaison, `L`, and the hyphen after it gets a tie, `T`.
- **Blocked liaison.** Words before which there is no liaison: those with an
  h aspiré (Wiktionary's list, `--h-aspire`), `onze`, `oui`, and words
  starting with y but `y` and `yeux`. They go in `blockers.txt`.

`words.tsv` has the most frequent words (wordfreq's ranking) that Lexique
has and that align: word, hints, pronunciation.
"""

import argparse
import csv
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

LETTERS = "abcdefghijklmnopqrstuvwxyzàâæçéèêëîïôœùûüÿ"
VOWEL_LETTERS = set("aeiouyàâæéèêëîïôœùûüÿ")
VOWELS = set("aeEioOuy29°@5§1")
NASALS = set("@5§1")
GRAPHEMES = {"eau", "au", "ai", "aî", "ei", "ou", "oû", "où", "oi", "oî", "oe", "oê", "eu", "eû", "œu", "ue",
             "oy", "an", "am", "en", "em", "in", "im", "yn", "ym", "on", "om", "un", "um", "ain", "aim", "ein", "eim",
             "ch", "ph", "th", "gn", "qu", "gu", "sc", "ck", "sch", "tch", "ng", "cq", "ill", "il"}
GRAPHEMES |= {c + c for c in "bcdfglmnprstz"}
CONSONANTS = {
    "b": "b p", "c": "k s g", "ç": "s", "d": "d t", "f": "f v", "g": "g Z k", "j": "Z", "k": "k", "l": "l j",
    "m": "m", "n": "n N", "p": "p", "q": "k", "r": "R", "s": "s z S", "t": "t s", "v": "v", "w": "w v",
    "x": "s z k", "z": "z s", "ch": "S k", "ph": "f", "th": "t", "gn": "N", "qu": "k", "gu": "g", "sc": "s",
    "ck": "k", "sch": "S", "ng": "G N", "cq": "k", "ll": "l j", "ill": "j", "il": "j",
}
PAIRS = {"x": ["ks", "gz"], "oi": ["wa"], "oî": ["wa"], "oe": ["wa"], "oê": ["wa"], "oy": ["waj"], "y": ["ij"],
         "cc": ["ks"], "qu": ["kw", "k8"], "gu": ["gw", "g8"], "j": ["dZ"], "ch": ["tS"], "tch": ["tS"],
         "gn": ["gn"], "ou": ["wa"], "ill": ["ij"], "ll": ["lj"], "u": ["8i"], "i": ["ij"], "ay": ["Ej", "ej"]}
VARIABLE = {"plus", "tous", "six", "dix", "huit", "cinq", "vingt", "but", "août", "donc", "fait", "os",
            "ours", "mœurs", "moeurs", "cerf", "exact", "ananas", "fils"}
NOT_PAIRS = {"est"}          # "east" would be read after "qui plus est"
# Elided forms (l', qu'): written before an apostrophe, all their letters said.
ELIDED = {"l", "d", "c", "j", "n", "s", "t", "m", "qu", "jusqu", "lorsqu", "puisqu", "quoiqu"}
EXTRA_BLOCKERS = {"onze", "onzième", "onzièmes", "oui", "ouistiti", "ouistitis", "uhlan", "uhlans"}
# In Wiktionary's category for another sense or a variant, but with an h muet:
# l'humeur, avant-hier.
NOT_BLOCKERS = {"hier", "humeur", "humeurs", "humus", "hindi", "hiatus", "hyper", "hum", "huma", "hume",
                "hilaire", "henry", "hem", "heu", "hou"}


def plausible(g, phones):
    """Whether grapheme `g` can spell `phones` (a string of Lexique phonemes)."""
    if not phones:
        return len(g) == 1
    if len(phones) > 1:
        return phones in PAIRS.get(g, ())
    if g == "ue":                    # accueil, orgueil
        return phones == "9"
    p = phones
    vowelish = all(c in VOWEL_LETTERS for c in g)
    nasal_grapheme = len(g) > 1 and g[-1] in "nm" and all(c in VOWEL_LETTERS for c in g[:-1])
    if p in NASALS:
        return nasal_grapheme or g == "en"
    if p in VOWELS:
        return vowelish
    if p == "j":
        return g in ("i", "ï", "y", "î", "il", "ill", "ll", "l")
    if p == "w":
        return g in ("o", "ou", "w", "u")
    if p == "8":
        return g in ("u", "ü")
    if g not in CONSONANTS and len(g) == 2 and g[0] == g[1]:
        g = g[0]
    return p in CONSONANTS.get(g, "").split()


def segmentations(word, cuts=()):
    """The graphemes starting at each position; none spans a cut (a
    compound's hyphen)."""
    n = len(word)
    nexts = [[] for _ in range(n + 1)]
    for i in range(n):
        for k in (1, 2, 3):
            g = word[i:i + k]
            if i + k <= n and (k == 1 or g in GRAPHEMES) and not any(i < c < i + k for c in cuts):
                nexts[i].append(g)
    return nexts


def align(word, phones, cost, cuts=()):
    """The cheapest alignment of `word` (letters only) with `phones`: a list
    of (grapheme, phonemes), or None. Of equally cheap ones, the one whose
    silent letters end its parts, as French spelling has them: each phoneme
    goes to the latest part that can say it (*sous-sol*: sou-s, then s-o-l)
    and within it to the earliest letter (*ils content*: con-t, then e-n-t)."""
    nexts = segmentations(word, cuts)
    n, m = len(word), len(phones)
    starts = [0] + sorted(cuts)
    part = [sum(1 for s in starts[1:] if s <= i) for i in range(n + 1)]

    def placement(i, k):             # the tie-break: lower is better
        return k * (1000 * (len(starts) - part[i]) + i - starts[part[i]])
    best = {(0, 0): (0.0, 0, None)}
    for i in range(n + 1):
        for j in range(m + 1):
            if (i, j) not in best or i == n:
                continue
            c0, t0, _ = best[(i, j)]
            for g in nexts[i]:
                for k in (0, 1, 2, 3):
                    if j + k > m:
                        continue
                    ph = phones[j:j + k]
                    c = cost(g, ph)
                    if c is None:
                        continue
                    key, cand = (i + len(g), j + k), (c0 + c, t0 + placement(i, k))
                    if key not in best or cand[0] < best[key][0] - 1e-9 or (
                            cand[0] < best[key][0] + 1e-9 and cand[1] < best[key][1]):
                        best[key] = (*cand, (i, j, g, k))
    if (n, m) not in best:
        return None
    out, key = [], (n, m)
    while key != (0, 0):
        i, j, g, k = best[key][2]
        out.append((g, phones[j:j + k]))
        key = (i, j)
    return out[::-1]


def hints(alignment):
    """One hint per letter."""
    poly = sum(1 for _, ph in alignment for p in ph if p in VOWELS) >= 2
    out = []
    for g, ph in alignment:
        if not ph:
            h = "x"
        elif ph in NASALS and g[-1] in "nm":
            h = "n"
        elif poly and ph == "°":
            h = "r"
        else:
            h = "."
        out += [h] * len(g)
    return "".join(out)


def agree(hint_strings):
    return "".join(cs[0] if len(set(cs)) == 1 else "." for cs in zip(*hint_strings))


def learn(entries, rounds=6):
    """Hard EM over (word, [phones]): align, count, re-cost, repeat."""
    def cost(g, ph):
        return 1.0 if plausible(g, ph) else None
    for _ in range(rounds):
        counts, totals = Counter(), Counter()
        for word, prons in entries:
            for phones in prons:
                a = align(word, phones, cost)
                for g, ph in a or ():
                    counts[(g, ph)] += 1
                    totals[g] += 1
        table = {k: -math.log((v + 0.1) / (totals[k[0]] + 1)) for k, v in counts.items()}

        def cost(g, ph, table=table):
            if not plausible(g, ph):
                return None
            return table.get((g, ph), 12.0) + (0.0 if len(g) > 1 else 0.5)
    return cost


def read_lexique(path):
    """spelling -> [(phonemes, part of speech, frequency per million, lemma)]."""
    out = defaultdict(list)
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            freq = float(r["freqfilms2"] or 0) + float(r["freqlivres"] or 0)
            out[r["ortho"]].append((r["phon"], r["cgram"], freq, r["lemme"]))
    return out


def common(entries, share=0.05):
    """The pronunciations with at least `share` of the entries' frequency."""
    by_phon = Counter()
    for phon, _, freq, _ in entries:
        by_phon[phon] += freq
    total = sum(by_phon.values())
    if not total:
        return list(by_phon)
    return [p for p, f in by_phon.items() if f >= share * total]


def lookup(lexique, word):
    """Lexique writes œ as oe."""
    return lexique.get(word) or lexique.get(word.replace("œ", "oe"), [])


class Hinter:
    def __init__(self, cost):
        self.cost = cost

    def word(self, word, phons, cuts=()):
        """The agreed hints of `word` over `phons`, or None if none aligns."""
        aligned = [a for a in (align(word, p, self.cost, cuts) for p in phons) if a]
        if not aligned:
            return None
        h = agree([hints(a) for a in aligned])
        if word in VARIABLE and h[-1] != ".":
            h = h[:-1] + "."
        return h


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("lexique")
    ap.add_argument("--h-aspire", required=True, help="Wiktionary's words with an h aspiré, one per line")
    ap.add_argument("--words", type=int, default=30000)
    ap.add_argument("--compound-freq", type=float, default=1.0, help="per million, films and books")
    ap.add_argument("--out", required=True)
    ap.add_argument("--show", type=int, default=0)
    args = ap.parse_args()
    import wordfreq
    lexique = read_lexique(args.lexique)
    alpha = [w for w in wordfreq.top_n_list("fr", 400000) if re.fullmatch(f"[{LETTERS}]+", w)]
    ranked = [w for w in alpha if lookup(lexique, w)]
    cost = learn([(w, common(lookup(lexique, w))) for w in ranked[:args.words]])
    hinter = Hinter(cost)
    rows, failed, homographs = [], [], []
    for w in ranked:
        if len(rows) == args.words:
            break
        entries = lookup(lexique, w)
        if w in ELIDED:
            rows.append((w, "." * len(w), common(lookup(lexique, w + "'") or entries)[0]))
            continue
        h = hinter.word(w, common(entries))
        if h is None or len(w) < 2 and w not in ("a", "à", "y", "ô"):
            failed.append(w)
            continue
        rows.append((w, h, common(entries)[0]))
        verbs = [e for e in entries if e[1] in ("VER", "AUX")]
        others = [e for e in entries if e[1] not in ("VER", "AUX")]
        noun_share = sum(e[2] for e in others) / (sum(e[2] for e in entries) or 1)
        if verbs and others and w not in NOT_PAIRS and noun_share >= 0.2:
            noun, verb = hinter.word(w, common(others)), hinter.word(w, common(verbs))
            if noun and verb and noun != verb:
                homographs.append((w, noun, verb))
    listed = {w: h for w, h, _ in rows}
    pair_words = {w for w, *_ in homographs}
    compounds = []
    for c, entries in lexique.items():
        parts = re.split(r"([-'])", c)
        if len(parts) < 3 or sum(e[2] for e in entries) < args.compound_freq or "" in parts:
            continue
        if not all(re.fullmatch(f"[{LETTERS}]+", p) for p in parts[::2]):
            continue
        cuts = [sum(len(p) for p in parts[:k:2]) for k in range(2, len(parts), 2)]
        h = hinter.word("".join(parts[::2]), common(entries), cuts)
        if h is None:
            continue
        out, alone, i = [], [], 0
        for k, p in enumerate(parts):
            if k % 2:
                out.append("T" if out[-1][-1] == "L" else ".")      # only after a hyphen
                alone.append(".")
                continue
            ph, i = h[i:i + len(p)], i + len(p)
            own = listed.get(p, "." * len(p))
            if k + 1 < len(parts) and parts[k + 1] == "-" and own[-1] == "x" and ph[-1] == "." and p[-1] in "stdxzn":
                ph = ph[:-1] + "L"
            out.append(ph)
            alone.append(own)
        if "".join(out) != "".join(alone) and not any(p in pair_words for p in parts[::2]):
            compounds.append((c, "".join(out)))
    aspire = {l.strip() for l in open(args.h_aspire, encoding="utf-8") if l.strip()}
    blockers = sorted(w for w in listed if w not in NOT_BLOCKERS and (
        w in aspire or w in EXTRA_BLOCKERS or w.startswith("y") and w not in ("y", "yeux")))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "words.tsv", "w", encoding="utf-8") as f:
        for w, h, p in rows:
            f.write(f"{w}\t{h}\t{p}\n")
    with open(out / "homographs.tsv", "w", encoding="utf-8") as f:
        for w, noun, verb in homographs:
            f.write(f"{w}\t{noun}\t{verb}\n")
    with open(out / "compounds.tsv", "w", encoding="utf-8") as f:
        for c, h in sorted(compounds):
            f.write(f"{c}\t{h}\n")
    with open(out / "blockers.txt", "w", encoding="utf-8") as f:
        f.write("# Words before which there is no liaison: h aspiré (Wiktionary), onze, oui, y- words.\n")
        f.write("".join(w + "\n" for w in blockers))
    total = sum(wordfreq.word_frequency(w, "fr") for w in alpha)
    covered = sum(wordfreq.word_frequency(w, "fr") for w, *_ in rows)
    print(f"wrote {out}: {len(rows)} words, {covered / total:.1%} of running text; {len(failed)} skipped, "
          f"e.g. {' '.join(failed[:25])}; {len(homographs)} verb/noun pairs, {len(compounds)} compounds, "
          f"{len(blockers)} blockers")
    for w, h, p in rows[:args.show]:
        a = align(w, p, cost)
        print(f"  {w:14} {h:14} {' '.join(g + '=' + (ph or '_') for g, ph in a)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
