"""The relaxed notation's front end: passes that read a line the way
relaxed.py does, and leave it as the tokens of the LaTeX that lays out the
same, for program.py's passes to lay out.

    (a+b)/(c+d)   ->  \\frac (a+b) / (c+d)    the parentheses as braces
    1/2           ->  \\frac {1} / {2}        braces inserted
    x^12          ->  x ^ {12}

What the line doesn't have (a fraction's \\frac, braces around a part with
no parentheses) is inserted as virtual tokens, which draw nothing and count
no characters. A fraction's slash stays between its parts, as a token that
hides (Z). Everything else that isn't a construct's becomes text ("c").

The passes:
 1. paren depth (parentheses past BRACE_LIMIT, and what follows, are text),
    then which parentheses match, and which groups are empty;
 2. what each token's right neighbor is, then words: where they start and
    end, and their kind (number, number and letter, letter, function,
    other), as relaxed.word_kind;
 3. which slashes are in a run that a slash next to a long word poisons;
 4. a parenthesis level at a time, outermost first, on track A (a small
    view of S, compact()): scripts (with the argument each `^` and `_`
    would take, found right to left), then the elements as scripts leave
    them, then fractions (their left side found left to right, their
    right side right to left) and their parts. What a level decides goes
    to B (results), not S: in S, every combination of it would be a value
    of its own, and so a glyph.
 5. the virtual tokens around each token (Insert), and its LaTeX kind.

Values are (class, depth, flags), flags a sorted tuple of names and (key,
value) pairs.
"""

import layout as L
import program as P
import relaxed as R
from program import BLANK, LTR, RTL, Context, Derive, Insert, Map, strip

LIMIT = L.BRACE_LIMIT
FN_LETTERS = set("".join(R.FUNCTIONS))
PREFIXES = {f[:k] for f in R.FUNCTIONS for k in range(1, len(f) + 1)}
OPS = set(R.OPERATORS) - {"-"}
EDGE = set(R.EDGES) - set(R.OPERATORS) - set("().")
LEVELS = range(LIMIT + 1)


# values ----------------------------------------------------------------------

def V(cls, d, *flags):
    return (cls, d, tuple(sorted(set(flags), key=repr)))


def flags(v):
    return v[2] if len(v) > 2 else ()


def has(v, f):
    return f in flags(v)


def get(v, key, default=None):
    for f in flags(v):
        if isinstance(f, tuple) and f[0] == key:
            return f[1]
    return default


def put(v, *new, drop=()):
    """v with flags `new` (a keyed one replacing its key's) and without
    the names or keys in `drop`."""
    keys = {f[0] for f in new if isinstance(f, tuple)} | set(drop)
    old = [f for f in flags(v) if (f[0] if isinstance(f, tuple) else f) not in keys]
    return V(v[0], v[1], *old, *new)


def char_class(ch):
    if ch.isdigit():
        return ("d",)
    if ch.isalpha():
        return ("l", ch if ch in FN_LETTERS else "*")
    if ch in "()^_/-.":
        return (ch,)
    if ch in OPS:
        return ("o",)
    if ch in EDGE:
        return ("e",)
    return ("x",)


def tokens(line):
    """The font's tokens for a line, as program.tokens gives them for
    LaTeX: S holds the character's class."""
    out = []
    for kind, start, end, value in R.lex(line):
        if kind == "sym":
            out.append({"text": line[start:end], "char": value, "S": ("Y",), "G": ("g", value, "Y2")})
        elif kind == "cmd":
            out.append({"text": "s", "char": "s", "S": ("R",), "G": ("g", "s", "R")})
            for ch in "qrt":
                out.append({"text": ch, "char": ch, "S": ("Ls", ch), "G": ("g", ch, "Ls")})
        elif kind == " ":
            out.append({"text": " ", "char": " ", "S": (" ",)})
        else:
            out.append({"text": value, "char": value, "S": char_class(value), "G": ("g", value, None)})
    for t in out:
        if "G" in t:
            for tr in "ABC":
                t[tr] = BLANK
    return out


# 1. depth, matching ------------------------------------------------------------

