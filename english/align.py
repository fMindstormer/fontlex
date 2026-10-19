#!/usr/bin/env python3
"""Align English spellings with their CMUdict pronunciations, letter by letter.

    python english/align.py CMUDICT --words 5000 --out english/lexicon

Each word is cut into graphemes (a letter, or a listed digraph such as `sh`,
`ee`, `er`) and each grapheme is given 0, 1 or 2 phonemes; the costs of
grapheme-phoneme pairs are learned by hard EM over the words, starting from
which letters plausibly spell which sounds. From the alignment each letter
gets a hint: `S` the vowel with primary stress, `r` a reduced vowel (the
schwa of AH0, ER0, or IH0 and UH0), `x` silent, `.` none. Stress and reduced
vowels are only marked in words of two or more syllables. A word with several
pronunciations keeps only the hints all of them agree on; pronunciations that
don't align (abbreviations: `us` as U.S.) are left out.

The output `words.tsv` has the most frequent words (wordfreq's ranking) that
CMUdict has and that align: word, hints, pronunciation.
"""

import argparse
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

VOWELS = {"AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY", "IH", "IY", "OW", "OY", "UH", "UW"}
REDUCED = {"AH0", "ER0", "IH0", "UH0"}
VOWEL_LETTERS = set("aeiouy")
# Graphemes longer than a letter. Doubled consonants count as one grapheme;
# `gh` is listed for `tough` (F), and is silent in `night` like any letter;
# `ti`, `ci`, `si` spell "sh" in `nation`, `musician`, `vision`.
DIGRAPHS = {"ph", "th", "sh", "ch", "ck", "ng", "wh", "gh", "qu", "tch", "dg", "kn", "wr", "ti", "ci", "si",
            "ee", "ea", "oa", "ai", "ay", "oo", "ou", "ow", "oi", "oy", "au", "aw", "ew", "ie", "ei",
            "ey", "ue", "ui", "eu", "er", "ir", "ur", "ar", "or", "ear", "our", "ough", "augh", "eigh"}
DIGRAPHS |= {c + c for c in "bcdfgklmnprstvz"}
DIGRAPHS -= {"kn", "wr"}      # these are a silent letter and a sound, as taught

# Which consonant letters can spell which consonant phonemes (as one phoneme).
CONSONANTS = {
    "b": "B", "c": "K S CH SH", "d": "D JH T", "f": "F V", "g": "G JH ZH", "h": "HH", "j": "JH Y HH",
    "k": "K", "l": "L", "m": "M", "n": "N NG", "p": "P", "q": "K", "r": "R", "s": "S Z SH ZH",
    "t": "T SH CH DH TH", "v": "V", "w": "W", "x": "Z", "z": "Z S ZH TS", "y": "Y",
}
# Pairs of phonemes one grapheme can spell.
PAIRS = {
    "x": ["K S", "G Z", "K SH", "G ZH"], "u": ["Y UW", "Y UH", "Y AH", "W AH", "W IH", "W EH", "W AY"],
    "o": ["W AH", "W AA"], "eu": ["Y UW"], "ew": ["Y UW"], "ue": ["Y UW"], "qu": ["K W"],
    "l": ["AH L"], "m": ["AH M"], "n": ["AH N"], "r": ["ER R"], "i": ["Y AH", "Y UW", "IY AH", "AY AH"],
    "e": ["Y UW", "IY AH"], "a": ["EY AH", "AH L"], "y": ["W AY"],
    "j": ["HH"], "c": ["K S", "T S"], "z": ["T S"], "ai": ["AY AH"], "wh": ["HH W"],
}


def plausible(g, phones):
    """Whether grapheme `g` can spell `phones` (a tuple of 0-2 phonemes,
    without stress digits), before learning."""
    if not phones:
        return len(g) == 1 or g == "gh"
    key = " ".join(phones)
    if len(phones) == 2:
        if key in PAIRS.get(g, ()):
            return True
        if g in ("ar", "or", "our", "ear", "er", "ir", "ur") and phones[1] == "R" and phones[0] in VOWELS:
            return True
        return False
    p = phones[0]
    vowelish = any(c in VOWEL_LETTERS for c in g) or g in ("w",)
    if p in VOWELS:
        if p == "ER" and (g in ("r", "er", "ir", "ur", "ar", "or", "ear", "our") or g.endswith("r")):
            return True
        if g in ("w",):
            return False
        return vowelish and not any(c in "rlmnbdfgkpstvz" for c in g)
    if p == "Y" and g in ("i", "e", "y", "j"):
        return True
    if p == "W" and g in ("u", "o", "w", "wh"):
        return True
    if g in CONSONANTS:
        return p in CONSONANTS[g].split()
    if len(g) == 2 and g[0] == g[1]:
        return p in CONSONANTS.get(g[0], "").split()
    table = {"ph": "F", "th": "TH DH", "sh": "SH", "ch": "CH K SH", "ck": "K", "ng": "NG N", "wh": "W HH",
             "gh": "F G", "tch": "CH", "dg": "JH", "ti": "SH CH", "ci": "SH", "si": "SH ZH"}
    return p in table.get(g, "").split()


def segmentations(word):
    """Grapheme sequences that spell `word`, lazily (a DAG over positions)."""
    n = len(word)
    nexts = [[] for _ in range(n + 1)]
    for i in range(n):
        for k in (1, 2, 3, 4):
            g = word[i:i + k]
            if i + k <= n and (k == 1 or g in DIGRAPHS):
                nexts[i].append(g)
    return nexts


