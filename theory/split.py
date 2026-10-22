"""How to split a lexer into font passes, for lexers that ask which of k
constructs starts here.

    python theory/split.py tails                       # link destinations: seconds
    python theory/split.py html                        # raw HTML and autolinks: about a minute
    python theory/split.py tails --build --shaper harfbuzz --shaper coretext

Both are questions Fontlex Markdown asks (markdown/tails.py,
markdown/htmlauto.py), here over printable ASCII alone. Does a link
destination of one of 8 forms follow this `]`? Which of 8 kinds of raw HTML
or autolink starts at this `<` (the first in commonmark.js's order)? Each is
k recognizers read right to left, whose answers at the trigger combine.

A split is a partition of the k recognizers into passes. Each pass runs
the product of its group, minimized against the group's answer. The passes
are independent, so their order doesn't matter, and a pass's states are
temporary glyphs that the next pass reuses (the pool in passes.py). So a
split costs, for each character, the most variants any one of its passes
gives that character, summed over characters. Passes cost lookups and time
instead. The script compares:

- one pass: the whole product, minimized (ordinary state minimization);
- by hand: one pass per recognizer, as Fontlex Markdown does;
- the cheapest split for each number of passes, found by trying every
  partition (4,140 of 8 recognizers).

--build compiles a font for each one that fits, checks it against the
automata on random lines in each shaper, and measures its glyphs, GSUB
bytes and shaping time. "states" is the sum over the passes; "glyphs" and
"rules" are the model's counts, "built" the glyphs the font adds.
"""

import argparse
import io
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "markdown"))
import htmlauto  # noqa: E402
import tails  # noqa: E402

BASE = HERE.parent / "fonts" / "JetBrainsMono-Regular.ttf"
GLYPH_LIMIT = 65535
TAIL_CHARS = "()\"'<> "


class Instance:
    """k recognizers over `alphabet`, read right to left. back(j, R, c) is
    recognizer j's step; at the trigger, recognizer j answers answer[j] when
    found(j, R). A group answers the least of its recognizers' answers."""

    def __init__(self, name, names, back, found, answers, alphabet, trigger, reference, pieces):
        self.name, self.names, self.alphabet, self.trigger = name, names, alphabet, trigger
        self.reference, self.pieces = reference, pieces
        self.machines = [recognizer(lambda R, c, j=j: back(j, R, c), lambda R, j=j: found(j, R), alphabet)
                         for j in range(len(names))]
        self.answers = answers


def tails_instance():
    autos = [tails.Automaton(form, 3) for form in tails.FORMS]

    def reference(text, i):
        q = "S0"
        for c in text[i + 1:]:
            q = tails.step(q, c if c in TAIL_CHARS else "O", 3)
            if q in (tails.ACC, None):
                return True if q else None
        return None
    pieces = ["](", "]", "(", ")", " ", '"', "'", "<", ">", "a", "aa", "](a)", "](<a>)", '](a "a")',
              "](a 'a')", "](a (a))", "](<a> 'a')", "]((a))", "](a(a)a)", "](a\n"]
    # "a" stands for every character the automaton doesn't tell apart.
    return Instance("tails", ["/".join(map(str, f)) for f in tails.FORMS],
                    lambda j, R, c: autos[j].back(R, c if c in TAIL_CHARS else "O"),
                    lambda j, R: autos[j].start in R, [True] * len(autos), list(TAIL_CHARS + "]a"), "]",
                    reference, [p.rstrip("\n") for p in pieces])