def depth_step(state, v):
    d, dead = state
    k = v[0]
    extra = [("c", v[1])] if k in ("l", "Ls") else []
    if k == " ":
        return V(" ", d), state
    if dead:
        if k in ("(", ")"):
            return V("e", d), state
        if k in ("^", "_", "/", "R", "Ls"):
            return V("x", d), state
        return V(k, d, *extra), state
    if k == "(":
        if d == LIMIT:
            return V("e", d), (d, True)
        return V("(", d), (d + 1, False)
    if k == ")":
        if d == 0:
            return V("e", 0), state
        return V(")", d - 1), (d - 1, False)
    return V(k, d, *extra), state


def match_step(state, v):
    """Right to left: which parentheses match (one that doesn't is text),
    and which open an empty group."""
    pend, right_close = state
    k, d = v[0], v[1]
    if k == ")":
        return v, (pend | {d}, True)
    if k == "(":
        if d in pend:
            out = put(v, "empty") if right_close else v
            return out, (frozenset(x for x in pend if x < d), False)
        return V("e", d), (pend, False)
    return v, (pend, False)


def empty_closer(prev, v):
    return put(v, "empty") if prev is not None and prev[0] == "(" and has(prev, "empty") else v


# 2. neighbors, words -----------------------------------------------------------

def right_class(v, right):
    """What a token is to the one before it: a digit, a letter, a point
    before a digit, a matched non-empty "(", "_", the "sqrt" before one
    ("q"), or "x"."""
    k = v[0]
    if k == "d":
        return "d"
    if k == "l":
        return "l"
    if k == ".":
        return "p" if right == "d" else "x"
    if k == "(" and not has(v, "empty"):
        return "("
    if k == "_":
        return "_"
    if k in ("Ls", "R") and right in ("(", "q"):
        return "q"
    return "x"


def next_step(right, v):
    if v[0] == " ":
        return v, "x"
    return put(v, ("n", right)), right_class(v, right)


def advance(ph, k, ch):
    """A word's phase after one more character (k "d", "l" or "p")."""
    if ph is None:
        if k == "d":
            return "N0"
        return ("P", ch) if ch in PREFIXES else "L*"
    if ph == "O":
        return "O"
    if ph in ("N0", "N1"):
        if k == "d":
            return ph
        if k == "p":
            return "N1" if ph == "N0" else "O"
        return "NL1"
    if ph in ("NL1", "NL2"):
        return "NL2" if k == "l" else "O"
    if ph == "L*":
        return "O"
    if k == "l" and ph[1] + ch in PREFIXES:
        return ("P", ph[1] + ch)
    return "O"


def kind_of(ph):
    """relaxed.word_kind, with "split" for another word that is a number
    and letters (a script takes the number)."""
    if ph in ("N0", "N1"):
        return "num"
    if ph == "NL1":
        return "numlet"
    if ph == "NL2":
        return "split"
    if ph == "L*":
        return "let"
    if ph == "O":
        return "other"
    pre = ph[1]
    if len(pre) == 1:
        return "let"
    return "fn" if pre in R.FUNCTIONS else "other"


def word_step(state, v):
    """Left to right: state (phase, last kind) inside a word, or None."""
    k = v[0]
    if k == " ":
        return v, None
    nxt = get(v, "n")
    point = k == "." and state is not None and state[1] == "d" and nxt == "d"
    if k not in ("d", "l") and not point:
        if k == ".":
            return V("e", v[1], ("n", nxt)), None        # a point in no number: punctuation
        return v, None
    kk = "p" if point else k
    ph = advance(state[0] if state else None, kk, get(v, "c", "*"))
    start = state is None
    end = not (nxt in ("d", "l") or (nxt == "p" and k == "d"))
    pre = ph in ("N0", "N1")
    out = V("w", v[1], ("ph", ph), *(["start"] if start else []), *(["end", ("n", nxt)] if end else []),
            *(["pre"] if pre else []), *(["prelast"] if pre and nxt == "l" else []))
    return out, (None if end else (ph, "d" if kk in ("d", "p") else "l"))


def kind_step(state, v):
    """Right to left: every character of a word learns its kind."""
    if v[0] != "w":
        return v, None
    if has(v, "end"):
        state = kind_of(get(v, "ph"))
    return put(v, ("k", state), drop=("ph",)), (None if has(v, "start") else state)


OPERAND_WORDS = ("num", "numlet", "let")


def bad_start(v):
    return v[0] == "w" and has(v, "start") and get(v, "k") not in OPERAND_WORDS


