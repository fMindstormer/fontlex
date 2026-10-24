#!/usr/bin/env python3
"""Fontlex Math: compile program.py's passes into a font.

    python math/mathfont.py OUT.ttf [--base fonts/JetBrainsMono-Regular.ttf] [--relaxed]

--relaxed builds the relaxed notation's font (relaxed.py): front.py's
passes, then program.py's.

Every pass becomes GSUB lookups (transducers through markdown/passes.py's
Pipeline; Derive, Context and Map as reverse chaining and single
substitutions). The compiler keeps, for each kind of token, the set of
values its five glyphs can hold together (the joint domain): a Derive
reading several tracks gets one rule per combination that occurs, not per
combination of the tracks' values. Then GPOS places the final glyphs:
heights in flow, extra advances, and the attachment chains of fractions
(see assemble.py).
"""

import argparse
import io
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "markdown"))
sys.path.insert(1, os.path.join(HERE, ".."))

from fontTools import subset
from fontTools.otlLib import builder as otl
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables import otTables as ot

import fontbuild as fb
import passes as mp

import assemble as A
import front
import layout as L
import program as P
import relaxed as R

BASE = os.path.join(HERE, "..", "fonts", "JetBrainsMono-Regular.ttf")
FINAL = {"glyph", "radical", "space", "hid", "root", "qbase", "fendbase", "adv", "dx", "dy", "dxy",
         "dx@root", "dx@fend", "at@base", "y", "ink", "_"}
SLOT_INDEX = {t: i for i, t in enumerate(P.ORDER)}
FILTER = 0x0010
SKELETON = mp.SKELETON