def align(word, phones, cost):
    """The cheapest alignment: a list of (grapheme, phoneme tuple), or None."""
    letters = word.replace("'", "")
    bare = [re.sub(r"\d", "", p) for p in phones]
    nexts = segmentations(letters)
    n, m = len(letters), len(phones)
    best = {(0, 0): (0.0, None)}
    for i in range(n + 1):
        for j in range(m + 1):
            if (i, j) not in best or i == n:
                continue
            c0 = best[(i, j)][0]
            for g in nexts[i]:
                for k in (0, 1, 2):
                    if j + k > m:
                        continue
                    ph = tuple(bare[j:j + k])
                    c = cost(g, ph)
                    if c is None:
                        continue
                    key = (i + len(g), j + k)
                    if key not in best or c0 + c < best[key][0]:
                        best[key] = (c0 + c, (i, j, g, k))
    if (n, m) not in best:
        return None
    out, key = [], (n, m)
    while key != (0, 0):
        i, j, g, k = best[key][1]
        out.append((g, tuple(phones[j:j + k])))
        key = (i, j)
    return out[::-1]


def hints(word, alignment):
    """One hint per character of `word` (apostrophes get `.`)."""
    phones = [p for _, ph in alignment for p in ph]
    poly = sum(1 for p in phones if p[-1].isdigit()) >= 2
    out = []
    for g, ph in alignment:
        if not ph:
            h = "x"
        elif poly and any(p.endswith("1") for p in ph) and any(c in VOWEL_LETTERS for c in g):
            h = "S"
        elif poly and len(ph) == 1 and ph[0] in REDUCED and any(c in VOWEL_LETTERS for c in g):
            h = "r"
        else:
            h = "."
        out += [h] * len(g)
    letters = iter(out)
    return "".join("." if c == "'" else next(letters) for c in word)


def agree(hint_strings):
    """The hints every pronunciation gives."""
    return "".join(cs[0] if len(set(cs)) == 1 else "." for cs in zip(*hint_strings))


def learn(entries, rounds=6):
    """Hard EM: align with the current costs, re-estimate, repeat."""
    def prior(g, ph):
        return 1.0 if plausible(g, tuple(re.sub(r"\d", "", p) for p in ph)) else None
    cost = lambda g, ph: prior(g, ph)
    for _ in range(rounds):
        counts, totals = Counter(), Counter()
        for word, prons in entries:
            for phones in prons:
                a = align(word, phones, cost)
                if a:
                    for g, ph in a:
                        counts[(g, ph)] += 1
                        totals[g] += 1
        table = {k: -math.log((v + 0.1) / (totals[k[0]] + 1)) for k, v in counts.items()}

        def cost(g, ph, table=table):
            bare = tuple(re.sub(r"\d", "", p) for p in ph)
            if not plausible(g, bare):
                return None
            # Prefer a listed digraph to a letter and a silent letter.
            return table.get((g, bare), 12.0) + (0.0 if len(g) > 1 else 0.5)
        # The table is keyed by bare phonemes.
        counts2 = Counter()
        for (g, ph), v in counts.items():
            counts2[(g, tuple(re.sub(r"\d", "", p) for p in ph))] += v
        tot2 = Counter()
        for (g, _), v in counts2.items():
            tot2[g] += v
        table.clear()
        table.update({k: -math.log((v + 0.1) / (tot2[k[0]] + 1)) for k, v in counts2.items()})
    return cost


def read_cmudict(path):
    prons = defaultdict(list)
    for line in open(path, encoding="utf-8"):
        line = line.split("#")[0].strip()
        if line:
            w, *ph = line.split()
            prons[re.sub(r"\(\d+\)$", "", w)].append(ph)
    return prons


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmudict")
    ap.add_argument("--words", type=int, default=5000)
    ap.add_argument("--out", required=True)
    ap.add_argument("--show", type=int, default=0, help="print this many alignments")
    args = ap.parse_args()
    import wordfreq
    prons = read_cmudict(args.cmudict)
    ranked = [w for w in wordfreq.top_n_list("en", 200000)
              if re.fullmatch(r"[a-z]+(?:'[a-z]+)?", w) and w in prons]
    train = [(w, prons[w]) for w in ranked[:30000]]
    cost = learn(train)
    rows, failed = [], []
    for w in ranked:
        if len(rows) == args.words:
            break
        aligned = [a for a in (align(w, p, cost) for p in prons[w]) if a]
        if not aligned or len(w.replace("'", "")) < 2 and w not in ("a", "i"):
            failed.append(w)
            continue
        rows.append((w, agree([hints(w, a) for a in aligned]), " ".join(prons[w][0]), aligned[0]))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "words.tsv", "w", encoding="utf-8") as f:
        for w, h, p, _ in rows:
            f.write(f"{w}\t{h}\t{p}\n")
    print(f"wrote {out / 'words.tsv'}: {len(rows)} words; {len(failed)} skipped (no alignment), "
          f"e.g. {' '.join(failed[:20])}")
    for w, h, p, a in rows[:args.show]:
        print(f"  {w:14} {h:14} {' '.join(g + '=' + ('-'.join(ph) or '_') for g, ph in a)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
