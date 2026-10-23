"""The passes Fontlex Math runs, as functions over tokens.

The font works on a token per character (a symbol command, `\\alpha`, is
one token; its letters are hidden at once and take no part). After every
character's glyph come four empty marks, its tracks S, A, B and C; a pass
reads and rewrites one track and sees only track glyphs, never the
characters. A space has no tracks, since WebKit gives every glyph of a
space character the space's width: when a pass needs spaces, the space's
own glyph stands in for the track, and a value of the form ("sp", depth)
on it is put back to (" ", depth) after.

Passes:
    Map(track, fn)                   every value v becomes fn(v)
    Derive(target, sources, fn)      target = fn(target, *sources), all of
                                     one token
    Context(track, fn, targets)      v = fn(previous, v) where `targets`
                                     accepts v, previous being the value
                                     before it (as it was before the pass)
                                     that `ctx_view` accepts, or None
    LTR(track, step, init, view)     a transducer, left to right
    RTL(track, step, init, view)     and right to left

A transducer's step(state, v) returns (new v, new state), and the token
keeps the pair: a glyph must record the state the next one reads. The
Map after it (strip) drops the state.

simulate(line) runs the passes in Python; mathfont.py compiles them.
"""

import layout as L

TRACKS = ("S", "A", "B", "C")
ORDER = ("G",) + TRACKS            # a token's glyphs, in the order they follow each other
BRACE_LIMIT = L.BRACE_LIMIT
BLANK = ("_",)
U = L.UNIT * 2                     # widths are counted in 60s (a margin is one)
WIDTH = tuple(w // U for w in L.WIDTH)
MARGINS = 2 * L.MARGIN // U


class Map:
    def __init__(self, track, fn, spaces=False):
        self.track, self.fn, self.spaces = track, fn, spaces


class Derive:
    """target = fn(target, *[key(source)]): the font compiles one rule per
    combination of the sources' keys that occurs, so a key should keep only
    what fn needs of its source."""
    def __init__(self, target, sources, fn, keys=None, spaces=False):
        self.target, self.sources, self.fn, self.spaces = target, sources, fn, spaces
        self.keys = keys or [None] * len(sources)

    def key(self, i, v):
        return v if self.keys[i] is None else self.keys[i](v)


class Context:
    """fn(previous, v) for the values `targets` accepts; previous is the
    last value before it that `ctx_view` accepts (on ctx_track, or the same
    track, where the targets count too)."""
    def __init__(self, track, fn, targets, ctx_view=lambda v: True, spaces=False, ctx_track=None):
        self.track, self.fn, self.targets, self.spaces = track, fn, targets, spaces
        self.ctx_track = ctx_track or track
        self.ctx_view = ctx_view


class LTR:
    def __init__(self, track, step, init, view=lambda v: True, spaces=False):
        self.track, self.step, self.init, self.view, self.spaces = track, step, init, view, spaces


class RTL(LTR):
    pass


class Impossible(Exception):
    """What a step raises for an input that can't come in the state it is
    in (the font compiles steps over more states and inputs than lines
    give)."""


def unwrap(v):
    return v[0] if isinstance(v, tuple) and len(v) == 2 and isinstance(v[0], tuple) else v


def strip(track, spaces=False):
    return Map(track, unwrap, spaces)


def restore_space(v):
    return (" ", v[1]) if v[0] == "sp" else v


# tokens -------------------------------------------------------------------

def tokens(line):
    """The font's tokens: dicts with "text" (their characters), "char"
    (what the token's glyph shows), and the tracks' first values."""
    out = []
    for kind, start, end, value in L.lex(line):
        if kind == "cmd":
            first = "F" if value == "frac" else "R"
            out.append({"text": "\\", "char": "\\", "S": (first,)})
            for ch in line[start + 1:end]:
                out.append({"text": ch, "char": ch, "S": ("Lf" if first == "F" else "Ls",)})
            continue
        if kind == "sym":
            out.append({"text": line[start:end], "char": value, "S": ("Y", end - start)})
            continue
        s = {"{": ("O",), "}": ("C",), "^": ("P",), "_": ("B",), " ": (" ",)}.get(kind, ("c",))
        out.append({"text": value, "char": value, "S": s})
    for t in out:
        if t["S"] != (" ",):
            tag = {"F": "F", "R": "R", "Lf": "Lf", "Ls": "Ls", "Y": "Y"}.get(t["S"][0])
            t["G"] = ("g", t["char"], tag)
            for tr in TRACKS[1:]:
                t[tr] = BLANK
    return out


def depth_of(s):
    """A token's brace depth, once known (a brace: its level)."""
    return s[2] if s[0] == "Y" else s[1]


# 1. brace depth -------------------------------------------------------------

def depth_step(state, v):
    depth, dead = state
    k = v[0]
    if dead:
        return demote(v, depth), state
    if k == "O":
        if depth == BRACE_LIMIT:
            return ("b", depth), (depth, True)
        return ("O", depth + 1), (depth + 1, False)
    if k == "C":
        if depth == 0:
            return ("b", 0), state
        return ("C", depth), (depth - 1, False)
    if k == "Y":
        return ("Y", v[1], depth), state
    return (k, depth), state


def demote(v, depth):
    """Past too many open braces nothing more is structure: text that can't
    be a script's argument ("b"), like a closing brace with nothing open."""
    if v[0] == "Y":
        return ("Y", v[1], depth)
    return ({" ": " ", "c": "c"}.get(v[0], "b"), depth)


# 2. what each brace belongs to ----------------------------------------------

OPENS = {"Lf": "N", "Ls": "Q", "P": "U", "B": "W"}


def is_open(v):
    return v[0] == "O" and len(v) == 2


def kind_of_open(prev, v):
    return ("O", v[1], OPENS.get(prev[0], "G") if prev else "G")


def level_braces(level):
    return lambda v: v[0] in ("O", "C") and v[1] == level


def closer_kind(prev, v):
    return ("C", v[1], prev[2])


def is_bare_open(v):
    return v[0] == "O" and v[2] == "G"


def denominator(prev, v):
    if prev and prev[0] == "C" and prev[2] == "N":
        return ("O", v[1], "D")
    return v


def denominator_closer(prev, v):
    return ("C", v[1], "D") if prev[2] == "D" else v


# 3. checks: a space inside, fractions in fractions, length ---------------------

def check_a_input(s):
    if s[0] in ("O", "C"):
        return (s[0], s[1], s[2] in "ND")
    if s[0] == " ":
        return ("sp", s[1])
    return ("x",)


def check_a_step(state, v):
    """Which open braces hold a space, and how many fractions are open."""
    dirty, depth, fracs = state
    if v[0] == "O":
        _, d, fr = v
        fracs = min(BRACE_LIMIT, fracs + fr)     # (bounded, as no more braces can be open)
        return ("O", fr and fracs > L.MAX_FRACTIONS), (dirty - {d}, d, fracs)
    if v[0] == "C":
        _, d, fr = v
        return ("C", d in dirty), (frozenset(x for x in dirty if x < d), d - 1, max(0, fracs - fr))
    if v[0] == "sp":
        return v, (dirty | frozenset(range(1, depth + 1)), depth, fracs)
    return ("x",), state


def check_b_input(s):
    k = s[0]
    if k == "O":
        return ("O", s[1], s[2] == "G")
    if k == "C":
        return ("C", s[1])
    if k in ("F", "R", "P", "B"):
        return ("start", s[1])
    if k in ("Lf", "Ls"):
        return ("cont",)
    if k in ("c", "b"):
        return ("t", s[1], 1)
    if k == "Y":
        return ("t", s[2], s[1])
    return ("sp", s[1])


def check_b_step(count, v):
    """Characters since a construct outside all others began."""
    k = v[0]
    if k == "start":
        count = 1 if v[1] == 0 else count + 1
    elif k == "cont" or k == "C":
        count += 1
    elif k == "O":
        count = 1 if (v[1] == 1 and v[2]) else count + 1
    elif k == "t":
        count = 0 if v[1] == 0 else count + v[2]
    elif k == "sp":
        count = 0 if v[1] == 0 else count + 1
    count = min(count, L.MAX_CHARS + 1)
    if k == "C":
        return ("C", v[1] == 1 and count > L.MAX_CHARS), count
    return (v if k == "sp" else ("x",)), count


def merge_checks(s, a, b):
    if s[0] == "C":
        return ("Ck", s[1], s[2], not a[1] and not b[1])
    if s[0] == "O":
        return ("Ok", s[1], s[2], a[1])
    return s


# 4. which constructs are laid out, a brace level at a time ----------------------

def valid_input(level):
    def fn(s):
        k = s[0]
        if k == "Ok":
            return ("O", s[2], s[3]) if s[1] == level else ("in",) if s[1] > level else ("x",)
        if k == "Ck":
            return ("C", s[2], s[3]) if s[1] == level else ("in",) if s[1] > level else ("x",)
        d = depth_of(s)
        if k == " ":
            return ("sp", d)
        if d >= level or k in ("Lf", "Ls"):
            return ("in",)
        if d < level - 1:
            return ("x",)
        if k in ("F", "R", "P", "B"):
            return (k,)
        if k in ("c", "Y"):
            return ("t",)
        return ("sp", d)
    return fn


def valid_view(v):
    return v[0] != "in"


def valid_step(state, v):
    """Right to left. state: (pending, root, next):
    pending: what lies to the right at this level: None, ("C", ok[,
      stacked]) past a closer, ("D", ok) past a denominator's opener, ("N",
      ok) past a numerator's closer;
    root: (kind, valid, stacked) for the command, ^ or _ left of an opener;
    next: what is right: "arg" (a character), "arg+sup" or "arg+sub" (a
      character, then a script that is laid out), "sup" or "sub" (that
      script), "x". A script followed by one of the other kind is stacked
      with it (unless it is itself the second of a pair: the role pass
      pairs them from the left)."""
    pending, root, nxt = state
    k = v[0]
    if k == "C":
        kind, ok = v[1], v[2]
        if kind == "N":
            if pending and pending[0] == "D":
                return ("C", False), (("N", pending[1] and ok), None, "x")
            return ("C", True), (("N", False), None, "x")
        if kind in ("U", "W"):
            return ("x",), (("C", ok, nxt == ("sup" if kind == "W" else "sub")), None, "x")
        return ("x",), (("C", ok), None, "x")
    if k == "O":
        kind, flag = v[1], v[2]
        if kind == "D":
            ok = pending is not None and pending[0] == "C" and pending[1]
            return ("x",), (("D", ok), None, "x")
        if kind == "N":
            valid = pending is not None and pending[0] == "N" and pending[1] and not flag
        else:
            valid = pending is not None and pending[0] == "C" and pending[1]
        stacked = kind in ("U", "W") and valid and pending[2]
        return ("O", valid), (None, (kind, valid, stacked) if kind != "G" else None, "x")
    if k in ("F", "R"):
        want = "N" if k == "F" else "Q"
        valid = root is not None and root[0] == want and root[1]
        return ("root", valid), (pending, None, "x")
    if k in ("P", "B"):
        want = "U" if k == "P" else "W"
        if root is not None and root[0] == want:
            valid, stacked, single = root[1], root[2], False
        elif nxt in ("arg", "arg+sup", "arg+sub"):
            other = "arg+sub" if k == "P" else "arg+sup"
            valid, stacked, single = True, nxt == other, True
        else:
            valid, stacked, single = False, False, False
        out = ("root", valid, stacked, single)
        return out, (pending, None, ("sup" if k == "P" else "sub") if valid else "x")
    if k == "t":
        return ("x",), (pending, None, "arg+" + nxt if nxt in ("sup", "sub") else "arg")
    return (v if k == "sp" else ("x",)), (pending, None, "x")


def merge_valid(level):
    def fn(s, a):
        k = s[0]
        if k == "Ok" and s[1] == level:
            return ("Ov", s[1], s[2], a[1] if a[0] == "O" else False)
        if k == "Ck" and s[1] == level:
            return ("Cv", s[1], s[2], a[0] == "C" and a[1])
        if a[0] == "root":
            return (k + "v", s[1]) + a[1:]
        return s
    return fn


def finish_valid(s):
    """What no level pass saw is too deep to lay out."""
    k = s[0]
    if k == "Ok":
        return ("Ov", s[1], s[2], False)
    if k == "Ck":
        return ("Cv", s[1], s[2], False)
    if k in ("F", "R"):
        return (k + "v", s[1], False)
    if k in ("P", "B"):
        return (k + "v", s[1], False, False, False)
    return s


# after this: Ov (level, kind, valid), Cv (level, kind, broken),
# Fv/Rv (depth, valid), Pv/Bv (depth, valid, stacked, single), Lf/Ls (depth),
# c (depth), Y (n, depth), " " (depth).


# 5. roles, a brace level at a time ---------------------------------------------

def role_input(level):
    def fn(s):
        k = s[0]
        if k == "Ov":
            if s[1] == level:
                return ("O", s[2], s[3])
            return ("in",) if s[1] > level else ("out",)
        if k == "Cv":
            if s[1] == level:
                return ("C", s[2], s[3])
            return ("in",) if s[1] > level else ("out",)
        d = depth_of(s)
        if k == " ":
            return ("sp", d, d >= level)
        if d >= level:
            return ("in",)
        if d < level - 1:
            return ("out",)
        if k in ("Fv", "Rv"):
            return (k[0], s[2])
        if k in ("Pv", "Bv"):
            return (k[0],) + s[2:]
        if k in ("Lf", "Ls"):
            return ("L",)
        if k in ("c", "Y"):
            return ("t",)
        return ("out",)
    return fn


SCRIPT = {"P": "U", "B": "W"}


def role_step(state, v):
    """state: (frame, root, pend, last):
    frame: the level's open frame: None, ("ok", kind), ("bad", end) inside
      a construct not laid out (end "D": a fraction's, which ends at the
      denominator's closer, or the numerator's when there is none), or
      ("D?",) between a fraction's two parts;
    root: ("F",) or ("R",) while a laid out command's letters pass, or
      ("S", kind, pos) between a script's ^ or _ and its brace;
    pend: (kind, pos) for a script whose argument is the next token;
    last: "sup1" or "sub1" right after the first script of a stacked pair.
    Script kinds are U and W (superscript, subscript); pos is "alone",
    "first" or "second" of a stacked pair."""
    frame, root, pend, last = state
    k = v[0]
    nlast = None
    if k == "F" or k == "R":
        if v[1]:
            return ("role", "froot" if k == "F" else "sroot"), (frame, (k,), None, None)
        return ("out",), (frame, None, None, None)
    if k == "L":
        if root is not None and root[0] in ("F", "R"):
            return ("role", "hide"), state
        return ("out",), (frame, None, None, None)
    if k in ("P", "B"):
        valid, stacked, single = v[1], v[2], v[3]
        if not valid:
            return ("out",), (frame, None, None, None)
        kind = SCRIPT[k]
        if (k == "B" and last == "sup1") or (k == "P" and last == "sub1"):
            pos = "second"
        elif stacked:
            pos = "first"
        else:
            pos = "alone"
        out = ("role", "sopen", kind, pos, single)
        if single:
            return out, (frame, None, (kind, pos), None)
        return out, (frame, ("S", kind, pos), None, None)
    if k == "t":
        if pend is not None:
            kind, pos = pend
            nlast = (kind == "U" and "sup1" or "sub1") if pos == "first" else None
            return ("role", "arg", kind, pos), (frame, None, None, nlast)
        return ("out",), (frame, None, None, None)
    if k == "O":
        kind, valid = v[1], v[2]
        if frame is not None and frame[0] == "bad":
            return ("inv",), state
        if frame == ("D?",):
            return ("role", "dopen"), (("ok", "D"), None, None, None)
        if not valid:
            return ("inv",), (("bad", "D" if kind == "N" else "other"), None, None, None)
        if kind in ("U", "W"):
            pos = root[2] if root is not None and root[0] == "S" else "alone"
            fk = kind + ("s" if pos != "alone" else "")
            return ("role", "gopen"), (("ok", fk, pos), None, None, None)
        return ("role", {"N": "nopen", "Q": "qopen"}.get(kind, "bopen")), (("ok", kind), None, None, None)
    if k == "C":
        kind, broken = v[1], v[2]
        if frame is not None and frame[0] == "bad":
            end = (frame[1] == "other") or kind == "D" or (kind == "N" and broken)
            return ("inv",), ((None if end else frame), None, None, None)
        if frame is None or frame[0] != "ok":
            return ("out",), (None, None, None, None)
        fk = frame[1]
        if fk == "N":
            return ("role", "mid"), (("D?",), None, None, None)
        if fk == "D":
            return ("role", "fend"), (None, None, None, None)
        if fk == "Q":
            return ("role", "qend"), (None, None, None, None)
        if fk[0] in "UW":
            pos = frame[2]
            kind = fk[0]
            nlast = (kind == "U" and "sup1" or "sub1") if pos == "first" else None
            return ("role", "gclose", kind, pos), (None, None, None, nlast)
        return ("role", "bclose"), (None, None, None, None)
    if k == "sp":                    # a space: inside the level's frame (which then isn't laid out) or not
        if v[2]:
            return v, state
        return v, (frame, None, None, None)
    if k == "in":
        if frame is None:
            return ("out",), (None, None, None, None)
        if frame[0] == "bad":
            return ("inv",), state
        return ("in", frame[1]), state
    return ("out",), (frame if frame is not None and frame[0] == "bad" else frame, None, None, None)


def role_view(v):
    return True


# 6. what each token is ---------------------------------------------------------

REDUCING = {"N", "D", "U", "Us", "W", "Ws"}
OPAQUE = {"N", "D", "Q", "Us", "Ws"}
CHAIN = {"N", "D"}


def style_of(path):
    return min(2, sum(f in REDUCING for f in path))


def shift_of(frame, s):
    return {"U": L.SUP[s], "Us": L.SUP[s], "W": -L.SUB[s], "Ws": -L.SUB_STACKED[s]}.get(frame, 0)


def describe(path):
    """(style, chain depth, deepest opaque level, flow y) of a path of frames."""
    s = style_of(path)
    k = sum(f in CHAIN for f in path)
    o = max((i + 1 for i, f in enumerate(path) if f in OPAQUE), default=0)
    y, st = 0, 0
    for f in path:
        if f in CHAIN:
            break
        y += shift_of(f, st)
        st = min(2, st + (f in REDUCING))
    return s, k, o, (y if k == 0 else None)


def fold(prev, o, level):
    """One level pass's output, read after the ones above it: ("run", style,
    chain depth, opaque, y) while the token is inside laid out frames, then
    ("done", result) with what combine() would give, less the token's kind."""
    if prev[0] == "done":
        return prev
    _, st, k, op, y = prev
    if o[0] in ("out", "inv"):
        return ("done", ("T", st, k, op, y))
    if o[0] == "in":
        return ("done", ("T", st, k, op, y)) if level > 3 else enter(prev, o[1], level)
    name, *details = o[1:]
    if name == "arg":
        skind, pos = details
        _, st2, k2, op2, y2 = enter(prev, skind + ("s" if pos != "alone" else ""), level)
        return ("done", ("Targ", st2, k2, op2, y2, (skind, pos, st, op)))
    return ("done", ("R", name, level, st, k, op, y) + tuple(details))


def enter(prev, frame, level):
    _, st, k, op, y = prev
    if frame in CHAIN:
        k, y = k + 1, None
    elif k == 0:
        y += shift_of(frame, st)
    return ("run", min(2, st + (frame in REDUCING)), k, level if frame in OPAQUE else op, y)


RUN = ("run", 0, 0, 0, 0)


def fold_finish(s, c):
    """The fold's result as combine() gives it."""
    kind = s[0] if s[0] in ("Y", " ") else "c"
    r = c[1] if c[0] == "done" else ("T",) + c[1:]
    if r[0] == "T":
        return ("T", kind) + r[1:]
    if r[0] == "Targ":
        return ("T", kind) + r[1:]
    return r


def combine(s, a, b, c):
    """A token's role from the three level passes: ("T", kind, style, chain
    depth, opaque, y[, arg]) for text, kind "c", "Y" or " "; ("R", role,
    level, style, chain depth, opaque, y, *details) for a construct's own
    token."""
    path = []
    role = None
    for level, o in ((1, a), (2, b), (3, c)):
        if o[0] in ("out", "inv"):
            break
        if o[0] == "in":
            path.append(o[1])
            continue
        role = (level,) + o[1:]
        break
    kind = s[0] if s[0] in ("Y", " ") else "c"
    if role is None:
        return ("T", kind) + describe(path)
    level, name, *details = role
    if name == "arg":
        skind, pos = details
        frame = skind + ("s" if pos != "alone" else "")
        st, k, o, y = describe(path + [frame])
        _, _, o_parent, _ = describe(path)
        return ("T", kind, st, k, o, y, (skind, pos, describe(path)[0], o_parent))
    return ("R", name, level) + describe(path) + tuple(details)


# 7. widths, a brace level at a time, innermost first -----------------------------

def contribution(s, b):
    """What a token adds to the width of the construct whose part it is in
    (the deepest one that isn't see-through: fractions, roots, stacked
    scripts), and that construct's level: (level, width, holds a fraction,
    holds a superscript), or None. Other constructs inside one are drawn
    from its own tokens' values."""
    if s[0] == "T":
        _, kind, st, k, o, y = s[:6]
        arg = s[6] if len(s) > 6 else None
        if kind == " ":
            return None
        if arg is not None and arg[1] != "alone" and b[0] in ("e1", "e2"):
            special = b[2] if b[0] == "e1" else max(0, -b[2])
            return [(o, WIDTH[st], False, False), (arg[3], special, False, False)]
        return [(o, WIDTH[st], False, False)]
    if s[0] != "R":
        return None
    name, level, st, k, o = s[1:6]
    if name in ("mid", "fend", "qend") and b == BLANK:
        return None                  # an outer construct's, not counted yet
    if name == "froot":
        return [(o, 0, True, False)]
    if name == "sopen" and s[7] == "U":
        return [(o, 0, False, True)]
    if name == "mid":
        return [(o, b[2], False, False)]
    if name == "fend":
        return [(o, max(0, -b[2]) + MARGINS, False, False)]
    if name == "sroot":
        return [(o, WIDTH[st], False, False)]
    if name == "qend":
        return [(o, b[2], False, False)]
    if name == "gclose" and b[0] in ("e1", "e2"):
        return [(o, b[2] if b[0] == "e1" else max(0, -b[2]), False, False)]
    return None


def width_input(level, kind):
    """What the counter of `kind` constructs (frac, sqrt, pair) at `level`
    sees of a token."""
    def fn(a, s, b):
        if s[0] == "R" and s[2] == level:
            name = s[1]
            if kind == "frac" and name in ("nopen", "mid", "dopen", "fend"):
                return (name,)
            if kind == "sqrt" and name in ("qopen", "qend"):
                return (name,)
            if kind == "pair" and name in ("sopen", "gclose") and s[8] != "alone":
                return (name, s[8])
        if kind == "pair" and s[0] == "T" and len(s) > 6 and s[6][1] != "alone" and s[4] == level:
            return ("argend", s[6][1], WIDTH[s[2]])
        parts = contribution(s, b)
        if parts:
            for o, w, frac, sup in parts:
                if o == level:
                    return ("w", w, frac, sup)
            if any(o > level for o, *_ in parts) and (parts[0][2] or parts[0][3]):
                return ("w", 0, parts[0][2], parts[0][3])
        return ("x",)
    return fn


def width_key(s):
    """What contribution() and width_input() read of S."""
    if s[0] == "T":
        return s[:3] + (0, s[4], 0) + s[6:]
    return s[:4] + (0, s[5], 0) + s[7:]


def pad_key(s):
    return s[:3] if s[0] == "R" else ("T",)


def result_key(b):
    """What contribution() reads of B: a result's tag and count."""
    if b[0] in ("mid", "fend", "qend", "e1", "e2", "o2"):
        return (b[0], 0, b[2]) + ((False,) if len(b) > 3 else ())
    return BLANK


def width_view(v):
    return v[0] != "x"


CAP = (L.MAX_CHARS + 1) * WIDTH[0]


def frac_step(state, v):
    k = v[0]
    if k == "nopen":
        return ("x",), ("num", 0, False)
    if k == "w":
        if state[0] == "num":
            return ("x",), ("num", min(CAP, state[1] + v[1]), state[2] or v[2])
        if state[0] == "den":
            return ("x",), ("den", max(-CAP, state[1] - v[1]), state[2] or v[2])
        return ("x",), state
    if k == "mid":
        return ("mid", state[1], state[2]), ("den", state[1], False)
    if k == "fend":
        return ("fend", state[1], state[2]), ("out",)
    return ("x",), state


def sqrt_step(state, v):
    k = v[0]
    if k == "qopen":
        return ("x",), ("rad", 0, 0)
    if k == "w":
        if state[0] == "rad":
            kind = 2 if (v[2] or state[2] == 2) else max(state[2], 1 if v[3] else 0)
            return ("x",), ("rad", min(CAP, state[1] + v[1]), kind)
        return ("x",), state
    if k == "qend":
        return ("qend", state[1], state[2]), ("out",)
    return ("x",), state


def pair_step(state, v):
    """The first script of a stacked pair counts its width up; the second
    counts down from it."""
    k = v[0]
    if k == "sopen":
        if v[1] == "first":
            return ("x",), ("first", 0)
        w1 = state[1] if state[0] == "between" else 0
        return ("o2", w1), ("second", w1)
    if k == "w":
        if state[0] == "first":
            return ("x",), ("first", min(CAP, state[1] + v[1]))
        if state[0] == "second":
            return ("x",), ("second", max(-CAP, state[1] - v[1]))
        return ("x",), state
    if k in ("gclose", "argend"):
        pos = v[1]
        w = v[2] if k == "argend" else 0
        if pos == "first":
            w1 = min(CAP, state[1] + w) if state[0] == "first" else 0
            return ("e1", w1), ("between", w1)
        d = max(-CAP, state[1] - w) if state[0] == "second" else 0
        return ("e2", d), ("out",)
    return ("x",), state


# The counters add widths in two digits: one pass adds the low digits
# (BASE of them) and leaves each token its carry, the next adds the high
# digits and carries, so a pass's rules are a digit's states times its
# inputs, not a width's times a width's. Whether a part holds a fraction
# (or how tall a root must be) has a pass of its own.

BASE = 16
HIGH = CAP // BASE + 1
SIGN = {"num": 1, "rad": 1, "first": 1, "den": -1, "second": -1, "out": 0, "between": 0}


def counter_op(kind):
    """What a token does to the counter: ("reset", mode), ("w", width)
    (added or taken away, as the mode says), or ("emit", tag, width,
    modes, then): the width added if the mode is one of `modes`, the count
    (or 0 in another mode) given as (tag, count), the mode becoming `then`
    and the count kept (or 0 with "out")."""
    def fn(v):
        k = v[0]
        if k == "w":
            return ("w", v[1])
        if kind == "frac":
            return {"nopen": ("reset", "num"), "mid": ("emit", "mid", 0, ("num",), "den"),
                    "fend": ("emit", "fend", 0, ("den",), "out")}.get(k, ("x",))
        if kind == "sqrt":
            return {"qopen": ("reset", "rad"), "qend": ("emit", "qend", 0, ("rad",), "out")}.get(k, ("x",))
        if k == "sopen":
            return ("reset", "first") if v[1] == "first" else ("emit", "o2", 0, ("between",), "second")
        if k in ("gclose", "argend"):
            w = v[2] if k == "argend" else 0
            assert w < BASE
            return ("emit", "e1", w, ("first",), "between") if v[1] == "first" else ("emit", "e2", w, ("second",), "out")
        return ("x",)
    return fn


def low_input(op):
    if op[0] == "w":
        return ("w", op[1] % BASE)
    if op[0] == "emit":
        return op[:2] + (op[2] % BASE,) + op[3:]
    return op


def low_step(state, v):
    mode, lo = state
    k = v[0]
    if k == "reset":
        return ("r",), (v[1], 0)
    if k == "w":
        sg = SIGN[mode]
        n = lo + sg * v[1]
        return ("c", n // BASE, sg), (mode, n % BASE)
    _, tag, w, modes, then = v
    if mode in modes:
        sg = SIGN[mode]
        n = lo + sg * w
        out = ("e", tag, n % BASE, n // BASE, sg, True, then != "out")
    else:
        out = ("e", tag, 0, 0, 0, False, then != "out")
    return out, (then, out[2] if then != "out" else 0)


def high_input(a, c):
    h = c[1] if c[0] == "hi" else 0
    if a[0] == "c":
        return ("d", a[2] * h + a[1])
    if a[0] == "e":
        _, tag, lo, carry, sg, ok, keep = a
        return ("E", tag, lo, sg * h + carry, ok, keep)
    return a


def high_step(hi, v):
    k = v[0]
    if k == "r":
        return ("x",), 0
    if k == "d":
        return ("x",), max(-HIGH, min(HIGH, hi + v[1]))
    _, tag, lo, delta, ok, keep = v
    used = max(-HIGH, min(HIGH, hi + delta)) if ok else 0
    return (tag, used * BASE + lo if ok else 0), (used if keep else 0)


def flag_input(kind):
    """What the flag pass of a counter sees (C), from its input."""
    def fn(a):
        k = a[0]
        if kind == "frac":
            if k == "w":
                return ("w", a[2])
            return {"nopen": ("r",), "mid": ("emit",), "fend": ("emit",)}.get(k, BLANK)
        if k == "w":
            return ("w", a[2], a[3])
        return {"qopen": ("r",), "qend": ("emit",)}.get(k, BLANK)
    return fn


def frac_flag_step(flag, v):
    """Whether the part holds a fraction."""
    if v[0] == "r":
        return ("x",), False
    if v[0] == "w":
        return ("x",), flag or v[1]
    return ("fl", flag), False


def sqrt_flag_step(kind, v):
    """How tall the root's sign is: 2 over a fraction, 1 over a superscript."""
    if v[0] == "r":
        return ("x",), 0
    if v[0] == "w":
        return ("x",), 2 if (v[1] or kind == 2) else max(kind, 1 if v[2] else 0)
    return ("fl", kind), 0


def merge_count(level, kind):
    def fn(b, a, c):
        if a[0] in ("mid", "fend", "qend", "e1", "e2", "o2"):
            return (a[0], level, a[1]) + ((c[1],) if kind != "pair" else ())
        return b
    return fn


def counter(level, kind):
    """The passes of one counter (see frac_step, sqrt_step and pair_step,
    which they compute)."""
    ops = counter_op(kind)
    P = [Derive("A", ["S"], lambda a, s: ("s", s), keys=[width_key]),
         Derive("A", ["B"], lambda a, b, f=width_input(level, kind): f(None, a[1], b), keys=[result_key])]
    if kind != "pair":
        P += [Derive("C", ["A"], lambda c, a, f=flag_input(kind): f(a)),
              LTR("C", frac_flag_step if kind == "frac" else sqrt_flag_step, False if kind == "frac" else 0,
                  view=lambda v: v != BLANK), strip("C")]
    P += [Derive("C", ["A"], lambda c, a: ("hi", a[1] // BASE) if a[0] == "w" else c),
          Map("A", lambda v: low_input(ops(v))),
          LTR("A", low_step, ("out", 0), view=width_view), strip("A"),
          Derive("A", ["C"], high_input),
          LTR("A", high_step, 0, view=width_view), strip("A"),
          Derive("B", ["A", "C"], merge_count(level, kind)),
          Map("A", lambda v: BLANK), Map("C", lambda v: BLANK)]
    return P


def merge_width(level):
    def fn(b, s, a):
        if a[0] in ("mid", "fend", "qend", "e1", "e2", "o2"):
            return (a[0], level) + a[1:]
        return b
    return fn


def pad_input(level):
    def fn(a, s, b):
        if s[0] == "R" and s[2] == level:
            name = s[1]
            if name == "fend":
                return ("fend", b[2], b[3])
            if name == "mid":
                return ("mid", b[3])
            if name in ("dopen", "nopen", "sroot"):
                return (name,)
            if name == "qend":
                return ("qend", b[3])
        return ("x",)
    return fn


def pad_step(state, v):
    """Right to left: a fraction's numerator and denominator learn d, the
    difference of their widths, and whether the other holds a fraction; a
    root learns how tall its sign is."""
    k = v[0]
    if k == "fend":
        return ("x",), ("d", v[1], v[2])
    if k == "dopen":
        if state is None or state[0] != "d":
            raise Impossible
        return ("dpad", state[1], state[2]), state
    if k == "mid":
        if state is None or state[0] != "d":
            raise Impossible
        return ("x",), ("n", state[1], v[1])
    if k == "nopen":
        if state is None or state[0] != "n":
            raise Impossible
        return ("npad", state[1], state[2]), None
    if k == "qend":
        return ("x",), ("k", v[1])
    if k == "sroot":
        if state is None or state[0] != "k":
            raise Impossible
        return ("kind", state[1]), None
    return ("x",), state


# The pads in two digits, as the counters: one right-to-left pass carries
# the low digit of d (and the flags), the next the high digit.

def pad_result_key(b):
    """What pad_input() reads of B."""
    if b[0] == "fend":
        return ("fend", 0, b[2], b[3])
    if b[0] in ("mid", "qend"):
        return (b[0], 0, 0, b[3])
    return BLANK


def pad_low(v):
    return ("fend", v[1] % BASE, v[2]) if v[0] == "fend" else v


def pad_low_step(state, v):
    """pad_step with d's low digit; a numerator's opener and a root's sign
    keep what they are, for the high digit's pass and the merge."""
    k = v[0]
    if k == "fend":
        return ("x",), ("d", v[1], v[2])
    if k == "dopen":
        if state is None or state[0] != "d":
            raise Impossible
        return ("dpadL", state[1], state[2]), state
    if k == "mid":
        if state is None or state[0] != "d":
            raise Impossible
        return ("mid",), ("n", state[1], v[1])
    if k == "nopen":
        if state is None or state[0] != "n":
            raise Impossible
        return ("npadL", state[1], state[2]), None
    if k == "qend":
        return ("x",), ("k", v[1])
    if k == "sroot":
        if state is None or state[0] != "k":
            raise Impossible
        return ("kind", state[1]), None
    return ("x",), state


def pad_high_input(c, a):
    if c[0] == "hi":
        return ("fend", c[1])
    return {"mid": ("mid",), "dpadL": ("dopen",), "npadL": ("nopen",)}.get(a[0], BLANK)


def pad_high_step(state, v):
    k = v[0]
    if k == "fend":
        return ("x",), ("d", v[1])
    if k == "dopen":
        if state is None or state[0] != "d":
            raise Impossible
        return ("dpadH", state[1]), state
    if k == "mid":
        if state is None or state[0] != "d":
            raise Impossible
        return ("x",), ("n", state[1])
    if k == "nopen":
        if state is None or state[0] != "n":
            raise Impossible
        return ("npadH", state[1]), None
    return ("x",), state


def merge_pads(b, a, c):
    if a[0] in ("dpadL", "npadL"):
        return (a[0][:4], c[1] * BASE + a[1], a[2])
    return a if a[0] == "kind" else b


def pads(level):
    """The passes of pad_step at a level."""
    return [Derive("A", ["S"], lambda a, s: ("s", s), keys=[pad_key]),
            Derive("A", ["B"], lambda a, b, f=pad_input(level): f(None, a[1], b), keys=[pad_result_key]),
            Derive("C", ["A"], lambda c, a: ("hi", a[1] // BASE) if a[0] == "fend" else BLANK),
            Map("A", pad_low),
            RTL("A", pad_low_step, None, view=width_view), strip("A"),
            Derive("C", ["A"], pad_high_input),
            RTL("C", pad_high_step, None, view=lambda v: v != BLANK), strip("C"),
            Derive("B", ["A", "C"], merge_pads),
            Map("A", lambda v: BLANK), Map("C", lambda v: BLANK)]


def merge_pad(b, a):
    """Into B, which a numerator's or denominator's opener or a root's
    sign leaves empty."""
    return a if a[0] in ("dpad", "npad", "kind") else b


def numerator_flag(level):
    def fn(c, s):
        if s[0] == "R" and s[1] == "fend" and s[2] == level:
            return ("wN?", level)
        return c
    return fn


def copy_width(prev, v):
    """A fraction's end learns its numerator's width, as ("wN", level, w):
    with the level, so no level's results look like another's targets."""
    return ("wN", v[1], prev[2] if prev is not None and prev[0] == "mid" else 0)


# the program ----------------------------------------------------------------

def every(_):
    return True


def program():
    P = [LTR("S", depth_step, (0, False), spaces=True), strip("S", spaces=True),
         Context("S", kind_of_open, targets=is_open, spaces=True)]
    for level in range(1, BRACE_LIMIT + 1):
        P.append(Context("S", closer_kind, targets=lambda v, l=level: v[0] == "C" and v[1] == l and len(v) == 2,
                         ctx_view=level_braces(level)))
    P.append(Context("S", denominator, targets=lambda v: v[0] == "O" and len(v) == 3 and v[2] == "G", spaces=True))
    for level in range(1, BRACE_LIMIT + 1):
        P.append(Context("S", denominator_closer,
                         targets=lambda v, l=level: v[0] == "C" and v[1] == l and v[2] == "G",
                         ctx_view=level_braces(level)))
    P += [Derive("A", ["S"], lambda a, s: check_a_input(s), spaces=True),
          LTR("A", check_a_step, (frozenset(), 0, 0), spaces=True), strip("A", spaces=True),
          Derive("B", ["S"], lambda b, s: check_b_input(s), spaces=True),
          LTR("B", check_b_step, 0, spaces=True), strip("B", spaces=True),
          Derive("S", ["A", "B"], merge_checks), Map("S", restore_space, spaces=True),
          Map("A", lambda v: BLANK), Map("B", lambda v: BLANK)]
    for level in range(1, L.MAX_DEPTH + 1):
        P += [Derive("A", ["S"], lambda a, s, l=level: valid_input(l)(s), spaces=True),
              RTL("A", valid_step, (None, None, "x"),
                  view=lambda v, l=level: v[0] != "in" and not (v[0] == "sp" and v[1] >= l), spaces=True),
              strip("A", spaces=True),
              Derive("S", ["A"], merge_valid(level)), Map("S", restore_space, spaces=True),
              Map("A", lambda v: BLANK)]
    P.append(Map("S", finish_valid))
    for level, tr in zip(range(1, L.MAX_DEPTH + 1), "ABC"):
        P += [Derive(tr, ["S"], lambda t, s, l=level: role_input(l)(s), spaces=True),
              LTR(tr, role_step, (None, None, None, None), spaces=True), strip(tr, spaces=True),
              Map("S", lambda v: (" ", v[1]) if v[0] == "sp" else v, spaces=True)]
    P += [Derive("A", [], lambda a: fold(RUN, a, 1)),
          Derive("B", ["A"], lambda b, a: fold(a, b, 2)),
          Derive("C", ["B"], lambda c, b: fold(b, c, 3)),
          Derive("S", ["C"], fold_finish),
          Map("S", lambda v: ("T", " ", 0, 0, 0, 0) if v[0] == " " else v, spaces=True)]
    P += [Map(tr, lambda v: BLANK) for tr in "ABC"]
    for level in range(L.MAX_DEPTH, 0, -1):
        for kind in ("frac", "sqrt", "pair"):
            P += counter(level, kind)
        P += pads(level)
    for level in range(L.MAX_DEPTH, 0, -1):
        P += [Derive("C", ["S"], numerator_flag(level)),
              Context("C", copy_width, targets=lambda v, l=level: v == ("wN?", l),
                      ctx_track="B", ctx_view=lambda v, l=level: v[0] == "mid" and v[1] == l)]
    P += finals()
    return P


def finals():
    """Each slot's glyph (see assemble.final), in an order that leaves the
    tracks a slot is made from unfinished until then. B is first reduced to
    what the slots need of it, for the token's S (assemble.localize), so
    the final passes read small values."""
    import assemble

    def made(slot, s, b=BLANK, c=BLANK, char=None):
        return assemble.final({"S": s, "B": b, "C": c, "char": char})[slot]

    def fend_width(c, is_fend):
        return c if is_fend else BLANK

    def fend_base(g, c):
        """A fraction's end in flow is a base as wide as its numerator, which
        C holds: made first, so that no rule reads B and C at once."""
        return ("fendbase", c[2]) if c != BLANK else g

    def slot(name):
        def fn(target, s, b):
            if name == "G" and target[0] == "fendbase":
                return target
            return made(name, s, b, char=target[1] if name == "G" else None)
        return fn
    def keyed(name, sources=("S", "B")):
        keys = [lambda s, n=name: assemble.slot_key(n, s)]
        if "B" in sources:
            keys.append(lambda b, n=name: assemble.needed(b, n))
        return keys
    P = [Derive("C", ["S"], fend_width, keys=[lambda s: s[0] == "R" and s[1] == "fend" and s[4] == 0]),
         final(Derive("G", ["C"], fend_base)),
         Derive("B", ["S"], lambda b, nc: assemble.localize(b, nc), keys=[assemble.need_class]),
         final(Derive("A", ["S", "B"], slot("A"), keys=keyed("A"))),
         final(Derive("G", ["S", "B"], slot("G"), keys=keyed("G"))),
         final(Derive("C", ["S", "B"], slot("C"), keys=keyed("C"))),
         final(Derive("B", ["S"], lambda b, s, f=slot("B"): f(b, s, assemble.needed(b, "B")), keys=keyed("B", ("S",)))),
         final(Map("S", lambda v: made("S", v))),
         final(Map("S", lambda v: ("space",) if v[0] == "T" and v[1] == " " else v, spaces=True))]
    return P


def final(p):
    """A pass whose outputs are a slot's glyphs (assemble.final): its track
    is finished after it."""
    p.final = True
    return p


# simulation -------------------------------------------------------------------

def slot(tok, track, spaces):
    if track in tok:
        return track
    return "S" if spaces and tok["S"] is not None and "A" not in tok else None


def run(P, toks):
    for p in P:
        if isinstance(p, Map):
            for t in toks:
                if "A" not in t and not p.spaces:
                    continue                  # a space, which the Map leaves alone
                tr = slot(t, p.track, p.spaces)
                if tr is not None:
                    t[tr] = p.fn(t[tr])
        elif isinstance(p, Derive):
            for t in toks:
                if p.target in t and all(s in t for s in p.sources):
                    t[p.target] = p.fn(t[p.target], *[p.key(i, t[s]) for i, s in enumerate(p.sources)])
                elif p.spaces and "A" not in t:
                    t["S"] = p.fn(t["S"], *[p.key(i, t["S"]) for i, _ in enumerate(p.sources)])
        elif isinstance(p, Context):
            seen = None
            orig = []
            for t in toks:
                trt = slot(t, p.track, p.spaces)
                trc = slot(t, p.ctx_track, p.spaces)
                cval = t[trc] if trc is not None else None
                tval = t[trt] if trt is not None else None
                orig.append((trt, tval, trc, cval))
            for t, (trt, tval, trc, cval) in zip(toks, orig):
                if p.ctx_track == p.track:
                    if trt is None:
                        continue
                    if p.targets(tval):
                        t[trt] = p.fn(seen, tval)
                    if p.targets(tval) or p.ctx_view(tval):
                        seen = tval
                    continue
                # two tracks: the token's glyphs in track order
                order = [(trc, cval, "ctx"), (trt, tval, "tgt")]
                if "SABC".index(p.ctx_track) > "SABC".index(p.track):
                    order.reverse()
                for tr, val, role in order:
                    if tr is None:
                        continue
                    if role == "tgt" and p.targets(val):
                        t[tr] = p.fn(seen, val)
                        seen = val
                    elif role == "ctx" and p.ctx_view(val):
                        seen = val
        else:
            ordered = toks if not isinstance(p, RTL) else list(reversed(toks))
            state = p.init
            for t in ordered:
                tr = slot(t, p.track, p.spaces)
                if tr is None or not p.view(t[tr]):
                    continue
                out, state = p.step(state, t[tr])
                t[tr] = (out, state)
    return toks


_PROGRAM = None


def simulate(line):
    global _PROGRAM
    if _PROGRAM is None:
        _PROGRAM = program()
    return run(_PROGRAM, tokens(line))