def bad_end(v):
    return v[0] == "w" and has(v, "end") and get(v, "k") not in OPERAND_WORDS


# 3. poisoned runs ---------------------------------------------------------------

def poison_right(state, v):
    if v[0] == "/":
        return put(v, ("rb", state)), bad_start(v)
    return v, bad_start(v) if v[0] != " " else False


def poison_left(state, v):
    prev_bad, seen = state
    if v[0] == " ":
        return v, (False, False)
    if v[0] == "/":
        bad = prev_bad or get(v, "rb")
        seen = seen or bad
        return put(v, ("bad", bad), ("seen", seen), drop=("rb",)), (False, seen)
    return v, (bad_end(v), seen)


def poison_ahead(ahead, v):
    if v[0] == " ":
        return v, False
    if v[0] == "/":
        out = put(v, drop=("bad", "seen"))
        if get(v, "seen") or ahead:
            out = put(out, "poison")
        return out, ahead or get(v, "bad")
    return v, ahead


def tidy(v):
    """Drop what the passes after the words don't read."""
    if v[0] == "w":
        keep = ("start", "end", "pre", "prelast", "k")
        out = V("w", v[1], *[f for f in flags(v) if (f[0] if isinstance(f, tuple) else f) in keep])
        if has(v, "end") and get(v, "n") in ("(", "_"):
            out = put(out, ("n", get(v, "n")))
        return out
    if v[0] in (")", "Y"):
        return V(v[0], v[1], *[f for f in flags(v) if f == "empty"], *(["us"] if get(v, "n") == "_" else []))
    if v[0] in ("R", "Ls"):
        return V(v[0], v[1], *(["sq"] if get(v, "n") in ("q", "(") else []), *([("c", get(v, "c"))] if v[0] == "Ls" else []))
    if v[0] == "(":
        return V("(", v[1], *[f for f in flags(v) if f == "empty"])
    if v[0] == "/":
        return V("/", v[1], *[f for f in flags(v) if f == "poison"])
    return V(v[0], v[1])


def paren_owner(prev, v):
    """A "(" after a function's name (or one letter) opens its arguments;
    after "sqrt", a root's contents."""
    if has(v, "empty") or prev is None:
        return v
    if prev[0] == "w" and has(prev, "end") and get(prev, "k") in ("let", "fn"):
        return put(v, "app")
    if prev[0] == "Ls":
        return put(v, "sq")
    return v


def closer_owner(prev, v):
    if prev is not None and prev[0] == "(":
        return put(v, *[f for f in ("app", "sq") if has(prev, f)])
    return v


# 4. a level: scripts -------------------------------------------------------------

def arg_info(v, right, carry):
    """What a script's argument would be if it started at token v, given
    `right` (that of the token after v) and `carry` (inside a word, read
    right to left: whether "_" follows its end). ("group"|"sym"|"word"|
    "split"|"minus", single, followed by "_") or None."""
    k = v[0]
    if k == "(" and not has(v, "empty") and not has(v, "app") and not has(v, "sq"):
        return ("group", False, carry)
    if k == "Y":
        return ("sym", True, has(v, "us"))
    if k == "w" and has(v, "start"):
        kind = get(v, "k")
        if kind in ("let", "fn") and has(v, "end") and get(v, "n") == "(":
            return None                  # f(x): a function's name, not an argument
        if kind in ("num", "let"):
            return ("word", has(v, "end"), carry)
        if kind in ("numlet", "split"):
            return ("split", has(v, "prelast"), False)
        return None
    if k == "-":
        if right is not None and right[0] in ("sym", "word", "split", "minus"):
            return ("minus", False, right[2])
        return None
    return None


def args_step(level):
    def step(state, v):
        """Right to left. state: (info of an argument starting at the next
        token, `_` after the current word's end or group's closer)."""
        right, carry = state
        if v[1] < level:
            return v, (None, False)
        if v[0] in ("^", "_"):
            out = put(v, ("ai", right))
        else:
            out = v
        if v[0] == "w" and has(v, "end"):
            carry = get(v, "n") == "_"
        if v[0] == ")":
            carry = has(v, "us")
        info = arg_info(v, right, carry)
        return out, (info, carry if (v[0] == "w" and not has(v, "start")) or v[0] == ")" else False)
    return step


