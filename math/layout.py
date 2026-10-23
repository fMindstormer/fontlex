"""What Fontlex Math draws for a line of text: the reference the font is
checked against.

A line is ordinary text in which a small subset of LaTeX is laid out:

    \\frac{N}{D}    a fraction            x^a  x^{..}   a superscript
    \\sqrt{X}       a square root         x_a  x_{..}   a subscript
    {X}            a group                x_a^b  x^b_a  stacked scripts
    \\alpha ...     a symbol (SYMBOLS)

A construct the font can't lay out shows as the source text, in the style
of whatever contains it. That's the case when it is incomplete (a brace
never closed, a fraction without its denominator, or BRACE_LIMIT braces
open when another one opens: that one and the rest of the line are text), holds a space (Safari
gives a space its full width wherever it is, so nothing can be placed
across one), nests deeper than MAX_DEPTH (MAX_FRACTIONS for fractions), or,
for a construct that isn't inside another, runs longer than MAX_CHARS
characters. Everything else is plain text, drawn in the text style.

Sizes are in font units. Text is set in three styles (text, script,
scriptscript, as in TeX): style 0 at full size, 1 at 0.7 and 2 at 0.5.
Every advance is a multiple of UNIT.

layout(line) returns (ink, advance): ink is a sorted list of
  ("glyph", name, style, x, y)        a character's glyph (name in the base
                                      font) at `style`, its origin at (x, y)
  ("rule", x0, x1, y0, y1)            a fraction bar or a root's overbar
  ("radical", style, kind, x, y)      a radical sign, `kind` its height
and advance the line's width. Rules that touch or overlap at the same
height are merged, since the font draws them in pieces.
"""

UNIT = 30
SCALE = (1.0, 0.7, 0.5)
WIDTH = (600, 420, 300)        # a character's advance in each style
MARGIN = 60                    # space on each side of a fraction
AXIS = (330, 230, 170)         # the fraction bar's center above the baseline
RULE = (40, 30, 20)            # bar and overbar thickness
GAP = (70, 50, 40)             # clearance between a bar and what's above or below it
DEPTH = (180, 130, 90)         # how far a character reaches below the baseline
HEIGHT = (760, 530, 380)       # and above it
SUP = (380, 270, 190)          # a superscript's baseline, above the base's
SUB = (160, 110, 80)           # a subscript's, below it
SUB_STACKED = (220, 150, 110)  # a subscript's below a superscript

MAX_DEPTH = 3       # constructs inside constructs
MAX_FRACTIONS = 2   # fractions inside fractions
MAX_CHARS = 24      # characters in a construct that isn't inside another
BRACE_LIMIT = MAX_DEPTH + 1   # braces open at once

SYMBOLS = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "varepsilon": "ε",
    "zeta": "ζ", "eta": "η", "theta": "θ", "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ",
    "nu": "ν", "xi": "ξ", "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ",
    "phi": "ϕ", "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π", "Sigma": "Σ",
    "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
    "cdot": "·", "times": "×", "div": "÷", "pm": "±", "mp": "∓", "circ": "∘",
    "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "ne": "≠", "neq": "≠", "approx": "≈",
    "equiv": "≡", "sim": "∼", "ll": "≪", "gg": "≫", "perp": "⊥", "parallel": "∥",
    "in": "∈", "notin": "∉", "subset": "⊂", "subseteq": "⊆", "cup": "∪", "cap": "∩",
    "forall": "∀", "exists": "∃", "neg": "¬", "land": "∧", "lor": "∨",
    "infty": "∞", "partial": "∂", "nabla": "∇", "sum": "∑", "prod": "∏", "int": "∫",
    "to": "→", "rightarrow": "→", "leftarrow": "←", "leftrightarrow": "↔",
    "Rightarrow": "⇒", "iff": "⇔", "ldots": "…", "cdots": "⋯", "prime": "′",
}
COMMANDS = ("frac", "sqrt")


def down(s):
    return min(s + 1, 2)


def numerator_shift(s, holds_fraction):
    """How far a fraction at style s raises its numerator's baseline."""
    t = down(s)
    below = fraction_depth(t) if holds_fraction else DEPTH[t]
    return AXIS[s] + RULE[s] // 2 + GAP[s] + below


def denominator_shift(s, holds_fraction):
    """How far it lowers its denominator's."""
    t = down(s)
    above = fraction_height(t) if holds_fraction else HEIGHT[t]
    return above + GAP[s] + RULE[s] // 2 - AXIS[s]


def fraction_depth(s):
    return denominator_shift(s, False) + DEPTH[down(s)]


def fraction_height(s):
    return numerator_shift(s, False) + HEIGHT[down(s)]


def root_top(s, kind):
    """Where a square root's overbar starts: kind 0 over plain text, 1 over a
    superscript, 2 over a fraction."""
    return (HEIGHT[s], SUP[s] + HEIGHT[down(s)], fraction_height(s))[kind] + GAP[s]