def html_instance():
    backs = [htmlauto.Backward(step) for _, step in htmlauto.KINDS]

    def reference(text, i):
        for k, (_, step) in enumerate(htmlauto.KINDS):
            q = "<"
            for c in text[i + 1:]:
                q = step(q, c)
                if q in (htmlauto.ACC, None):
                    break
            if q == htmlauto.ACC:
                return k
        return None
    pieces = ["<", ">", "a", "b", " ", "/", "-", "!", "?", '"', "'", "=", ":", "@", ".", "[", "]", "<a>",
              '<a href="x">', "<b c='d' e=f/>", "</a>", "</b >", "<!-- x -->", "<!-->", "<!--->", "<?x ?>",
              "<!DOCTYPE x>", "<![CDATA[ x ]]>", "<http://a.b/c>", "<a@b.co>", "<a-b@c-d.e>"]
    return Instance("html", [n for n, _ in htmlauto.KINDS], lambda j, R, c: backs[j].back(R, c),
                    lambda j, R: "<" in R, list(range(len(backs))), [chr(c) for c in range(0x20, 0x7F)], "<",
                    reference, pieces)


INSTANCES = {"tails": tails_instance, "html": html_instance}


# machines -----------------------------------------------------------------

def recognizer(back, found, alphabet):
    """A recognizer's right-to-left machine, minimized: (table, found),
    state 0 having read nothing; table[s][c] is the state after reading
    alphabet[c] in state s, found[s] whether the construct starts at a
    trigger read in state s."""
    init = frozenset()
    ids, todo, table, out = {init: 0}, [init], [], []
    while todo:
        R = todo.pop(0)
        row = []
        for c in alphabet:
            n = back(R, c)
            if n not in ids:
                ids[n] = len(ids)
                todo.append(n)
            row.append(ids[n])
        table.append(row)
        out.append(found(R))
    return minimize(table, out)


def minimize(table, out):
    """The minimal machine (Moore's refinement): states with the same output
    whose successors are equivalent merge. State 0 stays state 0."""
    cls, count = list(out), None
    while True:
        sig = {}
        new = [sig.setdefault((cls[s],) + tuple(cls[t] for t in row), len(sig)) for s, row in enumerate(table)]
        if len(sig) == count:
            break
        cls, count = new, len(sig)
    number, rep = {cls[0]: 0}, {}
    for s in range(len(table)):
        rep.setdefault(number.setdefault(cls[s], len(number)), s)
    return ([[number[cls[t]] for t in table[rep[i]]] for i in range(len(number))],
            [out[rep[i]] for i in range(len(number))])


class Pass:
    """One pass: the product of a group's recognizers, minimized against the
    group's answer. variants[c]: the glyphs it gives alphabet[c] (outputs
    other than the start state's, which leave the glyph as it is); rules:
    the (state, character) pairs whose output differs from the start state's,
    one reverse chaining rule entry each."""

    def __init__(self, group, table, answer, trigger):
        self.group, self.table, self.answer = group, table, answer
        self.variants = []
        for c in range(len(table[0])):
            outs = {(answer[s] if c == trigger else None, row[c]) for s, row in enumerate(table)}
            self.variants.append(len(outs - {(None, 0)}))
        start = lambda s, c: (answer[s] if c == trigger else None, table[s][c])
        self.rules = sum(start(s, c) != start(0, c) for s in range(1, len(table)) for c in range(len(table[0])))


def group_pass(machines, answers, group, trigger):
    ms = [machines[j] for j in group]
    init = (0,) * len(group)
    ids, todo, table, answer = {init: 0}, [init], [], []
    while todo:
        s = todo.pop(0)
        row = []
        for c in range(len(ms[0][0][0])):
            n = tuple(m[0][q][c] for m, q in zip(ms, s))
            if n not in ids:
                ids[n] = len(ids)
                todo.append(n)
            row.append(ids[n])
        table.append(row)
        answer.append(min((answers[j] for j, m, q in zip(group, ms, s) if m[1][q]), default=None))
    return Pass(group, *minimize(table, answer), trigger)


def all_passes(inst, workers):
    """A Pass for every nonempty group of recognizers."""
    k, trig = len(inst.machines), inst.alphabet.index(inst.trigger)
    groups = [g for r in range(1, k + 1) for g in combinations(range(k), r)]
    args = [(inst.machines, inst.answers, g, trig) for g in groups]
    if workers > 1:
        with ProcessPoolExecutor(workers) as ex:
            return dict(zip(groups, ex.map(group_pass, *zip(*args), chunksize=4)))
    return {g: group_pass(*a) for g, a in zip(groups, args)}