def element_start(v, prev_us):
    """The element a token starts, as (operand, first is a number, after
    "_", bare letter, plain group), or None if it continues one."""
    k = v[0]
    if k == "w":
        if not has(v, "start"):
            return None
        kind = get(v, "k")
        app = has(v, "end") and get(v, "n") == "(" and kind in ("let", "fn")
        return (kind in OPERAND_WORDS or app, kind == "num", prev_us, kind == "let" and not app, False)
    if k == "(":
        if has(v, "app") or has(v, "sq"):
            return None
        return (not has(v, "empty"), False, prev_us, False, True)
    if k == "R":
        return (has(v, "sq"), False, prev_us, False, False)
    if k == "Ls" or k == ")":
        return None
    if k == "Y":
        return (True, False, prev_us, False, False)
    return (False, False, prev_us, False, False)


def element_end(v):
    """Whether a token ends the element it is in (scripts aside)."""
    k = v[0]
    if k == "w":
        return has(v, "end") and not (get(v, "n") == "(" and get(v, "k") in ("let", "fn"))
    if k == "(":
        return False
    if k == "R":
        return False
    if k == "Ls":
        return get(v, "c") == "t" and not has(v, "sq")
    return True


def scripts_step(level):
    def step(state, v):
        """Left to right. state: (last, cur, arg, prev_us):
        last: the element that ended at the previous token, if a script
          may follow it: (its first token is a number, scripts it has);
        cur: the element being read, (operand, bare letter, plain group,
          whether its first token is a number, or None if no script may
          follow it), or "rest" for the letters after a script's number;
        arg: (kind, type, single, phase, base) while a script's argument
          is read, base being `last` before the script;
        prev_us: whether the previous token is "_"."""
        last, cur, arg, prev_us = state
        if v[1] < level:
            return v, (None, None, None, False)
        k = v[0]
        us = k == "_"
        if arg is not None:
            kind, typ, single, phase, base = arg
            out = put(v, "arg")
            if typ == "group":
                if phase == 0:
                    return put(out, "hide"), (last, cur, (kind, typ, single, 1, base), us)
                done = True
                out = put(out, "hide")
            elif k == "-":
                done = False
            elif k == "w":
                done = has(v, "prelast") if get(v, "k") in ("numlet", "split") else has(v, "end")
            else:
                done = True               # a symbol
            if not done:
                return out, (last, cur, arg, us)
            script = (base[0], base[1] + (kind,))
            out = put(out, "argend", *(["multi"] if not single and typ != "group" else []),
                      ("ed", (True, False, False)))
            if k == "w" and not has(v, "end"):
                # the letters after a number are text of their own
                return out, (script, "rest", None, us)
            return out, (script, None, None, us)
        if k in ("^", "_") and last is not None:
            info = get(v, "ai")
            firstnum, taken = last
            ok = info is not None and len(taken) < 2 and k not in taken and \
                not (k == "_" and firstnum) and not (k == "_" and info[2])
            if ok:
                form = "group" if info[0] == "group" else "single" if info[1] else "multi"
                return put(v, ("sc", form), drop=("ai",)), (last, None, (k, info[0], info[1], 0, last), us)
        v = put(v, drop=("ai",))
        if cur == "rest":
            start = (False, False, False, False, False)
        else:
            start = element_start(v, prev_us)
        if start is not None:
            operand, firstnum, after_us, bare, group = start
            cur = (operand, bare, group, firstnum if operand and not after_us else None)
            v = put(v, "pstart")
        if cur is None or cur == "rest":
            cur = (False, False, False, None)
        if element_end(v):
            operand, bare, group, sfirst = cur
            return put(v, ("ed", (operand, bare, group))), \
                ((sfirst, ()) if sfirst is not None else None, None, None, us)
        return v, (last, cur, None, us)
    return step


def post_end(level):
    def step(next_script, v):
        """Right to left: an element ends where no script follows."""
        if v[1] < level:
            return v, False
        out = v
        if get(v, "ed") is not None and not next_script:
            out = put(v, "pend")
        return out, get(v, "sc") is not None
    return step


# 4. a level: fractions ------------------------------------------------------------

def allowed(v):
    """Whether a token may stand next to a fraction (a symbol only on its
    own, not as a script's base or argument)."""
    return v is None or v[0] in (" ", "o", "-", "e") or standalone_sym(v)


def is_operator(v):
    return v[0] in ("o", "-") and not has(v, "arg")