# tokens --------------------------------------------------------------------

def tokenize(line):
    """[(kind, start, end, value)]: kind is "cmd" (value the name), "sym"
    (value the symbol), "{", "}", "^", "_", " ", "char" or "text"."""
    return give_up(lex(line), line)


def lex(line):
    """The tokens before braces are counted."""
    out, i = [], 0
    while i < len(line):
        ch = line[i]
        if ch == "\\":
            j = i + 1
            while j < len(line) and line[j].isascii() and line[j].isalpha():
                j += 1
            name = line[i + 1:j]
            if name in COMMANDS:
                out.append(("cmd", i, j, name))
                i = j
                continue
            if name in SYMBOLS:
                out.append(("sym", i, j, SYMBOLS[name]))
                i = j
                continue
        kind = ch if ch in "{}^_ " else "char"
        out.append((kind, i, i + 1, ch))
        i += 1
    return out


def give_up(toks, line):
    """A brace opened while BRACE_LIMIT are open, and everything after it,
    is plain text: kind "text", which, unlike "char", can't be a script's
    argument. So is a closing brace with nothing open."""
    out, depth, dead = [], 0, False
    for kind, start, end, value in toks:
        if not dead and kind == "{":
            if depth == BRACE_LIMIT:
                dead = True
            else:
                depth += 1
        elif not dead and kind == "}":
            if depth == 0:
                kind = "text"
            else:
                depth -= 1
        if dead and kind in ("{", "}", "^", "_", "cmd"):
            if kind == "cmd":
                out += [("text", k, k + 1, line[k]) for k in range(start, end)]
                continue
            kind = "text"
        out.append((kind, start, end, value))
    return out


# parsing -------------------------------------------------------------------

class Node:
    """A construct: kind "frac", "sqrt", "group", "sup" or "sub"; `parts`
    are lists of items (a fraction has two, the others one); `start` and
    `end` its first and last token; `ok` whether it is laid out."""

    def __init__(self, kind, start):
        self.kind, self.start, self.end = kind, start, None
        self.parts, self.ok, self.complete = [], True, False
        self.single = False       # a script whose argument is one token, not a group


def parse(toks):
    """Items of the whole line: token indices and Nodes. A construct's
    region runs from its first token to its last; an incomplete one runs to
    the end of the line."""
    pos = 0

    def items(closing):
        nonlocal pos
        out = []
        while pos < len(toks):
            kind = toks[pos][0]
            if kind == "}" and closing:
                return out, True
            node = construct(pos)
            if node is None:
                out.append(pos)
                pos += 1
            else:
                out.append(node)
        return out, False

    def group(kind, start):
        """A brace group at pos; returns the node with parts filled."""
        nonlocal pos
        node = Node(kind, start)
        pos += 1
        part, closed = items(True)
        node.parts.append(part)
        if closed:
            node.end = pos
            pos += 1
        node.complete = closed
        return node

    def construct(i):
        nonlocal pos
        kind = toks[i][0]
        nxt = toks[i + 1][0] if i + 1 < len(toks) else None
        if kind == "cmd" and nxt == "{":
            node = Node(toks[i][3], i)
            pos = i + 1
            inner = group("group", i + 1)
            node.parts = inner.parts
            node.end = inner.end
            if not inner.complete:
                return node
            if node.kind == "sqrt":
                node.complete = True
                return node
            if pos < len(toks) and toks[pos][0] == "{":
                den = group("group", pos)
                node.parts += den.parts
                node.end = den.end
                node.complete = den.complete
            else:
                node.complete = False       # a numerator without a denominator ends here
                node.end = inner.end
                node.broken = True
            return node
        if kind in "^_" and nxt in ("char", "sym", "{"):
            node = Node("sup" if kind == "^" else "sub", i)
            if nxt == "{":
                pos = i + 1
                inner = group("group", i + 1)
                node.parts, node.end, node.complete = inner.parts, inner.end, inner.complete
            else:
                node.single, node.parts, node.end, node.complete = True, [[i + 1]], i + 1, True
                pos = i + 2
            return node
        if kind == "{":
            pos = i
            return group("group", i)
        return None

    out, _ = items(False)
    return out


def validate(items, toks, depth=0, fractions=0):
    """Mark which constructs are laid out (see the module docstring)."""
    for it in items:
        if not isinstance(it, Node):
            continue
        d, f = depth + 1, fractions + (it.kind == "frac")
        has_space = any(toks[t][0] == " " for t in region(it, toks))
        last = toks[it.end][2] if it.end is not None else toks[-1][2]
        long = depth == 0 and last - toks[it.start][1] > MAX_CHARS
        it.ok = it.complete and not has_space and d <= MAX_DEPTH and f <= MAX_FRACTIONS and not long
        for part in it.parts:
            validate(part, toks, d, f)


