"""Cascades: passes that read what earlier passes wrote, and what they let a
font compute.

    python theory/cascade.py serial                # the link-tail machine as a cascade: a minute or two
    python theory/cascade.py slots tails           # split.py's splits with their states on inserted glyphs
    python theory/cascade.py ruler 80 - 10 4x4     # mark every character past column 80
    python theory/cascade.py iban                  # underline an IBAN whose check digits are wrong

serial: a partition of a machine's states has the substitution property
(Hartmanis and Stearns) when the transitions respect its blocks: states in
one block go to one block on every character. Such a partition runs the
machine as two passes. The front runs it on blocks and writes, at each
character, the block of its right neighbor; the back reads that and finds
the state within the block, so it needs as many states as the largest
block. The script finds every such partition of the one-pass link-tail
machine (split.py's, 364 states) as the closures of pairs of states, and
builds the cheapest cascade (fewest states in all).

slots: a pass records its state in a variant of each character, so a pass
of s states over a characters needs up to s*a glyphs. Instead, a multiple
substitution can insert one empty glyph (a slot) after each character, and
the pass writes its state there: s glyphs, shared by every character. The
script builds split.py's splits both ways, one slot per pass.

ruler: on slots, a pass can see every character the font has. One pass
counts to n; a cascade counts units mod m, then the carries. Radices are
written 10 or 4x4; `-` is the single pass.

iban: three passes in alternating directions: the BBAN mod 97 left to right,
then the remainder carried to the front and the first four characters folded
in right to left, then the verdict carried back over the number. Built on
variants of each character and on slots.

Every font is checked in each shaper against a Python reference, and timed
(nanoseconds per character in the shaper, the fastest of nine interleaved
runs).
"""

import argparse
import io
import math
import os
import random
import string
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import split  # noqa: E402  (also puts the project and markdown/ on the path)

BASE = split.BASE
LOOKUP_SUBTABLES = 6552    # a lookup's subtables, behind 16-bit offsets at 10 bytes each


# serial decomposition -----------------------------------------------------