def standalone_sym(v):
    return v[0] == "Y" and has(v, "pend") and has(v, "pstart") and not has(v, "arg")


def expr_step(state, v, operand):
    """The in-expression automaton, one token on. state: the set of what
    the tokens so far can be read as: 1 an operand (and spaces), 2 an
    operand, an operator (and spaces). A symbol on its own is either."""
    if standalone_sym(v):
        return frozenset({1} | ({2} if 1 in state else set()))
    if operand:
        return frozenset({1})
    if v[0] == " ":
        return state
    if is_operator(v):
        return frozenset({2}) if 1 in state else frozenset()
    return frozenset()


def side(ed, ok, expr):
    """What a fraction needs of an element next to its slash: None if it
    can't be a part (no operand, or something not allowed next to it),
    else (form, in an expression): form "b" a lone letter, "g" a plain
    group, "o" another operand."""
    operand, bare, group = ed
    if not (operand and ok):
        return None
    return ("b" if bare else "g" if group else "o", expr)


def left_step(level):
    def step(state, v):
        """Left to right. state: (prev, cur, expr, prev_ok): prev the
        element that ended at the previous token, as side() gives it; cur
        that being read, (allowed before it, in an expression)."""
        prev, cur, expr, prev_ok = state
        if v[1] < level:
            return v, (None, None, frozenset(), True)
        out = v
        if v[0] == "/":
            out = put(v, ("L", prev))
        if has(v, "pstart"):
            cur = (prev_ok, 2 in expr)
        nprev = None
        operand = False
        if has(v, "pend"):
            ed = get(v, "ed")
            c = cur if cur is not None else (False, False)
            nprev = side(ed, *c)
            operand = ed[0]
            cur = None
        return out, (nprev, cur, expr_step(expr, v, operand and not standalone_sym(v)), allowed(v))
    return step


def right_step(level):
    def step(state, v):
        """Right to left, as left_step: nxt the element that starts at the
        next token, as side() gives it; cur that being read, (operand,
        side)."""
        nxt, cur, expr, next_ok = state
        if v[1] < level:
            return v, (None, None, frozenset(), True)
        out = v
        if v[0] == "/":
            out = put(v, ("R", nxt))
        if has(v, "pend"):
            ed = get(v, "ed")
            cur = (ed[0], side(ed, next_ok, 2 in expr))
        nnxt = None
        operand = False
        if has(v, "pstart"):
            if cur is not None:
                operand, nnxt = cur
            cur = None
        return out, (nnxt, cur, expr_step(expr, v, operand and not standalone_sym(v)), allowed(v))
    return step


def decide(v):
    """A slash's verdict, from what is left and right of it."""
    if v[0] != "/":
        return v
    left, right = get(v, "L"), get(v, "R")
    out = put(v, drop=("L", "R"))
    if left is None or right is None or has(v, "poison"):
        return out
    if left[0] == "b" and right[0] == "b" and not (left[1] or right[1]):
        return out
    return put(out, ("Z", ("g" if left[0] == "g" else "b", "g" if right[0] == "g" else "b")))


def numerator_step(level):
    def step(state, v):
        """Right to left from a fraction's slash, over its numerator."""
        if v[1] < level:
            return v, None
        out = v
        if state is not None:
            if state[1]:
                out = put(out, ("nend", state[0]))
            if has(v, "pstart"):
                return put(out, ("nstart", state[0])), None
            return out, (state[0], False)
        z = get(v, "Z")
        return out, ((z[0], True) if z else None)
    return step


def denominator_step(level):
    def step(state, v):
        """Left to right from a fraction's slash, over its denominator."""
        if v[1] < level:
            return v, None
        out = v
        if state is not None:
            if state[1]:
                out = put(out, ("dstart", state[0]))
            if has(v, "pend"):
                return put(out, ("dend", state[0])), None
            return out, (state[0], False)
        z = get(v, "Z")
        return out, ((z[1], True) if z else None)
    return step


LEVEL_FLAGS = {"start", "end", "k", "prelast", "n", "empty", "app", "sq", "us", "c", "poison"}
RESULTS = {"sc", "hide", "Z", "nstart", "nend", "dstart", "dend"}