class Font:
    def __init__(self, base):
        chars = {chr(c) for c in range(0x21, 0x7F)} | set(L.SYMBOLS.values())
        self.chars = sorted(chars)
        f = TTFont(base, recalcTimestamp=False)
        opts = subset.Options()
        opts.layout_features, opts.hinting, opts.notdef_outline = ["*"], False, True
        opts.name_IDs = ["*"]
        sub = subset.Subsetter(opts)
        sub.populate(unicodes=[0x20] + [ord(c) for c in chars])
        sub.subset(f)
        data = io.BytesIO()
        f.save(data)
        data.seek(0)
        self.b = fb.FontBuilder(data)
        if "GPOS" in self.b.font:
            del self.b.font["GPOS"]
        self.cmap = self.b.font.getBestCmap()
        self.pl = mp.Pipeline(self.b)
        self.pl.merged = self.merged
        self.gs = self.b.font.getGlyphSet()
        self.names = {}          # (family, value) -> glyph name
        self.value_of = {}       # glyph name -> (family, value)
        self.anchor = {}         # final glyph -> its descriptor, for GPOS
        self.finished = set()    # tracks whose values are final glyphs
        self.temp = []           # transducer outputs, reused by every pass
        self.stats = []
        self.pool = []           # nested lookups: (index, mapping)
        self.pool_of = {}        # glyph -> {pool index: output}
        self.rules = 0
        self.mult = []
        self.inserts = {}        # virtual tokens before a character -> its glyph's number
        self.recycling = False   # reuse the glyphs of values no token holds any more
        self.free = []
        self.freed = 0

    # glyphs ------------------------------------------------------------------

    def glyph(self, family, v, final=False):
        """The glyph that holds value v on a track (family: a track, or "sp"
        for a space's own glyph), or, once the track is finished (or for a
        final pass's output), the final glyph v describes."""
        if family == "G":
            return self.char_glyph(v) if v[0] == "g" else self.final_glyph(v)
        if final or family in self.finished:
            return self.final_glyph(v)
        key = (family, v)
        name = self.names.get(key)
        if name is None and self.free:
            name = self.free.pop()
            self.names[key] = name
            self.value_of[name] = key
        if name is None:
            name = f"_{family}{len(self.names) + self.freed}"
            self.b.empty(name, 0, gdef_class=3)
            self.names[key] = name
            self.value_of[name] = key
        return name

    def recycle(self, J, SP):
        """Free the glyphs of track values the domain no longer has: no
        token can hold them, and the lookups that made or read them have
        run, so a later value may take their names."""
        live = {("sp", v) for v in SP}
        for s, sets in J.items():
            live.add(("S", s))
            for tr in OTHERS:
                if tr != "G":
                    live |= {(tr, v) for v in sets[tr]}
        for key in [k for k in self.names if k[0] in ("S", "A", "B", "C", "sp") and k not in live]:
            if key[0] in self.finished:
                continue
            name = self.names.pop(key)
            del self.value_of[name]
            self.free.append(name)
            self.freed += 1

    def temp_glyph(self, i):
        """A transducer's i-th output, which the strip after it turns back
        into a value: every pass reuses the same glyphs."""
        while len(self.temp) <= i:
            self.temp.append(self.b.empty(f"_t{len(self.temp)}", 0, gdef_class=3))
        return self.temp[i]

    def char_glyph(self, v):
        """A character's glyph; ("g", "", "V") is a virtual token's
        (front.py), and a fourth part, the virtual tokens to put before
        it, makes a glyph of its own until they are."""
        ch, tag = v[1], v[2]
        if tag == "V":
            name = "_virtual"
            if name not in self.b.ids:
                self.b.empty(name, 0, gdef_class=1)
            self.value_of[name] = ("G", v)
            return name
        base = self.cmap[ord(ch)]
        if tag is None and len(v) == 3:
            return base
        name = f"{base}.{tag}" if tag is not None else base
        if len(v) > 3:
            name += f".i{self.inserts.setdefault(v[3], len(self.inserts))}"
        if name not in self.b.ids:
            self.b.composite(name, [(base, 0, 0)], self.b.advance(base))
        self.value_of[name] = ("G", v)
        return name

    def final_glyph(self, v):
        key = ("fin", v)
        if key in self.names:
            return self.names[key]
        name = self.make_final(v)
        self.names[key] = name
        self.anchor[name] = v
        return name

    def make_final(self, v):
        b = self.b
        k = v[0]
        if k == "_":
            return b.empty("_blank", 0, gdef_class=3)
        if k == "space":
            return self.cmap[0x20]
        if k == "hid":
            return b.empty("_hid", 0, gdef_class=3)
        if k == "glyph":
            _, ch, st, mode = v
            base = self.cmap[ord(ch)]
            if st == 0 and mode == "b":
                return base
            sc = L.SCALE[st]
            name = f"{base}.s{st}{mode}"
            return b.composite(name, [(base, 0, 0, ((sc, 0), (0, sc)))] if sc != 1 else [(base, 0, 0)],
                               L.WIDTH[st] if mode == "b" else 0, 1 if mode == "b" else 3)
        if k == "radical":
            _, st, kind, mode = v
            return self.radical(f"_radical{st}{kind}{mode}", st, kind, mode)
        if k in ("root", "qbase"):
            return b.empty(f"_{k}", 0, gdef_class=1)
        if k == "fendbase":
            return b.empty(f"_fendbase{v[1]}", 0, gdef_class=1)
        if k == "adv":
            return b.empty(f"_adv{v[1]}".replace("-", "m"), 0, gdef_class=1)
        if k == "ink":
            _, band, direction, start, length, digit = v
            x0 = start * L.UNIT
            x1 = x0 + length * L.UNIT * (1 if direction == "R" else -1)
            name = f"_ink{len(self.names)}"
            if length:
                return b.rect(name, min(x0, x1), band[0], max(x0, x1), band[1]) and self.mark(name)
            return b.empty(name, 0, gdef_class=3)
        name = "_" + "_".join(str(x) for x in v).replace("-", "m").replace("@", "at")
        return b.empty(name, 0, gdef_class=3)

    def size_of(self, first):
        """Subtables and rules in the lookups from index `first` on."""
        n = 0
        for lk in self.pl.lookups[first:]:
            for st in lk.SubTable:
                sets = getattr(st, "ChainSubClassSet", None)
                n += sum(len(cs.ChainSubClassRule) for cs in sets if cs) if sets else 1
        return n

    # nested lookups ---------------------------------------------------------

    def nested(self, mapping):
        """A single substitution for contextual rules to call: one of a pool
        shared by every pass, as the lookup list has room for few lookups.
        A pool lookup takes the mapping if it sends none of its glyphs
        elsewhere."""
        mapping = changed(mapping)
        bad = set()
        for g, o in mapping.items():
            for i, o2 in self.pool_of.get(g, {}).items():
                if o2 != o:
                    bad.add(i)
        i = next((i for i in range(len(self.pool)) if i not in bad), None)
        if i is None:
            i = self.new_pool()
        for g, o in mapping.items():
            self.put(i, g, o)
        return self.pool[i][0]

    def new_pool(self):
        st = fb.single({})
        self.pool.append((self.pl.add(fb.lookup(1, [st]), top=False), st.mapping))
        return len(self.pool) - 1

    def put(self, i, g, o):
        self.pool[i][1][g] = o
        self.pool_of.setdefault(g, {})[i] = o

    def assign(self, mapping):
        """Pool lookups for a rule's mapping, {glyph: lookup index}: one
        lookup if one takes it all, else each glyph in the first that can
        take it (the rule's glyphs then fall into more classes)."""
        bad = set()
        for g, o in mapping.items():
            for i, o2 in self.pool_of.get(g, {}).items():
                if o2 != o:
                    bad.add(i)
        i = next((i for i in range(len(self.pool)) if i not in bad), None)
        if i is not None:
            for g, o in mapping.items():
                self.put(i, g, o)
            return {g: self.pool[i][0] for g in mapping}
        out = {}
        for g, o in mapping.items():
            have = self.pool_of.get(g, {})
            i = next((i for i, o2 in have.items() if o2 == o), None)
            if i is None:
                i = next((i for i in range(len(self.pool)) if i not in have), None)
                if i is None:
                    i = self.new_pool()
                self.put(i, g, o)
            out[g] = self.pool[i][0]
        return out

    def merged(self, mappings):
        return {name: self.nested(m) for name, m in sorted(mappings.items(), key=lambda kv: -len(kv[1]))}

    def temp_mark(self):
        name = f"_x{len(self.b.order)}"
        return self.b.empty(name, 0, gdef_class=3)

    def chain(self, back_cd, ahead_cd, rules, flag, sees):
        """A chaining context lookup (format 2) of rules (backtrack classes
        in text order, lookahead classes, mapping): each rule substitutes
        the glyphs of its mapping where its context matches. Rules for one
        glyph are tried in order."""
        assigned = []
        for back, ahead, m in rules:
            ch = changed(m)
            idx = self.assign(ch) if ch else {}
            # (a glyph the rule keeps as it is stops the rules after it)
            assigned.append({g: idx.get(g) for g in m})
        sig = defaultdict(list)
        for ri, a in enumerate(assigned):
            for g, idx in a.items():
                sig[g].append((ri, idx))
        if not sig:
            return
        by_sig = defaultdict(list)
        for g, s in sig.items():
            by_sig[tuple(s)].append(g)
        input_class = {}
        sets = [None]
        for c, (s, gs) in enumerate(sorted(by_sig.items(), key=lambda kv: min(map(self.b.gid, kv[1])))):
            for g in gs:
                input_class[g] = c + 1
            cs = ot.ChainSubClassSet()
            cs.ChainSubClassRule = []
            for ri, idx in s:
                back, ahead, _ = rules[ri]
                r = ot.ChainSubClassRule()
                r.Backtrack, r.BacktrackGlyphCount = list(reversed(back)), len(back)
                r.Input, r.InputGlyphCount = [], 1
                r.LookAhead, r.LookAheadGlyphCount = list(ahead), len(ahead)
                r.SubstLookupRecord = []
                if idx is not None:
                    rec = ot.SubstLookupRecord()
                    rec.SequenceIndex, rec.LookupListIndex = 0, idx
                    r.SubstLookupRecord = [rec]
                r.SubstCount = len(r.SubstLookupRecord)
                cs.ChainSubClassRule.append(r)
            cs.ChainSubClassRuleCount = len(cs.ChainSubClassRule)
            sets.append(cs)
        st = ot.ChainContextSubst()
        st.Format = 2
        st.Coverage = self.pl.coverage(input_class)
        st.BacktrackClassDef = self.pl._classdef(back_cd)
        st.InputClassDef = self.pl._classdef(input_class, fill=True)
        st.LookAheadClassDef = self.pl._classdef(ahead_cd)
        st.ChainSubClassSet, st.ChainSubClassSetCount = sets, len(sets)
        ms = self.pl.mark_set(sees)
        self.pl.add(fb.lookup(6, split_subtable(self, st, input_class), flag, ms))
        self.rules += sum(len(cs.ChainSubClassRule) for cs in sets[1:])

    def mark(self, name):
        self.b.classes[name] = 3
        return name

    def radical(self, name, st, kind, mode):
        """A radical sign one character wide: a short tick down to the
        vertex, and a long stroke up to the overbar."""
        w = L.WIDTH[st]
        sc = L.SCALE[st]
        bar = L.root_top(st, kind)
        low = -int(L.DEPTH[st] * 0.85)
        mid = int(L.AXIS[st] * 0.9)
        vertex = (0.42 * w, low)
        pen = TTGlyphPen(None)
        for (x0, y0), (x1, y1), th in (((0.06 * w, mid), vertex, 62 * sc),
                                        (vertex, (w, bar + L.RULE[st] / 2), 72 * sc)):
            dx, dy = x1 - x0, y1 - y0
            n = (dx * dx + dy * dy) ** 0.5
            ox, oy = -dy / n * th / 2, dx / n * th / 2
            pts = [(x0 + ox, y0 + oy), (x1 + ox, y1 + oy), (x1 - ox, y1 - oy), (x0 - ox, y0 - oy)]
            area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))
            if area > 0:            # clockwise, as TrueType draws outer contours
                pts.reverse()
            pen.moveTo(tuple(map(round, pts[0])))
            for p in pts[1:]:
                pen.lineTo(tuple(map(round, p)))
            pen.closePath()
        return self.b.add(name, pen.glyph(), w if mode == "b" else 0, 0, 1 if mode == "b" else 3)

    # lookups -----------------------------------------------------------------

    def reverse(self, rules, sees, flag=SKELETON):
        """A reverse chaining lookup: rules (mapping, backtrack, lookahead)."""
        subs = [self.pl.reverse_rule(*r) for r in rules]
        ms = self.pl.mark_set(sees)
        assert len(subs) < 65536
        return self.pl.add(fb.lookup(8, subs, flag, ms))