def region(node, toks):
    end = node.end if node.complete else len(toks) - 1
    if not node.complete and getattr(node, "broken", False):
        end = node.end
    return range(node.start, end + 1)


# layout --------------------------------------------------------------------

def has(items, test):
    for it in items:
        if isinstance(it, Node) and it.ok:
            if test(it) or any(has(p, test) for p in it.parts):
                return True
    return False


class Layout:
    def __init__(self, line):
        self.line = line
        self.toks = tokenize(line)
        self.items = parse(self.toks)
        validate(self.items, self.toks)
        self.ink = []

    def run(self):
        width = self.seq(self.items, 0, 0, 0, top=True)
        return sorted(merge(self.ink)), width

    def glyph(self, tok, s, x, y):
        kind, start, end, value = self.toks[tok]
        if kind == " ":
            return WIDTH[0]
        if kind == "sym":
            self.ink.append(("glyph", value, s, x, y))
            return WIDTH[s]
        # a command (\frac, \sqrt) is drawn letter by letter
        for k, ch in enumerate(self.line[start:end]):
            self.ink.append(("glyph", ch, s, x + k * WIDTH[s], y))
        return (end - start) * WIDTH[s]

    def source(self, node, s, x, y):
        """A construct that isn't laid out: its characters as text."""
        w = 0
        for t in region(node, self.toks):
            w += self.glyph(t, s, x + w, y)
        return w

    def seq(self, items, s, x, y, top=False):
        """Lay out items from (x, y) at style s; returns the width."""
        w, i = 0, 0
        while i < len(items):
            it = items[i]
            if not isinstance(it, Node):
                w += self.glyph(it, s, x + w, y)
            elif not it.ok:
                w += self.source(it, s, x + w, y)
            elif it.kind in ("sup", "sub"):
                nxt = items[i + 1] if i + 1 < len(items) else None
                pair = isinstance(nxt, Node) and nxt.ok and nxt.kind in ("sup", "sub") \
                    and nxt.kind != it.kind and nxt.start == it.end + 1
                if pair:
                    sub, sup = (it, nxt) if it.kind == "sub" else (nxt, it)
                    a = self.seq(sub.parts[0], down(s), x + w, y - SUB_STACKED[s])
                    b = self.seq(sup.parts[0], down(s), x + w, y + SUP[s])
                    w += max(a, b)
                    i += 2
                    continue
                shift = SUP[s] if it.kind == "sup" else -SUB[s]
                w += self.seq(it.parts[0], down(s), x + w, y + shift)
            elif it.kind == "group":
                w += self.seq(it.parts[0], s, x + w, y)
            elif it.kind == "sqrt":
                kind = 2 if has(it.parts[0], lambda n: n.kind == "frac") else \
                    1 if has(it.parts[0], lambda n: n.kind == "sup") else 0
                inner = self.seq(it.parts[0], s, x + w + WIDTH[s], y)
                self.ink.append(("radical", s, kind, x + w, y))
                top_ = y + root_top(s, kind)
                self.ink.append(("rule", x + w + WIDTH[s], x + w + WIDTH[s] + inner, top_, top_ + RULE[s]))
                w += WIDTH[s] + inner
            elif it.kind == "frac":
                t = down(s)
                num, den = it.parts
                wn = self.measure(num, t)
                wd = self.measure(den, t)
                m = max(wn, wd)
                up = numerator_shift(s, has(num, lambda n: n.kind == "frac"))
                dn = denominator_shift(s, has(den, lambda n: n.kind == "frac"))
                self.seq(num, t, x + w + MARGIN + (m - wn) // 2, y + up)
                self.seq(den, t, x + w + MARGIN + (m - wd) // 2, y - dn)
                bar = y + AXIS[s]
                self.ink.append(("rule", x + w + MARGIN // 2, x + w + m + 3 * MARGIN // 2,
                                 bar - RULE[s] // 2, bar + RULE[s] // 2))
                w += m + 2 * MARGIN
            i += 1
        return w

    def measure(self, items, s):
        saved = self.ink
        self.ink = []
        w = self.seq(items, s, 0, 0)
        self.ink = saved
        return w


def merge(ink):
    """Rules at the same height that touch or overlap, as one."""
    rules = sorted((r for r in ink if r[0] == "rule"), key=lambda r: (r[3], r[4], r[1]))
    out = [r for r in ink if r[0] != "rule"]
    cur = None
    for r in rules:
        if r[2] <= r[1]:
            continue
        if cur and cur[3:] == r[3:] and r[1] <= cur[2]:
            cur = cur[:2] + (max(cur[2], r[2]),) + cur[3:]
        else:
            if cur:
                out.append(cur)
            cur = r
    if cur:
        out.append(cur)
    return out


def layout(line):
    return Layout(line).run()


if __name__ == "__main__":
    import sys
    for line in sys.argv[1:]:
        ink, w = layout(line)
        print(line, "width", w)
        for r in ink:
            print("  ", r)
