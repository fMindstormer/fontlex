#!/usr/bin/env python3
"""Compile the English pronunciation-hint font.

    python english/enfont.py --base fonts/NotoSans-Regular.ttf --bold fonts/NotoSans-Bold.ttf \\
        --lexicon english/lexicon/words.tsv --out build

Each listed word's letters are drawn with their hints (align.py): the
stressed vowel bold in the accent color, reduced vowels gray, silent letters
pale. Other text is drawn as the base font draws it. The passes:

1. Right to left: each word's last letter becomes its "final" variant (a
   word is letters, with apostrophes between letters: `don't`).
2. Left to right: each word's first letter becomes its "initial" variant
   (or "initial and final", for a one-letter word).
3. One context rule per listed word with hints, case-insensitive (glyph
   classes ignore case), from an initial letter to a final one, so it matches
   the whole word only. It applies a hint lookup at each hinted letter.
4. Initial and final variants that no rule claimed go back to plain letters.
"""

import argparse
import sys
from pathlib import Path

from fontTools.ttLib.tables import otTables as ot

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "markdown"))
import fontbuild as fb  # noqa: E402

LETTERS = "abcdefghijklmnopqrstuvwxyz"
APOSTROPHES = "'’"
HINTS = {"S": "stress", "r": "reduced", "x": "silent"}
PALETTES = {
    "light": {"stress": "#C2272D", "reduced": "#7D8597", "silent": "#C0C5CE"},
    "dark": {"stress": "#FF7B7B", "reduced": "#98A0B1", "silent": "#565D6B"},
}
FORMS = ("I", "F", "IF")      # initial, final, both
SUBTABLE_BYTES = 40000        # rules per subtable, under its 16-bit offsets


def coverage(glyphs, gid):
    cov = ot.Coverage()
    cov.glyphs = sorted(set(glyphs), key=gid)
    return cov


def read_lexicon(path):
    words = {}
    for line in open(path, encoding="utf-8"):
        word, hints, _ = line.rstrip("\n").split("\t")
        words[word] = hints
    return words


