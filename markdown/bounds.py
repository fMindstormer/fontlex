"""Which of the Markdown font's bounds a line goes past.

The font is exact within its bounds (mdfont.py's constants). exceeds(line)
parses the line as CommonMark does (cm_inline) and lists the bounds it
passes; verify.py counts a mismatch only on lines that pass none. Emphasis
is checked by running the font's algorithm, peel(), on each run of
delimiters CommonMark matches together: rounds in which an opener pairs
with the closer right after it in the sequence of unmatched runs.
"""

import re
import unicodedata

import cm_block
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


def peel(runs, rounds, search, walls=True):
    """The font's emphasis matching. Each round is one left-to-right pass
    over the runs still unmatched: a settled opener pairs with the first
    unsettled closer after it if it is the nearest opener eligible for it
    (looking past at most `search` others, which are discarded); a closer
    with no eligible opener left of it settles (becomes an opener if it can
    open). A `~` run pairs only whole, as strikethrough if the two have the
    same length, and otherwise both stay as text (as in cmark-gfm).

    With `walls`, a `~` closer that finds no opener is a wall: no later `~`
    closer of its length looks for an opener before it. That is cmark-gfm's
    lower bound for opener searches, which it keeps per length but not per
    whether the closer can also open (commonmark.js, for `*` and `_`, keeps
    it per both, which never changes what matches)."""
    index = {id(x): k for k, x in enumerate(runs)}
    wall = {}                   # `~` run length -> the index of its last wall

    def floor(c):
        return wall.get(c.n, -1) if walls and c.cc == "~" else -1

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
                    if eligible(e, c) and index[id(e)] >= floor(c) and not any(
                            eligible(x, c) and index[id(x)] >= floor(c) for x in between):
                        if c.cc == "~":
                            if e.n == c.n:
                                e.opens.append(e.n)
                                c.closes.append(c.n)
                            e.r = c.r = 0
                        else:
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
                    if index[id(x)] < floor(e):
                        d = -1
                        break
                    if d >= search or not x.settled or eligible(x, e):
                        break
                else:
                    d = -1
                if d == -1:
                    e.settled = True
                    e.alive = e.can_open
                    if e.cc == "~":
                        wall[e.n] = index[id(e)]
            i += 1
    return [(tuple(x.closes), tuple(x.opens)) for x in runs]


def emphasis_roles(line, rounds=100, search=100, gfm=False):
    """What peel() makes of a line with no other syntax than `*` and `_`
    (and with `gfm`, `~`): each character's cm_inline Role."""
    p, runs, i = cm.InlineParser(line, gfm=gfm), [], 0
    while i < len(line):
        if line[i] in ("*_~" if gfm else "*_"):
            p.pos = i
            n, o, c = p.scan_delims(line[i])
            if (o or c) and (line[i] != "~" or n <= 2):
                runs.append((i, Run(line[i], n, o, c)))
            i += n
        else:
            i += 1
    result = peel([r for _, r in runs], rounds, search)
    events, hidden = {}, set()
    for (start, run), (closes, opens) in zip(runs, result):
        p = start
        for u in closes:
            events[p] = (-1, "~" if run.cc == "~" else u)
            hidden.update(range(p, p + u))
            p += u
        q = start + run.n
        for u in opens:
            q -= u
            events[q] = (1, "~" if run.cc == "~" else u)
            hidden.update(range(q, q + u))
    out, depth = [], {1: 0, 2: 0, "~": 0}
    for i in range(len(line)):
        if i in events:
            d, u = events[i]
            depth[u] += d
        if i in hidden:
            out.append(cm.HIDDEN)
        else:
            out.append(cm.Role("text", frozenset(s for s, u in (("em", 1), ("strong", 2), ("strike", "~"))
                                                 if depth[u])))
    return out


class _Parser(cm.InlineParser):
    """cm_inline's parser, noting what the font's bounds are about."""

    def __init__(self, subject, offset, notes, gfm=True):
        super().__init__(subject, offset, gfm)
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
        self.closing = True          # emphasis processed now is a link's text
        try:
            r = super().parse_close_bracket(block)
        finally:
            self.closing = False
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
            rounds = F.INNER_ROUNDS if getattr(self, "closing", False) else F.ROUNDS
            reference = peel(fresh(), 100, 100)
            if peel(fresh(), 100, 100, walls=False) != reference:
                self.notes.add("a `~` that cmark-gfm's opener search passes by")
            elif peel(fresh(), rounds, F.SEARCH, walls=False) != reference:
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


EMAIL_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.+-_@")
# Where a bare URL can start, roughly (the font reads it exactly).
CANDIDATE = re.compile(r"(?:^|(?<=[ \t*_~(]))www\.|(?<![A-Za-z])(?i:https?|ftp)://")


