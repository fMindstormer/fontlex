"""A line's block structure, read from its start one character at a time:
the automaton the Markdown font's first left-to-right pass runs.

It reads only the characters that can make up a line's block markup (PREFIX)
and stops at the first character of its content. Whatever needs the rest of
the line it gets from marks that right-to-left passes put on characters
before it reads them (marks() computes them directly, for testing): whether
a space or tab or the end of the line comes next, whether only whitespace
follows, whether a thematic break, an HTML block, a code fence, a link
reference definition or a task box starts here.

step() follows cm_block (commonmark.js's block parser, and cmark-gfm's task
items), tabs and all: a tab advances to the next multiple of 4 columns, and
a block quote's optional space or a list item's padding can take part of one.
"""

import re

import cm_block

PREFIX = frozenset(" \t>-+*_#`~<[]xX.)0123456789")

# Modes: what the rest of the line is, once the automaton stops.
PARAGRAPH, HEADING, CODE, DIM, RULE = "para", "heading", "code", "dim", "rule"


def marks(line):
    """The marks each character gets from the right-to-left passes: a set of
    names (with ("hashes", n) for runs of `#`)."""
    out = []
    n = len(line)
    for i, c in enumerate(line):
        m = set()
        rest = line[i + 1:]
        if rest[:1] in ("", " ", "\t"):
            m.add("wsnext")
        if not rest.strip(" \t"):
            m.add("blank")
        if c in "-*_" and cm_block.RE_THEMATIC_BREAK.match(line, i):
            m.add("hr")
        if c == "#":
            run = len(line[i:]) - len(line[i:].lstrip("#"))
            if run <= 6 and line[i + run:i + run + 1] in ("", " ", "\t"):
                m.add("atx")
        if c in "`~" and cm_block.RE_FENCE.match(line, i):
            m.add("fence")
        if c == "<" and any((cm_block.RE_HTML_BLOCK_7 if k == 7 else cm_block.RE_HTML_BLOCK_OPEN[k]).match(line, i)
                            for k in range(1, 8)):
            m.add("html")
        if c == "[":
            if cm_block.reference_definition(line[i:]):
                m.add("def")
            if re.match(r"\[[ xX]\][ \t\x0b\x0c]", line[i:]):
                m.add("task")
            if "[x]" in line[i:] or "[X]" in line[i:]:
                m.add("xbox")
        if c.isdigit() and c in "0123456789" and re.match(r"[0-9]{1,9}[.)](?:[ \t]|$)", line[i:]):
            m.add("ordinal")
        out.append(frozenset(m))
    assert len(out) == n
    return out


def _tab(col):
    return 4 - col % 4


# The state is a tuple: (phase, col, depth, item, a, b). col is the column the
# next character starts at, modulo 4 (all a tab needs), depth the containers
# so far (0, 1, or 2 for more), item whether the last container is the line's
# first and a list item (so a task box may follow). a and b are per phase:
#   "start": a block start; a = columns of indentation so far
#   "quote": just after `>`, its optional space next
#   "digits": in an ordered list marker
#   "after": after a list marker; a = columns of whitespace so far
#   "atx": in a heading's opening `#`s;  "atx-space": after them
#   "box": in a task box; a = 1 or 2 characters read, b = checked
#   "boxed": after a task box (its paragraph follows)
INIT = ("start", 0, 0, False, 0, 0)