class EnglishFont:
    def __init__(self, base, bold):
        self.b = b = fb.FontBuilder(base)
        b.palettes = PALETTES
        b.import_style("b", bold)
        cmap = b.font.getBestCmap()
        self.letter = {}                 # glyph -> lowercase letter
        for c in LETTERS:
            for ch in (c, c.upper()):
                if ord(ch) in cmap:
                    self.letter[cmap[ord(ch)]] = c
        self.apostrophes = [cmap[ord(c)] for c in APOSTROPHES if ord(c) in cmap]
        self.plain = sorted(self.letter, key=b.gid)
        self.form = {}                   # (glyph, form) -> variant
        self.hinted = {}                 # (glyph, hint) -> hinted glyph
        for g in self.plain:
            for f in FORMS:
                self.form[(g, f)] = b.composite(f"{g}.w{f}", [(g, 0, 0)], b.advance(g))
            for h, entry in HINTS.items():
                body = fb.styled(g, "b") if h == "S" else g
                name = b.composite(f"{g}.h{h}", [(body, 0, 0)], b.advance(body))
                b.colr[name] = [(body, entry)]
                self.hinted[(g, h)] = name
            b.alias[g] = [self.form[(g, f)] for f in FORMS] + [self.hinted[(g, h)] for h in HINTS]

    def forms(self, *which):
        return [self.form[(g, f)] for g in self.plain for f in which]

    def build(self, words):
        b, gid = self.b, self.b.gid
        lookups, top = [], []

        def add(lk, is_top=True):
            lookups.append(lk)
            if is_top:
                top.append(len(lookups) - 1)
            return len(lookups) - 1

        letters, finals = self.plain, self.forms("F")
        # 1. Final letters, right to left: a letter followed by a letter (or
        # an apostrophe and a letter) stays; any other becomes final.
        subtables = []
        for ahead in ([letters + finals], [self.apostrophes, letters + finals], []):
            st = ot.ReverseChainSingleSubst()
            st.Format = 1
            st.Coverage = coverage(letters, gid)
            st.BacktrackCoverage = []
            st.LookAheadCoverage = [coverage(c, gid) for c in ahead]
            st.Substitute = [g if ahead else self.form[(g, "F")] for g in st.Coverage.glyphs]
            subtables.append(st)
        add(fb.lookup(8, subtables))
        # 2. Initial letters, left to right: a letter after a letter (or a
        # letter and an apostrophe) stays; any other becomes initial.
        to_initial = add(fb.lookup(1, [fb.single({**{g: self.form[(g, "I")] for g in letters},
                                                  **{self.form[(g, "F")]: self.form[(g, "IF")] for g in letters}})]),
                         is_top=False)
        word_glyphs = letters + self.forms(*FORMS)
        subtables = []
        for behind in ([word_glyphs], [self.apostrophes, word_glyphs], []):
            st = ot.ChainContextSubst()
            st.Format = 3
            st.BacktrackCoverage = [coverage(c, gid) for c in behind]
            st.InputCoverage = [coverage(letters + finals, gid)]
            st.LookAheadCoverage = []
            st.BacktrackGlyphCount, st.InputGlyphCount, st.LookAheadGlyphCount = len(behind), 1, 0
            st.SubstLookupRecord = []
            if not behind:
                r = ot.SubstLookupRecord()
                r.SequenceIndex, r.LookupListIndex = 0, to_initial
                st.SubstLookupRecord.append(r)
            st.SubstCount = len(st.SubstLookupRecord)
            subtables.append(st)
        add(fb.lookup(6, subtables))
        # 3. The words. Classes ignore case; position matters only at the
        # ends, through the initial and final forms.
        hint_lookup = {}
        for h in HINTS:
            mapping = {}
            for g in letters:
                for src in [g] + [self.form[(g, f)] for f in FORMS]:
                    mapping[src] = self.hinted[(g, h)]
            hint_lookup[h] = add(fb.lookup(1, [fb.single(mapping)]), is_top=False)
        klass, classes = {}, {}

        def class_of(key):
            return classes.setdefault(key, len(classes) + 1)
        for g, c in self.letter.items():
            klass[g] = class_of(("mid", c))
            for f in FORMS:
                klass[self.form[(g, f)]] = class_of((f, c))
        for g in self.apostrophes:
            klass[g] = class_of(("apostrophe",))
        rules = {}                                   # first class -> rules
        for word, hints in sorted(words.items()):
            if set(hints) == {"."}:
                continue
            chars = [c for c in word]
            keys = []
            for i, c in enumerate(chars):
                if c == "'":
                    keys.append(("apostrophe",))
                    continue
                first, last = i == 0, i == len(chars) - 1
                keys.append((("IF" if last else "I") if first else ("F" if last else "mid"), c))
            r = ot.SubClassRule()
            r.Class = [classes[k] for k in keys[1:]]
            r.GlyphCount = len(keys)
            r.SubstLookupRecord = []
            for i, h in enumerate(hints):
                if h in HINTS:
                    rec = ot.SubstLookupRecord()
                    rec.SequenceIndex, rec.LookupListIndex = i, hint_lookup[h]
                    r.SubstLookupRecord.append(rec)
            r.SubstCount = len(r.SubstLookupRecord)
            rules.setdefault(classes[keys[0]], []).append(r)
        cd = ot.ClassDef()
        cd.classDefs = klass
        first_glyphs = {}
        for g, k in klass.items():
            first_glyphs.setdefault(k, []).append(g)
        subtables, chunk, size = [], [], 0
        firsts = sorted(rules)
        for k in firsts + [None]:
            cost = 0 if k is None else sum(6 + 2 * (r.GlyphCount - 1) + 4 * r.SubstCount for r in rules[k])
            if k is None or (chunk and size + cost > SUBTABLE_BYTES):
                st = ot.ContextSubst()
                st.Format = 2
                st.Coverage = coverage([g for c in chunk for g in first_glyphs[c]], gid)
                st.ClassDef = cd
                st.SubClassSet = [None] * (len(classes) + 1)
                for c in chunk:
                    s = ot.SubClassSet()
                    s.SubClassRule = rules[c]
                    s.SubClassRuleCount = len(rules[c])
                    st.SubClassSet[c] = s
                st.SubClassSetCount = len(st.SubClassSet)
                subtables.append(st)
                chunk, size = [], 0
            if k is not None:
                chunk.append(k)
                size += cost
        add(fb.lookup(5, subtables))
        # 4. Back to plain letters.
        add(fb.lookup(1, [fb.single({self.form[(g, f)]: g for g in letters for f in FORMS})]))
        gsub = fb.build_gsub(lookups, top=top)
        return b.finish(gsub, family="Fontlex English"), sum(len(v) for v in rules.values())


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", required=True)
    ap.add_argument("--bold", required=True)
    ap.add_argument("--lexicon", default=str(HERE / "lexicon" / "words.tsv"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    words = read_lexicon(args.lexicon)
    font, n_rules = EnglishFont(args.base, args.bold).build(words)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "Fontlex-English.ttf"
    font.save(path)
    font.flavor = "woff2"
    font.save(path.with_suffix(".woff2"))
    print(f"wrote {path} and .woff2: {len(words)} words, {n_rules} with hints, "
          f"{len(font.getGlyphOrder())} glyphs, {path.with_suffix('.woff2').stat().st_size // 1024} KB as WOFF2")
    return 0


if __name__ == "__main__":
    sys.exit(main())
