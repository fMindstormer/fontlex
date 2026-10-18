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

    def merged(self, mappings):
        """Nested single substitutions for the named mappings, as few as
        possible: mappings that never send one glyph to two places share one
        (first fit, largest first). Returns {name: lookup index}."""
        bins = []    # [mapping, names]
        for name, m in sorted(mappings.items(), key=lambda kv: -len(kv[1])):
            for b in bins:
                if all(b[0].get(g, o) == o for g, o in m.items()):
                    b[0].update(m)
                    b[1].append(name)
                    break
            else:
                bins.append([dict(m), [name]])
        out = {}
        for m, names in bins:
            idx = self.nested(m)
            for name in names:
                out[name] = idx
        return out

    def gsub(self):
        return fb.build_gsub(self.lookups, self.top)

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

    def _explore(self, inputs, step, init):
        states, index, todo, out = [init], {init: 0}, [init], {}
        self.unchanged = set()   # inputs some state leaves as they are
        ordered = sorted(inputs.items(), key=lambda gs: self.gid(gs[0]))
        while todo:
            s = todo.pop()
            for g, sym in ordered:
                r = step(s, sym)
                if r is IMPOSSIBLE:
                    continue
                if r is None:
                    self.unchanged.add(g)
                    continue
                kind, ns = r
                o = kind if isinstance(kind, str) else self.var(g, kind)
                out[(g, s)] = (o, ns)
                if ns not in index:
                    index[ns] = len(states)
                    states.append(ns)
                    todo.append(ns)
        records = {}
        for (g, s), (o, ns) in out.items():
            if records.setdefault(o, ns) != ns:
                raise ValueError(f"output {self.info.get(o, o)} records two states: {records[o]}, {ns}")
        return states, index, out, records

    def ltr(self, inputs, step, init, sees=(), skeleton=True, fill_backtrack=False):
        """A left-to-right transducer.

        inputs: glyph -> symbol. step(state, symbol) -> (kind, new state), where
        the glyph becomes var(glyph, kind) (or `kind` itself if it is a glyph
        name), None to leave the glyph unchanged, or IMPOSSIBLE where it can't
        occur. Each output must record a
        single state. A glyph whose left neighbor (among the glyphs the pass
        sees: its inputs, outputs and `sees`; or all glyphs if not `skeleton`)
        records no state starts from `init`. `fill_backtrack` may give glyphs
        between outputs of one state that state too, shrinking the class
        definition; only safe when every glyph a rule can see to its left is an
        output. Returns ({(glyph, state): output}, states).
        """
        states, index, out, records = self._explore(inputs, step, init)
        sig = {}
        for g in inputs:
            key = tuple((self.key(out[(g, s)][0]), out[(g, s)][1])
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
            targets.setdefault(self.key(o), {})[g] = o
        target_lookup = self.merged(targets)
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
            explicit = [s for s in states if s != init and (g, s) in out and out[(g, s)] != default]
            order = [(s, True) for s in explicit]
            if explicit and default is not None:
                order = [(init, True)] + order
            if default is not None:
                order.append((init, False))
            for s, back in order:
                o, ns = out[(g, s)]
                rule = ot.ChainSubClassRule()
                rule.Backtrack = [index[s] + 1] if back else []
                rule.BacktrackGlyphCount = len(rule.Backtrack)
                rule.Input, rule.InputGlyphCount = [], 1
                rule.LookAhead, rule.LookAheadGlyphCount = [], 0
                rec = ot.SubstLookupRecord()
                rec.SequenceIndex = 0
                rec.LookupListIndex = target_lookup[self.key(o)]
                rule.SubstLookupRecord, rule.SubstCount = [rec], 1
                rules.append(rule)
            cs = ot.ChainSubClassSet()
            cs.ChainSubClassRule, cs.ChainSubClassRuleCount = rules, len(rules)
            st.ChainSubClassSet.append(cs)
        st.ChainSubClassSetCount = len(st.ChainSubClassSet)
        ms = self.mark_set(set(input_class) | set(back_class) | set(sees)) if skeleton else None
        self.add(fb.lookup(6, [st], SKELETON if skeleton else 0, ms))
        return {k: v[0] for k, v in out.items()}, states

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

    def rtl(self, inputs, step, init, sees=(), skeleton=True):
        """A right-to-left transducer (reverse chaining substitutions); the
        arguments are as for ltr(), with the right neighbor's state."""
        states, index, out, records = self._explore(inputs, step, init)
        by_state = {}
        for o, ns in records.items():
            by_state.setdefault(ns, set()).add(o)
        rules = []
        # The subtable with nothing after it is the default (the start
        # state's output); a state gets its own subtable only for the inputs
        # whose output differs there.
        default = {g: out[(g, init)][0] for g in inputs if (g, init) in out}
        for s in [s for s in states if s != init]:
            mapping = {g: out[(g, s)][0] for g in inputs if (g, s) in out and out[(g, s)][0] != default.get(g)}
            if mapping:
                rules.append((mapping, (), (by_state[s],)))
        if default:
            rules.append((default, (), ()))
        self.reverse(rules, set(inputs) | set(records) | set(sees) if skeleton else None)
        return {k: v[0] for k, v in out.items()}, states