def closure(table, s, t):
    """The finest partition with the substitution property that puts s and t
    in one block, as a block number per state."""
    parent = list(range(len(table)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    todo = [(s, t)]
    while todo:
        a, b = (find(x) for x in todo.pop())
        if a != b:
            parent[b] = a
            # A block's representative stands for all of it: every member's
            # successors were merged with the representative's when it joined.
            todo.extend(zip(table[a], table[b]))
    number = {}
    return tuple(number.setdefault(find(x), len(number)) for x in range(len(table)))


def _closures(table, firsts):
    found = set()
    for s in firsts:
        for t in range(s + 1, len(table)):
            lab = closure(table, s, t)
            if max(lab) > 0:
                found.add(lab)
    return found


def sp_partitions(table, workers):
    """Every nontrivial pair closure, cheapest cascade first: fewest states
    in front and back together (blocks plus the largest block)."""
    shares = [range(i, len(table), workers) for i in range(workers)]
    found = set()
    with ProcessPoolExecutor(workers) as ex:
        for part in ex.map(_closures, [table] * workers, shares):
            found |= part

    def cost(lab):
        sizes = {}
        for blk in lab:
            sizes[blk] = sizes.get(blk, 0) + 1
        return (len(sizes) + max(sizes.values()), len(sizes), lab)
    return sorted(found, key=cost)


def build_serial(inst, p, lab):
    """The font for machine p run as front (on lab's blocks) and back; the
    trigger ends up as `_answer<a>` as in split.build()."""
    import fontbuild as fb
    import passes
    b = fb.FontBuilder(str(BASE))
    cmap = b.font.getBestCmap()
    pl = passes.Pipeline(b)
    char = {cmap[ord(ch)]: ch for ch in inst.alphabet}
    index = {ch: i for i, ch in enumerate(inst.alphabet)}
    trig_c = index[inst.trigger]
    members = {}
    for s, blk in enumerate(lab):
        members.setdefault(blk, []).append(s)
    local = {s: members[lab[s]].index(s) for s in range(len(lab))}
    b0, i0 = lab[0], local[0]
    front = {lab[s]: {c: lab[t] for c, t in enumerate(row)} for s, row in enumerate(p.table)}
    marks = {g: pl.var(g, ("x",)) for g in char}
    pl.single(marks)

    # The front's output names the right neighbor's block; a character left
    # as it is means the start block, there and here.
    def fstep(bn, sym):
        nb = front[bn][index[sym[0]]]
        return None if bn == nb == b0 else (("x", ("f", bn)), nb)
    fout, fstates = pl.rtl({g: (char[pl.base_of(g)], pl.kind_of(g)) for g in sorted(marks.values(), key=pl.gid)},
                           fstep, b0)
    tape = set(marks.values()) | set(fout.values())

    def bstep(idx, sym):
        ch, kind = sym
        bn = kind[1][1] if len(kind) > 1 else b0
        if idx >= len(members[bn]):
            return passes.IMPOSSIBLE
        q, c = members[bn][idx], index[ch]
        ans = p.answer[q] if c == trig_c else None
        ni = local[p.table[q][c]]
        return ("x",) + ((ans,) if ans is not None else ()) + (("s", ni),), ni
    pl.begin_temp()
    bout, bstates = pl.rtl({g: (char[pl.base_of(g)], pl.kind_of(g)) for g in sorted(tape, key=pl.gid)}, bstep, i0)
    strip = {o: pl.var(o, pl.kind_of(o)[:-1]) for o in set(bout.values())}
    pl.single(strip)
    pl.end_temp()
    trig = cmap[ord(inst.trigger)]
    shown = {a: b.composite(f"_answer{a}", [(trig, 0, 0)], b.advance(trig)) for a in sorted(set(inst.answers))}
    pl.single({g: shown[pl.kind_of(g)[1]] if len(pl.kind_of(g)) > 1 else pl.base_of(g) for g in strip.values()})
    return finish(b, pl, "Fontlex Cascade"), (len(fstates), len(bstates))


# slots --------------------------------------------------------------------

def build_slots(inst, passes_):
    """split.build() with each pass on its own slot after every character
    (a track): its inputs are the classes of characters it can't tell apart,
    its outputs one glyph per state (and answer), whatever the character."""
    import fontbuild as fb
    import passes
    b = fb.FontBuilder(str(BASE))
    cmap = b.font.getBestCmap()
    pl = passes.Pipeline(b)
    trig_c = inst.alphabet.index(inst.trigger)
    letter = {c: cmap[ord(ch)] for c, ch in enumerate(inst.alphabet)}
    tracks = []      # per pass: (classes, class glyph of each character, {(state, answer): glyph})
    for k, p in enumerate(passes_):
        cls = {}
        for c, ch in enumerate(inst.alphabet):
            cls.setdefault((tuple(row[c] for row in p.table), ch == inst.trigger), []).append(c)
        cl = list(cls.values())
        cg = {c: g for i, cs in enumerate(cl) for g in [b.empty(f"_p{k}c{i}", 0, gdef_class=3)] for c in cs}
        tracks.append((cl, cg, {}))
    pl.add(fb.lookup(2, [fb.multiple({letter[c]: [letter[c]] + [t[1][c] for t in tracks] for c in letter})]))
    for k, (p, (cl, cg, outs)) in enumerate(zip(passes_, tracks)):
        def out(q, c):
            key = (p.table[q][c], p.answer[q] if c == trig_c else None)
            if key not in outs:
                outs[key] = b.empty(f"_p{k}s{key[0]}a{key[1]}", 0, gdef_class=3)
            return outs[key]
        reps = [cs[0] for cs in cl]
        default = {cg[c]: out(0, c) for c in reps}
        rules = [(q, {cg[c]: out(q, c) for c in reps if out(q, c) != default[cg[c]]}) for q in range(1, len(p.table))]
        recording = {}
        for (ns, _), g in outs.items():
            recording.setdefault(ns, set()).add(g)
        # One subtable per state, as in passes.rtl(); the last, with no context, for the start state.
        pl.reverse([(m, (), (recording[q],)) for q, m in rules if m and q in recording] + [(default, (), ())],
                   set(cg.values()) | set(outs.values()))
    trig = letter[trig_c]
    shown = {a: b.composite(f"_answer{a}", [(trig, 0, 0)], b.advance(trig)) for a in sorted(set(inst.answers))}
    order = sorted(shown)
    for cl, cg, outs in tracks:
        # The trigger takes the least answer of any track: each track's
        # slot is the next glyph this lookup sees after the trigger.
        rules = []
        for a in order:
            with_a = {g for (_, ans), g in outs.items() if ans == a}
            if with_a:
                cur = [trig] + [shown[x] for x in order if x > a]
                rules.append(pl.chain_rule([], [set(cur)], [with_a], [(0, pl.nested({g: shown[a] for g in cur}))]))
        if rules:
            pl.add(fb.lookup(6, rules, 0, pl.mark_set(set(cg.values()) | set(outs.values()))))
    return finish(b, pl, "Fontlex Slots")


def check_slots(inst, shaper, order, text):
    """split.check() for a slot font: a character's first glyph is its own."""
    first = {}
    for g in shaper.shape(text)[0]:
        first.setdefault(g[1], order[g[0]])
    bad = []
    for i, ch in enumerate(text):
        name = first[i]
        got = name[len("_answer"):] if name.startswith("_answer") else None
        want = inst.reference(text, i) if ch == inst.trigger else None
        if got != (None if want is None else str(want)):
            bad.append(i)
    return bad


# a ruler ------------------------------------------------------------------

def build_ruler(n, radices):
    """A font in which every character at index >= n gets a bar under it,
    for every character the font has. Each character gets a slot; counters
    mod each radix run left to right, each advanced by the previous one's
    carries (the first by every character), and a last counter saturates
    at n over their product."""
    import fontbuild as fb
    import passes
    b = fb.FontBuilder(str(BASE))
    cmap = b.font.getBestCmap()
    pl = passes.Pipeline(b)
    span = math.prod(radices)
    assert n % span == 0, f"{n} isn't a multiple of {span}"
    top = n // span
    slot = b.empty("_slot", 0, gdef_class=3)
    adv = b.advance(cmap[ord("a")])
    bar = b.rect("_over", -adv, -260, 0, -200)
    letters = sorted(set(cmap.values()), key=b.gid)
    # WebKit gives every glyph of a space character the space's width, so a
    # space gets no slot after it: it becomes a slot of its own, which turns
    # back into the space (or an underlined one) at the end.
    spaces = {cmap[c]: b.empty(f"_space{c:x}", 0, gdef_class=3) for c in (0x20, 0xA0) if c in cmap}
    ins = {g: [g, slot] for g in letters if g not in spaces}
    ins.update({g: [s] for g, s in spaces.items()})
    pl.add(fb.lookup(2, [fb.multiple(ins)]))
    back = {s: g for g, s in spaces.items()}
    barred = {s: b.composite(f"_over{s}", [(g, 0, 0), (bar, adv, 0)], b.advance(g)) for s, g in back.items()}
    cur = {g: True for g in [slot, *back]}      # glyph -> carry in
    for m in radices:
        def step(v, carry, m=m):
            nv = (v + 1) % m if carry else v
            return ("w", m, nv, carry and nv == 0), nv
        out, _ = pl.ltr(cur, step, m - 1)
        cur = {o: pl.kind_of(o)[3] for o in set(out.values())}

    def last(t, carry):
        nt = min(t + 1, top) if carry else t
        return ("t", nt), nt
    out, _ = pl.ltr(cur, last, -1)
    final = {}
    for o in set(out.values()):
        base, hit = pl.base_of(o), pl.kind_of(o)[1] == top
        final[o] = (barred[base] if hit else back[base]) if base in back else bar if hit else slot
    pl.single(final)
    return finish(b, pl, "Fontlex Ruler"), sum(radices) + top + 1, len(letters)


def ruler_chars():
    """Characters to test with: those the base font has, but no combining
    marks or controls, and spaces often."""
    from fontTools.ttLib import TTFont
    cmap = TTFont(str(BASE)).getBestCmap()
    return [chr(c) for c in sorted(cmap) if chr(c).isprintable() and not chr(c).isspace()
            and not 0x300 <= c < 0x370] + [" "] * 20


def random_lines(chars, count, seed, lo, hi):
    rng = random.Random(seed)
    return ["".join(rng.choice(chars) for _ in range(rng.randint(lo, hi))) for _ in range(count)]


def ruler_wrong(shaper, order, text, n):
    barred = {g[1] for g in shaper.shape(text)[0] if order[g[0]].startswith("_over")}
    return barred != set(range(n, len(text)))


# an IBAN check ------------------------------------------------------------

ALNUM = string.digits + string.ascii_uppercase + string.ascii_lowercase


def value(ch):
    return int(ch) if ch.isdigit() else ord(ch.upper()) - ord("A") + 10


def iban_valid(text):
    s = text.replace(" ", "")
    if len(s) < 5 or not (s[:2].isalpha() and s[2:4].isdigit()):
        return False
    return int("".join(str(value(ch)) for ch in s[4:] + s[:4])) % 97 == 1


def build_iban(slots):
    """Underline every character of an IBAN (letters, digits, and spaces
    skipped) whose check digits are wrong. With `slots`, the passes run on
    one slot after each character; without, on variants of the characters."""
    import fontbuild as fb
    import passes
    b = fb.FontBuilder(str(BASE))
    cmap = b.font.getBestCmap()
    pl = passes.Pipeline(b)
    letters = {cmap[ord(ch)]: ch for ch in ALNUM}
    made, kinds = {}, {}

    def emit(kind):
        """A pass's output: the kind itself (a variant of the character), or
        on slots one glyph per kind."""
        if not slots:
            return kind
        if kind not in made:
            made[kind] = b.empty("_" + "_".join(map(str, kind)), 0, gdef_class=3)
            kinds[made[kind]] = kind
        return made[kind]
    kind_of = kinds.get if slots else pl.kind_of
    if slots:
        inputs = {emit(("in", v)): v for v in range(36)}
        pl.add(fb.lookup(2, [fb.multiple({g: [g, emit(("in", value(ch)))] for g, ch in letters.items()})]))
    else:
        marks = {g: pl.var(g, ("x",)) for g in letters}
        pl.single(marks)
        inputs = {m: value(letters[g]) for g, m in marks.items()}

    # 1. Left to right: the first four characters' places (two letters, two
    # digits), then the BBAN's remainder mod 97, by Horner's rule (a letter
    # counts as two digits).
    def head(s, v):
        if s == "bad":
            return emit(("bad",)), "bad"
        if s[0] == "p":
            k = s[1]
            if (k < 2) != (v >= 10):
                return emit(("bad",)), "bad"
            return emit(("h", k, v)), ("p", k + 1) if k < 3 else ("r", 0)
        r = (s[1] * (10 if v < 10 else 100) + v) % 97
        return emit(("b", r)), ("r", r)
    out, st1 = pl.ltr(inputs, head, ("p", 0))
    # 2. Right to left: the last character's remainder carried to the front,
    # where the rearranged number BBAN + first four is r * 10^6 + their value.
    weight = {3: 1, 2: 10, 1: 100, 0: 10000}

    def fold(s, kind):
        if s == "bad" or kind == ("bad",):
            return emit(("B",)), "bad"
        if kind[0] == "b":
            if s == "end":
                return emit(("X", kind[1])), ("X", kind[1])
            return (emit(("X", s[1])), s) if s[0] == "X" else (emit(("B",)), "bad")
        _, k, v = kind
        if s == "end" or (k == 3) != (s[0] == "X") or s[0] == "V":
            return emit(("B",)), "bad"
        acc = ((s[1] * 10 ** 6 if k == 3 else s[1]) + v * weight[k]) % 97
        if k == 0:
            return emit(("V", acc == 1)), ("V", acc == 1)
        return emit(("A", acc)), ("A", acc)
    out, st2 = pl.rtl({o: kind_of(o) for o in set(out.values())}, fold, "end")

    # 3. Left to right: the first character's verdict to every character.
    def carry(s, kind):
        ok = kind == ("V", True) if s == "start" else s
        return emit(("ok",) if ok else ("err",)), ok
    out, st3 = pl.ltr({o: kind_of(o) for o in set(out.values())}, carry, "start")
    adv = b.advance(cmap[ord("0")])
    if slots:
        pl.single({emit(("err",)): b.rect("_wrong", -adv, -260, 0, -200)})
    else:
        line = b.rect("_underline", 0, -260, adv, -200)
        pl.single({o: pl.base_of(o) if pl.kind_of(o) == ("ok",) else
                   b.composite(f"_wrong_{pl.base_of(o)}", [(pl.base_of(o), 0, 0), (line, 0, 0)], adv)
                   for o in set(out.values())})
    return finish(b, pl, "Fontlex IBAN"), [len(st1), len(st2), len(st3)]


def iban_samples(n, seed=1):
    """Valid IBANs of random countries and BBANs, a third with one character
    changed, a fifth with two neighbors swapped, some in lowercase, half in
    groups of four."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        cc = "".join(rng.choice(string.ascii_uppercase) for _ in range(2))
        bban = "".join(rng.choice(string.digits + string.ascii_uppercase) for _ in range(rng.randint(10, 30)))
        s = cc + f"{98 - int(''.join(str(value(ch)) for ch in bban + cc + '00')) % 97:02d}" + bban
        r = rng.random()
        if r < 0.3:
            i = rng.randrange(len(s))
            s = s[:i] + rng.choice(string.digits if s[i].isdigit() else string.ascii_uppercase) + s[i + 1:]
        elif r < 0.5:
            i = rng.randrange(len(s) - 1)
            s = s[:i] + s[i + 1] + s[i] + s[i + 2:]
        elif r < 0.6:
            s = s.lower()
        if rng.random() < 0.5:
            s = " ".join(s[i:i + 4] for i in range(0, len(s), 4))
        out.append(s)
    return out


def iban_wrong(shaper, order, text):
    names = {}
    for g in shaper.shape(text)[0]:
        names.setdefault(g[1], []).append(order[g[0]])
    flagged = [any(n.startswith("_wrong") for n in names[i]) for i, ch in enumerate(text) if ch != " "]
    return flagged != [not iban_valid(text)] * len(flagged)


# shared -------------------------------------------------------------------

def finish(b, pl, family):
    """(font bytes, glyphs added, GSUB bytes)."""
    from fontTools.ttLib import TTFont
    font = b.finish(pl.gsub(), pl.mark_sets, family=family)
    buf = io.BytesIO()
    font.save(buf)
    data = buf.getvalue()
    tt = TTFont(io.BytesIO(data))
    return data, len(tt.getGlyphOrder()) - len(b.base_names), tt.reader.tables["GSUB"].length


def gsub_bytes(data):
    from fontTools.ttLib import TTFont
    return TTFont(io.BytesIO(data)).reader.tables["GSUB"].length


def shapers_for(data, names):
    import test_fontlex
    from fontTools.ttLib import TTFont
    return [test_fontlex.SHAPERS[s](data) for s in names], TTFont(io.BytesIO(data)).getGlyphOrder()


def timings(fonts, texts, rounds=9):
    """Nanoseconds per character for each font in each shaper: the fastest
    of `rounds` runs, taking the fonts in turn."""
    chars = sum(map(len, texts))
    best = {}
    for _ in range(rounds):
        for label, shapers in fonts.items():
            for i, shaper in enumerate(shapers):
                t0 = time.perf_counter()
                for t in texts:
                    shaper.shape(t)
                best[label, i] = min(best.get((label, i), float("inf")), time.perf_counter() - t0)
    return {label: [best[label, i] / chars * 1e9 for i in range(len(shapers))] for label, shapers in fonts.items()}


def long_lines(inst, n):
    texts = split.lines(inst, n, seed=2)
    return [" ".join(texts[i:i + 40]) for i in range(0, len(texts), 40)]


def table(rows, times, shapers):
    head = f"{'':22} {'passes':>6} {'states':>7} {'glyphs':>7} {'GSUB KB':>8}" + \
        "".join(f" {'ns/char ' + s[:2]:>10}" for s in shapers)
    print(head)
    for label, passes_, states, built, gsub, wrong in rows:
        line = f"{label:22} {passes_:6} {states:7} "
        if built is None:
            line += f"{'':7} {'':8}  {gsub}"
        else:
            line += f"{built:7} {gsub / 1024:8.0f}" + "".join(f" {t:10.0f}" for t in times[label])
            if any(wrong):
                line += "  wrong: " + ", ".join(f"{w} in {s}" for w, s in zip(wrong, shapers) if w)
        print(line)
    return 1 if any(any(r[5]) for r in rows if r[3] is not None) else 0


# commands -----------------------------------------------------------------

def serial(args, shapers):
    inst = split.tails_instance()
    k = len(inst.machines)
    p = split.group_pass(inst.machines, inst.answers, tuple(range(k)), inst.alphabet.index(inst.trigger))
    t0 = time.perf_counter()
    parts = sp_partitions(p.table, args.workers)
    print(f"link tails: one pass of {len(p.table)} states; {len(parts)} partitions with the substitution "
          f"property, found in {time.perf_counter() - t0:.0f} s")
    for lab in parts[:3]:
        sizes = [lab.count(x) for x in set(lab)]
        print(f"  {len(sizes)} blocks, the largest of {max(sizes)}: front and back {len(sizes) + max(sizes)} states")
    texts = split.lines(inst, args.lines)
    rows, fonts = [], {}
    (data, built, gsub), (fs, bs) = build_serial(inst, p, parts[0])
    label = f"cascade, {fs} + {bs}"
    fonts[label], order = shapers_for(data, shapers)
    rows.append((label, 2, fs + bs, built, gsub,
                 [sum(bool(split.check(inst, s, order, t)) for t in texts) for s in fonts[label]]))
    by_group = split.all_passes(inst, 1)
    for label, spl in split.choices(inst, by_group):
        if label in ("one pass", "by hand", "best of 2"):
            data, built, _ = split.build(inst, spl)
            fonts[label], order = shapers_for(data, shapers)
            rows.append((label, len(spl), sum(len(q.table) for q in spl), built, gsub_bytes(data),
                         [sum(bool(split.check(inst, s, order, t)) for t in texts) for s in fonts[label]]))
    return table(rows, timings(fonts, long_lines(inst, args.lines)), shapers)


def slots(args, shapers):
    inst = split.INSTANCES[args.instance]()
    by_group = split.all_passes(inst, args.workers if args.instance == "html" else 1)
    texts = split.lines(inst, args.lines)
    rows, fonts = [], {}
    for label, spl in split.choices(inst, by_group):
        if label not in ("one pass", "by hand", "best of 2", "best of 5"):
            continue
        states = sum(len(q.table) for q in spl)
        for mode in ("variants", "slots"):
            name = f"{label}, {mode}"
            if mode == "variants" and split.glyphs(spl) + 2000 > split.GLYPH_LIMIT:
                rows.append((name, len(spl), states, None, f"{split.glyphs(spl):,} glyphs: doesn't fit", []))
                continue
            if mode == "slots" and max(len(q.table) for q in spl) > LOOKUP_SUBTABLES:
                rows.append((name, len(spl), states, None,
                             f"a pass of {max(len(q.table) for q in spl):,} states: more subtables than a lookup "
                             f"can address ({LOOKUP_SUBTABLES:,})", []))
                continue
            if mode == "variants":
                data, built, _ = split.build(inst, spl)
                gsub = gsub_bytes(data)
            else:
                data, built, gsub = build_slots(inst, spl)
            fonts[name], order = shapers_for(data, shapers)
            check = split.check if mode == "variants" else check_slots
            rows.append((name, len(spl), states, built, gsub,
                         [sum(bool(check(inst, s, order, t)) for t in texts) for s in fonts[name]]))
    return table(rows, timings(fonts, long_lines(inst, args.lines)), shapers)


def ruler(args, shapers):
    chars = ruler_chars()
    n = args.n
    texts = random_lines(chars, args.lines, 1, 0, 2 * n + 40)
    rows, fonts = [], {}
    for spec in args.radices or ["-"]:
        radices = [] if spec == "-" else [int(x) for x in spec.split("x")]
        (data, built, gsub), states, letters = build_ruler(n, radices)
        label = "one pass" if not radices else f"{spec}, then {n // math.prod(radices)}"
        fonts[label], order = shapers_for(data, shapers)
        rows.append((label, len(radices) + 1, states, built, gsub,
                     [sum(ruler_wrong(s, order, t, n) for t in texts) for s in fonts[label]]))
    print(f"past column {n}, for all {letters:,} characters of the base font "
          f"(a pass on variants of each would need {(n + 1) * letters:,} glyphs)")
    return table(rows, timings(fonts, random_lines(chars, 200, 2, n, 2 * n)), shapers)


def iban(args, shapers):
    texts = iban_samples(args.lines)
    print(f"{sum(map(iban_valid, texts))} of {len(texts)} samples valid")
    rows, fonts = [], {}
    for label, on_slots in (("variants", False), ("slots", True)):
        (data, built, gsub), states = build_iban(on_slots)
        fonts[label], order = shapers_for(data, shapers)
        rows.append((label, 3, sum(states), built, gsub,
                     [sum(iban_wrong(s, order, t) for t in texts) for s in fonts[label]]))
    return table(rows, timings(fonts, texts), shapers)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--shaper", action="append", choices=["harfbuzz", "coretext"])
    ap.add_argument("--lines", type=int, default=2000, help="random lines to check and time (default 2000)")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("serial")
    sp = sub.add_parser("slots")
    sp.add_argument("instance", choices=sorted(split.INSTANCES))
    sp = sub.add_parser("ruler")
    sp.add_argument("n", type=int)
    sp.add_argument("radices", nargs="*", help="10, 4x4, ...; - for one pass")
    sub.add_parser("iban")
    args = ap.parse_args()
    shapers = args.shaper or ["harfbuzz"]
    return {"serial": serial, "slots": slots, "ruler": ruler, "iban": iban}[args.command](args, shapers)


if __name__ == "__main__":
    sys.exit(main())