def partitions(xs):
    if not xs:
        yield []
        return
    for p in partitions(xs[1:]):
        yield [(xs[0],)] + p
        for i in range(len(p)):
            yield p[:i] + [(xs[0],) + p[i]] + p[i + 1:]


def glyphs(split):
    """Pool glyphs: per character, the most any pass of the split needs."""
    return sum(max(p.variants[c] for p in split) for c in range(len(split[0].variants)))


def choices(inst, by_group):
    """(label, split) for one pass, by hand, and the cheapest split for each
    number of passes (fewest glyphs, then fewest rules)."""
    k = len(inst.machines)
    best = {}
    for part in partitions(list(range(k))):
        split = [by_group[tuple(sorted(g))] for g in part]
        cost = (glyphs(split), sum(p.rules for p in split))
        if len(split) not in best or cost < best[len(split)][0]:
            best[len(split)] = (cost, split)
    out = [("one pass", [by_group[tuple(range(k))]]), ("by hand", [by_group[(j,)] for j in range(k)])]
    return out + [(f"best of {n}", best[n][1]) for n in sorted(best) if 1 < n < k]


# fonts --------------------------------------------------------------------

def build(inst, split):
    """The font for a split, as bytes: every character of the alphabet
    becomes a mark, each pass runs right to left over the marks, and the
    trigger ends up as glyph `_answer<a>` where the answer is a."""
    import fontbuild as fb
    import passes
    b = fb.FontBuilder(str(BASE))
    cmap = b.font.getBestCmap()
    pl = passes.Pipeline(b)
    char = {cmap[ord(ch)]: ch for ch in inst.alphabet}
    index = {ch: i for i, ch in enumerate(inst.alphabet)}
    marks = {g: pl.var(g, ("x",)) for g in char}
    pl.single(marks)
    alive = set(marks.values())
    for p in split:
        def step(s, sym, p=p):
            ch, kind = sym
            ns, out = p.table[s][index[ch]], kind
            if ch == inst.trigger and p.answer[s] is not None:
                out = ("x", min(kind[1:] + (p.answer[s],)))
            return None if ns == 0 and out == kind else (out + (("s", ns),), ns)
        pl.begin_temp()
        out, _ = pl.rtl({g: (char[pl.base_of(g)], pl.kind_of(g)) for g in sorted(alive, key=pl.gid)}, step, 0)
        strip = {o: pl.var(o, pl.kind_of(o)[:-1]) for o in set(out.values())}
        pl.single(strip)
        pl.end_temp()
        alive |= set(strip.values())
    trig = cmap[ord(inst.trigger)]
    shown = {a: b.composite(f"_answer{a}", [(trig, 0, 0)], b.advance(trig)) for a in sorted(set(inst.answers))}
    pl.single({g: shown[pl.kind_of(g)[1]] if len(pl.kind_of(g)) > 1 else pl.base_of(g) for g in alive})
    gsub = pl.gsub()
    font = b.finish(gsub, pl.mark_sets, family="Fontlex Split")
    buf = io.BytesIO()
    font.save(buf)
    return buf.getvalue(), len(font.getGlyphOrder()) - len(b.base_names), len(gsub.table.LookupList.Lookup)


def lines(inst, n, seed=1):
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        s, length = "", rng.randint(10, 100)
        while len(s) < length:
            s += rng.choice(inst.pieces) if rng.random() < 0.8 else rng.choice(inst.alphabet)
            if rng.random() < 0.1:
                i = rng.randrange(len(s))
                s = s[:i] + s[i + 1:]
        out.append(s)
    return out


def check(inst, shaper, order, text):
    """The positions where the font's answer differs from the automata's."""
    names = {g[1]: order[g[0]] for g in shaper.shape(text)[0]}
    bad = []
    for i, ch in enumerate(text):
        got = names[i][len("_answer"):] if names[i].startswith("_answer") else None
        want = inst.reference(text, i) if ch == inst.trigger else None
        if got != (None if want is None else str(want)):
            bad.append(i)
    return bad


