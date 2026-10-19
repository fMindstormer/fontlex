"""Raw HTML and autolinks as automata, for checking from right to left.

Forward from "<" (a `<` just read), each accepts at the `>` that ends a valid
construct of its kind, following CommonMark 0.31.2's definitions (and
commonmark.js's regular expressions). Characters are ASCII, or NONASCII
standing for any other character. Every construct ends at its first
acceptance.
"""

import string

LETTER = set(string.ascii_letters)
DIGIT = set(string.digits)
ALNUM = LETTER | DIGIT
WS = {" ", "\t"}
ACC = "ACC"
EMAIL_LOCAL = ALNUM | set(".!#$%&'*+/=?^_`{|}~-")
NONASCII = "\x80"
GT_NO = "\x81"           # a `>` with more than whitespace after it on the line
ALPHABET = [chr(c) for c in range(0x21, 0x7F)] + [" ", "\t", NONASCII]


def open_tag(q, c):
    if q == "<":
        return "name" if c in LETTER else None
    if q == "name":
        if c in ALNUM or c == "-":
            return q
        return {" ": "ws", "\t": "ws", "/": "/", ">": ACC}.get(c)
    if q in ("ws", "attr-ws"):                    # attr-ws: whitespace after an attribute name
        if c in WS:
            return q
        if c in LETTER or c in "_:":
            return "attr"
        if c == "=" and q == "attr-ws":
            return "="
        return {"/": "/", ">": ACC}.get(c)
    if q == "attr":
        if c in ALNUM or c in "_.:-":
            return q
        return {" ": "attr-ws", "\t": "attr-ws", "=": "=", "/": "/", ">": ACC}.get(c)
    if q == "=":
        if c in WS:
            return q
        if c == '"':
            return "dq"
        if c == "'":
            return "sq"
        return None if c in "=<>`" else "uq"
    if q == "uq":                                 # unquoted value
        if c in WS:
            return "ws"
        if c == ">":
            return ACC
        return None if c in "\"'=<`" else q
    if q in ("dq", "sq"):
        return "value" if c == {"dq": '"', "sq": "'"}[q] else q
    if q == "value":
        if c in WS:
            return "ws"
        return {"/": "/", ">": ACC}.get(c)
    if q == "/":
        return ACC if c == ">" else None
    raise ValueError(q)


def close_tag(q, c):
    if q == "<":
        return "/" if c == "/" else None
    if q == "/":
        return "name" if c in LETTER else None
    if q == "name":
        if c in ALNUM or c == "-":
            return q
        return "ws" if c in WS else (ACC if c == ">" else None)
    if q == "ws":
        return q if c in WS else (ACC if c == ">" else None)
    raise ValueError(q)


def comment(q, c):
    """<!--> , <!---> or <!-- ... --> (the first "-->")."""
    steps = {"<": {"!": "!"}, "!": {"-": "!-"}, "!-": {"-": "open"}}
    if q in steps:
        return steps[q].get(c)
    if q == "open":
        return ACC if c == ">" else ("open-" if c == "-" else "body")
    if q == "open-":
        return ACC if c == ">" else ("--" if c == "-" else "body")
    if q == "body":
        return "-" if c == "-" else "body"
    if q == "-":
        return "--" if c == "-" else "body"
    if q == "--":
        return ACC if c == ">" else ("--" if c == "-" else "body")
    raise ValueError(q)


def processing(q, c):
    """<? ... ?>"""
    if q == "<":
        return "body" if c == "?" else None
    if q == "body":
        return "?" if c == "?" else "body"
    if q == "?":
        return ACC if c == ">" else ("?" if c == "?" else "body")
    raise ValueError(q)


def declaration(q, c):
    """<! + ASCII letter + anything but > + >"""
    if q == "<":
        return "!" if c == "!" else None
    if q == "!":
        return "body" if c in LETTER else None
    if q == "body":
        return ACC if c == ">" else "body"
    raise ValueError(q)


def cdata(q, c):
    """<![CDATA[ ... ]]>"""
    prefix = "![CDATA["
    if isinstance(q, str) and q.startswith("<"):
        k = len(q) - 1
        if c != prefix[k]:
            return None
        return q + c if k + 1 < len(prefix) else "body"
    if q == "body":
        return "]" if c == "]" else "body"
    if q == "]":
        return "]]" if c == "]" else "body"
    if q == "]]":
        return ACC if c == ">" else ("]]" if c == "]" else "body")
    raise ValueError(q)


def uri_autolink(q, c):
    """<scheme:...> with a scheme of 2 to 32 characters."""
    if q == "<":
        return ("s", 1) if c in LETTER else None
    if q == "body":
        if c == ">":
            return ACC
        return None if c in WS or c == "<" else q
    n = q[1]
    if c == ":" and n >= 2:
        return "body"
    if (c in ALNUM or c in "+.-") and n < 32:
        return ("s", n + 1)
    return None


def email_autolink(q, c):
    if q == "<":
        return "local" if c in EMAIL_LOCAL else None
    if q == "local":
        if c == "@":
            return "label-start"
        return q if c in EMAIL_LOCAL else None
    if q == "label-start":
        return "label" if c in ALNUM else None
    if q in ("label", "label-"):              # label-: the label's last character was "-"
        if c in ALNUM:
            return "label"
        if c == "-":
            return "label-"
        if q == "label" and c == ".":
            return "label-start"
        return ACC if q == "label" and c == ">" else None
    raise ValueError(q)


# In the order a `<` is tried: commonmark.js tries an email autolink, a URI
# autolink, then raw HTML (whose kinds can't overlap).
KINDS = [("email", email_autolink), ("uri", uri_autolink), ("open", open_tag), ("close", close_tag),
         ("comment", comment), ("pi", processing), ("decl", declaration), ("cdata", cdata)]


def line_tag(step):
    """The tag kind as it starts an HTML block of type 7 (a whole tag alone
    on its line): only a `>` with nothing but whitespace after it can end it,
    so another `>` (GT_NO) is a character inside quotes and fails elsewhere."""
    def f(q, c):
        if c != GT_NO:
            return step(q, c)
        n = step(q, ">")
        return None if n == ACC else n
    return f


LINE_KINDS = [("open7", line_tag(open_tag)), ("close7", line_tag(close_tag))]


def states(step):
    seen, todo = {"<"}, ["<"]
    while todo:
        q = todo.pop()
        for c in ALPHABET + [GT_NO]:
            n = step(q, c)
            if n not in (None, ACC) and n not in seen:
                seen.add(n)
                todo.append(n)
    return sorted(seen, key=str)


class Backward:
    """A kind's right-to-left step: from the set of states that reach
    acceptance reading what lies to the right, the set reading one more."""

    def __init__(self, step):
        self.step, self.states = step, states(step)

    def back(self, R, c):
        return frozenset(q for q in self.states
                         if (n := self.step(q, c)) == ACC or (n is not None and n in R))
