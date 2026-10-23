"""What each token finally draws, and where that puts it.

final(token) turns a token's track values, once the passes have run, into
its glyphs: the character's glyph, then movers and ink. The font builds the
same glyphs (mathfont.py); place() puts them where the shapers' rules do,
so a simulated line can be checked against layout.py before any font is
built.

Inside a fraction nothing advances: every glyph is a mark, placed by an
attachment chain. Each link is the character's glyph (for text) or a
mover, an empty mark that sits a fixed distance (dx, dy) from the link
before it. A mover's distance comes from one value (a width, a padding),
never from two, so each value needs only as many movers as it has values.
Ink (a bar, an overbar) hangs off a token's last mover, outside the chain.
Outside fractions, text advances as usual; flow (top-level text,
superscripts, roots) gets its height from a y offset on the base glyph.
"""

import layout as L
import program as P

U30 = L.UNIT            # movers and pads count in 30s


DIGIT = 23              # a rule's length in 30s is split into two pieces: below 23, and a multiple of it
SLOTS = ("G", "S", "A", "B", "C")
VALUES = ("mid", "fend", "qend", "e1", "e2", "o2", "npad", "dpad", "kind")
NONE = ("_",)


def rule_pieces(band, direction, start, length):
    """Two ink glyphs drawing `length` (in 30s) from `start` (30s from the
    glyph they hang off), rightwards ("R") or leftwards ("L")."""
    if length <= 0:
        return [NONE, NONE]
    low, high = length % DIGIT, length - length % DIGIT
    return [("ink", band, direction, start, low, 0), ("ink", band, direction, 0, high, 1) if high else NONE]


