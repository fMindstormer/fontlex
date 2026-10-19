#!/usr/bin/env python3
"""Compile the French pronunciation-hint font.

    python french/frfont.py --base fonts/NotoSans-Regular.ttf --bold fonts/NotoSans-Bold.ttf --out build

Each listed word's letters are drawn with their hints (align.py): silent
letters pale, the letters of a nasal vowel violet, a schwa that speakers may
drop blue. A liaison, the last letter of a word said before the next word's
vowel, is bold green, with a green tie under the space or hyphen. Other text
is drawn as the base font draws it. A word is letters; an apostrophe or a
hyphen ends one (`l'homme`, `peut-être`). The passes:

1. Right to left: each word's last letter becomes its "final" variant.
2. Left to right: each word's first letter becomes an "initial" variant that
   also records the second letter (or "initial and final", for a one-letter
   word), so a word is only tried against the rules for its first two
   letters.
3. Cue words (lexicon/cues.tsv: `le`, `très`, `ils`, `ne`, ...): their last
   letter becomes a noun-cue or verb-cue variant. Words before which there is
   no liaison (blockers.txt: `haricot`, `onze`): their first letter becomes a
   "blocking" variant.
4. Verb/noun pairs (homographs.tsv) after a cue and one space get that
   reading's hints: "le président", "ils président".
5. Liaison: a listed trigger (liaison.txt: `les`, `nous`, `un`, `dans`, ...),
   not after a hyphen, then one space, then a vowel or h that doesn't block:
   the trigger's last letter becomes the liaison glyph, the space a tie.
6. Liaison in inversion: a word's last s, x, t, d or z before a hyphen and
   `il`, `ils`, `elle`, `elles`, `on`, `en` or `y` ("vont-ils", "allons-y").
7. One context rule per listed word or compound with hints, case-insensitive,
   from an initial letter to a final one, so it matches whole words only.
   Compounds (compounds.tsv: `peut-être`) are tried first.
8. The variants that no rule claimed go back to plain letters.
"""

import argparse
import sys
from pathlib import Path

from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib.tables import otTables as ot

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "markdown"))
sys.path.insert(0, str(HERE.parent / "english"))
import fontbuild as fb  # noqa: E402
from enfont import context_subtables, coverage, read_table, record  # noqa: E402

LETTERS = "abcdefghijklmnopqrstuvwxyzàâæçéèêëîïôœùûüÿ"
LINKS_TO = set("aeiouyàâæéèêëîïôœùûüÿh")       # a liaison links to a vowel, or an h muet
APOSTROPHES = "'’"
HINTS = {"x": "silent", "r": "reduced", "n": "nasal", "L": "liaison"}
TIE = "T"
PALETTES = {
    "light": {"silent": "#BCC2CC", "reduced": "#4F74B8", "nasal": "#9447B0", "liaison": "#16855A"},
    "dark": {"silent": "#596070", "reduced": "#86A8E6", "nasal": "#C996DD", "liaison": "#5FD0A0"},
}
CUE_FORMS = {"noun": ("FN", "IFN"), "verb": ("FV", "IFV")}
CLITICS = ("il", "ils", "elle", "elles", "on", "en", "y")
INVERTED = "sxtdz"


class Lexicon:
    """lexicon/: words.tsv (word, hints), homographs.tsv (word, noun hints,
    verb hints), compounds.tsv (compound, hints), cues.tsv (word, noun or
    verb), liaison.txt (trigger words) and blockers.txt."""

    def __init__(self, directory):
        d = Path(directory)

        def lines(name):
            return [l.strip() for l in open(d / name, encoding="utf-8") if l.strip() and not l.startswith("#")]
        self.words = read_table(d / "words.tsv", 2)
        self.homographs = read_table(d / "homographs.tsv", 3)
        self.compounds = read_table(d / "compounds.tsv", 2)
        self.cues = read_table(d / "cues.tsv", 2)
        self.triggers = lines("liaison.txt")
        self.blockers = set(lines("blockers.txt"))
        parts = {p for c in self.compounds for p in c.replace("-", "'").split("'")}
        assert not set(self.triggers) & set(self.homographs), "a trigger can't be a verb/noun pair"
        assert not self.blockers & set(self.cues), "a cue can't block liaison"
        assert not parts & set(self.homographs), "a compound can't hold a verb/noun pair"
        assert all(len(w) > 1 for w in self.blockers | set(self.triggers))


def tokens(text):
    """A word or compound's parts: words, and the hyphens and apostrophes
    between them."""
    out, word = [], ""
    for ch in text:
        if ch in "-" + APOSTROPHES:
            out += [word, ch]
            word = ""
        else:
            word += ch
    return out + [word]