def measure(inst, split, shapers, n):
    """Build the split's font and check it on n random lines in each shaper:
    (built glyphs, lookups, GSUB bytes, shapers, lines wrong)."""
    import test_fontlex
    from fontTools.ttLib import TTFont
    data, extra, lookups = build(inst, split)
    tt = TTFont(io.BytesIO(data))
    order = tt.getGlyphOrder()
    made = [test_fontlex.SHAPERS[name](data) for name in shapers]
    wrong = sum(bool(check(inst, shaper, order, t)) for shaper in made for t in lines(inst, n))
    return extra, lookups, tt.reader.tables["GSUB"].length, made, wrong


def timings(inst, fonts, n, rounds=9):
    """Nanoseconds per character for each font in each shaper, on lines of
    about 2,000 characters (the shaper's work, not the call's): the fastest
    of `rounds` runs, taking the fonts in turn so that load on the machine
    falls on all of them alike."""
    texts = lines(inst, n, seed=2)
    long = [" ".join(texts[i:i + 40]) for i in range(0, len(texts), 40)]
    chars = sum(map(len, long))
    best = {}
    for _ in range(rounds):
        for label, shapers in fonts.items():
            for i, shaper in enumerate(shapers):
                t0 = time.perf_counter()
                for t in long:
                    shaper.shape(t)
                best[label, i] = min(best.get((label, i), float("inf")), time.perf_counter() - t0)
    return {label: [best[label, i] / chars * 1e9 for i in range(len(shapers))] for label, shapers in fonts.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("instance", choices=sorted(INSTANCES))
    ap.add_argument("--build", action="store_true", help="build, check and time a font for each split")
    ap.add_argument("--shaper", action="append", choices=["harfbuzz", "coretext"])
    ap.add_argument("--lines", type=int, default=2000, help="random lines to check and time (default 2000)")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    args = ap.parse_args()
    inst = INSTANCES[args.instance]()
    t0 = time.perf_counter()
    by_group = all_passes(inst, args.workers if args.instance == "html" else 1)
    k = len(inst.names)
    print(f"{inst.name}: {k} recognizers over {len(inst.alphabet)} characters, "
          f"{len(by_group)} groups in {time.perf_counter() - t0:.0f} s")
    shapers = args.shaper or ["harfbuzz"]
    rows, fonts, failed = [], {}, 0
    for label, split in choices(inst, by_group):
        sizes = sorted(len(p.table) for p in split)
        per = str(sizes[0]) if len(sizes) == 1 else f"{sizes[0]}-{sizes[-1]}"
        g = glyphs(split)
        line = f"{label:12} {len(split):6} {per:>15} {sum(sizes):7} {g:7} {sum(p.rules for p in split):8}"
        if args.build and g + 2000 < GLYPH_LIMIT:      # the base font has 1,743
            extra, lookups, gsub, fonts[label], wrong = measure(inst, split, shapers, args.lines)
            line += f" {extra:7} {lookups:7} {gsub / 1024:7.0f}"
            failed += bool(wrong)
        rows.append((label, line, split, wrong if label in fonts else 0))
    times = timings(inst, fonts, args.lines) if fonts else {}
    head = f"{'':12} {'passes':>6} {'states per pass':>15} {'states':>7} {'glyphs':>7} {'rules':>8}"
    if args.build:
        head += f" {'built':>7} {'lookups':>7} {'GSUB KB':>7}" + "".join(f" {'ns/char ' + s[:2]:>10}" for s in shapers)
    print(head)
    for label, line, split, wrong in rows:
        if label in times:
            line += "".join(f" {t:10.0f}" for t in times[label])
        elif args.build:
            line += "  doesn't fit in 65,535 glyphs"
        if wrong:
            line += f"  {wrong} lines wrong"
        print(line)
        if 1 < len(split) < k:
            print(f"{'':12} " + " | ".join(" ".join(inst.names[j] for j in p.group) for p in split))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