def compact(level):
    """What a level's passes read of S, on A: a token outside the level is
    a boundary (shallower) or unseen (deeper). A space's glyph is its only
    one, so it stays as it is."""
    def fn(a, s):
        if s[0] == " ":
            return s
        if s[1] < level:
            return ("bd", s[1])
        if s[1] > level:
            return ("deep", s[1])
        return V(s[0], s[1], *[f for f in flags(s) if (f[0] if isinstance(f, tuple) else f) in LEVEL_FLAGS])
    return fn


def result_key(a):
    """What a level leaves in S: a script's form, a hidden parenthesis, an
    argument that a virtual brace closes ("ac"), a fraction's slash and
    the ends of its parts."""
    if a[0] in ("bd", "deep"):
        return ()
    out = [f for f in flags(a) if (f[0] if isinstance(f, tuple) else f) in RESULTS]
    if has(a, "argend") and has(a, "multi"):
        out.append("ac")
    return tuple(sorted(out, key=repr))


def merge(level):
    """A level's results, onto B (which nothing else uses until step 5)."""
    def fn(b, res):
        if not res:
            return b
        return ("r",) + tuple(sorted(set((b[1:] if b[0] == "r" else ()) + res), key=repr))
    return fn


def clean_space(v):
    """A space's glyph is also its A: what the level wrote there goes."""
    return V(" ", v[1]) if v[0] == " " else v


def level_passes(level):
    at = lambda v, l=level: v[1] <= l
    return [Derive("A", ["S"], compact(level), spaces=True),
            RTL("A", args_step(level), (None, False), view=at, spaces=True), strip("A", spaces=True),
            LTR("A", scripts_step(level), (None, None, None, False), view=at, spaces=True), strip("A", spaces=True),
            RTL("A", post_end(level), False, view=at, spaces=True), strip("A", spaces=True),
            LTR("A", left_step(level), (None, None, frozenset(), True), view=at, spaces=True),
            strip("A", spaces=True),
            RTL("A", right_step(level), (None, None, frozenset(), True), view=at, spaces=True),
            strip("A", spaces=True),
            Map("A", decide, spaces=True),
            RTL("A", numerator_step(level), None, view=at, spaces=True), strip("A", spaces=True),
            LTR("A", denominator_step(level), None, view=at, spaces=True), strip("A", spaces=True),
            Derive("B", ["A"], merge(level), keys=[result_key]),
            Map("A", lambda v: BLANK),
            Map("S", clean_space, spaces=True)]


# 5. LaTeX kinds and virtual tokens ---------------------------------------------------

def results(b):
    return b[1:] if b is not None and b[0] == "r" else ()


def latex_kind(v, b):
    """The token's kind in program.tokens' terms (a virtual token has it
    already), from its S and the results its level left in B."""
    if len(v) != 3:
        return v
    k = v[0]
    r = V("", 0, *results(b))
    if k == " ":
        return (" ",)
    if k == "Y":
        return ("Y", 2)
    if k in ("(", ")"):
        hidden = has(r, "hide") or has(v, "sq") or \
            any(get(r, key) == "g" for key in ("nstart", "nend", "dstart", "dend"))
        return (("O",) if k == "(" else ("C",)) if hidden else ("c",)
    if k in ("^", "_"):
        return (("P",) if k == "^" else ("B",)) if get(r, "sc") else ("c",)
    if k == "/":
        return ("Z",) if get(r, "Z") else ("c",)
    if k in ("R", "Ls"):
        return (k,) if has(v, "sq") else ("c",)
    return ("c",)


def before(v, b):
    form = get(V("", 0, *results(b)), "nstart")
    if form is None:
        return []
    return [("F",)] if form == "g" else [("F",), ("O",)]


def after(v, b):
    r = V("", 0, *results(b))
    out = []
    if has(r, "ac"):
        out.append(("C",))
    if get(r, "nend") == "b":
        out.append(("C",))
    if get(r, "dend") == "b":
        out.append(("C",))
    z = get(r, "Z")
    if z is not None and z[1] == "b":
        out.append(("O",))
    if get(r, "sc") == "multi":
        out.append(("O",))
    return out


