#!/usr/bin/env python3
"""Compile the English pronunciation-hint font.

    python english/enfont.py --base fonts/NotoSans-Regular.ttf --bold fonts/NotoSans-Bold.ttf --out build

Each listed word's letters are drawn with their hints (align.py): the
stressed vowel bold in the accent color, reduced vowels in a muted blue,
silent letters pale. Other text is drawn as the base font draws it. A word is
letters, with apostrophes between letters (`don't`). The passes:

1. Right to left: each word's last letter becomes its "final" variant.
2. Left to right: each word's first letter becomes an "initial" variant that
   also records the second letter (or "initial and final", for a one-letter
   word), so a word is only tried against the rules for its first two
   letters.
3. Cue words (lexicon/cues.tsv: `the`, `a`, `to`, `will`, ...): their last
   letter becomes a noun-cue or verb-cue variant of its final form.
4. Noun/verb pairs (lexicon/homographs.tsv) right before a reading marker
   (U+FE00 noun, U+FE01 verb: markers/README.md), or else after a cue and
   one space, get that reading's hints: "the record" REcord, "to record"
   reCORD, "a new record" + U+FE00 REcord.
5. One context rule per listed word with hints, case-insensitive (glyph
   classes ignore case), from an initial letter to a final one, so it matches
   whole words only. It applies a hint lookup at each hinted letter. A pair
   with no cue before it gets only the hints both readings share.
6. The variants that no rule claimed go back to plain letters.

Stylistic sets turn a kind of hint off: ss01 silent letters, ss02 reduced
vowels, ss03 stress (HINT_SETS; the French font shares the numbering).
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
    "light": {"stress": "#C2272D", "reduced": "#4F74B8", "silent": "#BCC2CC"},
    "dark": {"stress": "#FF7B7B", "reduced": "#86A8E6", "silent": "#596070"},
}
# Stylistic sets that turn one kind of hint off, numbered alike in every hint font.
HINT_SETS = {"silent": ("ss01", "No silent-letter hints"), "reduced": ("ss02", "No reduced-vowel hints"),
             "stress": ("ss03", "No stress hints"), "nasal": ("ss04", "No nasal-vowel hints"),
             "liaison": ("ss05", "No liaison hints")}
# Invisible characters after a noun/verb pair that pick its reading (markers/README.md).
MARKERS = {"noun": "\uFE00", "verb": "\uFE01"}
SECOND = list(LETTERS) + ["'"]       # what an initial form can record as the next character
CUE_FORMS = {"noun": ("FN", "IFN"), "verb": ("FV", "IFV")}
SUBTABLE_BYTES = 40000               # rules per subtable, under its 16-bit offsets


def coverage(glyphs, gid):
    cov = ot.Coverage()
    cov.glyphs = sorted(set(glyphs), key=gid)
    return cov


def read_table(path, columns):
    rows = {}
    for line in open(path, encoding="utf-8"):
        if line.strip() and not line.startswith("#"):
            parts = line.rstrip("\n").split("\t")
            rows[parts[0]] = parts[1] if columns == 2 else tuple(parts[1:columns])
    return rows


def read_lexicon(directory):
    """(words: word -> hints, homographs: word -> (noun, verb), cues: word -> noun|verb)."""
    d = Path(directory)
    return (read_table(d / "words.tsv", 2), read_table(d / "homographs.tsv", 3), read_table(d / "cues.tsv", 2))


def record(index, lookup_index):
    r = ot.SubstLookupRecord()
    r.SequenceIndex, r.LookupListIndex = index, lookup_index
    return r


def context_subtables(rules, cd, klass, classes, gid):
    """Format 2 context subtables for `rules` (first class -> rules), of
    about SUBTABLE_BYTES each, in order of first class; one class's rules
    may continue in the next subtable (a shaper tries each subtable whose
    coverage has the glyph)."""
    first_glyphs = {}
    for g, k in klass.items():
        first_glyphs.setdefault(k, []).append(g)
    chunks, size = [[]], 0
    for k in sorted(rules):
        for r in rules[k]:
            cost = 8 + 2 * (r.GlyphCount - 1) + 4 * r.SubstCount
            if chunks[-1] and size + cost > SUBTABLE_BYTES:
                chunks.append([])
                size = 0
            chunks[-1].append((k, r))
            size += cost
    subtables = []
    for chunk in chunks:
        sets = {}
        for k, r in chunk:
            sets.setdefault(k, []).append(r)
        st = ot.ContextSubst()
        st.Format = 2
        st.Coverage = coverage([g for k in sets for g in first_glyphs[k]], gid)
        st.ClassDef = cd
        st.SubClassSet = [None] * (len(classes) + 1)
        for k, rs in sets.items():
            cs = ot.SubClassSet()
            cs.SubClassRule, cs.SubClassRuleCount = rs, len(rs)
            st.SubClassSet[k] = cs
        st.SubClassSetCount = len(st.SubClassSet)
        subtables.append(st)
    return subtables


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
        self.space = cmap[ord(" ")]
        self.marker = {}                 # noun|verb -> an empty glyph, so no font falls back for it
        for kind, ch in MARKERS.items():
            self.marker[kind] = f"uni{ord(ch):04X}"
            b.add_base_glyph(self.marker[kind], ord(ch), 0)
        self.plain = sorted(self.letter, key=b.gid)
        self.forms = ["F", "IF"] + [f"I{y}" for y in SECOND] + [f for fs in CUE_FORMS.values() for f in fs]
        self.form = {}                   # (glyph, form) -> variant
        self.hinted = {}                 # (glyph, hint) -> hinted glyph
        for g in self.plain:
            for f in self.forms:
                name = f"{g}.w{f}".replace("'", "_apos")
                self.form[(g, f)] = b.composite(name, [(g, 0, 0)], b.advance(g))
            for h, entry in HINTS.items():
                body = fb.styled(g, "b") if h == "S" else g
                name = b.composite(f"{g}.h{h}", [(body, 0, 0)], b.advance(body))
                b.colr[name] = [(body, entry)]
                self.hinted[(g, h)] = name
            b.alias[g] = [self.form[(g, f)] for f in self.forms] + [self.hinted[(g, h)] for h in HINTS]

    def all_forms(self, *which):
        return [self.form[(g, f)] for g in self.plain for f in which]

    def keys(self, word):
        """The class keys of a word's characters."""
        out = []
        for i, c in enumerate(word):
            if c == "'":
                out.append(("apostrophe",))
            elif len(word) == 1:
                out.append(("IF", c))
            elif i == 0:
                out.append(("I", c, word[1]))
            elif i == len(word) - 1:
                out.append(("F", c))
            else:
                out.append(("mid", c))
        return out

    def build(self, words, homographs, cues):
        b, gid = self.b, self.b.gid
        lookups, top = [], []

        def add(lk, is_top=True):
            lookups.append(lk)
            if is_top:
                top.append(len(lookups) - 1)
            return len(lookups) - 1

        def single(mapping):
            return add(fb.lookup(1, [fb.single(mapping)]), is_top=False)

        letters, finals = self.plain, self.all_forms("F")
        any_form = letters + self.all_forms(*self.forms)
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
        # letter and an apostrophe) stays; any other becomes initial, keyed by
        # what follows it.
        to_initial = {y: single({g: self.form[(g, f"I{y}")] for g in letters}) for y in SECOND}
        to_single = single({self.form[(g, "F")]: self.form[(g, "IF")] for g in letters})
        subtables = []

        def chain3(behind, inputs, ahead, records):
            st = ot.ChainContextSubst()
            st.Format = 3
            st.BacktrackCoverage = [coverage(c, gid) for c in behind]
            st.InputCoverage = [coverage(c, gid) for c in inputs]
            st.LookAheadCoverage = [coverage(c, gid) for c in ahead]
            st.BacktrackGlyphCount, st.InputGlyphCount, st.LookAheadGlyphCount = len(behind), len(inputs), len(ahead)
            st.SubstLookupRecord, st.SubstCount = records, len(records)
            return st
        for behind in ([any_form], [self.apostrophes, any_form]):          # not a word's start: no change
            subtables.append(chain3(behind, [letters + finals], [], []))
        subtables.append(chain3([], [finals], [], [record(0, to_single)]))
        for y in SECOND:
            same = [g for g in letters if self.letter[g] == y]
            nxt = self.apostrophes if y == "'" else same + [self.form[(g, "F")] for g in same]
            subtables.append(chain3([], [letters], [nxt], [record(0, to_initial[y])]))
        add(fb.lookup(6, subtables))
        # Classes: case ignored; a word's first letter is keyed by its second.
        klass, classes = {}, {}

        def class_of(key):
            return classes.setdefault(key, len(classes) + 1)
        for g in letters:
            c = self.letter[g]
            klass[g] = class_of(("mid", c))
            klass[self.form[(g, "F")]] = class_of(("F", c))
            klass[self.form[(g, "IF")]] = class_of(("IF", c))
            for y in SECOND:
                klass[self.form[(g, f"I{y}")]] = class_of(("I", c, y))
            for final, single_form in CUE_FORMS.values():                 # a cue word's end is still its end
                klass[self.form[(g, final)]] = klass[self.form[(g, "F")]]
                klass[self.form[(g, single_form)]] = klass[self.form[(g, "IF")]]
        for g in self.apostrophes:
            klass[g] = class_of(("apostrophe",))
        cd = ot.ClassDef()
        cd.classDefs = klass
        # 3. Cue words: the last letter becomes a cue form.
        to_cue = {kind: single({**{self.form[(g, "F")]: self.form[(g, final)] for g in letters},
                                **{self.form[(g, "IF")]: self.form[(g, one)] for g in letters}})
                  for kind, (final, one) in CUE_FORMS.items()}
        cue_rules = {}
        for word, kind in sorted(cues.items()):
            keys = self.keys(word)
            r = ot.SubClassRule()
            r.Class = [classes[k] for k in keys[1:]]
            r.GlyphCount = len(keys)
            r.SubstLookupRecord = [record(len(keys) - 1, to_cue[kind])]
            r.SubstCount = 1
            cue_rules.setdefault(classes[keys[0]], []).append(r)
        add(fb.lookup(5, context_subtables(cue_rules, cd, klass, classes, gid)))
        # Hint lookups, from any form of a letter.
        hint_lookup = {h: single({src: self.hinted[(g, h)] for g in letters
                                  for src in [g] + [self.form[(g, f)] for f in self.forms]}) for h in HINTS}

        def hint_records(hints):
            return [record(i, hint_lookup[h]) for i, h in enumerate(hints) if h in HINTS]
        # 4. Noun/verb pairs before a marker, or after a cue and a space.
        back = ot.ClassDef()
        back.classDefs = {self.space: 1}
        for kind, forms in CUE_FORMS.items():
            for g in letters:
                for f in forms:
                    back.classDefs[self.form[(g, f)]] = 2 if kind == "noun" else 3
        ahead = ot.ClassDef()
        ahead.classDefs = {self.marker["noun"]: 1, self.marker["verb"]: 2}
        pair_rules = {}
        for word, (noun, verb) in sorted(homographs.items()):
            keys = self.keys(word)
            for behind, after, hints in (([], [1], noun), ([], [2], verb), ([1, 2], [], noun), ([1, 3], [], verb)):
                r = ot.ChainSubClassRule()
                r.Backtrack, r.Input, r.LookAhead = behind, [classes[k] for k in keys[1:]], after
                r.BacktrackGlyphCount, r.InputGlyphCount, r.LookAheadGlyphCount = len(behind), len(keys), len(after)
                r.SubstLookupRecord = hint_records(hints)
                r.SubstCount = len(r.SubstLookupRecord)
                pair_rules.setdefault(classes[keys[0]], []).append(r)
        st = ot.ChainContextSubst()
        st.Format = 2
        st.Coverage = coverage([g for g, k in klass.items() if k in pair_rules], gid)
        st.BacktrackClassDef, st.InputClassDef = back, cd
        st.LookAheadClassDef = ahead
        st.ChainSubClassSet = [None] * (len(classes) + 1)
        for k, rs in pair_rules.items():
            cs = ot.ChainSubClassSet()
            cs.ChainSubClassRule, cs.ChainSubClassRuleCount = rs, len(rs)
            st.ChainSubClassSet[k] = cs
        st.ChainSubClassSetCount = len(st.ChainSubClassSet)
        add(fb.lookup(6, [st]))
        # 5. The words.
        rules = {}
        for word, hints in sorted(words.items()):
            if set(hints) == {"."}:
                continue
            keys = self.keys(word)
            r = ot.SubClassRule()
            r.Class = [classes[k] for k in keys[1:]]
            r.GlyphCount = len(keys)
            r.SubstLookupRecord = hint_records(hints)
            r.SubstCount = len(r.SubstLookupRecord)
            rules.setdefault(classes[keys[0]], []).append(r)
        add(fb.lookup(5, context_subtables(rules, cd, klass, classes, gid)))
        # 6. Back to plain letters.
        add(fb.lookup(1, [fb.single({self.form[(g, f)]: g for g in letters for f in self.forms})]))
        # The stylistic sets: one kind of hint back to plain letters.
        sets = {}
        for h, entry in HINTS.items():
            tag, label = HINT_SETS[entry]
            sets[tag] = ([single({self.hinted[(g, h)]: g for g in letters})], label)
        gsub = fb.build_gsub(lookups, top=top, sets=sets)
        return b.finish(gsub, family="Fontlex English"), sum(len(v) for v in rules.values())


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", required=True)
    ap.add_argument("--bold", required=True)
    ap.add_argument("--lexicon", default=str(HERE / "lexicon"), help="the directory of words.tsv and the rest")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    words, homographs, cues = read_lexicon(args.lexicon)
    font, n_rules = EnglishFont(args.base, args.bold).build(words, homographs, cues)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "Fontlex-English.ttf"
    font.save(path)
    font.flavor = "woff2"
    font.save(path.with_suffix(".woff2"))
    print(f"wrote {path} and .woff2: {len(words)} words, {n_rules} with hints, {len(homographs)} noun/verb "
          f"pairs, {len(font.getGlyphOrder())} glyphs, {path.with_suffix('.woff2').stat().st_size // 1024} KB as WOFF2")
    return 0


if __name__ == "__main__":
    sys.exit(main())
