"""Compiling passes over a glyph run into GSUB lookups.

A pass is a deterministic transducer: it reads glyphs in one direction and
replaces each with a variant that records the state it leaves behind, so the
next glyph's rule can read that state from its neighbor (the left neighbor's
output in left-to-right passes; the right neighbor's in right-to-left ones,
which are reverse chaining lookups). A pass sees only its own glyphs: the
rest are skipped through GDEF mark filtering, which is why intermediate
glyphs are marks. That keeps state off ordinary text: a pass over `*` and
`_` never multiplies the letters by its states.

Intermediate glyphs are `var(base, kind)`: an empty mark standing for the
character of `base`, with `kind` (a tuple) saying what has been learned
about it.
"""

from fontTools.ttLib.tables import otTables as ot

import fontbuild as fb

IMPOSSIBLE = object()   # what a step returns for an input that can't occur in a state
# In an anchored pass, the state a glyph is in when its neighbor (left in a
# left-to-right pass, right in a right-to-left one) records no state: there is
# a glyph there, but not one of the pass's outputs. `init` then means the
# start (or the end) of the line itself.
OTHER = ("other",)


class Seq(tuple):
    """An output of several glyphs (a multiple substitution): the last one
    records the state."""

IGNORE_BASE = 0x0002
IGNORE_LIGATURES = 0x0004
SKELETON = IGNORE_BASE | IGNORE_LIGATURES


