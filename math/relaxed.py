"""What a relaxed Fontlex Math would draw for a line: the reference for a
font that typesets math written the way people write it in plain text.

    (a+b)/(c+d)   1/2   x/2   2a/3   a+b/c     fractions
    x^2  x^(n+1)  x_1  x_i^2  H_2O  x^-1      scripts
    sqrt(x)  sqrt(x^2+1)                      square roots
    <=  >=  !=  ->  =>  +-                    symbols

The layout is layout.py's; what differs is what counts as a construct.
Ordinary text must stay ordinary, so the rules are narrow:

- An operand (of a fraction, a script's base) is a whole word that is a
  number (12, 3.5), a number and one letter (2a), or one letter; a
  symbol; a parenthesized group; a group after one letter or a function
  name (f(x), sin(x), with its parentheses shown); or sqrt(..). Scripts
  after it belong to it. Longer words (and/or, km/h, page/2) are text.
- A group that is all of a fraction's operand, a script's argument or a
  root's contents loses its parentheses: (a+b)/2. With a script it keeps
  them: (a+b)^2/c. An empty group, as in f(), is none of these.
- A script's argument is a number, one letter (not followed by another),
  a symbol, a group, or one of those after a minus. A number may be
  followed by letters, which are text after it: x^2y, H_2O. Two scripts of
  different kinds stack; a third is text.
- Two lone letters make a fraction only next to an operator with an
  operand past it (a+b/c, x = a/b), so w/o, n/a, I/O-conversion and C/C++
  stay text. Slashes in a row (a/b/c, 10/23/2026, //)
  make none, and neither does any slash in a run of characters without a
  space where a slash touches a longer word (tr/a-z/A-Z/, s/x/y/g). A
  fraction's neighbours outside it are spaces, operators, punctuation or
  nothing: C/C++ and $1/g stay text.
- A subscript's base isn't a number, and no script touches another
  underscore: 1_000_000, 1.09_01 and T_U_INT stay text.
- A space inside a construct, or past layout.py's limits on depth and
  length, leaves it as its characters (as in layout.py: WebKit gives a
  space's glyphs a space's width).
- Parentheses nest at most BRACE_LIMIT deep: one opened past that, and the
  rest of the line, is text, as an unmatched parenthesis is.

layout(line) returns what layout.layout does.
"""

import layout as L

SYMBOLS = {"<=": "≤", ">=": "≥", "!=": "≠", "->": "→", "=>": "⇒", "+-": "±"}
FUNCTIONS = ("sin", "cos", "tan", "log", "ln", "exp")
OPERATORS = set("+-=<>*·×÷±≤≥≠→⇒")
EDGES = OPERATORS | set(".,;:!?[]{}()~\"'`")    # what may touch a fraction


def lex(line):
    """[(kind, start, end, value)]: kind "cmd" (sqrt, before a parenthesis
    and after no letter or digit), "sym", "(", ")", "^", "_", "/", " " or
    "char"."""
    out, i = [], 0
    while i < len(line):
        two = line[i:i + 2]
        if two in SYMBOLS:
            out.append(("sym", i, i + 2, SYMBOLS[two]))
            i += 2
            continue
        if line.startswith("sqrt(", i) and not (i and (line[i - 1].isalnum() or line[i - 1] in "._")):
            out.append(("cmd", i, i + 4, "sqrt"))
            i += 4
            continue
        ch = line[i]
        out.append((ch if ch in "()^_/ " else "char", i, i + 1, ch))
        i += 1
    return out


def match(toks):
    """{index of "(": index of its ")"}; parentheses that don't match, or
    open past BRACE_LIMIT (with everything after), become "text"."""
    out, stack, dead = {}, [], False
    toks = list(toks)
    for i, (kind, start, end, value) in enumerate(toks):
        if dead:
            if kind in ("(", ")", "^", "_", "/", "cmd"):
                toks[i] = ("text", start, end, value)
            continue
        if kind == "(":
            if len(stack) == L.BRACE_LIMIT:
                dead = True
                toks[i] = ("text", start, end, value)
            else:
                stack.append(i)
        elif kind == ")":
            if stack:
                out[stack.pop()] = i
            else:
                toks[i] = ("text", start, end, value)
    for i in stack:
        toks[i] = ("text",) + toks[i][1:]
    return toks, out


# elements ------------------------------------------------------------------

class El:
    """A piece of one parenthesis level: kind "word" (sub: "num", "numlet",
    "let", "fn" or "other"), "group", "app" (a word and a group), "sqrt",
    "sym", "op" (any other token: value its character), "script" (an
    operand with its scripts) or "frac"; lo and hi its first and last
    token."""

    def __init__(self, kind, lo, hi, **kw):
        self.kind, self.lo, self.hi = kind, lo, hi
        self.sub = self.value = None
        self.__dict__.update(kw)

    def operand(self):
        if self.kind == "group" and self.hi == self.lo + 1:
            return False        # (), as in code
        return self.kind in ("group", "app", "sqrt", "sym", "script") or \
            self.kind == "word" and self.sub in ("num", "numlet", "let")