# The domain: what each kind of token's glyphs can hold. Tokens are grouped
# by their S value, and a group keeps a set of values per other track (any
# combination of them may occur: an over-approximation, which only costs
# rules). Spaces have a set of their own glyph's values.

OTHERS = ("G", "A", "B", "C")


def group():
    return {tr: set() for tr in OTHERS}


def merge_into(J, s, sets):
    g = J.setdefault(s, group())
    for tr in OTHERS:
        g[tr] |= sets[tr]


def values(J, track):
    """(group, value) for every value of the track."""
    for s, sets in J.items():
        if track == "S":
            yield s, s
        else:
            for v in sets[track]:
                yield s, v


def size(J):
    return sum(sum(len(x) for x in sets.values()) for sets in J.values())


def compile_program(font, prog, J, SP, verbose=False):
    """Returns the domain as the program leaves it."""
    import time
    i = 0
    while i < len(prog):
        p = prog[i]
        final = getattr(p, "final", False)
        t0, n0 = time.time(), len(font.pl.lookups)
        if isinstance(p, P.Map):
            J, SP = compile_map(font, p, J, SP, final)
        elif isinstance(p, P.Derive):
            J, SP = compile_derive(font, p, J, SP, final)
        elif isinstance(p, P.Context):
            J, SP = compile_context(font, p, J, SP)
        elif isinstance(p, P.Insert):
            J, SP = compile_insert(font, p, J, SP)
        else:
            assert prog[i + 1].fn is P.unwrap, "a transducer is followed by strip"
            J, SP = compile_transducer(font, p, J, SP)
            i += 1
        if final:
            font.finished.add(getattr(p, "target", None) or getattr(p, "track", None))
        if font.recycling:
            font.recycle(J, SP)
        if verbose:
            print(f"{i:4} {type(p).__name__:10} {getattr(p, 'target', None) or getattr(p, 'track', '-')}  groups {len(J):6} "
                  f"values {size(J):7}  SP {len(SP):3}  glyphs {len(font.b.order):6}  "
                  f"{font.size_of(n0):8} rules  {time.time() - t0:5.1f}s", flush=True)
        i += 1
    return J, SP


def safe(pred):
    """A predicate that is false where it can't be evaluated: on values of
    the domain no line gives."""
    def fn(v):
        try:
            return pred(v)
        except (TypeError, IndexError, KeyError, P.Impossible):
            return False
    return fn


def changed(mapping):
    return {a: b for a, b in mapping.items() if a != b}


def map_values(J, track, results):
    """The domain once each value of the track has become one of
    results[value] (values not in results stay)."""
    out = {}
    for s, sets in J.items():
        if track == "S":
            for ns in results.get(s, {s}):
                merge_into(out, ns, sets)
        else:
            new = dict(sets)
            new[track] = set()
            for v in sets[track]:
                new[track] |= results.get(v, {v})
            merge_into(out, s, new)
    return out


def compile_map(font, p, J, SP, final=False):
    mapping, results = {}, {}
    for _, v in values(J, p.track):
        if v not in results:
            nv = p.fn(v)
            results[v] = {nv}
            mapping[font.glyph(p.track, v)] = font.glyph(p.track, nv, final)
    newSP = set()
    for v in SP:
        nv = p.fn(v) if p.spaces else v
        if p.spaces:
            mapping[font.glyph("sp", v)] = font.glyph("sp", nv, final and nv[0] in FINAL)
        newSP.add(nv)
    mapping = changed(mapping)
    if mapping:
        font.pl.single(mapping)
    return map_values(J, p.track, results), newSP