def step(state, ch, mk):
    """(role, new state) for the next character, or None where the line's
    content starts (and the automaton stops). Roles: "indent" (whitespace,
    drawn plain), "quote", "bullet", "number" (an ordered marker, plain),
    "box-open"/"box-close" (hidden), "box"/"checked", "atx" (a heading's
    `#`s, dimmed), and the leaf starts "fence", "html", "def" (all dimmed to
    the end of the line), "hr" (a rule to the end), "code" (the last column
    of a code block's indentation: code follows)."""
    phase, col, depth, item, a, b = state
    width = (1 if ch == " " else _tab(col)) if ch in " \t" else 1
    nxt = (col + width) % 4
    deeper = min(depth + 1, 2)

    if phase == "quote":                      # its optional space or tab: one column
        if ch == " ":
            return "indent", ("start", (col + 1) % 4, depth, False, 0, 0)
        if ch == "\t":
            return "indent", ("start", nxt, depth, False, width - 1, 0)
        phase, a = "start", 0
    if phase == "after":                      # whitespace after a list marker
        if ch in " \t":
            w = a + width
            if "blank" in mk:                 # an empty item: nothing more to draw
                return "indent", ("done", 0, 0, False, 0, 0)
            if w >= 5:                        # padding 1, and the rest (4 columns) indents code
                return "code", ("done", 0, 0, False, 0, 0)
            return "indent", ("after", nxt, depth, item, w, 0)
        phase, a = "start", 0                 # 1 to 4 columns: the content starts here
    if phase == "digits":
        if ch.isdigit():
            return "number", ("digits", (col + 1) % 4, depth, item, 1, 0)
        return "number", ("after", (col + 1) % 4, deeper, depth == 0, 0, 0)   # `.` or `)`
    if phase == "atx":
        if ch == "#":
            return "atx", ("atx", 0, 0, False, 0, 0)
        if ch in " \t":
            return "indent", ("atx-space", 0, 0, False, 0, 0)
        return None
    if phase == "atx-space":
        return ("indent", ("atx-space", 0, 0, False, 0, 0)) if ch in " \t" else None
    if phase == "box":
        if a == 1:
            return ("checked" if b else "box"), ("box", 0, 0, False, 2, b)
        return "box-close", ("boxed", 0, 0, False, 0, 0)
    if phase == "boxed":
        if ch in " \t":
            return "indent", ("boxed", 0, 0, False, 0, 0)
        return ("def", ("done", 0, 0, False, 0, 0)) if ch == "[" and "def" in mk else None
    if phase == "done":
        return None

    # A block start, after `a` columns of indentation.
    if ch in " \t":
        ind = a + width
        if ind >= 4:
            if "blank" in mk:
                return "indent", ("done", 0, 0, False, 0, 0)
            return "code", ("done", 0, 0, False, 0, 0)
        return "indent", ("start", nxt, depth, item, ind, 0)
    if ch == ">":
        return "quote", ("quote", (col + 1) % 4, deeper, False, 0, 0)
    if ch == "#" and "atx" in mk:
        return "atx", ("atx", 0, 0, False, 0, 0)
    if ch in "`~" and "fence" in mk:
        return "fence", ("done", 0, 0, False, 0, 0)
    if ch == "<" and "html" in mk:
        return "html", ("done", 0, 0, False, 0, 0)
    if ch in "-*_" and "hr" in mk:
        return "hr", ("done", 0, 0, False, 0, 0)
    if ch in "-+*" and "wsnext" in mk:
        return "bullet", ("after", (col + 1) % 4, deeper, depth == 0, 0, 0)
    if ch.isdigit() and "ordinal" in mk:
        return "number", ("digits", (col + 1) % 4, depth, False, 1, 0)
    if ch == "[":
        if item and "task" in mk:
            return "box-open", ("box", 0, 0, False, 1, "xbox" in mk)
        if "def" in mk:
            return "def", ("done", 0, 0, False, 0, 0)
    return None


def run(line):
    """The role step() gives each character (None from where it stops) and
    the mode of the rest of the line."""
    mk = marks(line)
    roles, state = [None] * len(line), INIT
    for i, ch in enumerate(line):
        if ch not in PREFIX:
            break
        r = step(state, ch, mk[i])
        if r is None:
            break
        roles[i], state = r
    last = next((r for r in reversed(roles) if r), None)
    mode = {"fence": DIM, "html": DIM, "def": DIM, "hr": RULE, "code": CODE}.get(last, PARAGRAPH)
    if any(r == "atx" for r in roles):
        mode = HEADING
    return roles, mode
