"""Which of the Markdown font's bounds a line goes past.

The font is exact within its bounds (mdfont.py's constants). exceeds(line)
parses the line as CommonMark does (cm_inline) and lists the bounds it
passes; verify.py counts a mismatch only on lines that pass none. Emphasis
is checked by running the font's algorithm, peel(), on each run of
delimiters CommonMark matches together: rounds in which an opener pairs
with the closer right after it in the sequence of unmatched runs.
"""

import re

import cm_inline as cm
import mdfont as F


class Run:
    def __init__(self, cc, n, can_open, can_close):
        self.cc, self.n, self.can_open, self.can_close = cc, n, can_open, can_close
        self.r, self.closes, self.opens = n, [], []
        self.alive, self.settled = True, not can_close


def eligible(o, c):
    if o.cc != c.cc or not o.can_open or not o.settled:
        return False
    return not ((c.can_open or o.can_close) and c.n % 3 != 0 and (o.n + c.n) % 3 == 0)


def peel(runs, rounds, search):
    """The font's emphasis matching. Each round is one left-to-right pass
    over the runs still unmatched: a settled opener pairs with the first
    unsettled closer after it if it is the nearest opener eligible for it
    (looking past at most `search` others, which are discarded); a closer
    with no eligible opener left of it settles (becomes an opener if it can
    open)."""
    for _ in range(rounds):
        seq = [x for x in runs if x.alive]
        i = 0
        while i < len(seq):
            e = seq[i]
            if e.alive and e.settled and e.can_open:
                j = i + 1
                while j < len(seq) and seq[j].settled:
                    j += 1
                if j < len(seq) and j - i - 1 <= search:
                    c, between = seq[j], seq[i + 1:j]
                    if eligible(e, c) and not any(eligible(x, c) for x in between):
                        use = 2 if c.r >= 2 and e.r >= 2 else 1
                        e.r -= use
                        e.opens.append(use)
                        c.r -= use
                        c.closes.append(use)
                        for x in between:
                            x.alive = False
                        if e.r == 0:
                            e.alive = False
                        if c.r == 0:
                            c.alive = c.settled = False
                        i = j + 1
                        continue
            if e.alive and not e.settled:
                left = [x for x in seq[:i] if x.alive][::-1]
                for d, x in enumerate(left):
                    if d >= search or not x.settled or eligible(x, e):
                        break
                else:
                    e.settled = True
                    e.alive = e.can_open
            i += 1
    return [(tuple(x.closes), tuple(x.opens)) for x in runs]


def emphasis_roles(line, rounds=100, search=100):
    """What peel() makes of a line with no other syntax than `*` and `_`:
    each character's cm_inline Role."""
    p, runs, i = cm.InlineParser(line), [], 0
    while i < len(line):
        if line[i] in "*_":
            p.pos = i
            n, o, c = p.scan_delims(line[i])
            if o or c:
                runs.append((i, Run(line[i], n, o, c)))
            i += n
        else:
            i += 1
    result = peel([r for _, r in runs], rounds, search)
    events, hidden = {}, set()
    for (start, run), (closes, opens) in zip(runs, result):
        p = start
        for u in closes:
            events[p] = (-1, u)
            hidden.update(range(p, p + u))
            p += u
        q = start + run.n
        for u in opens:
            q -= u
            events[q] = (1, u)
            hidden.update(range(q, q + u))
    out, depth = [], {1: 0, 2: 0}
    for i in range(len(line)):
        if i in events:
            d, u = events[i]
            depth[u] += d
        if i in hidden:
            out.append(cm.HIDDEN)
        else:
            out.append(cm.Role("text", frozenset(s for s, u in (("em", 1), ("strong", 2)) if depth[u])))
    return out