def word_kind(text):
    digits = number_length(text)
    rest = text[digits:]
    if digits and not rest:
        return "num"
    if digits and len(rest) == 1 and rest.isalpha():
        return "numlet"
    if not digits and len(rest) == 1 and rest.isalpha():
        return "let"
    if text in FUNCTIONS:
        return "fn"
    return "other"


def number_length(text):
    """How many of text's first characters are a number: digits, with at
    most one point between digits."""
    n, point = 0, False
    while n < len(text) and (text[n].isdigit() or text[n] == "." and not point and 0 < n < len(text) - 1
                             and text[n + 1].isdigit()):
        point |= text[n] == "."
        n += 1
    return n


def is_word_char(line, toks, i):
    return toks[i][0] == "char" and toks[i][3].isalnum()


def words(line, toks):
    """{token index: (first, last) of its word}: runs of letters and digits,
    with a point between digits."""
    out, i = {}, 0
    while i < len(toks):
        if is_word_char(line, toks, i):
            j = i
            while j + 1 < len(toks) and (is_word_char(line, toks, j + 1) or
                                         toks[j + 1][0] == "char" and toks[j + 1][3] == "." and j + 2 < len(toks)
                                         and toks[j][3].isdigit() and toks[j + 2][0] == "char"
                                         and toks[j + 2][3].isdigit()):
                j += 1
            for k in range(i, j + 1):
                out[k] = (i, j)
            i = j + 1
        else:
            i += 1
    return out


def poisoned(line, toks):
    """Indices of the slashes in a run without spaces where some slash
    touches a word that can't be an operand: none of them is a fraction."""
    w = words(line, toks)
    bad = lambda k: k in w and word_kind(line[toks[w[k][0]][1]:toks[w[k][1]][2]]) not in ("num", "numlet", "let")
    out, run = set(), []
    for i, t in enumerate(toks + [(" ", 0, 0, " ")]):
        if t[0] == " ":
            if any(bad(k - 1) or bad(k + 1) for k in run):
                out.update(run)
            run = []
        elif t[0] == "/":
            run.append(i)
    return out