def compile_derive(font, p, J, SP, final=False):
    """target = fn(target, *keys): a reverse chaining subtable for each
    combination of keys, its contexts every source glyph with that key."""
    import itertools
    ti = SLOT_INDEX[p.target]
    sis = [SLOT_INDEX[s] for s in p.sources]
    combos = defaultdict(dict)          # keys -> {target glyph: new glyph}
    members = [defaultdict(set) for _ in p.sources]   # per source: key -> glyphs
    out = {}
    for s, sets in J.items():
        by_key = []
        for k, src in enumerate(p.sources):
            d = defaultdict(set)
            for v in ([s] if src == "S" else sets[src]):
                try:
                    d[p.key(k, v)].add(v)
                except (TypeError, IndexError, KeyError, P.Impossible):
                    pass
            by_key.append(d)
        targets = [s] if p.target == "S" else sets[p.target]
        new_targets = set()
        for keys in itertools.product(*[list(d) for d in by_key]):
            hit = set()
            for v in targets:
                try:
                    nv = p.fn(v, *keys)
                    ng = font.glyph(p.target, nv, final)
                except (TypeError, IndexError, KeyError, P.Impossible):   # a token that can't occur
                    continue
                g = font.glyph(p.target, v)
                assert combos[keys].setdefault(g, ng) == ng, (p.target, v, keys)
                hit.add(nv)
            if not hit:
                continue
            for k, (key, src) in enumerate(zip(keys, p.sources)):
                members[k][key] |= {font.glyph(src, v) for v in by_key[k][key]}
            if p.target == "S":
                # the new group: its sources' values are those with these keys
                new = {tr: set(sets[tr]) for tr in OTHERS}
                for k, src in enumerate(p.sources):
                    if src != "S":
                        new[src] = set(by_key[k][keys[k]])
                for ns in hit:
                    merge_into(out, ns, new)
            new_targets |= hit
        if p.target != "S":
            new = dict(sets)
            new[p.target] = new_targets
            merge_into(out, s, new)
    combos, members = merge_classes(combos, members)
    # a context class for each key of each source
    before = sorted((k for k, si in enumerate(sis) if si < ti), key=lambda k: sis[k])
    after = sorted((k for k, si in enumerate(sis) if si > ti), key=lambda k: sis[k])
    back_cd, ahead_cd, cls = {}, {}, {}
    sees = set()
    for k in range(len(p.sources)):
        cd = back_cd if sis[k] < ti else ahead_cd
        n = max(cd.values(), default=0)
        for key, glyphs in members[k].items():
            n += 1
            cls[(k, key)] = n
            for g in glyphs:
                cd[g] = n
            sees |= glyphs
    rules = []
    for keys, mapping in combos.items():
        sees |= set(mapping)
        mapping = changed(mapping)
        if mapping:
            rules.append(([cls[(k, keys[k])] for k in before], [cls[(k, keys[k])] for k in after], mapping))
    newSP = set(SP)
    space_rule = None
    if p.spaces:
        mapping = {}
        newSP = set()
        for v in SP:
            nv = p.fn(v, *[p.key(k, v) for k in range(len(sis))])
            mapping[font.glyph("sp", v)] = font.glyph("sp", nv)
            newSP.add(nv)
        mapping = changed(mapping)
        if mapping:
            space_rule = ([], [], mapping)
            sees |= set(mapping)
    # A character's own glyph is a base, so a pass that changes or reads it
    # can't skip bases (no other base comes between a token's glyphs).
    flag = 0 if p.target == "G" or "G" in p.sources else SKELETON
    split(font, back_cd, ahead_cd, rules, space_rule, flag, sees)
    return out, newSP


def merge_classes(combos, members):
    """Keys of a source that no rule tells apart, one class: two keys
    merge where every combination with the same other keys maps the
    targets both cover alike (a combination only one has never occurs
    with the other, so it may apply to both)."""
    n = len(next(iter(combos), ()))
    for p in range(n):
        by_key = defaultdict(dict)
        for keys, m in combos.items():
            by_key[keys[p]][keys[:p] + keys[p + 1:]] = m
        classes, rep = [], {}
        for key in sorted(by_key, key=lambda k: -len(by_key[k])):
            sig = by_key[key]
            for cl in classes:
                if all(cl[1][o].get(g, x) == x for o, m in sig.items() if o in cl[1] for g, x in m.items()):
                    for o, m in sig.items():
                        cl[1].setdefault(o, {}).update(m)
                    rep[key] = cl[0]
                    break
            else:
                classes.append([key, {o: dict(m) for o, m in sig.items()}])
                rep[key] = key
        merged = defaultdict(dict)
        for keys, m in combos.items():
            merged[keys[:p] + (rep[keys[p]],) + keys[p + 1:]].update(m)
        combos = merged
        glyphs = defaultdict(set)
        for key, gs in members[p].items():
            glyphs[rep[key]] |= gs
        members[p] = glyphs
    return combos, members


def split_subtable(font, st, input_class):
    """Pipeline._split, but with each rule's own size (its lookahead too),
    and room for the class definitions, which the parts share."""
    fixed = 6 * (len(st.BacktrackClassDef.classDefs) + len(st.LookAheadClassDef.classDefs) + 2 * len(input_class))
    limit = max(4000, 56000 - fixed)
    sizes = {}
    for c in range(1, len(st.ChainSubClassSet)):
        cs = st.ChainSubClassSet[c]
        sizes[c] = 2 + sum(2 + 8 + 2 * len(r.Backtrack) + 2 * len(r.LookAhead) + 4 * r.SubstCount
                           for r in cs.ChainSubClassRule)
    chunks, cur, size = [], [], 0
    for c in range(1, len(st.ChainSubClassSet)):
        if cur and size + sizes[c] > limit:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(c)
        size += sizes[c]
    chunks.append(cur)
    if len(chunks) == 1:
        return [st]
    out = []
    for chunk in chunks:
        part = ot.ChainContextSubst()
        part.Format = 2
        renumber = {c: i + 1 for i, c in enumerate(chunk)}
        classes = {g: renumber[c] for g, c in input_class.items() if c in renumber}
        part.Coverage = font.pl.coverage(classes)
        part.BacktrackClassDef = st.BacktrackClassDef
        part.InputClassDef = font.pl._classdef(classes, fill=True)
        part.LookAheadClassDef = st.LookAheadClassDef
        part.ChainSubClassSet = [None] + [st.ChainSubClassSet[c] for c in chunk]
        part.ChainSubClassSetCount = len(part.ChainSubClassSet)
        out.append(part)
    return out


MANY = 32       # outputs of one glyph that one pass may give: more take two steps