class _Parser(cm.InlineParser):
    """cm_inline's parser, noting what the font's bounds are about."""

    def __init__(self, subject, offset, notes):
        super().__init__(subject, offset)
        self.notes = notes

    def _depth(self):
        d, b = 0, self.brackets
        while b is not None:
            d, b = d + 1, b.previous
        return d

    def parse_open_bracket(self, block):
        r = super().parse_open_bracket(block)
        if self._depth() > F.MAX_BRACKETS:
            self.notes.add(f"more than {F.MAX_BRACKETS} open brackets")
        return r

    def parse_bang(self, block):
        r = super().parse_bang(block)
        if self._depth() > F.MAX_BRACKETS:
            self.notes.add(f"more than {F.MAX_BRACKETS} open brackets")
        return r

    def parse_close_bracket(self, block):
        opener = self.brackets
        before = block.last
        r = super().parse_close_bracket(block)
        made = block.last is not before and block.last.type in ("link", "image")
        if opener is not None and not opener.active and _valid_tail(self.subject, self.pos):
            self.notes.add("a link destination after a link in link text")
        if made:
            node = block.last
            inner = sum(1 for _ in _walk(node) if _.type == "link")
            if inner > F.MAX_LINKS_INSIDE:
                self.notes.add("too many links in one link text")
        return r

    def parse_link_destination(self):
        start = self.pos
        r = super().parse_link_destination()
        if r is not None:
            depth = deepest = 0
            for ch in re.sub(r"\\.", "", self.subject[start:self.pos]):
                depth += (ch == "(") - (ch == ")")
                deepest = max(deepest, depth)
            if deepest > F.PARENS:
                self.notes.add(f"parentheses nested more than {F.PARENS} deep in a destination")
        return r

    def process_emphasis(self, bottom):
        delims, d = [], self.delimiters
        while d is not None and d is not bottom:
            delims.append(d)
            d = d.previous
        delims.reverse()
        runs = [Run(x.cc, x.origdelims, x.can_open, x.can_close) for x in delims]
        if any(x.n > F.MAX_DELIMS for x in runs):
            self.notes.add(f"a delimiter run longer than {F.MAX_DELIMS}")
        elif runs:
            fresh = lambda: [Run(x.cc, x.n, x.can_open, x.can_close) for x in runs]
            rounds = F.ROUNDS if self.brackets is None or bottom is None else F.INNER_ROUNDS
            if peel(fresh(), rounds, F.SEARCH) != peel(fresh(), 100, 100):
                self.notes.add("emphasis nested past the font's rounds or search")
        return super().process_emphasis(bottom)


def _valid_tail(s, pos):
    """Does a link destination start at s[pos] (just after a `]`)?"""
    p = cm.InlineParser(s)
    p.pos = pos
    if p.peek() != "(":
        return False
    p.pos += 1
    p.spnl()
    if p.parse_link_destination() is None:
        return False
    p.spnl()
    if p.subject[p.pos - 1] in cm.LINK_WHITESPACE:
        p.parse_link_title()
    p.spnl()
    return p.peek() == ")"


def _walk(node):
    c = node.first
    while c:
        yield c
        yield from _walk(c)
        c = c.next


def exceeds(line, cmap=None):
    """The bounds of the font that `line` goes past (an empty set if none);
    with the font's `cmap`, also references to characters it lacks."""
    notes = set()
    for i, role in enumerate(cm.roles(line)):
        if role.kind != "entity":
            continue
        ref = cm.RE_ENTITY.match(line, i).group()
        digits = ref[3:-1] if ref[:3].lower() == "&#x" else ref[2:-1]
        if ref[1] == "#" and len(digits) > 1 and digits[0] == "0":
            notes.add("a numeric character reference with leading zeros")
        elif ref[1] == "#" and cm.decode_entity(ref) == "\uFFFD" and ref not in ("&#0;",):
            notes.add("a numeric character reference to no character")
        elif len(role.char) != 1:
            notes.add("a reference to several characters")
        elif cmap is not None and ord(role.char) not in cmap:
            notes.add("a reference to a character the font lacks")
    for m in re.finditer(r"\\+", line):
        if len(m.group()) > F.MAX_BACKSLASHES:
            notes.add(f"more than {F.MAX_BACKSLASHES} backslashes in a row")
    for m in re.finditer(r"`+", line):
        if len(m.group()) > F.MAX_TICKS:
            notes.add(f"a backtick run longer than {F.MAX_TICKS}")
    stripped = line.strip(" \t")
    node = _Parser(stripped, len(line) - len(line.lstrip(" \t")), notes).parse()

    def depth(n, lv, em, strong):
        for c in n.children():
            if c.type in ("link", "image"):
                if lv + 1 > F.LEVELS:
                    notes.add(f"link or image text nested more than {F.LEVELS} deep")
                depth(c, lv + 1, em, strong)
            elif c.type == "emph":
                if em + 1 > F.MAX_DEPTH:
                    notes.add(f"emphasis nested more than {F.MAX_DEPTH} deep")
                depth(c, lv, em + 1, strong)
            elif c.type == "strong":
                if strong + 1 > F.MAX_DEPTH:
                    notes.add(f"strong emphasis nested more than {F.MAX_DEPTH} deep")
                depth(c, lv, em, strong + 1)
    depth(node, 0, 0, 0)
    return notes
