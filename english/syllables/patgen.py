#!/usr/bin/env python3
"""Train Liang patterns that split English words into syllables.

    python english/syllables/patgen.py english/syllables/data/mhyph.txt \\
        --lexicon english/lexicon/words.tsv --all --out english/syllables/syllables.pat.txt

The words and their syllables come from the Moby Hyphenation List (public
domain; english/syllables/fetch_data.sh), which splits words the way
dictionaries do: a vowel that ends a syllable is long (ti-ger), a short one
keeps the consonant after it (cab-in), and a consonant before -le starts the
last syllable (ta-ble). Every tenth word, picked by a hash of the word, is
held out of training to measure the patterns on words they haven't seen.

Patterns are found as Liang's patgen finds them: level by level, odd levels
adding breaks and even levels taking wrong ones back, and at each level the
letter windows around a gap that do more good than harm are kept as
patterns. fontlex.syllable_breaks applies them, as the font does.
"""

import argparse
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
from fontlex import syllable_breaks  # noqa: E402

BREAK = "•"     # Moby's syllable mark, byte 0xA5 in Mac Roman

# Per level: window lengths, weights of good and bad, and the score a window
# needs. Odd levels add breaks, even levels take wrong ones back.
LEVELS = [
    (range(2, 6), 1, 2, 4),
    (range(2, 7), 1, 1, 3),
    (range(3, 8), 1, 2, 2),
    (range(3, 8), 1, 1, 2),
    (range(4, 9), 1, 1, 1),
    (range(4, 9), 1, 1, 1),
    (range(5, 10), 1, 1, 1),
]


def load(path) -> dict[str, frozenset[int]]:
    """Word (lowercase) -> indices k where a syllable starts at word[k]. Single
    words of the letters a-z only. Where a word is listed more than once
    (Pol-ish and pol-ish, over and o-ver, rec-ord and re-cord), a lowercase
    entry wins over a capitalized one, one with breaks over one without (the
    list has some words unsplit as well), and then the first listed."""
    found: dict[str, list] = defaultdict(list)
    for line in Path(path).read_bytes().decode("mac_roman").splitlines():
        entry = line.strip()
        plain = entry.replace(BREAK, "")
        if not plain.isascii() or not plain.isalpha():
            continue
        breaks, k = set(), 0
        for ch in entry:
            if ch == BREAK:
                breaks.add(k)
            else:
                k += 1
        found[plain.lower()].append((not plain.islower(), not breaks, len(found[plain.lower()]),
                                     frozenset(breaks)))
    return {word: min(entries)[3] for word, entries in found.items()}


def syllables_said(phones: str) -> int:
    """Syllables in a CMUdict pronunciation: its vowels, which carry a stress digit."""
    return sum(p[-1].isdigit() for p in phones.split())


def inflected(word: str, words) -> list[frozenset[int]]:
    """Ways to split `word` as an inflected form of a listed word: as the
    stem is split, with or without a new syllable for the ending (box-es,
    want-ed, look-ing, mak-ing, run-ning, com-pa-nies, stud-ied)."""
    out = []

    def stem(s, *new):
        b = words.get(s)
        if b is not None:
            out.append(b)
            out.extend(b | {k} for k in new if 0 < k < len(word))

    if word.endswith("ies") or word.endswith("ied"):
        stem(word[:-3] + "y")
    if word.endswith("s"):
        stem(word[:-1], len(word) - 2)          # games, chang-es
    if word.endswith("es"):
        stem(word[:-2], len(word) - 2)          # box-es
    if word.endswith("ed"):
        stem(word[:-2], len(word) - 2)          # called, want-ed
        stem(word[:-1], len(word) - 2)          # based, cre-at-ed
        if len(word) > 4 and word[-3] == word[-4]:
            stem(word[:-3], len(word) - 3)      # stopped, ad-mit-ted
    if word.endswith("ing"):
        stem(word[:-3], len(word) - 3)          # look-ing
        stem(word[:-3] + "e", len(word) - 3)    # mak-ing
        if len(word) > 5 and word[-4] == word[-5]:
            stem(word[:-4], len(word) - 4)      # run-ning
    return out


def augment(words, lexicon) -> dict[str, frozenset[int]]:
    """Frequent words (`lexicon`: english/lexicon/words.tsv, with CMUdict
    pronunciations) to add to the list or correct in it: one-syllable words,
    unsplit (the list splits a few, from capitalized entries such as I-s),
    and inflected forms the list lacks, where a split as the stem is split
    has as many syllables as the pronunciation."""
    added = {}
    for line in Path(lexicon).read_text(encoding="utf-8").splitlines():
        word, _, phones = line.split("\t")[:3]
        word = word.lower()
        if word in added or not (word.isascii() and word.isalpha()):
            continue
        n = syllables_said(phones)
        if n == 1:
            if words.get(word) != frozenset():
                added[word] = frozenset()
            continue
        if word in words:
            continue
        for b in inflected(word, words):
            if len(b) + 1 == n:
                added[word] = b
                break
    return added