def _bare_links(line, node, a, notes):
    """Where bare URLs and emails (GFM's extended autolinks) go past the
    font's reading of them."""
    for m in re.finditer(r"[A-Za-z0-9.+\-_@]+", line):
        if m.group().count("@") > 1:
            notes.add("two `@` in one email-like word")
        # The text cmark-gfm reads has escapes and references resolved: one
        # that stands for an email's character joins the word there.
        if "@" in m.group():
            before, after = line[:m.start()], line[m.end():]
            ref = re.search(r"&(?:#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z0-9]+);$", before)
            ref_after = re.match(r"&(?:#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z0-9]+);", after)
            joins = lambda r: r is not None and cm.decode_entity(r.group()) in EMAIL_CHARS
            if (before[-1:] == "\\" and before[-2:-1] in EMAIL_CHARS or re.match(r"\\[.+\-_@]", after)
                    or joins(ref) or joins(ref_after)):
                notes.add("an escape or reference next to an email-like word")
    starts = [m.start() for m in CANDIDATE.finditer(line)]
    for m in CANDIDATE.finditer(line):
        dom = re.match(r"[A-Za-z0-9._\\-]*", line[m.end():]).group()
        if "\\" in dom:
            notes.add("a backslash in a URL's domain")
        labels = dom.split(".")
        if dom.count(".") > 10 and "_" in "".join(labels[-2:]):
            notes.add("a URL domain with `_` and more than 10 dots")
    for n in _walk(node):
        kind = getattr(n, "bare", None)
        if n.type != "link" or not kind:
            continue
        src = [i for c in _walk(n) for i in c.src]
        s0, s1 = min(src), max(src) + 1
        # A shaper may compose a letter with a mark: cmark-gfm reads the letter.
        prefix = s1 + 1 if kind == "email" else line.index(":", s0) + 4 if line[s0] != "w" else s0 + 5
        if any(unicodedata.combining(c) for c in line[s0:prefix]):
            notes.add("a combining mark in an email or after a URL's first characters")
        if kind == "email":
            if "\\" in line[s0:s1] or "&" in line[s0:s1]:
                notes.add("an escape or reference in an email")
            if re.match(r"(mailto|xmpp):", line[s0:s1]):
                notes.add("an email after mailto: or xmpp:")
            continue
        if line[s1 - 1] == "\\":
            notes.add("a bare URL ending in a backslash")
        if re.match(r"[^ \t<]*&#?[A-Za-z0-9]+;[?!.,:*_~'\")]*(?:[ \t<]|$)", line[s0:]):
            notes.add("a reference ending a bare URL's word")
        if s0 == a and line[s0] == "w" and a > 0 and line[a - 1] not in " \t":
            notes.add("a www. link after leading whitespace other than spaces and tabs")
        word = re.match(r"[^ \t<]*", line[s0:]).group()
        start = line.index(":", s0) if line[s0] != "w" else s0
        depth = lo = hi = 0
        for c in line[start:s0 + len(word)]:
            depth += (c == "(") - (c == ")")
            lo, hi = min(lo, depth), max(hi, depth)
        if lo < -F.URL_PARENS or hi > F.URL_PARENS:
            notes.add(f"a bare URL's parentheses more than {F.URL_PARENS} out of balance")
        before = re.search(r"[^ \t<]*$", line[:s0]).group()
        if any(s0 - len(before) <= k < s0 for k in starts):
            notes.add("a bare URL inside another one's word")


def exceeds(line, cmap=None):
    """The bounds of the font that `line` goes past (an empty set if none);
    with the font's `cmap`, also references to characters it lacks."""
    notes = set()
    for i, role in enumerate(cm_block.roles(line)):
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
    if re.search(r"(?<!\\)(?:\\\\)*\\~", line) and re.search(r"[*_~]\\~|\\~[*_~]", line):
        notes.add("an escaped `~` next to a delimiter")
    if re.search(r"~{4,}[*_]", line):     # a `~` run's 4th character on knows nothing before the run
        notes.add("a `*` or `_` right after 4 or more `~`")
    blocks,definition, inline = cm_block.parse(line, gfm=True)
    if definition:
        notes.add("a link reference definition")
    leaf = blocks[-1] if blocks else None
    if leaf is not None and leaf.type == "heading" and re.search(r"#{9,}[ \t]*$", line):
        notes.add("a heading's closing #s more than 8")
    if inline is None:
        return notes
    _, a, z = inline
    quotes = [b.marker[0] for b in blocks if b.type == "quote"]
    if a < len(line) and line[a] in "*_~" and quotes and a == quotes[-1] + 1:
        notes.add("a delimiter run right after a `>` with no space")
    node = _Parser(line[a:z], a, notes).parse()
    _bare_links(line, node, a, notes)
    heading = 1 if leaf.type == "heading" else 0

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
    depth(node, 0, 0, heading)
    return notes