class Parser:
    def __init__(self, line):
        self.line = line
        self.toks, self.match = match(lex(line))
        self.poisoned = poisoned(line, self.toks)

    def elements(self, lo, hi):
        toks, out, i = self.toks, [], lo
        while i <= hi:
            kind = toks[i][0]
            if kind == "(":
                j = self.match[i]
                out.append(El("group", i, j))
                i = j + 1
                continue
            if kind == "cmd":
                j = self.match.get(i + 1)
                if j is not None and j > i + 2:
                    out.append(El("sqrt", i, j))
                    i = j + 1
                    continue
            if kind == "char" and toks[i][3].isalnum():
                j = i
                while j + 1 <= hi and (is_word_char(self.line, toks, j + 1) or
                                       toks[j + 1][3] == "." and toks[j + 1][0] == "char" and j + 2 <= hi and
                                       toks[j][3].isdigit() and toks[j + 2][0] == "char" and toks[j + 2][3].isdigit()):
                    j += 1
                text = self.line[toks[i][1]:toks[j][2]]
                sub = word_kind(text)
                if sub in ("let", "fn") and j + 1 <= hi and toks[j + 1][0] == "(" and \
                        self.match[j + 1] > j + 2:
                    k = self.match[j + 1]
                    out.append(El("app", i, k, word=(i, j)))
                    i = k + 1
                    continue
                out.append(El("word", i, j, sub=sub))
                i = j + 1
                continue
            out.append(El("sym" if kind == "sym" else "op", i, i, value=toks[i][3]))
            i += 1
        return out

    def scripts(self, els):
        """Attach scripts to their operands."""
        out, i = [], 0
        while i < len(els):
            e = els[i]
            if e.kind == "op" and e.value in "^_" and out and out[-1].operand() and \
                    self.toks[e.lo][0] in "^_" and self.script_base(out, e.value):
                base = out[-1]
                taken = [s[0] for s in base.scripts] if base.kind == "script" else []
                arg = self.argument(els, i + 1)
                if arg is not None and e.value == "_" and self.underscore(arg[0][-1].hi + 1):
                    arg = None
                if arg is not None and len(taken) < 2 and e.value not in taken:
                    if base.kind != "script":
                        base = El("script", base.lo, base.hi, base=base, scripts=[])
                        out[-1] = base
                    pieces, rest, n = arg
                    base.scripts.append((e.value, e.lo, pieces))
                    base.hi = pieces[-1].hi
                    i += 1 + n
                    if rest is not None:
                        out.append(rest)
                    continue
            out.append(e)
            i += 1
        return out

    def underscore(self, i):
        return 0 <= i < len(self.toks) and self.toks[i][0] == "_"

    def script_base(self, out, kind):
        """Whether out[-1] can take a script of kind ^ or _."""
        base = out[-1]
        first = base.base if base.kind == "script" else base
        if kind == "_" and first.kind == "word" and first.sub == "num":
            return False
        return not self.underscore(first.lo - 1)

    def argument(self, els, i):
        """A script's argument at els[i]: (its elements, an element left
        over after it, how many elements it took) or None."""
        if i >= len(els):
            return None
        e = els[i]
        if e.kind == "op" and e.value == "-" and i + 1 < len(els):
            got = self.argument(els, i + 1)
            if got is not None and got[0][0].kind != "group":
                return [e] + got[0], got[1], got[2] + 1
            return None
        if e.kind in ("group", "sym") and e.operand():
            return [e], None, 1
        if e.kind != "word":
            return None
        if e.sub in ("num", "let"):
            return [e], None, 1
        text = self.line[self.toks[e.lo][1]:self.toks[e.hi][2]]
        n = number_length(text)
        if n and text[n:].isalpha():
            return [El("word", e.lo, e.lo + n - 1, sub="num")], El("word", e.lo + n, e.hi, sub="text"), 1
        return None

    def fractions(self, els):
        slashes = [i for i, e in enumerate(els)
                   if e.kind == "op" and e.value == "/" and self.toks[e.lo][0] == "/"]
        good = []
        for i in slashes:
            if not (0 < i < len(els) - 1 and els[i - 1].operand() and els[i + 1].operand()):
                continue
            if i - 2 in slashes or i + 2 in slashes or i - 1 in slashes or i + 1 in slashes:
                continue
            if els[i].lo in self.poisoned:
                continue
            before = els[i - 2] if i >= 2 else None
            after = els[i + 2] if i + 2 < len(els) else None
            if not all(x is None or x.kind == "sym" or x.kind == "op" and x.value in EDGES | {" "}
                       for x in (before, after)):
                continue
            a, b = els[i - 1], els[i + 1]
            if a.kind == "word" and a.sub == "let" and b.kind == "word" and b.sub == "let":
                if not (self.in_expression(els, i - 1, -1) or self.in_expression(els, i + 1, 1)):
                    continue
            good.append(i)
        out, i = [], 0
        while i < len(els):
            if i + 1 in good:
                out.append(El("frac", els[i].lo, els[i + 2].hi, num=els[i], den=els[i + 2]))
                i += 3
                continue
            out.append(els[i])
            i += 1
        return out

    @staticmethod
    def in_expression(els, i, step):
        """Whether, past spaces, an operator follows els[i] (step 1) or
        precedes it (-1), with an operand past it."""
        def next_one(j):
            j += step
            while 0 <= j < len(els) and els[j].kind == "op" and els[j].value == " ":
                j += step
            return j if 0 <= j < len(els) else None
        j = next_one(i)
        if j is None or not (els[j].kind == "sym" or els[j].kind == "op" and els[j].value in OPERATORS):
            return False
        k = next_one(j)
        return k is not None and els[k].operand()

    # items: what layout.Layout lays out --------------------------------------

    def seq(self, lo, hi):
        if lo > hi:
            return []
        els = self.fractions(self.scripts(self.elements(lo, hi)))
        out = []
        for e in els:
            out += self.items(e)
        return out

    def inside(self, e):
        """An operand's items when it is all of a part: a group's without
        its parentheses."""
        if e.kind == "group":
            return self.seq(e.lo + 1, e.hi - 1)
        return self.items(e)

    def items(self, e):
        if e.kind == "group":
            return [e.lo] + self.seq(e.lo + 1, e.hi - 1) + [e.hi]
        if e.kind == "app":
            w0, w1 = e.word
            return list(range(w0, w1 + 1)) + self.items(El("group", w1 + 1, e.hi))
        if e.kind == "sqrt":
            return [self.node("sqrt", e.lo, e.hi, [self.seq(e.lo + 2, e.hi - 1)])]
        if e.kind == "script":
            out = self.items(e.base)
            for kind, at, pieces in e.scripts:
                part = self.inside(pieces[0]) if len(pieces) == 1 else \
                    [x for p in pieces for x in self.items(p)]
                out.append(self.node("sup" if kind == "^" else "sub", at, pieces[-1].hi, [part]))
            return out
        if e.kind == "frac":
            return [self.node("frac", e.lo, e.hi, [self.inside(e.num), self.inside(e.den)])]
        return list(range(e.lo, e.hi + 1))

    def node(self, kind, start, end, parts):
        n = L.Node(kind, start)
        n.end, n.parts, n.complete = end, parts, True
        return n


class Layout(L.Layout):
    def __init__(self, line):
        p = Parser(line)
        self.line, self.toks = line, p.toks
        self.items = p.seq(0, len(p.toks) - 1)
        L.validate(self.items, self.toks)
        self.ink = []


def layout(line):
    return Layout(line).run()


def constructs(line):
    """The constructs laid out on a line, outermost, as (kind, source)."""
    lay = Layout(line)
    out = []
    for it in lay.items:
        if isinstance(it, L.Node) and it.ok:
            out.append((it.kind, line[lay.toks[it.start][1]:lay.toks[it.end][2]]))
    return out


if __name__ == "__main__":
    import sys
    for line in sys.argv[1:]:
        ink, w = layout(line)
        print(line, "width", w, constructs(line))
        for r in ink:
            print("  ", r)