class FrenchFont:
    def __init__(self, base, bold, block_letters):
        self.b = b = fb.FontBuilder(base)
        b.palettes = PALETTES
        b.import_style("b", bold)
        cmap = b.font.getBestCmap()
        self.letter = {}                 # glyph -> lowercase letter
        for c in LETTERS:
            for ch in (c, c.upper()):
                if ord(ch) in cmap:
                    self.letter[cmap[ord(ch)]] = c
        self.name = {c: cmap[ord(c)] for c in LETTERS}
        self.apostrophes = [cmap[ord(c)] for c in APOSTROPHES]
        self.space, self.hyphen = cmap[ord(" ")], cmap[ord("-")]
        self.plain = sorted(self.letter, key=b.gid)
        self.form = {}                   # (glyph, form) -> variant
        self.hinted = {}                 # (glyph, hint) -> hinted glyph
        for g in self.plain:
            forms = ["F", "IF"] + [f for fs in CUE_FORMS.values() for f in fs] + [f"I:{y}" for y in LETTERS]
            if self.letter[g] in block_letters:
                forms += [f"B:{y}" for y in LETTERS]
            for f in forms:
                tag = f if ":" not in f else f[0] + "_" + self.name[f[2:]]
                self.form[(g, f)] = b.composite(f"{g}.w{tag}", [(g, 0, 0)], b.advance(g))
            for h, entry in HINTS.items():
                body = fb.styled(g, "b") if h == "L" else g
                name = b.composite(f"{g}.h{h}", [(body, 0, 0)], b.advance(body))
                b.colr[name] = [(body, entry)]
                self.hinted[(g, h)] = name
            b.alias[g] = [v for (g2, _), v in self.form.items() if g2 == g] + [self.hinted[(g, h)] for h in HINTS]
        self.tie = {}
        for g in (self.space, self.hyphen):
            arc = self.arc(f"_tie_{g}", b.advance(g))
            parts = [(arc, "liaison")] if g == self.space else [(g, None), (arc, "liaison")]
            name = b.composite(f"{g}.h{TIE}", [(p, 0, 0) for p, _ in parts], b.advance(g))
            b.colr[name] = parts
            self.tie[g] = name
            b.alias[g] = [name]

    def arc(self, name, adv):
        """A tie under the baseline, from a little left of the glyph to a
        little right of it, so it reaches the letters it links."""
        upem = self.b.upem
        x0, x1, top, depth, w = -upem * 0.1, adv + upem * 0.1, -upem * 0.06, upem * 0.12, upem * 0.065
        n = 16
        outer = [(x0 + (x1 - x0) * i / n, top - depth * (1 - (2 * i / n - 1) ** 2)) for i in range(n + 1)]
        inner = [(x, y + w * (1 - 0.6 * abs(2 * i / n - 1))) for i, (x, y) in enumerate(outer)]
        pen = TTGlyphPen(None)
        for i, pt in enumerate(outer + inner[::-1]):
            (pen.moveTo if i == 0 else pen.lineTo)((round(pt[0]), round(pt[1])))
        pen.closePath()
        return self.b.add(name, pen.glyph(), 0, round(x0))

    def forms_of(self, glyphs, *which):
        return [self.form[(g, f)] for g in glyphs for f in which if (g, f) in self.form]

    def keys(self, text):
        """The class keys of a word's or compound's characters."""
        out = []
        for t in tokens(text):
            if t == "-":
                out.append(("hyphen",))
            elif t in APOSTROPHES:
                out.append(("apostrophe",))
            elif len(t) == 1:
                out.append(("IF", t))
            else:
                out += [("I", t[0], t[1])] + [("mid", c) for c in t[1:-1]] + [("F", t[-1])]
        return out

    def build(self, lex):
        b, gid = self.b, self.b.gid
        lookups, top = [], []

        def add(lk, is_top=True):
            lookups.append(lk)
            if is_top:
                top.append(len(lookups) - 1)
            return len(lookups) - 1

        def single(mapping):
            return add(fb.lookup(1, [fb.single(mapping)]), is_top=False)

        def chain3(behind, inputs, ahead, records):
            st = ot.ChainContextSubst()
            st.Format = 3
            st.BacktrackCoverage = [coverage(c, gid) for c in behind]
            st.InputCoverage = [coverage(c, gid) for c in inputs]
            st.LookAheadCoverage = [coverage(c, gid) for c in ahead]
            st.BacktrackGlyphCount, st.InputGlyphCount, st.LookAheadGlyphCount = len(behind), len(inputs), len(ahead)
            st.SubstLookupRecord, st.SubstCount = records, len(records)
            return st

        def of_letters(cs):
            return [g for g in self.plain if self.letter[g] in cs]
        letters = self.plain
        finals = self.forms_of(letters, "F")
        any_form = letters + list(self.form.values())
        # 1. Final letters, right to left: a letter followed by a letter stays;
        # any other becomes final.
        subtables = []
        for ahead in ([letters + finals], []):
            st = ot.ReverseChainSingleSubst()
            st.Format = 1
            st.Coverage = coverage(letters, gid)
            st.BacktrackCoverage = []
            st.LookAheadCoverage = [coverage(c, gid) for c in ahead]
            st.Substitute = [g if ahead else self.form[(g, "F")] for g in st.Coverage.glyphs]
            subtables.append(st)
        add(fb.lookup(8, subtables))
        # 2. Initial letters, left to right, keyed by what follows.
        to_initial = {y: single({g: self.form[(g, f"I:{y}")] for g in letters}) for y in LETTERS}
        to_single = single({self.form[(g, "F")]: self.form[(g, "IF")] for g in letters})
        subtables = [chain3([any_form], [letters + finals], [], []), chain3([], [finals], [], [record(0, to_single)])]
        for y in LETTERS:
            same = of_letters(y)
            subtables.append(chain3([], [letters], [same + self.forms_of(same, "F")], [record(0, to_initial[y])]))
        add(fb.lookup(6, subtables))
        # Classes: case ignored; a word's first letter is keyed by its second.
        klass, classes = {}, {}

        def class_of(key):
            return classes.setdefault(key, len(classes) + 1)
        for g in letters:
            c = self.letter[g]
            klass[g] = class_of(("mid", c))
            for (g2, f), v in self.form.items():
                if g2 == g:
                    klass[v] = class_of(("F", c) if f in ("F", "FN", "FV") else ("IF", c) if f in ("IF", "IFN", "IFV")
                                        else ("I", c, f[2:]))
            klass[self.hinted[(g, "L")]] = class_of(("F", c))         # a liaison is still its word's end
        for g in self.apostrophes:
            klass[g] = class_of(("apostrophe",))
        klass[self.hyphen] = klass[self.tie[self.hyphen]] = class_of(("hyphen",))
        klass[self.space] = class_of(("space",))
        cd = ot.ClassDef()
        cd.classDefs = klass

        def context_rule(keys, records):
            r = ot.SubClassRule()
            r.Class = [classes[k] for k in keys[1:]]
            r.GlyphCount = len(keys)
            r.SubstLookupRecord, r.SubstCount = records, len(records)
            return classes[keys[0]], r
        # 3. Cue words' last letters, blockers' first letters.
        to_cue = {kind: single({**{self.form[(g, "F")]: self.form[(g, final)] for g in letters},
                                **{self.form[(g, "IF")]: self.form[(g, one)] for g in letters}})
                  for kind, (final, one) in CUE_FORMS.items()}
        to_block = single({self.form[(g, f)]: self.form[(g, "B" + f[1:])] for (g, f) in self.form
                           if f.startswith("I:") and (g, "B" + f[1:]) in self.form})
        marks = {}
        for word, kind in sorted(lex.cues.items()):
            k, r = context_rule(self.keys(word), [record(len(word) - 1, to_cue[kind])])
            marks.setdefault(k, []).append(r)
        for word in sorted(lex.blockers):
            k, r = context_rule(self.keys(word), [record(0, to_block)])
            marks.setdefault(k, []).append(r)
        add(fb.lookup(5, context_subtables(marks, cd, klass, classes, gid)))
        # Hint lookups, from any form of a letter.
        hint_lookup = {h: single({src: self.hinted[(g, h)] for g in letters
                                  for src in [g] + self.forms_of([g], *[f for (g2, f) in self.form if g2 == g])})
                       for h in HINTS}
        to_tie = single({g: self.tie[g] for g in self.tie})
        to_plain = single({self.form[(g, f)]: g for (g, f) in self.form if f[:2] in ("I:", "B:") or f == "IF"})

        def hint_records(hints):
            out = [record(i, hint_lookup[h]) for i, h in enumerate(hints) if h in HINTS]
            return out + [record(i, to_tie) for i, h in enumerate(hints) if h == TIE]

        def chain2(rules, back, ahead):
            st = ot.ChainContextSubst()
            st.Format = 2
            st.Coverage = coverage([g for g, k in klass.items() if k in rules], gid)
            st.BacktrackClassDef, st.InputClassDef, st.LookAheadClassDef = ot.ClassDef(), cd, ot.ClassDef()
            st.BacktrackClassDef.classDefs, st.LookAheadClassDef.classDefs = back, ahead
            st.ChainSubClassSet = [None] * (len(classes) + 1)
            for k, rs in rules.items():
                cs = ot.ChainSubClassSet()
                cs.ChainSubClassRule, cs.ChainSubClassRuleCount = rs, len(rs)
                st.ChainSubClassSet[k] = cs
            st.ChainSubClassSetCount = len(st.ChainSubClassSet)
            return st

        def chain_rule(behind, keys, ahead, records):
            r = ot.ChainSubClassRule()
            r.Backtrack, r.Input, r.LookAhead = behind, [classes[k] for k in keys[1:]], ahead
            r.BacktrackGlyphCount, r.InputGlyphCount, r.LookAheadGlyphCount = len(behind), len(keys), len(ahead)
            r.SubstLookupRecord, r.SubstCount = records, len(records)
            return r
        # 4. Verb/noun pairs after a cue and a space. A reading without hints
        # turns the first letter plain, so step 7 doesn't match the word.
        back = {self.space: 1}
        for kind, forms in CUE_FORMS.items():
            for v in self.forms_of(letters, *forms):
                back[v] = 2 if kind == "noun" else 3
        pairs = {}
        for word, (noun, verb) in sorted(lex.homographs.items()):
            keys = self.keys(word)
            for cue_class, hints in ((2, noun), (3, verb)):
                pairs.setdefault(classes[keys[0]], []).append(
                    chain_rule([1, cue_class], keys, [], hint_records(hints) or [record(0, to_plain)]))
        add(fb.lookup(6, [chain2(pairs, back, {})]))
        # 5. Liaison after a trigger and a space; not after a hyphen, where the
        # trigger is an inverted subject ("ont-ils eu").
        to_liaison = single({v: self.hinted[(g, "L")] for g in letters for v in self.forms_of([g], "F", "FN", "FV")})
        links_to = [g for g in letters if self.letter[g] in LINKS_TO]
        ahead = {g: 1 for g in links_to + [v for (g, f), v in self.form.items() if g in links_to and f[0] != "B"]
                 + [self.hinted[(g, h)] for g in links_to for h in HINTS]}
        rules = {}
        for word in lex.triggers:
            keys = self.keys(word) + [("space",)]
            rules.setdefault(classes[keys[0]], []).extend([
                chain_rule([1], keys, [], []),
                chain_rule([], keys, [1], [record(len(word) - 1, to_liaison), record(len(word), to_tie)])])
        add(fb.lookup(6, [chain2(rules, {self.hyphen: 1, self.tie[self.hyphen]: 1}, ahead)]))
        # 6. Liaison in inversion: "vont-ils", "allons-y".
        subtables = []
        for clitic in CLITICS:
            if len(clitic) == 1:
                ahead = [self.forms_of(of_letters(clitic), "IF", "IFN", "IFV")]
            else:
                ahead = ([self.forms_of(of_letters(clitic[0]), f"I:{clitic[1]}")]
                         + [of_letters(c) for c in clitic[1:-1]]
                         + [self.forms_of(of_letters(clitic[-1]), "F", "FN", "FV")])
            said = self.forms_of(of_letters(INVERTED), "F", "FN", "FV")
            subtables.append(chain3([], [said, [self.hyphen]], ahead, [record(0, to_liaison), record(1, to_tie)]))
        add(fb.lookup(6, subtables))
        # 7. Compounds, longest first, then words.
        rules, n_rules = {}, 0
        for text, hints in sorted(lex.compounds.items(), key=lambda kv: -len(kv[0])):
            k, r = context_rule(self.keys(text), hint_records(hints))
            rules.setdefault(k, []).append(r)
            n_rules += 1
        for word, hints in sorted(lex.words.items()):
            if set(hints) != {"."}:
                k, r = context_rule(self.keys(word), hint_records(hints))
                rules.setdefault(k, []).append(r)
                n_rules += 1
        add(fb.lookup(5, context_subtables(rules, cd, klass, classes, gid)))
        # 8. Back to plain letters.
        add(fb.lookup(1, [fb.single({v: g for (g, _), v in self.form.items()})]))
        gsub = fb.build_gsub(lookups, top=top)
        return b.finish(gsub, family="Fontlex French"), n_rules


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", required=True)
    ap.add_argument("--bold", required=True)
    ap.add_argument("--lexicon", default=str(HERE / "lexicon"), help="the directory of words.tsv and the rest")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    lex = Lexicon(args.lexicon)
    font, n_rules = FrenchFont(args.base, args.bold, {w[0] for w in lex.blockers}).build(lex)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "Fontlex-French.ttf"
    font.save(path)
    font.flavor = "woff2"
    font.save(path.with_suffix(".woff2"))
    print(f"wrote {path} and .woff2: {len(lex.words)} words, {n_rules} rules (words with hints and compounds), "
          f"{len(lex.homographs)} verb/noun pairs, {len(lex.triggers)} liaison triggers, {len(lex.blockers)} "
          f"blockers, {len(font.getGlyphOrder())} glyphs, {path.with_suffix('.woff2').stat().st_size // 1024} KB as WOFF2")
    return 0


if __name__ == "__main__":
    sys.exit(main())