class Pipeline:
    def __init__(self, builder):
        self.fb = builder
        self.lookups = []
        self.top = []         # indices of the lookups the feature applies, in order
        self.mark_sets = []
        self.first_set = 0
        gdef = builder.font["GDEF"].table
        if gdef.Version >= 0x00010002 and gdef.MarkGlyphSetsDef is not None:
            self.first_set = len(gdef.MarkGlyphSetsDef.Coverage)
        self.variants = {}    # (base, kind) -> variant name
        self.info = {}        # variant name -> (base, kind)
        self.pool = {}        # base -> temporary glyphs, reused by every temporary pass
        self.temp = None      # (base, kind) -> pool glyph, while a temporary pass is built
        self.gid = builder.gid
        # How outputs are compared when grouping inputs into classes: glyphs
        # whose outputs differ only in this key's terms share rules.
        self.key = lambda o: self.kind_of(o) or o
        self.bins = []        # [mapping, lookup index]: merged()'s lookups, shared by every pass
        self.seq_bins = []    # the same for multiple substitutions
        self.companions = []  # rtl_keyed()'s marks, reused by every such pass
        self.keyed_stats = []

    # glyphs -------------------------------------------------------------

    def var(self, base, kind):
        """The intermediate glyph for character glyph `base` with `kind`."""
        base = self.base_of(base)
        key = (base, kind)
        if self.temp is not None and kind and isinstance(kind[-1], tuple) and kind[-1][:1] == ("s",):
            # A temporary pass's output (its state is the kind's last item):
            # the next unused glyph of the base's pool, valid until end_temp().
            name = self.temp.get(key)
            if name is None:
                pool = self.pool.setdefault(base, [])
                used = sum(1 for b, _ in self.temp if b == base)
                if used == len(pool):
                    pool.append(self.fb.empty(f"_t{sum(map(len, self.pool.values()))}", 0, gdef_class=3))
                name = self.temp[key] = pool[used]
                self.info[name] = key
            return name
        name = self.variants.get(key)
        if name is None:
            name = f"_v{len(self.variants)}"
            self.fb.empty(name, 0, gdef_class=3)
            self.variants[key] = name
            self.info[name] = key
        return name

    def begin_temp(self):
        """Outputs that record a state (kind ending ("s", ...)) come from the
        reusable pool until end_temp(); the pass must turn them all back into
        other glyphs before then."""
        self.temp = {}

    def end_temp(self):
        for name in self.temp.values():
            del self.info[name]
        self.temp = None

    def base_of(self, name):
        return self.info[name][0] if name in self.info else name

    def kind_of(self, name):
        return self.info[name][1] if name in self.info else ()

    def mark_set(self, glyphs):
        self.mark_sets.append(set(glyphs))
        return self.first_set + len(self.mark_sets) - 1

    # lookups ------------------------------------------------------------

    def add(self, lookup, top=True):
        """Add a lookup; `top` ones run in the order added, the others are only
        called from contextual rules."""
        self.lookups.append(lookup)
        if top:
            self.top.append(len(self.lookups) - 1)
        return len(self.lookups) - 1

    def single(self, mapping, flag=0, mark_set=None, top=True):
        mapping = {a: b for a, b in mapping.items() if a != b}
        return self.add(fb.lookup(1, [fb.single(mapping)], flag, mark_set), top)

    def nested(self, mapping):
        """A single substitution for contextual rules to call."""
        return self.single(mapping, top=False)

    def merged(self, mappings, multiple=False):
        """Nested single substitutions for the named mappings (multiple ones,
        of Seq outputs, with `multiple`), as few as possible: mappings that
        never send one glyph to two places share one (first fit, largest
        first), with any earlier pass's too. Each is called only on glyphs
        of its own mapping, so what the rest of a shared lookup does never
        shows; fewer lookups leave more room under the 16-bit offsets
        (fontbuild.build_gsub). Returns {name: lookup index}."""
        out = {}
        bins = self.seq_bins if multiple else self.bins
        for name, m in sorted(mappings.items(), key=lambda kv: -len(kv[1])):
            m = {g: tuple(o) for g, o in m.items()} if multiple else m
            for b in bins:
                if all(b[0].get(g, o) == o for g, o in m.items()):
                    b[0].update(m)
                    st = self.lookups[b[1]].SubTable[0]
                    st.mapping.update({g: list(o) for g, o in m.items()} if multiple
                                      else {g: o for g, o in m.items() if g != o})
                    out[name] = b[1]
                    break
            else:
                out[name] = (self.add(fb.lookup(2, [fb.multiple(m)]), top=False) if multiple
                             else self.nested(m))
                bins.append([dict(m), out[name]])
        return out

    def gsub(self, unwrapped=()):
        return fb.build_gsub(self.lookups, self.top, unwrapped=unwrapped)

    def coverage(self, glyphs):
        cov = ot.Coverage()
        cov.glyphs = sorted(set(glyphs), key=self.gid)
        return cov

    def chain_rule(self, backtrack, inp, lookahead, records):
        """A format 3 chaining rule; contexts are lists of glyph sets in text
        order; records are (input position, lookup index)."""
        st = ot.ChainContextSubst()
        st.Format = 3
        st.BacktrackCoverage = [self.coverage(g) for g in reversed(backtrack)]
        st.InputCoverage = [self.coverage(g) for g in inp]
        st.LookAheadCoverage = [self.coverage(g) for g in lookahead]
        st.BacktrackGlyphCount, st.InputGlyphCount, st.LookAheadGlyphCount = \
            len(backtrack), len(inp), len(lookahead)
        st.SubstLookupRecord = []
        for pos, idx in records:
            r = ot.SubstLookupRecord()
            r.SequenceIndex, r.LookupListIndex = pos, idx
            st.SubstLookupRecord.append(r)
        st.SubstCount = len(st.SubstLookupRecord)
        return st

    def class_rules(self, back_classes, input_classes, rules, ahead_classes=None):
        """A format 2 chaining subtable: many rules in one, where format 3
        takes a subtable each. Classes are {glyph: class} (none: class 0);
        rules is {first input class: [(backtrack classes in text order,
        classes of the inputs after the first, records[, lookahead
        classes])]}, each list tried in order, and the subtable covers the
        glyphs of those first classes."""
        st = ot.ChainContextSubst()
        st.Format = 2
        st.Coverage = self.coverage({g for g, c in input_classes.items() if c in rules})
        st.BacktrackClassDef = self._classdef(back_classes)
        st.InputClassDef = self._classdef(input_classes)
        st.LookAheadClassDef = self._classdef(ahead_classes or {})
        st.ChainSubClassSet = []
        for c in range(max(rules) + 1):
            if c not in rules:
                st.ChainSubClassSet.append(None)
                continue
            cs = ot.ChainSubClassSet()
            cs.ChainSubClassRule = []
            for back, inp, records, *ahead in rules[c]:
                ahead = list(ahead[0]) if ahead else []
                r = ot.ChainSubClassRule()
                r.Backtrack, r.BacktrackGlyphCount = list(reversed(back)), len(back)
                r.Input, r.InputGlyphCount = list(inp), len(inp) + 1
                r.LookAhead, r.LookAheadGlyphCount = ahead, len(ahead)
                r.SubstLookupRecord = []
                for pos, idx in records:
                    rec = ot.SubstLookupRecord()
                    rec.SequenceIndex, rec.LookupListIndex = pos, idx
                    r.SubstLookupRecord.append(rec)
                r.SubstCount = len(r.SubstLookupRecord)
                cs.ChainSubClassRule.append(r)
            cs.ChainSubClassRuleCount = len(cs.ChainSubClassRule)
            st.ChainSubClassSet.append(cs)
        st.ChainSubClassSetCount = len(st.ChainSubClassSet)
        return st

    def chain(self, rules, sees=None):
        """A lookup of format 3 rules (backtrack, input, lookahead, records).
        With `sees`, the lookup skips base glyphs and every mark not in it."""
        ms = self.mark_set(sees) if sees is not None else None
        return self.add(fb.lookup(6, [self.chain_rule(*r) for r in rules],
                                  SKELETON if sees is not None else 0, ms))

    def reverse_rule(self, mapping, backtrack=(), lookahead=()):
        st = ot.ReverseChainSingleSubst()
        st.Format = 1
        glyphs = sorted(mapping, key=self.gid)
        st.Coverage = self.coverage(glyphs)
        st.Substitute = [mapping[g] for g in glyphs]
        st.GlyphCount = len(glyphs)
        st.BacktrackCoverage = [self.coverage(g) for g in reversed(backtrack)]
        st.LookAheadCoverage = [self.coverage(g) for g in lookahead]
        st.BacktrackGlyphCount, st.LookAheadGlyphCount = len(backtrack), len(lookahead)
        return st

    def reverse(self, rules, sees=None):
        """A lookup of reverse chaining rules (mapping, backtrack, lookahead)."""
        ms = self.mark_set(sees) if sees is not None else None
        return self.add(fb.lookup(8, [self.reverse_rule(*r) for r in rules],
                                  SKELETON if sees is not None else 0, ms))

    # transducers -------------------------------------------------------

    def _explore(self, inputs, step, init, anchored=False, make=None):
        states, index, todo, out = [init], {init: 0}, [init], {}
        if anchored:
            states, index, todo = [init, OTHER], {init: 0, OTHER: 1}, [init, OTHER]
        self.unchanged = set()   # inputs some state leaves as they are
        self.kept = set()        # (input, state) pairs left unchanged
        ordered = sorted(inputs.items(), key=lambda gs: self.gid(gs[0]))
        while todo:
            s = todo.pop()
            for g, sym in ordered:
                r = step(s, sym)
                if r is IMPOSSIBLE:
                    continue
                if r is None:
                    self.unchanged.add(g)
                    self.kept.add((g, s))
                    continue
                kind, ns = r
                assert ns != OTHER, "no output can record OTHER"
                o = kind if isinstance(kind, (str, Seq)) else (make or self.var)(g, kind)
                out[(g, s)] = (o, ns)
                if ns not in index:
                    index[ns] = len(states)
                    states.append(ns)
                    todo.append(ns)
        records = {}
        for (g, s), (o, ns) in out.items():
            o = o[-1] if isinstance(o, Seq) else o
            if records.setdefault(o, ns) != ns:
                raise ValueError(f"output {self.info.get(o, o)} records two states: {records[o]}, {ns}")
        return states, index, out, records

    def _tkey(self, o):
        """How outputs group into the substitutions a pass calls: by self.key,
        and sequences by their last glyph."""
        return ("seq", o[-1]) if isinstance(o, Seq) else self.key(o)

    def ltr(self, inputs, step, init, sees=(), skeleton=True, fill_backtrack=False, anchored=False):
        """A left-to-right transducer.

        inputs: glyph -> symbol. step(state, symbol) -> (kind, new state), where
        the glyph becomes var(glyph, kind) (or `kind` itself if it is a glyph
        name), None to leave the glyph unchanged, or IMPOSSIBLE where it can't
        occur. Each output must record a single state. A glyph whose left
        neighbor (among the glyphs the pass sees: its inputs, outputs and
        `sees`; or all glyphs if not `skeleton`) records no state starts from
        `init`. `fill_backtrack` may give glyphs between outputs of one state
        that state too, shrinking the class definition; only safe when every
        glyph a rule can see to its left is an output. With `anchored` (and
        not `skeleton`), a glyph after a glyph that records no state is in
        state OTHER, and only the line's first glyph starts from `init`.
        Returns ({(glyph, state): output}, states).
        """
        assert not (anchored and (skeleton or fill_backtrack))
        states, index, out, records = self._explore(inputs, step, init, anchored)
        sig = {}
        for g in inputs:
            key = tuple((self._tkey(out[(g, s)][0]), out[(g, s)][1])
                        if (g, s) in out else None for s in states)
            sig.setdefault(key, []).append(g)
        input_class = {}
        for i, gs in enumerate(sorted(sig.values(), key=lambda gs: self.gid(gs[0]))):
            for g in gs:
                input_class[g] = i + 1
        back_class = {o: index[ns] + 1 for o, ns in records.items()}
        # One substitution per kind of output (in self.key's terms) maps every
        # input that becomes that kind of output: a rule's inputs share one.
        targets = {}
        for (g, s), (o, ns) in out.items():
            targets.setdefault(self._tkey(o), {})[g] = o
        seqs = {k: m for k, m in targets.items() if isinstance(k, tuple) and k[:1] == ("seq",)}
        target_lookup = self.merged({k: m for k, m in targets.items() if k not in seqs})
        target_lookup.update(self.merged(seqs, multiple=True))
        st = ot.ChainContextSubst()
        st.Format = 2
        st.Coverage = self.coverage(input_class)
        st.BacktrackClassDef = self._classdef(back_class, fill=fill_backtrack)
        st.InputClassDef = self._classdef(input_class, fill=True)
        st.LookAheadClassDef = self._classdef({})
        rep = {c: g for g, c in input_class.items()}
        st.ChainSubClassSet = [None]
        for c in range(1, max(input_class.values()) + 1):
            g, rules = rep[c], []
            # The rule with nothing before it is the default, for the start of
            # the line and any state without a rule of its own: it gives the
            # start state's output, and other states get rules only where they
            # differ. The start state's rule comes first when there are others
            # (it is the usual one).
            default = out.get((g, init))
            explicit = [s for s in states if s not in (init, OTHER) and (g, s) in out and out[(g, s)] != default]
            # A state that leaves the glyph as it is needs a rule of its own
            # when the default would change it.
            kept = [s for s in states if s not in (init, OTHER) and (g, s) in self.kept and default is not None]
            order = [(s, True) for s in explicit + kept]
            if explicit and default is not None:
                order = [(init, True)] + order
            if anchored and (default is not None or (g, OTHER) in out):
                order.append((OTHER, True))
            if default is not None:
                order.append((init, False))
            for s, back in order:
                rule = ot.ChainSubClassRule()
                rule.Backtrack = ([0] if s == OTHER else [index[s] + 1]) if back else []
                rule.BacktrackGlyphCount = len(rule.Backtrack)
                rule.Input, rule.InputGlyphCount = [], 1
                rule.LookAhead, rule.LookAheadGlyphCount = [], 0
                rule.SubstLookupRecord = []
                if (g, s) in out:
                    rec = ot.SubstLookupRecord()
                    rec.SequenceIndex = 0
                    rec.LookupListIndex = target_lookup[self._tkey(out[(g, s)][0])]
                    rule.SubstLookupRecord = [rec]
                rule.SubstCount = len(rule.SubstLookupRecord)
                rules.append(rule)
            cs = ot.ChainSubClassSet()
            cs.ChainSubClassRule, cs.ChainSubClassRuleCount = rules, len(rules)
            st.ChainSubClassSet.append(cs)
        st.ChainSubClassSetCount = len(st.ChainSubClassSet)
        ms = self.mark_set(set(input_class) | set(back_class) | set(sees)) if skeleton else None
        self.add(fb.lookup(6, self._split(st, input_class), SKELETON if skeleton else 0, ms))
        return {k: v[0] for k, v in out.items()}, [s for s in states if s != OTHER]

    def _split(self, st, input_class, limit=48000):
        """The format 2 subtable as subtables small enough for 16-bit
        offsets: each takes some of the input classes (its coverage only
        their glyphs, so exactly one applies to a glyph) and shares the
        backtrack class definition. Sizes are estimated, with identical
        rules and class sets counted once, as the font compiler stores them."""
        def rule_key(r):
            return (tuple(r.Backtrack), tuple((x.SequenceIndex, x.LookupListIndex) for x in r.SubstLookupRecord))

        def ranges(gids):
            gids = sorted(gids)
            return sum(1 for a, b in zip([None] + gids, gids) if a is None or b != a + 1)
        back_ids = [self.gid(g) for g in st.BacktrackClassDef.classDefs]
        fixed = 16 + 6 * ranges(back_ids)
        glyphs_of = {}
        for g, c in input_class.items():
            glyphs_of.setdefault(c, []).append(self.gid(g))
        chunks, cur, seen, size = [], [], set(), fixed
        for c in range(1, len(st.ChainSubClassSet)):
            cs = st.ChainSubClassSet[c]
            keys = [rule_key(r) for r in cs.ChainSubClassRule]
            new = [k for k in set(keys) if k not in seen]
            cost = 2 + 2 * len(keys) + sum(10 + 2 * len(k[0]) + 4 * len(k[1]) for k in new) \
                + 12 * ranges(glyphs_of[c])
            if cur and size + cost > limit:
                chunks.append(cur)
                cur, seen, size = [], set(), fixed
                new = set(keys)
                cost = 2 + 2 * len(keys) + sum(10 + 2 * len(k[0]) + 4 * len(k[1]) for k in new) \
                    + 12 * ranges(glyphs_of[c])
            cur.append(c)
            seen |= set(new)
            size += cost
        chunks.append(cur)
        if len(chunks) == 1:
            return [st]
        out = []
        for chunk in chunks:
            part = ot.ChainContextSubst()
            part.Format = 2
            renumber = {c: i + 1 for i, c in enumerate(chunk)}
            classes = {g: renumber[c] for g, c in input_class.items() if c in renumber}
            part.Coverage = self.coverage(classes)
            part.BacktrackClassDef = st.BacktrackClassDef
            part.InputClassDef = self._classdef(classes, fill=True)
            part.LookAheadClassDef = st.LookAheadClassDef
            part.ChainSubClassSet = [None] + [st.ChainSubClassSet[c] for c in chunk]
            part.ChainSubClassSetCount = len(part.ChainSubClassSet)
            out.append(part)
        return out

    def _classdef(self, classes, fill=False):
        """A class definition; with `fill`, glyphs lying between two glyphs of
        one class (in glyph order) get that class, so ranges merge."""
        cd = ot.ClassDef()
        cd.classDefs = {g: c for g, c in classes.items() if c}
        if fill and cd.classDefs:
            order = self.fb.order
            ids = sorted(self.gid(g) for g in cd.classDefs)
            for a, b in zip(ids, ids[1:]):
                ca, cb = cd.classDefs[order[a]], cd.classDefs[order[b]]
                if ca == cb and b - a > 1:
                    for i in range(a + 1, b):
                        cd.classDefs[order[i]] = ca
        return cd

    def rtl_keyed(self, inputs, step, init, anchored=False, strip=True):
        """A right-to-left pass compiled small. It runs on companion marks,
        one after each input glyph, which stand for the few kinds of input
        the pass tells apart (keys): a reverse chaining rule maps every key
        for each state, where rtl() maps every input glyph. The companions
        record the state; a ligature folds each back into its glyph, which
        takes from it what the pass leaves there. Reverse chaining inside an
        Extension lookup is lost on DirectWrite (fontbuild.build_gsub), so
        these must stay small.

        With `strip`, the state goes right after: an output's kind ends
        ("s", state), the pass leaves var(base, the kind without it), and
        the states are minimized against that; returns the glyphs the inputs
        end as. Without, outputs stay as they are, and it returns what rtl()
        does. `anchored` as for rtl(): every glyph is seen, and next to one
        the pass doesn't read, the state is OTHER.

        A glyph and its companion ligate: for a mark that keeps no ligature
        ids, and for a base glyph it leaves a base (to lookup flags too)."""
        states, _, out, _ = self._explore(inputs, step, init, anchored, make=lambda g, kind: (self.base_of(g), kind))
        gs = sorted(inputs, key=self.gid)
        none = OTHER if anchored else init      # what an unchanged glyph's left neighbor reads

        def fin(g, s):        # what the input is left as; a pair the pass never meets counts as unchanged
            if (g, s) not in out:
                return g
            base, kind = out[(g, s)][0]
            if not strip:
                return self.var(base, kind)
            return self.var(base, kind[:-1]) if kind[:-1] else base

        def nxt(g, s):
            return out[(g, s)][1] if (g, s) in out else none
        part = {s: tuple(fin(g, s) for g in gs) for s in states}
        count = len(set(part.values()))
        while True:           # Moore's refinement
            ids = {}
            new = {s: ids.setdefault((part[s], tuple(part[nxt(g, s)] for g in gs)), len(ids)) for s in states}
            part = new
            if len(ids) == count:
                break
            count = len(ids)
        rep = {}
        for s in states:
            rep.setdefault(part[s], s)
        classes, c0, c_other = list(rep), part[init], part.get(OTHER)
        delta = {(c, g): part[nxt(g, rep[c])] for c in classes for g in gs}
        left = {(g, c): fin(g, rep[c]) for c in classes for g in gs}
        changed = {g for g in gs if any(left[(g, c)] != g for c in classes)}
        keys = {}
        for g in gs:
            keys.setdefault((tuple(delta[(c, g)] for c in classes), g in changed), []).append(g)
        key_of = {g: k for k, members in enumerate(keys.values()) for g in members}
        changed_keys = {key_of[g] for g in changed}
        rep_of = [members[0] for members in keys.values()]

        # A companion records the state its left neighbor reads, and after a
        # glyph the pass changes, the state it read too.
        def record(k, c):
            t = delta[(c, rep_of[k])]
            return (t, c) if k in changed_keys else (t,)
        values = sorted({record(k, c) for k in range(len(keys)) for c in classes})
        need = len(keys) + len(values) + 1
        while len(self.companions) < need:
            self.companions.append(self.fb.empty(f"_c{len(self.companions)}", 0, gdef_class=3))
        K = self.companions[:len(keys)]
        D = dict(zip(values, self.companions[len(keys):len(keys) + len(values)]))
        X = self.companions[need - 1]
        self.add(fb.lookup(2, [fb.multiple({g: [g, K[key_of[g]]] for g in gs})]))

        def mapping(c, fallback):
            return {K[k]: D[record(k, c)] for k in range(len(keys))
                    if fallback is None or record(k, c) != record(k, fallback)}
        rules = []
        if anchored:          # the glyph after a companion: an input (its companion then has the state), any other, or none
            for c in classes:
                ahead = {D[v] for v in values if v[0] == c}
                m = mapping(c, c_other)
                if m and ahead and c != c_other:
                    rules.append((m, (), (set(gs), ahead)))
            if c_other != c0:
                rules.append((mapping(c_other, c0), (), (set(self.fb.order),)))
        else:
            for c in classes:
                ahead = {D[v] for v in values if v[0] == c}
                m = mapping(c, c0)
                if m and ahead and c != c0:
                    rules.append((m, (), (ahead,)))
        rules.append((mapping(c0, None), (), ()))
        self.reverse(rules, None if anchored else set(K) | set(D.values()))
        unchanged = [g for g in gs if g not in changed]
        if unchanged:
            self.chain([([set(unchanged)], [set(D.values())], [], [(0, self.nested({d: X for d in D.values()}))])])
        lig = ot.LigatureSubst()
        lig.ligatures = {}
        for g in gs:
            pairs = [(X, g)] if g not in changed else sorted({(D[record(key_of[g], c)], left[(g, c)])
                                                              for c in classes})
            for comp, glyph in pairs:
                L = ot.Ligature()
                L.Component, L.LigGlyph, L.CompCount = [comp], glyph, 2
                lig.ligatures.setdefault(g, []).append(L)
        self.add(fb.lookup(4, [lig]))
        self.keyed_stats.append((len(gs), len(states), len(classes), len(keys), len(values)))
        if not strip:
            return {(g, s): fin(g, s) for g in gs for s in states if (g, s) in out}, [s for s in states if s != OTHER]
        return set(unchanged) | {left[(g, c)] for g in changed for c in classes}

    def rtl(self, inputs, step, init, sees=(), skeleton=True, anchored=False):
        """A right-to-left transducer (reverse chaining substitutions); the
        arguments are as for ltr(), with the right neighbor's state (and in
        an anchored pass, `init` only at the end of the line)."""
        assert not (anchored and skeleton)
        states, index, out, records = self._explore(inputs, step, init, anchored)
        by_state = {}
        for o, ns in records.items():
            by_state.setdefault(ns, set()).add(o)
        rules = []
        # The subtable with nothing after it is the default (the start
        # state's output); a state gets its own subtable only for the inputs
        # whose output differs there, or which it leaves alone where the
        # default would change them (in an anchored pass, for all of them).
        default = {g: out[(g, init)][0] for g in inputs if (g, init) in out}

        def mapping(s):
            m = {}
            for g in inputs:
                o = out[(g, s)][0] if (g, s) in out else g if (g, s) in self.kept else None
                if o is not None and (anchored or o != default.get(g, g)):
                    m[g] = o
            return m
        for s in [s for s in states if s not in (init, OTHER)]:
            m = mapping(s)
            if m and s in by_state:
                rules.append((m, (), (by_state[s],)))
        if anchored:      # (a neighbor that records the start state is the default's)
            m = mapping(OTHER)
            if m:
                rules.append((m, (), (set(self.fb.order) - set(records),)))
        if default:
            rules.append((default, (), ()))
        self.reverse(rules, set(inputs) | set(records) | set(sees) if skeleton else None)
        return {k: v[0] for k, v in out.items()}, [s for s in states if s != OTHER]