def bar_band(st, dy=0):
    y = L.AXIS[st] + dy
    return (y - L.RULE[st] // 2, y + L.RULE[st] // 2)


def frame_of(arg):
    return arg[0] + ("s" if arg[1] != "alone" else "")


def final(t):
    """The token's glyphs, slot by slot: G (the character's own), S, A, B,
    C. The font finishes them in the order A, G, C, B, S, so each is made
    from the tracks still unfinished then: A and G may use any, C uses S, B
    and C, B uses S and B, and S only itself.

    Glyphs: ("glyph", char, style, "b" or "m") a character (a base glyph
    that advances, or a mark in a chain); ("radical", style, kind, b/m);
    ("space",); ("hid",) nothing; movers ("dx", v), ("dy", w), ("dxy", v,
    w), links of a chain (v in 30s); ("dx@root", v), ("dx@fend", pad) and
    ("at@base",), marks on the glyph that starts or ends a fraction or ends
    a root in flow; bases ("root",), ("qbase",), ("fendbase", wN) and
    ("adv", v) (an advance of v 30s); ("y", y) the base glyph's height in
    flow; ("ink", band, direction, start, length, digit) a rule's piece."""
    s, b, c = t["S"], t.get("B"), t.get("C")
    out = {k: NONE for k in SLOTS}
    # B and C may be finished already, when a slot that doesn't use them is made
    b = b if b and b[0] in VALUES else ("?", 0, 0, False)
    c = c if c and c[0] == "wN" else ("?", 0, 0)
    if s[0] == "T":
        kind, st, k, o, y = s[1:6]
        arg = s[6] if len(s) > 6 else None
        if kind == " ":
            out["G"] = ("space",)
            return out
        out["G"] = ("glyph", t["char"], st, "m" if k else "b")
        extra = 2 * max(0, b[2]) if arg is not None and arg[1] == "second" and b[0] == "e2" else 0
        if k:
            out["S"] = ("dx", P.WIDTH[st] * 2)
            if arg is not None:
                out["A"] = ("dy", -P.shift_of(frame_of(arg), arg[2]))
            if extra:
                out["B"] = ("dx", extra)
        else:
            if y:
                out["S"] = ("y", y)
            if extra:
                out["B"] = ("adv", extra)
        return out
    name, level, st, k, o, y = s[1:7]
    details = s[7:]
    out["G"] = ("hid",)
    margin = L.MARGIN // U30
    if name == "froot":
        if k == 0:
            out["G"] = ("root",)
            out["S"] = ("dx@root", margin)
            if y:
                out["A"] = ("y", y)
        else:
            out["G"] = ("dx", margin)
    elif name == "nopen":
        _, d, flag = b[:3]
        out["G"] = ("dx", max(0, -d))
        out["A"] = ("dy", L.numerator_shift(st, flag))
    elif name == "mid":
        _, _, wn, flag = b
        out["G"] = ("dx", -2 * wn)
        out["A"] = ("dy", -L.numerator_shift(st, flag))
        out["B"], out["C"] = rule_pieces(bar_band(st), "R", -1, 2 * wn + 2)
    elif name == "dopen":
        _, d, flag = b[:3]
        down = L.denominator_shift(st, flag)
        out["G"] = ("dx", d)
        out["A"] = ("dy", -down)
        out["B"], out["C"] = rule_pieces(bar_band(st, down), "R", -1, -d + 1)
    elif name == "fend":
        _, _, d, flag = b
        pad = max(0, -d)
        if k == 0:
            out["G"] = ("fendbase", c[2])
            if y:
                out["S"] = ("y", y)
            out["A"] = ("dx@fend", pad)
            out["B"], out["C"] = rule_pieces(bar_band(st), "R", 0, pad + 1)
        else:
            out["G"] = ("dx", max(0, d))
            out["A"] = ("dxy", margin, L.denominator_shift(st, flag))
            out["B"], out["C"] = rule_pieces(bar_band(st), "L", -1, pad + 1)
    elif name == "sroot":
        kind = b[1]
        out["G"] = ("radical", st, kind, "m" if k else "b")
        if k:
            out["S"] = ("dx", P.WIDTH[st] * 2)
        elif y:
            out["S"] = ("y", y)
    elif name == "qend":
        _, _, wr, kind = b
        top = L.root_top(st, kind)
        band = (top, top + L.RULE[st])
        if k == 0:
            out["G"] = ("qbase",)
            if y:
                out["S"] = ("y", y)
            out["A"] = ("at@base",)
        else:
            out["G"] = ("dx", 0)
        out["B"], out["C"] = rule_pieces(band, "L", 0, 2 * wr)
    elif name in ("sopen", "gclose"):
        kind, pos = details[0], details[1]
        shift = P.shift_of(kind + ("s" if pos != "alone" else ""), st)
        if name == "sopen":
            move = -2 * b[2] if pos == "second" else 0
            out["A"] = ("dy", shift) if k else NONE
        else:
            move = 2 * max(0, b[2]) if pos == "second" else 0
            out["A"] = ("dy", -shift) if k else NONE
        if move:
            out["G"] = ("dx", move) if k else ("adv", move)
    return out


def slot_key(slot, s):
    """What final(t)[slot] reads of a token's S: s with the rest blanked
    (depth beyond being in a chain, levels, opaque levels, and heights
    except where the slot is placed by one)."""
    if s[0] == "T":
        kind, st, k, o, y = s[1:6]
        arg = s[6] if len(s) > 6 else None
        k = min(k, 1)
        if slot == "G":
            return ("T", kind, st, k, 0, 0)
        if slot == "S":
            return ("T", "c", st, k, 0, 0 if k else y)
        if slot == "A":
            return ("T", "c", 0, k, 0, 0) + (((arg[0], arg[1], arg[2], 0),) if k and arg is not None else ())
        second = arg is not None and arg[1] == "second"
        return ("T", "c", 0, k, 0, 0) + ((("U", "second", 0, 0),) if slot == "B" and second else ())
    name, level, st, k, o, y = s[1:7]
    uses = ROLE_USES.get(name, {}).get(slot, "")
    details = s[7:]
    if name == "sopen":
        details = details[:2] + (False,)
    if "d" not in uses and name in ("sopen", "gclose"):
        details = ("U", "alone") + details[2:]
    k = min(k, 1) if "k" in uses else 0
    return ("R", name, 0, st if "s" in uses else 0, k, 0, y if "y" in uses and not k else 0) + details


# What each role's slots read of S, as final() makes them: s(tyle), k
# (inside a chain), y (height in flow), d(etails).
ROLE_USES = {
    "froot": {"G": "k", "S": "k", "A": "ky"},
    "nopen": {"A": "s"},
    "mid": {"A": "s", "B": "s", "C": "s"},
    "dopen": {"A": "s", "B": "s", "C": "s"},
    "fend": {"G": "k", "S": "ky", "A": "ks", "B": "ks", "C": "ks"},
    "sroot": {"G": "sk", "S": "sky"},
    "qend": {"G": "k", "S": "ky", "A": "k", "B": "s", "C": "s"},
    "sopen": {"G": "kd", "A": "skd"},
    "gclose": {"G": "kd", "A": "skd"},
}


def need_class(s):
    """What need() reads of a token's S."""
    if s[0] == "T":
        arg = s[6] if len(s) > 6 else None
        return ("T", arg is not None and arg[1] == "second")
    name = s[1]
    return (name, s[4] > 0, s[8] if name in ("sopen", "gclose") and len(s) > 8 else None)


def need(slot, nc, b):
    """What final(t)[slot] reads of B, for a token whose S has need_class
    nc: b with the rest blanked, so the font needs a rule per value of
    that, not of b."""
    if b is None or b[0] not in VALUES:
        return P.BLANK
    if nc[0] == "T":
        if slot == "B" and nc[1] and b[0] == "e2":
            return ("e2", 0, max(0, b[2]))
        return P.BLANK
    name, k, pos = nc
    tag = b[0]
    if name == "nopen" and tag == "npad":
        return {"G": ("npad", min(0, b[1]), False), "A": ("npad", 0, b[2])}.get(slot, P.BLANK)
    if name == "dopen" and tag == "dpad":
        if slot == "G":
            return ("dpad", b[1], False)
        return ("dpad", 0, b[2]) if slot == "A" else b if slot in "BC" else P.BLANK
    if name == "mid" and tag == "mid":
        return ("mid", 0, 0, b[3]) if slot == "A" else ("mid", 0, b[2], False) if slot in "GBC" else P.BLANK
    if name == "fend" and tag == "fend":
        if slot == "G":
            return ("fend", 0, max(0, b[2]), False) if k else P.BLANK
        if slot == "A":
            return ("fend", 0, 0, b[3]) if k else ("fend", 0, min(0, b[2]), False)
        return ("fend", 0, min(0, b[2]), False) if slot in "BC" else P.BLANK
    if name == "sroot" and tag == "kind":
        return b if slot == "G" else P.BLANK
    if name == "qend" and tag == "qend":
        return ("qend", 0, b[2], b[3]) if slot in "BC" else P.BLANK
    if name in ("sopen", "gclose") and slot == "G" and pos == "second":
        return (tag, 0, b[2])
    return P.BLANK


NEEDS = "AGCB"


def localize(b, nc):
    """B as the finals read it: what each slot's glyph needs of it, for a
    token whose S has need_class nc."""
    needs = tuple(need(slot, nc, b) for slot in NEEDS)
    return P.BLANK if all(n == P.BLANK for n in needs) else ("n",) + needs


def needed(b, slot):
    """A localized B's part for one slot."""
    return b[1 + NEEDS.index(slot)] if b[0] == "n" else P.BLANK


def place(toks):
    """(ink, advance) as layout.layout() gives them, from the glyphs final()
    makes, placed the way GPOS places them."""
    ink = []
    pen = 0
    link = None          # where the chain's next link attaches
    parent = None        # where the next ink piece hangs
    for t in toks:
        f = {k: t.get(k, NONE) for k in SLOTS}
        if "A" not in t:              # a space
            f = {"G": t["S"], "S": NONE, "A": NONE, "B": NONE, "C": NONE}
        ys = [v[1] for v in f.values() if v[0] == "y"]
        y = ys[0] if ys else 0
        base = None
        for slot in SLOTS:
            g = f[slot]
            kind = g[0]
            if kind == "_":
                continue
            if kind == "space":
                pen += L.WIDTH[0]
            elif kind in ("glyph", "radical"):
                st, mode = (g[2], g[3]) if kind == "glyph" else (g[1], g[3])
                pos = (pen, y) if mode == "b" else link
                if mode == "b":
                    pen += L.WIDTH[st]
                ink.append(("glyph", g[1], st) + pos if kind == "glyph" else ("radical", st, g[2]) + pos)
            elif kind in ("root", "qbase", "fendbase", "adv", "hid"):
                if kind != "hid":
                    base = (pen, y, g)
                if kind == "adv":
                    pen += g[1] * U30
            elif kind in ("dx", "dy", "dxy"):
                dx = g[1] if kind != "dy" else 0
                dy = g[-1] if kind != "dx" else 0
                link = (link[0] + dx * U30, link[1] + dy)
                parent = link
            elif kind == "dx@root":
                link = (base[0] + g[1] * U30, base[1])
                parent = link
            elif kind == "dx@fend":
                wn = base[2][1]
                parent = (base[0] + (2 + 2 * wn + g[1]) * U30, base[1])
                pen += (2 * wn + 2 * g[1] + 4) * U30
            elif kind == "at@base":
                parent = (base[0], base[1])
            elif kind == "ink":
                _, band, direction, start, length, digit = g
                x0 = parent[0] + start * U30
                x1 = x0 + length * U30 if direction == "R" else x0 - length * U30
                if length:
                    ink.append(("rule", min(x0, x1), max(x0, x1), parent[1] + band[0], parent[1] + band[1]))
                parent = (x1, parent[1])
    return sorted(L.merge(ink)), pen


def check(line):
    want = L.layout(line)
    got = place(P.simulate(line))
    return got == want, got, want


if __name__ == "__main__":
    import sys
    for line in sys.argv[1:]:
        ok, got, want = check(line)
        print("ok" if ok else "DIFF", line)
        if not ok:
            for r in sorted(set(got[0]) | set(want[0])):
                print("   ", "  " if (r in got[0]) == (r in want[0]) else ("+ " if r in got[0] else "- "), r)
            print("    advance", got[1], "want", want[1])