def held_out(word: str) -> bool:
    return zlib.crc32(word.encode()) % 10 == 0


def train(words: dict[str, frozenset[int]], levels=LEVELS, log=print) -> dict[str, list[int]]:
    """Liang patterns (letters with "." at word edges -> a level per gap)."""
    items = [("." + w + ".", frozenset(k + 1 for k in b)) for w, b in words.items()]
    values = {w: [0] * (len(w) + 1) for w, _ in items}
    patterns: dict[str, list[int]] = {}
    for level, (lengths, good_w, bad_w, need) in enumerate(levels, 1):
        adds = level % 2 == 1
        for n in lengths:
            good, bad = Counter(), Counter()
            for w, brk in items:
                vals = values[w]
                # gaps between the word's letters: before dotted index 2 .. len - 2
                for g in range(2, len(w) - 1):
                    if (vals[g] % 2 == 1) == adds:
                        continue             # this level can't change the gap
                    count = good if (g in brk) == adds else bad
                    for start in range(max(0, g - n), min(g, len(w) - n) + 1):
                        count[w[start:start + n], g - start] += 1
            chosen = defaultdict(list)
            for key, gc in good.items():
                if gc * good_w - bad[key] * bad_w >= need:
                    chosen[key[0]].append(key[1])
            for letters, offsets in chosen.items():
                levels_of = patterns.setdefault(letters, [0] * (len(letters) + 1))
                for off in offsets:
                    levels_of[off] = max(levels_of[off], level)
            for w, _ in items:
                vals = values[w]
                for start in range(len(w) - n + 1):
                    for off in chosen.get(w[start:start + n], ()):
                        vals[start + off] = max(vals[start + off], level)
            if log:
                log(f"level {level}, length {n}: {sum(map(len, chosen.values())):,} patterns")
    return patterns


def score(words, patterns) -> tuple[int, int, int, int, int]:
    """Words exactly right, words, and breaks right, found and wanted."""
    longest = max(map(len, patterns))
    right = hit = found = wanted = 0
    for w, want in words.items():
        got = set(syllable_breaks(w, patterns, longest))
        right += got == want
        hit += len(got & want)
        found += len(got)
        wanted += len(want)
    return right, len(words), hit, found, wanted


def report(label, words, patterns):
    right, n, hit, found, wanted = score(words, patterns)
    print(f"{label}: {right:,} of {n:,} words exactly right ({right / n:.1%}); "
          f"breaks: precision {hit / max(found, 1):.1%}, recall {hit / max(wanted, 1):.1%}")


def write(patterns, path):
    lines = []
    for letters in sorted(patterns):
        levels = patterns[letters]
        if not any(levels):
            continue
        lines.append("".join((str(v) if v else "") + c for v, c in zip(levels, letters)) +
                     (str(levels[-1]) if levels[-1] else ""))
    Path(path).write_text("% Generated by english/syllables/patgen.py from the Moby Hyphenation List.\n"
                          + "\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(lines):,} patterns to {path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("moby", help="mhyph.txt")
    ap.add_argument("--lexicon", help="english/lexicon/words.tsv: the 30,000 most frequent words with "
                                      "their pronunciations, to add what the list lacks and to score")
    ap.add_argument("--out", help="pattern file to write")
    ap.add_argument("--all", action="store_true", help="train on every word, the held-out ones too")
    args = ap.parse_args()
    words = load(args.moby)
    common = set()
    if args.lexicon:
        added = augment(words, args.lexicon)
        print(f"{len(words):,} words listed; {sum(w not in words for w in added):,} frequent words added, "
              f"{sum(w in words for w in added):,} one-syllable words unsplit")
        words |= added
        common = {line.split("\t")[0].lower() for line in Path(args.lexicon).read_text(encoding="utf-8").splitlines()}
    test = {w: b for w, b in words.items() if held_out(w)}
    trainset = words if args.all else {w: b for w, b in words.items() if w not in test}
    print(f"training on {len(trainset):,} words")
    patterns = train(trainset)
    report("training words", trainset, patterns)
    if not args.all:
        report("held-out words", test, patterns)
        if common:
            report("frequent words, held out", {w: b for w, b in test.items() if w in common}, patterns)
    if common:
        report("frequent words", {w: b for w, b in words.items() if w in common}, patterns)
    if args.out:
        write(patterns, args.out)


if __name__ == "__main__":
    main()
