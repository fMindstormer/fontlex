"""The link destination after a `]`: `(dest "title")`, as an automaton.

It reads only the characters that matter here: ( ) " ' < > space and tab,
with O standing for any other character (a run of them acts as one, so the
font can skip ordinary text). Escaped characters count as O. Forward from
S0 (just after the `]`) it accepts at the `)` that ends a valid destination,
following commonmark.js's parseCloseBracket. FORMS split it into eight
automata, one per form of destination and title, whose right-to-left
versions are far smaller than the whole one's and together accept the same.
"""

ACC = "ACC"
TITLES = {"dq": "Tdq", "sq": "Tsq", "paren": "Tpar"}
FORMS = [(d, t) for d in ("raw", "angle") for t in (None, "dq", "sq", "paren")]


def step(q, c, parens):
    """The next state after reading c in state q, ACC, or None (no link)."""
    if q == "S0":
        return "S1" if c == "(" else None
    if q == "S1":                         # after "(", in spaces
        if c == " ":
            return "S1"
        if c == "<":
            return "A"
        if c == ")":
            return ACC                    # empty destination
        if c == "(":
            return ("R", 1)
        if c == "\t":
            return None
        return ("R", 0)                   # O, quotes and ">" start a raw destination
    if q == "A":                          # <angle destination>
        if c == ">":
            return "T0"
        return None if c == "<" else "A"
    if isinstance(q, tuple):              # raw destination at parenthesis depth d
        d = q[1]
        if c == "(":
            return ("R", d + 1) if d < parens else None
        if c == ")":
            return ACC if d == 0 else ("R", d - 1)
        if c == " ":
            return "T1" if d == 0 else None
        if c == "\t":
            return None
        return q
    if q == "T0":                         # just after an angle destination
        if c == " ":
            return "T1"
        return ACC if c == ")" else None
    if q == "T1":                         # spaces after the destination: a title or ")"
        if c == " ":
            return "T1"
        if c == ")":
            return ACC
        return {'"': "Tdq", "'": "Tsq", "(": "Tpar"}.get(c)
    if q in ("Tdq", "Tsq", "Tpar"):
        if c == {"Tdq": '"', "Tsq": "'", "Tpar": ")"}[q]:
            return "T2"
        if q == "Tpar" and c == "(":
            return None
        return q
    if q == "T2":                         # after the title
        if c == " ":
            return "T2"
        return ACC if c == ")" else None
    raise ValueError(q)


def states(parens):
    return ["S0", "S1", "A", "T0", "T1", "Tdq", "Tsq", "Tpar", "T2"] + [("R", d) for d in range(parens + 1)]


class Automaton:
    """One form of destination and title; back() is its right-to-left step."""

    def __init__(self, form, parens):
        self.dest, self.title = form
        self.parens = parens
        self.states = states(parens)
        self.start = "S0"

    def fwd(self, q, c):
        n = step(q, c, self.parens)
        if q == "S1":
            if n == "A" and self.dest != "angle":
                return None
            if (n == ACC or isinstance(n, tuple)) and self.dest != "raw":
                return None
        if q == "T1" and n in TITLES.values() and n != TITLES.get(self.title):
            return None
        if n == ACC and (self.title is None) != (q != "T2"):
            return None
        return n

    def back(self, R, c):
        """The states from which reading c and then what R accepts reaches ACC."""
        return frozenset(q for q in self.states if (n := self.fwd(q, c)) == ACC or (n is not None and n in R))