def split(font, back_cd, ahead_cd, rules, extra, flag, sees):
    """The rules as one lookup, or, where a glyph has more than MANY
    outputs, as two: the first sends it to one of its outputs' groups (a
    glyph of this pass's own), the second to the output."""
    outs = defaultdict(set)
    for _, _, m in rules:
        for g, o in m.items():
            outs[g].add(o)
    many = {g: sorted(os) for g, os in outs.items() if len(os) > MANY}
    if not many:
        font.chain(back_cd, ahead_cd, rules + ([extra] if extra else []), flag, sees)
        return
    temp = {}
    for g, os in many.items():
        for h in range((len(os) + MANY - 1) // MANY):
            temp[(g, h)] = font.temp_mark()
    group = {(g, o): temp[(g, i // MANY)] for g, os in many.items() for i, o in enumerate(os)}
    first = [(b, a, {g: group.get((g, o), o) for g, o in m.items()}) for b, a, m in rules]
    second = [(b, a, {group[(g, o)]: o for g, o in m.items() if g in many}) for b, a, m in rules]
    font.chain(back_cd, ahead_cd, first + ([extra] if extra else []), flag, sees)
    ctx = set(back_cd) | set(ahead_cd)
    font.chain(back_cd, ahead_cd, [r for r in second if r[2]], flag, ctx | set(temp.values()))


def compile_context(font, p, J, SP):
    """v = fn(previous, v): a reverse chaining rule for each kind of
    previous value (the glyph before the target among those the pass
    sees), and one for none."""
    is_target, in_view = safe(p.targets), safe(p.ctx_view)
    targets = {(p.track, v) for _, v in values(J, p.track) if is_target(v)}
    ctx = {(p.ctx_track, v) for _, v in values(J, p.ctx_track) if in_view(v)}
    if p.spaces:
        targets |= {("sp", v) for v in SP if is_target(v)}
        ctx |= {("sp", v) for v in SP if in_view(v)}
    ctx |= targets                       # a target counts as the previous value too
    by_mapping = defaultdict(set)
    results = defaultdict(set)
    for cf, cv in ctx | {(None, None)}:
        m = {}
        for tf, tv in targets:
            try:
                nv = p.fn(cv, tv)
            except (TypeError, IndexError, KeyError, P.Impossible):     # a previous value that can't come before this target
                continue
            m[font.glyph(tf, tv)] = font.glyph(tf, nv)
            results[(tf, tv)].add(nv)
        m = tuple(sorted(changed(m).items()))
        by_mapping[m].add(None if cf is None else font.glyph(cf, cv))
    default = next((dict(m) for m, glyphs in by_mapping.items() if None in glyphs), {})
    rules = []
    for m, glyphs in by_mapping.items():
        glyphs = glyphs - {None}
        m = dict(m)
        if glyphs and m != default:
            # what the default would change, kept as it is
            rules.append(({g: m.get(g, g) for g in set(m) | set(default)}, [glyphs], []))
    if default:
        rules.append((default, [], []))
    sees = {font.glyph(f, v) for f, v in ctx}
    if any(r[0] for r in rules):
        others = {font.glyph(p.track, v) for _, v in values(J, p.track)} - {font.glyph(f, v) for f, v in targets}
        if not (p.ctx_track != p.track and forward_context(font, p, by_mapping, default, targets, results, sees, others)):
            font.reverse(rules, sees)
    track_results = {v: results[(f, v)] for f, v in targets if f != "sp"}
    newSP = set()
    for v in SP:
        newSP |= results[("sp", v)] if p.spaces and is_target(v) else {v}
    return map_values(J, p.track, track_results), newSP


def forward_context(font, p, by_mapping, default, targets, results, sees, others):
    """A Context on another track as a format 2 lookup, applied left to
    right, so the previous target may already have its new value: allowed
    where fn gives the same for it as for its old value, and where no new
    value is also a value the track holds that isn't a target (`others`),
    which the lookup would then take for one. Returns whether it could be
    done."""
    if any(font.glyph(tf, nv) in others for tf, tv in targets for nv in results[(tf, tv)]
           if nv != tv):
        return False
    group_of = {}
    for i, (m, glyphs) in enumerate(by_mapping.items()):
        for g in glyphs - {None}:
            group_of[g] = i
    back_cd = {g: i + 1 for g, i in group_of.items()}
    for tf, tv in targets:
        g = font.glyph(tf, tv)
        for nv in results[(tf, tv)]:
            o = font.glyph(tf, nv)
            if o == g:
                continue
            if o in back_cd and back_cd[o] != back_cd.get(g):
                return False
            for xf, xv in targets:
                try:
                    if p.fn(nv, xv) != p.fn(tv, xv):
                        return False
                except (TypeError, IndexError, KeyError, P.Impossible):
                    return False
            if g in back_cd:
                back_cd[o] = back_cd[g]
    rules = []
    for i, (m, glyphs) in enumerate(by_mapping.items()):
        m = dict(m)
        if glyphs - {None} and m != default:
            rules.append(([i + 1], [], {g: m.get(g, g) for g in set(m) | set(default)}))
    if default:
        rules.append(([], [], default))
    outputs = {o for _, _, m in rules for o in m.values()}
    font.chain(back_cd, {}, rules, SKELETON, sees | outputs)
    return True


def compile_transducer(font, p, J, SP):
    """A transducer and the strip after it."""
    inputs = {}
    view = safe(p.view)
    for _, v in values(J, p.track):
        if view(v):
            inputs[font.glyph(p.track, v)] = (p.track, v)
    if p.spaces:
        for v in SP:
            if view(v):
                inputs[font.glyph("sp", v)] = ("sp", v)
    temp = {}                            # (family, value, state) -> temporary glyph

    def step(state, sym):
        family, v = sym
        try:
            out, ns = p.step(state, v)
        except (TypeError, IndexError, KeyError, P.Impossible):   # an input that can't come in this state
            return mp.IMPOSSIBLE
        key = (family, out, ns)
        if key not in temp:
            temp[key] = font.temp_glyph(len(temp))
        return temp[key], ns
    run = font.pl.rtl if isinstance(p, P.RTL) else font.pl.ltr
    outputs, states = run(inputs, step, p.init)
    meaning = {g: key for key, g in temp.items()}
    font.pl.single({g: font.glyph(family, out) for (family, out, ns), g in temp.items()})
    outs = defaultdict(set)              # what each input can become
    for (g, s), o in outputs.items():
        outs[inputs[g]].add(meaning[o][1])
    newSP = set()
    for v in SP:
        newSP |= outs[("sp", v)] if ("sp", v) in outs else {v}
    font.stats.append((type(p).__name__, p.track, len(inputs), len(states), len(temp)))
    return map_values(J, p.track, {v: o for (f, v), o in outs.items() if f != "sp"}), newSP


def compile_insert(font, p, J, SP):
    """Virtual tokens: a Derive gives each character's glyph (for those
    before it) and its C track (for those after) a glyph of its own, which
    a multiple substitution then replaces with the token's glyph or track
    and the virtual tokens' five glyphs each."""
    def safe2(fn):
        def k(s, b):
            try:
                return tuple(fn(s, b))
            except (TypeError, IndexError, KeyError, P.Impossible):
                return ()
        return k
    before, after = safe2(p.before), safe2(p.after)
    J0 = J
    J, SP = compile_derive(font, P.Derive("G", ["S", "B"], lambda g, s, b: g + (before(s, b),) if before(s, b) else g),
                           J, SP)
    J, SP = compile_derive(font, P.Derive("C", ["S", "B"], lambda c, s, b: ("ins", after(s, b)) if after(s, b) else c),
                           J, SP)
    vg = font.glyph("G", ("g", "", "V"))

    def token(v):
        return [vg, font.glyph("S", v)] + [font.glyph(tr, P.BLANK) for tr in "ABC"]
    mapping = {}
    for s, sets in J.items():
        for g in sets["G"]:
            if len(g) > 3:
                mapping[font.glyph("G", g)] = [x for v in g[3] for x in token(v)] + [font.glyph("G", g[:3])]
        for c in sets["C"]:
            if c[0] == "ins":
                mapping[font.glyph("C", c)] = [font.glyph("C", P.BLANK)] + [x for v in c[1] for x in token(v)]
    font.pl.add(fb.lookup(2, [fb.multiple(mapping)]))
    out = {s: {tr: set(x) for tr, x in sets.items()} for s, sets in J0.items()}
    for s, sets in J0.items():
        for b in sets["B"]:
            for v in before(s, b) + after(s, b):
                merge_into(out, v, {"G": {("g", "", "V")}, "A": {P.BLANK}, "B": {P.BLANK}, "C": {P.BLANK}})
    return out, SP


# the first lookups: commands, then the tracks ----------------------------------

def commands(font):
    """\\frac and \\sqrt get their own backslash and letters; a symbol's
    backslash becomes the symbol's own glyph (until the final passes) and
    its letters hide."""
    b, cmap = font.b, font.cmap
    letters = {cmap[ord(c)] for c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"}
    hid = font.glyph("G", ("hid",))
    to_hid = font.pl.nested({g: hid for g in letters})
    lf = font.pl.nested({cmap[ord(c)]: font.char_glyph(("g", c, "Lf")) for c in "frac"})
    ls = font.pl.nested({cmap[ord(c)]: font.char_glyph(("g", c, "Ls")) for c in "sqrt"})
    names = list(L.COMMANDS) + list(L.SYMBOLS)
    rules = []
    bs = cmap[ord("\\")]
    for name in sorted(names, key=lambda n: -len(n)):
        seq = [{bs}] + [{cmap[ord(c)]} for c in name]
        if name in L.COMMANDS:
            tag, letter = ("F", lf) if name == "frac" else ("R", ls)
            head = font.char_glyph(("g", "\\", tag))
        else:
            tag = f"Y{1 + len(name)}"
            head = font.char_glyph(("g", L.SYMBOLS[name], tag))
            letter = to_hid
        first = font.pl.nested({bs: head})
        rules.append(([], seq, [letters], []))                  # a longer name: not this command
        rules.append(([], seq, [], [(0, first)] + [(k, letter) for k in range(1, len(seq))]))
    font.pl.add(fb.lookup(6, [font.pl.chain_rule(*r) for r in rules]))


def initial(font):
    """The joint domain before the passes, and the lookup that gives every
    character its tracks."""
    J = {}
    cmap = font.cmap
    blank = P.BLANK

    def add(g, s):
        merge_into(J, s, {"G": {g}, "A": {blank}, "B": {blank}, "C": {blank}})
    kinds = {"{": ("O",), "}": ("C",), "^": ("P",), "_": ("B",)}
    for ch in font.chars:
        add(("g", ch, None), kinds.get(ch, ("c",)))
    add(("g", "\\", "F"), ("F",))
    add(("g", "\\", "R"), ("R",))
    for c in "frac":
        add(("g", c, "Lf"), ("Lf",))
    for c in "sqrt":
        add(("g", c, "Ls"), ("Ls",))
    for name, ch in L.SYMBOLS.items():
        add(("g", ch, f"Y{1 + len(name)}"), ("Y", 1 + len(name)))
    mapping = {}
    for s, sets in J.items():
        for gv in sets["G"]:
            g = font.glyph("G", gv)
            mapping[g] = [g, font.glyph("S", s)] + [font.glyph(tr, blank) for tr in "ABC"]
    SP = {(" ",)}
    mapping[cmap[0x20]] = [font.glyph("sp", (" ",))]
    font.pl.add(fb.lookup(2, [fb.multiple(mapping)]))
    return J, SP


def relaxed_commands(font):
    """The relaxed notation's (relaxed.lex): a two-character symbol's first
    character becomes the symbol and the second hides; "sqrt(" after no
    letter, digit, point or "_" gets a root's glyphs, as \\sqrt has."""
    cmap = font.cmap
    hid = font.glyph("G", ("hid",))
    rules = []
    for two, sym in R.SYMBOLS.items():
        a, b = cmap[ord(two[0])], cmap[ord(two[1])]
        head = font.char_glyph(("g", sym, "Y2"))
        rules.append(([], [{a}, {b}], [], [(0, font.pl.nested({a: head})), (1, font.pl.nested({b: hid}))]))
    font.pl.add(fb.lookup(6, [font.pl.chain_rule(*r) for r in rules]))
    word = {cmap[ord(c)] for c in font.chars if c.isalnum() or c in "._"}
    seq = [{cmap[ord(c)]} for c in "sqrt"]
    paren = {cmap[ord("(")]}
    head = font.pl.nested({cmap[ord("s")]: font.char_glyph(("g", "s", "R"))})
    letters = font.pl.nested({cmap[ord(c)]: font.char_glyph(("g", c, "Ls")) for c in "qrt"})
    rules = [([word], seq, [paren], []),
             ([], seq, [paren], [(0, head)] + [(k, letters) for k in range(1, 4)])]
    font.pl.add(fb.lookup(6, [font.pl.chain_rule(*r) for r in rules]))


def relaxed_initial(font):
    """As initial(), with each character's class (front.char_class) for S."""
    J = {}
    cmap = font.cmap
    blank = P.BLANK

    def add(g, s):
        merge_into(J, s, {"G": {g}, "A": {blank}, "B": {blank}, "C": {blank}})
    for ch in font.chars:
        add(("g", ch, None), front.char_class(ch))
    add(("g", "s", "R"), ("R",))
    for c in "qrt":
        add(("g", c, "Ls"), ("Ls", c))
    for sym in R.SYMBOLS.values():
        add(("g", sym, "Y2"), ("Y",))
    mapping = {}
    for s, sets in J.items():
        for gv in sets["G"]:
            g = font.glyph("G", gv)
            mapping[g] = [g, font.glyph("S", s)] + [font.glyph(tr, blank) for tr in "ABC"]
    SP = {(" ",)}
    mapping[cmap[0x20]] = [font.glyph("sp", (" ",))]
    font.pl.add(fb.lookup(2, [fb.multiple(mapping)]))
    return J, SP


# GPOS --------------------------------------------------------------------------

def anchor(x, y):
    return otl.buildAnchor(round(x), round(y))


def gpos(font):
    b = font.b
    finals = dict(font.anchor)            # glyph -> descriptor
    gid = b.gid
    lookups = []
    sets = []

    top = []

    def lookup(kind, subtables, flag=0, glyphs=None, nested=False):
        lk = otl.buildLookup(subtables, flag | (FILTER if glyphs is not None else 0),
                             None if glyphs is None else font.pl.first_set + len(font.pl.mark_sets) + len(sets))
        if glyphs is not None:
            sets.append(set(glyphs))
        lookups.append(lk)
        if not nested:
            top.append(len(lookups) - 1)
        return len(lookups) - 1

    by_kind = defaultdict(dict)
    for g, v in finals.items():
        by_kind[v[0]][g] = v

    # heights in flow
    flow_bases = [g for g, v in finals.items()
                  if (v[0] in ("glyph", "radical") and v[-1] == "b") or v[0] in ("root", "qbase", "fendbase")]
    ys = by_kind["y"]
    rules = []
    for g, v in sorted(ys.items()):
        single = lookup(1, [otl.buildSinglePosSubtable({x: otl.buildValue({"YPlacement": v[1]}) for x in flow_bases}, b.ids)],
                        nested=True)
        rules.append(chain_pos([set(flow_bases)], [{g}], [(0, single)], font))
    if rules:
        lookup(8, rules, 0, set(ys) | set(flow_bases))
    # advances
    adv = {g: otl.buildValue({"XAdvance": v[1] * L.UNIT}) for g, v in by_kind["adv"].items()}
    adv.update({g: otl.buildValue({"XAdvance": 2 * v[1] * L.UNIT}) for g, v in by_kind["fendbase"].items()})
    if adv:
        lookup(1, [otl.buildSinglePosSubtable(adv, b.ids)])
    rules = []
    fendbases = set(by_kind["fendbase"])
    for g, v in sorted(by_kind["dx@fend"].items()):
        single = lookup(1, [otl.buildSinglePosSubtable({x: otl.buildValue({"XAdvance": (2 * v[1] + 4) * L.UNIT}) for x in fendbases}, b.ids)],
                        nested=True)
        rules.append(chain_pos([fendbases], [{g}], [(0, single)], font))
    if rules:
        lookup(8, rules, 0, set(by_kind["dx@fend"]) | fendbases)
    # marks on bases
    marks, bases = {}, {}
    for g, v in by_kind["dx@root"].items():
        marks[g] = (0, anchor(-v[1] * L.UNIT, 0))
    for g, v in by_kind["dx@fend"].items():
        marks[g] = (1, anchor(-v[1] * L.UNIT, 0))
    for g, v in by_kind["at@base"].items():
        marks[g] = (2, anchor(0, 0))
    for g in by_kind["root"]:
        bases[g] = {0: anchor(0, 0)}
    for g, v in by_kind["fendbase"].items():
        bases[g] = {1: anchor((2 + 2 * v[1]) * L.UNIT, 0)}
    for g in by_kind["qbase"]:
        bases[g] = {2: anchor(0, 0)}
    if marks and bases:
        lookup(4, [otl.buildMarkBasePosSubtable(marks, bases, b.ids)])
    # chains
    members = {}
    for g, v in finals.items():
        if v[0] in ("glyph", "radical") and v[-1] == "m":
            members[g] = anchor(0, 0)
        elif v[0] == "dx":
            members[g] = anchor(-v[1] * L.UNIT, 0)
        elif v[0] == "dy":
            members[g] = anchor(0, -v[1])
        elif v[0] == "dxy":
            members[g] = anchor(-v[1] * L.UNIT, -v[2])
    links = dict.fromkeys(list(members) + list(by_kind["dx@root"]))
    lookup(6, [mark_mark({g: (0, a) for g, a in members.items()}, {g: {0: anchor(0, 0)} for g in links}, gid)],
           0, set(members) | set(links))
    # ink
    inks = by_kind["ink"]
    movers = [g for g, v in finals.items() if v[0] in ("dx", "dy", "dxy", "dx@root", "dx@fend", "at@base")]
    ink_parents = {g: {0: anchor(0, 0)} for g in movers}
    for g, v in inks.items():
        _, band, direction, start, length, digit = v
        end = (start + (length if direction == "R" else -length)) * L.UNIT
        ink_parents[g] = {0: anchor(end, 0)}
    if inks:
        lookup(6, [mark_mark({g: (0, anchor(0, 0)) for g in inks}, ink_parents, gid)], 0, set(inks) | set(movers))
    t = newTable("GPOS")
    t.table = ot.GPOS()
    t.table.Version = 0x00010000
    t.table.LookupList = ot.LookupList()
    t.table.LookupList.Lookup = lookups
    t.table.LookupList.LookupCount = len(lookups)
    features_and_scripts(t.table, "mark", top)
    return t, sets


def chain_pos(back, inputs, records, font, ahead=None):
    """A format 3 chaining positioning rule. With back given as the input
    and inputs as the lookahead, as gpos() calls it."""
    st = ot.ChainContextPos()
    st.Format = 3
    st.BacktrackCoverage = []
    st.InputCoverage = [font.pl.coverage(back[0])]
    st.LookAheadCoverage = [font.pl.coverage(x) for x in inputs]
    st.BacktrackGlyphCount, st.InputGlyphCount, st.LookAheadGlyphCount = 0, 1, len(st.LookAheadCoverage)
    st.PosLookupRecord = []
    for pos, idx in records:
        r = ot.PosLookupRecord()
        r.SequenceIndex, r.LookupListIndex = pos, idx
        st.PosLookupRecord.append(r)
    st.PosCount = len(st.PosLookupRecord)
    return st


def mark_mark(marks, bases, gid):
    """MarkMarkPos format 1: marks {glyph: (class, anchor)} attach to
    the mark before them, bases {glyph: {class: anchor}}."""
    st = ot.MarkMarkPos()
    st.Format = 1
    m1 = sorted(marks, key=gid)
    m2 = sorted(bases, key=gid)
    st.Mark1Coverage = otl.buildCoverage(m1, {g: gid(g) for g in m1})
    st.Mark2Coverage = otl.buildCoverage(m2, {g: gid(g) for g in m2})
    classes = sorted({c for c, _ in marks.values()})
    st.ClassCount = len(classes)
    st.Mark1Array = otl.buildMarkArray({g: marks[g] for g in m1}, {g: gid(g) for g in m1})
    st.Mark2Array = ot.Mark2Array()
    st.Mark2Array.Mark2Record = []
    for g in m2:
        rec = ot.Mark2Record()
        rec.Mark2Anchor = [bases[g].get(c) for c in classes]
        st.Mark2Array.Mark2Record.append(rec)
    st.Mark2Array.Mark2Count = len(m2)
    return st


def features_and_scripts(table, tag, indices):
    table.FeatureList = ot.FeatureList()
    fr = ot.FeatureRecord()
    fr.FeatureTag = tag
    fr.Feature = ot.Feature()
    fr.Feature.FeatureParams = None
    fr.Feature.LookupListIndex = indices
    fr.Feature.LookupCount = len(indices)
    table.FeatureList.FeatureRecord = [fr]
    table.FeatureList.FeatureCount = 1
    table.ScriptList = ot.ScriptList()
    table.ScriptList.ScriptRecord = []
    for s in ("DFLT", "grek", "latn"):
        sr = ot.ScriptRecord()
        sr.ScriptTag = s
        sr.Script = ot.Script()
        ls = sr.Script.DefaultLangSys = ot.LangSys()
        ls.ReqFeatureIndex, ls.FeatureIndex, ls.FeatureCount = 0xFFFF, [0], 1
        sr.Script.LangSysRecord, sr.Script.LangSysCount = [], 0
        table.ScriptList.ScriptRecord.append(sr)
    table.ScriptList.ScriptCount = len(table.ScriptList.ScriptRecord)


# assembling ---------------------------------------------------------------------

def build(base=BASE, verbose=False, relaxed=False):
    return build_font(Font(base), verbose, relaxed)


def build_font(font, verbose=False, relaxed=False):
    """relaxed: the relaxed notation's font (relaxed.py, front.py)."""
    if relaxed:
        font.recycling = True
        relaxed_commands(font)
        J, SP = relaxed_initial(font)
        prog = front.front() + P.program(relaxed=True)
    else:
        commands(font)
        J, SP = initial(font)
        prog = P.program()
    J, SP = compile_program(font, prog, J, SP, verbose)
    if verbose:
        for m in font.mult:
            print("derive", *m)
        for s in font.stats:
            print("transducer", *s)
        subtables = sum(len(lk.SubTable) for lk in font.pl.lookups)
        print(f"{len(J)} kinds of token at the end, {len(font.b.order)} glyphs, {len(font.pl.lookups)} GSUB lookups "
              f"({len(font.pool)} pooled), {subtables} subtables, {font.rules} format 2 rules")
    gsub = fb.build_gsub(font.pl.lookups, font.pl.top, feature="calt", scripts=("DFLT", "grek", "latn"))
    gp, gp_sets = gpos(font)
    return finish(font, gsub, gp, gp_sets, "Fontlex Relaxed Math" if relaxed else "Fontlex Math")


def finish(font, gsub, gp, gp_sets, family="Fontlex Math"):
    b = font.b
    f = b.font
    b._clear_bad_window(gsub)
    f.setGlyphOrder(b.order)
    b.glyf.glyphOrder = b.order
    for name, g in b.glyphs.items():
        b.glyf[name] = g
        b.hmtx[name] = b.metrics[name]
    for name, g in b.glyphs.items():
        # A scaled glyph's (or a drawn one's) left side bearing is its left
        # edge: Chrome on macOS clips the glyph there.
        if g.isComposite() or g.numberOfContours > 0:
            g.recalcBounds(b.glyf)
            b.hmtx[name] = (b.metrics[name][0], g.xMin)
    gdef = f["GDEF"].table
    cd = gdef.GlyphClassDef.classDefs
    for name in b.order:
        cd[name] = b.classes.get(name, cd.get(name) or 1)
    if gdef.Version < 0x00010002 or gdef.MarkGlyphSetsDef is None:
        gdef.Version = 0x00010002
        gdef.MarkGlyphSetsDef = ot.MarkGlyphSetsDef()
        gdef.MarkGlyphSetsDef.MarkSetTableFormat = 1
        gdef.MarkGlyphSetsDef.Coverage = []
    assert len(gdef.MarkGlyphSetsDef.Coverage) == font.pl.first_set
    for glyphs in font.pl.mark_sets + gp_sets:
        cov = ot.Coverage()
        cov.glyphs = sorted(glyphs, key=b.gid)
        gdef.MarkGlyphSetsDef.Coverage.append(cov)
    gdef.MarkGlyphSetsDef.MarkSetCount = len(gdef.MarkGlyphSetsDef.Coverage)
    if hasattr(gdef, "MarkAttachClassDef"):
        gdef.MarkAttachClassDef = None
    f["GSUB"] = gsub
    f["GPOS"] = gp
    post = f["post"]
    post.formatType = 2.0
    post.extraNames, post.mapping = [], {}
    import fontlex
    fontlex.set_family_name(f, family)
    return f


def tuples(x):
    return tuple(tuples(y) for y in x) if isinstance(x, list) else x


class Placed:
    """What gpos() needs of a Font, read back from a built font and its
    sidecar (OUT.json), to rebuild only GPOS."""
    def __init__(self, font, side):
        order = font.getGlyphOrder()
        self.anchor = {name: tuples(d) for name, d in side["finals"]}
        self.b = type("B", (), {})()
        self.b.ids = {name: i for i, name in enumerate(order)}
        self.b.gid = self.b.ids.__getitem__
        self.pl = type("PL", (), {})()
        self.pl.first_set, self.pl.mark_sets = side["gsub_sets"], []
        self.pl.coverage = lambda glyphs: mp.Pipeline.coverage(self.pl, glyphs)
        self.pl.gid = self.b.gid


def rebuild_gpos(path):
    import json
    f = TTFont(path)
    side = json.load(open(path + ".json"))
    placed = Placed(f, side)
    gp, sets = gpos(placed)
    gdef = f["GDEF"].table
    cov = gdef.MarkGlyphSetsDef.Coverage[:side["gsub_sets"]]
    for glyphs in sets:
        c = ot.Coverage()
        c.glyphs = sorted(glyphs, key=placed.b.gid)
        cov.append(c)
    gdef.MarkGlyphSetsDef.Coverage, gdef.MarkGlyphSetsDef.MarkSetCount = cov, len(cov)
    f["GPOS"] = gp
    return f


def main():
    import json
    if os.environ.get("PYTHONHASHSEED") != "0":
        # the same font every time: set order follows string hashes
        os.environ["PYTHONHASHSEED"] = "0"
        os.execv(sys.executable, [sys.executable] + sys.argv)
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out")
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--sidecar", action="store_true", help="also write OUT.json, for --gpos-only")
    ap.add_argument("--gpos-only", action="store_true", help="rebuild only OUT's GPOS (from OUT.json)")
    ap.add_argument("--relaxed", action="store_true", help="the relaxed notation's font (relaxed.py)")
    args = ap.parse_args()
    if args.gpos_only:
        f = rebuild_gpos(args.out)
    else:
        font = Font(args.base)
        f = build_font(font, verbose=True, relaxed=args.relaxed)
        if args.sidecar:
            json.dump({"gsub_sets": font.pl.first_set + len(font.pl.mark_sets),
                       "finals": sorted([name, d] for name, d in font.anchor.items())},
                      open(args.out + ".json", "w"))
    f.save(args.out)
    f.flavor = "woff2"
    f.save(os.path.splitext(args.out)[0] + ".woff2")
    print(f"wrote {args.out} and .woff2: {len(f.getGlyphOrder())} glyphs, {os.path.getsize(args.out)} bytes")


if __name__ == "__main__":
    main()