def front():
    P_ = [LTR("S", depth_step, (0, False), spaces=True), strip("S", spaces=True),
          RTL("S", match_step, (frozenset(), False), spaces=True), strip("S", spaces=True),
          Context("S", empty_closer, targets=lambda v: v[0] == ")", spaces=True),
          RTL("S", next_step, "x", spaces=True), strip("S", spaces=True),
          LTR("S", word_step, None, spaces=True), strip("S", spaces=True),
          RTL("S", kind_step, None, spaces=True), strip("S", spaces=True),
          RTL("S", poison_right, False, spaces=True), strip("S", spaces=True),
          LTR("S", poison_left, (False, False), spaces=True), strip("S", spaces=True),
          RTL("S", poison_ahead, False, spaces=True), strip("S", spaces=True),
          Map("S", tidy, spaces=True),
          Context("S", paren_owner, targets=lambda v: v[0] == "(", spaces=True)]
    for level in LEVELS:
        P_.append(Context("S", closer_owner, targets=lambda v, l=level: v[0] == ")" and v[1] == l,
                          ctx_view=lambda v, l=level: v[1] == l))
    for level in LEVELS:
        P_ += level_passes(level)
    P_ += [Insert(before, after),
           Derive("S", ["B"], latex_kind, spaces=True),
           Map("B", lambda v: BLANK)]
    return P_


# what relaxed.py's parse says the tokens should become -------------------------------

def expected(line):
    """[(kind, text)]: the LaTeX tokens relaxed.Parser's reading gives, kind
    as program.tokens has it and "v" + kind for a virtual token."""
    p = R.Parser(line)
    toks = p.toks

    def plain(i):
        kind = toks[i][0]
        if kind == "sym":
            return [("Y", toks[i][3])]
        if kind == " ":
            return [(" ", " ")]
        if kind == "cmd" or (kind == "text" and toks[i][3] == "sqrt"):
            return [("c", ch) for ch in "sqrt"]
        return [("c", toks[i][3])]

    def seq(lo, hi):
        out = []
        if lo > hi:
            return out
        for e in p.fractions(p.scripts(p.elements(lo, hi))):
            out += emit(e)
        return out

    def tokens_of(e):
        return [x for i in range(e.lo, e.hi + 1) for x in plain(i)]

    def emit(e):
        if e.kind == "group":
            return plain(e.lo) + seq(e.lo + 1, e.hi - 1) + plain(e.hi)
        if e.kind == "app":
            w0, w1 = e.word
            return [x for i in range(w0, w1 + 1) for x in plain(i)] + emit(R.El("group", w1 + 1, e.hi))
        if e.kind == "sqrt":
            return [("R", "s"), ("Ls", "q"), ("Ls", "r"), ("Ls", "t"), ("O", "(")] + \
                seq(e.lo + 2, e.hi - 1) + [("C", ")")]
        if e.kind == "script":
            out = emit(e.base)
            for kind, at, pieces in e.scripts:
                out.append(("P" if kind == "^" else "B", kind))
                if len(pieces) == 1 and pieces[0].kind == "group":
                    out += [("O", "(")] + seq(pieces[0].lo + 1, pieces[0].hi - 1) + [("C", ")")]
                else:
                    inner = [x for piece in pieces for x in tokens_of(piece)]
                    out += inner if len(inner) == 1 else [("vO", "")] + inner + [("vC", "")]
            return out
        if e.kind == "frac":
            out = [("vF", "")] + part(e.num)
            out.append(("Z", "/"))
            return out + part(e.den)
        return tokens_of(e)

    def part(e):
        if e.kind == "group":
            return [("O", "(")] + seq(e.lo + 1, e.hi - 1) + [("C", ")")]
        return [("vO", "")] + emit(e) + [("vC", "")]

    return seq(0, len(toks) - 1)


def got(line):
    """The same, from the passes."""
    toks = P.run(front(), tokens(line))
    out = []
    for t in toks:
        kind = t["S"][0]
        out.append((("v" + kind) if t.get("G", ("g", "", None))[2] == "V" else kind, t["char"]))
    return out


_PROGRAM = None


def simulate(line):
    global _PROGRAM
    if _PROGRAM is None:
        _PROGRAM = front() + P.program(relaxed=True)
    return P.run(_PROGRAM, tokens(line))


def check(line):
    import assemble
    want = R.layout(line)
    got_ = assemble.place(simulate(line))
    return got_ == want, got_, want


if __name__ == "__main__":
    import sys
    for line in sys.argv[1:]:
        a, b = expected(line), got(line)
        print("ok" if a == b else "DIFF", repr(line))
        if a != b:
            print("   want", a)
            print("   got ", b)
