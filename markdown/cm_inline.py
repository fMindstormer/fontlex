"""What CommonMark makes of one line of text, character by character.

A port of the inline parser of commonmark.js 0.31.2 (lib/inlines.js), the
reference implementation of CommonMark 0.31.2, for one line read as a whole
paragraph without link reference definitions: a font sees a line at a time
and can't look anything up elsewhere in the document. Besides the HTML, it
records what becomes of every source character (`roles`), which is what the
Markdown font has to draw.

Where commonmark.js and the spec differ, this follows the spec: Unicode
whitespace is the Zs category plus tab, line feed, form feed and carriage
return (JavaScript's `\\s` also has U+000B, U+2028, U+2029 and U+FEFF), and
whitespace inside HTML tags is spaces, tabs and line endings.

With `gfm`, GitHub's inline extensions are added as cmark-gfm 0.29.0.gfm.13
has them: strikethrough with `~` and `~~`, and links to www., http(s)://
and ftp:// addresses and to email addresses written without `<>` (gfm.py).
"""

import html.entities
import re
import unicodedata
from dataclasses import dataclass

import gfm as G

ASCII_PUNCTUATION = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
LINK_WHITESPACE = frozenset(" \t\n\x0b\x0c\r")  # reWhitespaceChar


def is_unicode_whitespace(c):
    return c in "\t\n\x0c\r" or unicodedata.category(c) == "Zs"


def is_unicode_punctuation(c):
    return unicodedata.category(c)[0] in "PS"


_ESCAPED = r"\\[!-/:-@\[-`{-~]"
_WS = r"[ \t\n\r]"
_TAGNAME = r"[A-Za-z][A-Za-z0-9-]*"
_ATTRIBUTE = (r"(?:" + _WS + r"+[a-zA-Z_:][a-zA-Z0-9:._-]*(?:" + _WS + r"*=" + _WS
              + r"*(?:[^\"'=<>`\x00-\x20]+|'[^']*'|\"[^\"]*\"))?)")
RE_HTML_TAG = re.compile(
    r"(?:<" + _TAGNAME + _ATTRIBUTE + r"*" + _WS + r"*/?>"
    r"|</" + _TAGNAME + _WS + r"*>"
    r"|<!-->|<!--->|<!--[\s\S]*?-->"
    r"|<\?[\s\S]*?\?>"
    r"|<![A-Za-z]+[^>]*>"
    r"|<!\[CDATA\[[\s\S]*?\]\]>)")
RE_EMAIL_AUTOLINK = re.compile(
    r"<([a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*)>")
RE_AUTOLINK = re.compile(r"<[A-Za-z][A-Za-z0-9.+-]{1,31}:[^<>\x00-\x20]*>")
RE_ENTITY = re.compile(r"&(?:#[xX][a-fA-F0-9]{1,6}|#[0-9]{1,7}|[a-zA-Z][a-zA-Z0-9]{1,31});")
RE_LINK_TITLE = re.compile(
    r'(?:"(?:' + _ESCAPED + r'|\\[^\\]|[^\\"\x00])*"'
    r"|'(?:" + _ESCAPED + r"|\\[^\\]|[^\\'\x00])*'"
    r"|\((?:" + _ESCAPED + r"|\\[^\\]|[^\\()\x00])*\))")
RE_LINK_DESTINATION_BRACES = re.compile(r"<(?:[^<>\n\\\x00]|\\.)*>")
RE_SPNL = re.compile(r" *(?:\n *)?")
RE_TICKS = re.compile(r"`+")
RE_MAIN = re.compile(r"[^\n`\[\]\\!<&*_'\"]+")
RE_MAIN_GFM = re.compile(r"[^\n`\[\]\\!<&*_'\"~w:]+")    # also stops where an extension may start
RE_ENTITY_OR_ESCAPED = re.compile(_ESCAPED + "|" + RE_ENTITY.pattern)

# Code points numeric references replace, as in HTML (the `entities` package).
C1_REPLACEMENTS = {
    0: 0xFFFD, 128: 8364, 130: 8218, 131: 402, 132: 8222, 133: 8230, 134: 8224, 135: 8225,
    136: 710, 137: 8240, 138: 352, 139: 8249, 140: 338, 142: 381, 145: 8216, 146: 8217,
    147: 8220, 148: 8221, 149: 8226, 150: 8211, 151: 8212, 152: 732, 153: 8482, 154: 353,
    155: 8250, 156: 339, 158: 382, 159: 376}


def decode_entity(ref):
    """The text an entity reference stands for, or the reference itself if unknown."""
    if ref[1] == "#":
        n = int(ref[3:-1], 16) if ref[2] in "xX" else int(ref[2:-1])
        if 0xD800 <= n <= 0xDFFF or n > 0x10FFFF:
            return "\uFFFD"
        return chr(C1_REPLACEMENTS.get(n, n))
    return html.entities.html5.get(ref[1:], ref)


def unescape_string(s):
    return RE_ENTITY_OR_ESCAPED.sub(
        lambda m: m.group(0)[1] if m.group(0)[0] == "\\" else decode_entity(m.group(0)), s)


_URI_SAFE = frozenset(";/?:@&=+$,-_.!~*'()#"
                      "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
_HEX = frozenset("0123456789abcdefABCDEF")


def normalize_uri(uri):
    """mdurl's encode: percent-encode what isn't safe, keeping existing %XX escapes."""
    out, i = [], 0
    while i < len(uri):
        c = uri[i]
        if c == "%" and i + 2 < len(uri) and uri[i + 1] in _HEX and uri[i + 2] in _HEX:
            out.append(uri[i:i + 3])
            i += 3
            continue
        out.append(c if c in _URI_SAFE else "".join(f"%{b:02X}" for b in c.encode("utf-8")))
        i += 1
    return "".join(out)


def escape_xml(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


class Node:
    """An inline node. `src` gives the source index of each character of a text
    node's literal, or of a code node's content. In a text node, `ent` marks
    the characters an entity reference decoded to: the first holds the whole
    decoded text, the others "" (None for other characters)."""

    def __init__(self, type, literal="", src=()):
        self.type, self.literal, self.src = type, literal, list(src)
        self.ent = [None] * len(literal)
        self.parent = self.first = self.last = self.prev = self.next = None
        self.destination = self.title = ""

    def append(self, child):
        child.unlink()
        child.parent = self
        if self.last:
            self.last.next, child.prev = child, self.last
        else:
            self.first = child
        self.last = child

    def insert_after(self, sibling):
        sibling.unlink()
        sibling.next, sibling.prev, sibling.parent = self.next, self, self.parent
        if self.next:
            self.next.prev = sibling
        elif self.parent:
            self.parent.last = sibling
        self.next = sibling

    def unlink(self):
        if self.prev:
            self.prev.next = self.next
        elif self.parent:
            self.parent.first = self.next
        if self.next:
            self.next.prev = self.prev
        elif self.parent:
            self.parent.last = self.prev
        self.parent = self.prev = self.next = None

    def children(self):
        c = self.first
        while c:
            yield c
            c = c.next


def text(literal, src):
    return Node("text", literal, src)


class Delimiter:
    def __init__(self, cc, numdelims, node, previous, can_open, can_close):
        self.cc, self.numdelims, self.origdelims, self.node = cc, numdelims, numdelims, node
        self.previous, self.next = previous, None
        self.can_open, self.can_close = can_open, can_close


class Bracket:
    def __init__(self, node, previous, previous_delimiter, image):
        self.node, self.previous, self.previous_delimiter = node, previous, previous_delimiter
        self.image, self.active = image, True


class InlineParser:
    """commonmark.js's InlineParser, method by method, with an empty refmap and
    smart punctuation off. Source indices are offset by `offset`."""

    def __init__(self, subject, offset=0, gfm=False):
        self.subject, self.offset, self.gfm = subject, offset, gfm
        self.pos = 0
        self.delimiters = self.brackets = None
        self.bytes = subject.encode("utf-8") if gfm else None
        # Byte offset of each character, and the character at each byte offset.
        self.byte_of = [0]
        for c in subject if gfm else "":
            self.byte_of.append(self.byte_of[-1] + len(c.encode("utf-8")))
        self.char_at = {b: i for i, b in enumerate(self.byte_of)}

    def src(self, start, end):
        return range(self.offset + start, self.offset + end)

    def match(self, regex):
        m = regex.match(self.subject, self.pos)
        if m is None:
            return None
        self.pos = m.end()
        return m.group(0)

    def peek(self):
        return self.subject[self.pos] if self.pos < len(self.subject) else None

    def spnl(self):
        self.match(RE_SPNL)
        return True

    def parse_backticks(self, block):
        start = self.pos
        while self.peek() == "`":
            self.pos += 1
        ticks = self.subject[start:self.pos]
        after_open = self.pos
        while True:
            m = RE_TICKS.search(self.subject, self.pos)
            if m is None:
                break
            self.pos = m.end()
            if m.group(0) == ticks:
                lo, hi = after_open, m.start()
                contents = self.subject[lo:hi].replace("\n", " ")
                pad = []
                if contents.strip(" ") and contents[0] == " " and contents[-1] == " ":
                    pad = [self.offset + lo, self.offset + hi - 1]
                    lo, hi = lo + 1, hi - 1
                node = Node("code", self.subject[lo:hi].replace("\n", " "), self.src(lo, hi))
                node.padding = pad
                block.append(node)
                return True
        self.pos = after_open
        block.append(text(ticks, self.src(start, after_open)))
        return True

    def parse_backslash(self, block):
        self.pos += 1
        c = self.peek()
        if c == "\n":
            self.pos += 1
            block.append(Node("linebreak"))
        elif c is not None and c in ASCII_PUNCTUATION:
            block.append(text(c, self.src(self.pos, self.pos + 1)))
            self.pos += 1
        else:
            block.append(text("\\", self.src(self.pos - 1, self.pos)))
        return True

    def parse_autolink(self, block):
        start = self.pos
        m = RE_EMAIL_AUTOLINK.match(self.subject, start)
        if m:
            dest, destination = m.group(1), normalize_uri("mailto:" + m.group(1))
        else:
            m = RE_AUTOLINK.match(self.subject, start)
            if m is None:
                return False
            dest = m.group(0)[1:-1]
            destination = normalize_uri(dest)
        self.pos = m.end()
        node = Node("link")
        node.destination = destination
        node.append(text(dest, self.src(start + 1, self.pos - 1)))
        block.append(node)
        return True

    def parse_html_tag(self, block):
        start = self.pos
        m = self.match(RE_HTML_TAG)
        if m is None:
            return False
        block.append(Node("html_inline", m, self.src(start, self.pos)))
        return True

    def scan_delims(self, cc):
        start = self.pos
        while self.peek() == cc:
            self.pos += 1
        numdelims = self.pos - start
        before = "\n" if start == 0 else self.subject[start - 1]
        after = self.peek() or "\n"
        if self.gfm:
            # cmark-gfm looks past tildes (its SKIP_CHARS) on both sides.
            i = start - 1
            while i > 0 and self.subject[i] == "~":
                i -= 1
            before = "\n" if start == 0 or self.subject[i] == "~" else self.subject[i]
            j = self.pos
            while j < len(self.subject) and self.subject[j] == "~":
                j += 1
            after = self.subject[j] if j < len(self.subject) else "\n"
        self.pos = start
        after_ws, after_p = is_unicode_whitespace(after), is_unicode_punctuation(after)
        before_ws, before_p = is_unicode_whitespace(before), is_unicode_punctuation(before)
        left = not after_ws and (not after_p or before_ws or before_p)
        right = not before_ws and (not before_p or after_ws or after_p)
        if cc == "_":
            return numdelims, left and (not right or before_p), right and (not left or after_p)
        return numdelims, left, right

    def handle_delim(self, cc, block):
        numdelims, can_open, can_close = self.scan_delims(cc)
        start = self.pos
        self.pos += numdelims
        node = text(self.subject[start:self.pos], self.src(start, self.pos))
        block.append(node)
        if (can_open or can_close) and (cc != "~" or numdelims <= 2):
            self.delimiters = Delimiter(cc, numdelims, node, self.delimiters, can_open, can_close)
            if self.delimiters.previous is not None:
                self.delimiters.previous.next = self.delimiters
        return True

    def remove_delimiter(self, delim):
        if delim.previous is not None:
            delim.previous.next = delim.next
        if delim.next is None:
            self.delimiters = delim.previous
        else:
            delim.next.previous = delim.previous

    def process_emphasis(self, stack_bottom):
        openers_bottom = {}
        closer = self.delimiters
        while closer is not None and closer.previous is not stack_bottom:
            closer = closer.previous
        while closer is not None:
            if not closer.can_close:
                closer = closer.next
                continue
            # cmark-gfm keys a `~` closer's lower bound by length alone.
            key = (closer.cc, None if closer.cc == "~" else closer.can_open, closer.origdelims % 3)
            bottom = openers_bottom.get(key, stack_bottom)
            opener, found = closer.previous, False
            while opener is not None and opener is not stack_bottom and opener is not bottom:
                odd_match = ((closer.can_open or opener.can_close) and closer.origdelims % 3 != 0
                             and (opener.origdelims + closer.origdelims) % 3 == 0)
                if opener.cc == closer.cc and opener.can_open and not odd_match:
                    found = True
                    break
                opener = opener.previous
            old_closer = closer
            if not found:
                closer = closer.next
            elif closer.cc == "~":
                closer = self.insert_strikethrough(opener, closer)
            else:
                use = 2 if closer.numdelims >= 2 and opener.numdelims >= 2 else 1
                opener_inl, closer_inl = opener.node, closer.node
                opener.numdelims -= use
                closer.numdelims -= use
                # The opener gives up its rightmost characters, the closer its leftmost.
                opener_inl.literal, opener_inl.src = opener_inl.literal[:-use], opener_inl.src[:-use]
                closer_inl.literal, closer_inl.src = closer_inl.literal[:-use], closer_inl.src[use:]
                opener_inl.ent, closer_inl.ent = opener_inl.ent[:-use], closer_inl.ent[use:]
                emph = Node("emph" if use == 1 else "strong")
                tmp = opener_inl.next
                while tmp is not None and tmp is not closer_inl:
                    nxt = tmp.next
                    emph.append(tmp)
                    tmp = nxt
                opener_inl.insert_after(emph)
                if opener.next is not closer:  # remove delimiters between opener and closer
                    opener.next, closer.previous = closer, opener
                if opener.numdelims == 0:
                    opener_inl.unlink()
                    self.remove_delimiter(opener)
                if closer.numdelims == 0:
                    closer_inl.unlink()
                    nxt = closer.next
                    self.remove_delimiter(closer)
                    closer = nxt
            if not found:
                openers_bottom[key] = old_closer.previous
                if not old_closer.can_open:
                    self.remove_delimiter(old_closer)
        while self.delimiters is not None and self.delimiters is not stack_bottom:
            self.remove_delimiter(self.delimiters)

    def insert_strikethrough(self, opener, closer):
        """cmark-gfm's strikethrough insert(): runs of the same length make a
        strikethrough; either way the opener, the closer and every delimiter
        between them are done with. Returns the next closer to try."""
        nxt = closer.next
        if opener.numdelims == closer.numdelims:
            node = Node("del")
            tmp = opener.node.next
            while tmp is not None and tmp is not closer.node:
                after = tmp.next
                node.append(tmp)
                tmp = after
            opener.node.insert_after(node)
            opener.node.unlink()
            closer.node.unlink()
        d = closer
        while d is not None and d is not opener:
            before = d.previous
            self.remove_delimiter(d)
            d = before
        self.remove_delimiter(opener)
        return nxt

    def parse_link_title(self):
        title = self.match(RE_LINK_TITLE)
        return None if title is None else unescape_string(title[1:-1])

    def parse_link_destination(self):
        res = self.match(RE_LINK_DESTINATION_BRACES)
        if res is not None:
            return normalize_uri(unescape_string(res[1:-1]))
        if self.peek() == "<":
            return None
        savepos, openparens, c = self.pos, 0, None
        while (c := self.peek()) is not None:
            if c == "\\" and self.subject[self.pos + 1:self.pos + 2] in ASCII_PUNCTUATION \
                    and self.pos + 1 < len(self.subject):
                self.pos += 2
            elif c == "(":
                self.pos += 1
                openparens += 1
            elif c == ")":
                if openparens < 1:
                    break
                self.pos += 1
                openparens -= 1
            elif c in LINK_WHITESPACE or c < " " or c == "\x7f":  # the spec also stops at controls
                break
            else:
                self.pos += 1
        if self.pos == savepos and c != ")":
            return None
        if openparens != 0:
            return None
        return normalize_uri(unescape_string(self.subject[savepos:self.pos]))

    def parse_open_bracket(self, block):
        node = text("[", self.src(self.pos, self.pos + 1))
        self.pos += 1
        block.append(node)
        self.brackets = Bracket(node, self.brackets, self.delimiters, False)
        return True

    def parse_bang(self, block):
        start = self.pos
        self.pos += 1
        if self.peek() == "[":
            self.pos += 1
            node = text("![", self.src(start, self.pos))
            block.append(node)
            self.brackets = Bracket(node, self.brackets, self.delimiters, True)
        else:
            block.append(text("!", self.src(start, self.pos)))
        return True

    def parse_close_bracket(self, block):
        close = self.pos
        self.pos += 1
        startpos = self.pos
        opener = self.brackets
        if opener is None or not opener.active:
            if opener is not None:
                self.brackets = opener.previous
            block.append(text("]", self.src(close, startpos)))
            return True
        matched, dest, title = False, None, None
        if self.peek() == "(":
            self.pos += 1
            self.spnl()
            dest = self.parse_link_destination()
            if dest is not None:
                self.spnl()
                if self.subject[self.pos - 1] in LINK_WHITESPACE:
                    title = self.parse_link_title()
                self.spnl()
                if self.peek() == ")":
                    self.pos += 1
                    matched = True
            if not matched:
                self.pos = startpos
        if not matched:  # no reference links: there are no definitions to look up
            self.brackets = opener.previous
            self.pos = startpos
            block.append(text("]", self.src(close, startpos)))
            return True
        node = Node("image" if opener.image else "link")
        node.destination, node.title = dest, title or ""
        tmp = opener.node.next
        while tmp is not None:
            nxt = tmp.next
            node.append(tmp)
            tmp = nxt
        block.append(node)
        self.process_emphasis(opener.previous_delimiter)
        self.brackets = opener.previous
        opener.node.unlink()
        if not opener.image:  # no links in links
            b = self.brackets
            while b is not None:
                if not b.image:
                    b.active = False
                b = b.previous
        return True

    def parse_entity(self, block):
        start = self.pos
        m = self.match(RE_ENTITY)
        if m is None:
            return False
        decoded = decode_entity(m)
        if decoded == m:
            block.append(text(m, self.src(start, self.pos)))
        else:
            node = text(decoded, [self.offset + start] + [None] * (len(decoded) - 1))
            node.ent = [decoded] + [""] * (len(decoded) - 1)
            block.append(node)
        return True

    def parse_string(self, block):
        start = self.pos
        m = self.match(RE_MAIN_GFM if self.gfm else RE_MAIN)
        if m is None:
            return False
        block.append(text(m, self.src(start, self.pos)))
        return True

    def parse_inline(self, block):
        c = self.peek()
        if c is None:
            return False
        if c == "\n":  # parseNewline
            self.pos += 1
            last = block.last
            if last is not None and last.type == "text" and last.literal.endswith(" "):
                hard = last.literal.endswith("  ")
                keep = len(last.literal.rstrip(" "))
                last.literal, last.src, last.ent = last.literal[:keep], last.src[:keep], last.ent[:keep]
                block.append(Node("linebreak" if hard else "softbreak"))
            else:
                block.append(Node("softbreak"))
            while self.peek() == " ":
                self.pos += 1
            return True
        handlers = {"\\": self.parse_backslash, "`": self.parse_backticks, "[": self.parse_open_bracket,
                    "!": self.parse_bang, "]": self.parse_close_bracket, "&": self.parse_entity,
                    "<": lambda b: self.parse_autolink(b) or self.parse_html_tag(b),
                    "*": lambda b: self.handle_delim(c, b), "_": lambda b: self.handle_delim(c, b)}
        if self.gfm:
            handlers.update({"~": lambda b: self.handle_delim(c, b), "w": self.parse_www, ":": self.parse_url})
        res = handlers.get(c, self.parse_string)(block)
        if not res:
            block.append(text(c, self.src(self.pos, self.pos + 1)))
            self.pos += 1
        return True

    # GFM's extended autolinks, found while parsing (www., scheme://) or
    # in the text afterwards (email addresses), as cmark-gfm does.

    def parse_www(self, block):
        if self.brackets is not None:          # not inside [ ] or ![ ]
            return False
        b = self.byte_of[self.pos]
        n = G.www_match(self.bytes, b)
        if not n:
            return False
        end = self.char_at[b + n]
        self.append_link(block, self.pos, end, "http://")
        return True

    def parse_url(self, block):
        if self.brackets is not None:
            return False
        b = self.byte_of[self.pos]
        m = G.url_match(self.bytes, b)
        if m is None:
            return False
        rewind, n = m                          # rewound letters are ASCII
        node = block.last                      # cmark_node_unput: take them back from the text
        k = rewind
        while k > 0 and node is not None and node.type == "text":
            take = min(k, len(node.literal))
            if take:
                node.literal, node.src, node.ent = node.literal[:-take], node.src[:-take], node.ent[:-take]
            k -= take
            node = node.prev
        self.append_link(block, self.pos - rewind, self.char_at[b + n], "")
        return True

    def append_link(self, block, start, end, prefix):
        node = Node("link")
        node.destination = normalize_uri(prefix + self.subject[start:end])
        node.append(text(self.subject[start:end], self.src(start, end)))
        block.append(node)
        self.pos = end

    def parse(self):
        block = Node("paragraph")
        while self.parse_inline(block):
            pass
        self.process_emphasis(None)
        if self.gfm:
            link_emails(block)
        return block


def link_emails(node):
    """cmark-gfm's autolink postprocess: in text outside links, adjacent text
    nodes merged, email addresses become links."""
    child = node.first
    while child is not None:
        if child.type == "text":
            while child.next is not None and child.next.type == "text":
                nxt = child.next
                child.literal, child.src, child.ent = (child.literal + nxt.literal, child.src + nxt.src,
                                                       child.ent + nxt.ent)
                nxt.unlink()
            pos = [0]
            for c in child.literal:
                pos.append(pos[-1] + len(c.encode("utf-8")))
            at = {b: i for i, b in enumerate(pos)}
            done = 0
            for bs, be, mailto in G.emails(child.literal.encode("utf-8")):
                s, e = at[bs], at[be]
                link = Node("link")
                link.destination = normalize_uri(("mailto:" if mailto else "") + child.literal[s:e])
                link.append(_slice(child, s, e))
                _insert_before(child, _slice(child, done, s))
                _insert_before(child, link)
                done = e
            if done:
                rest = _slice(child, done, len(child.literal))
                child.literal, child.src, child.ent = rest.literal, rest.src, rest.ent
        elif child.type != "link":
            link_emails(child)
        child = child.next


def _slice(node, a, b):
    n = text(node.literal[a:b], node.src[a:b])
    n.ent = node.ent[a:b]
    return n


def _insert_before(node, new):
    if node.prev is not None:
        node.prev.insert_after(new)
        return
    new.unlink()
    new.parent, new.prev, new.next = node.parent, None, node
    node.prev = new
    if node.parent is not None:
        node.parent.first = new


def render_html(node, in_image=False):
    """The HTML commonmark.js's HtmlRenderer writes for an inline node's children."""
    out = []
    for c in node.children():
        t = c.type
        if t == "text":
            out.append(escape_xml(c.literal))
        elif t == "softbreak":
            out.append("\n")
        elif t == "linebreak":
            out.append("" if in_image else "<br />\n")
        elif t == "code":
            body = escape_xml(c.literal)
            out.append(body if in_image else f"<code>{body}</code>")
        elif t == "html_inline":
            out.append(c.literal)
        elif t in ("emph", "strong", "del"):
            tag = {"emph": "em", "strong": "strong", "del": "del"}[t]
            body = render_html(c, in_image)
            out.append(body if in_image else f"<{tag}>{body}</{tag}>")
        elif t == "link":
            body = render_html(c, in_image)
            if in_image:
                out.append(body)
            else:
                title = f' title="{escape_xml(c.title)}"' if c.title else ""
                out.append(f'<a href="{escape_xml(c.destination)}"{title}>{body}</a>')
        elif t == "image":
            body = render_html(c, True)
            if in_image:
                out.append(body)
            else:
                title = f'" title="{escape_xml(c.title)}' if c.title else ""
                out.append(f'<img src="{escape_xml(c.destination)}" alt="{body}{title}" />')
    return "".join(out)


@dataclass(frozen=True)
class Role:
    """What becomes of one source character.

    kind: "text" (drawn, in `style`), "hidden" (markup), "dim" (drawn as is
    but dimmed: raw HTML, and block markup such as a heading's `#`s),
    "entity" (the first character of an entity reference, drawn as `char`;
    the rest of the reference is hidden), or for block markup drawn as a
    symbol: "bullet", "quote" (a block quote's `>`), "rule" (a thematic
    break), "box" and "checked" (a task list item's box).
    style: the subset of em, strong, code, link, image, strike and heading
    that applies; text in an image description is image only, as it becomes
    plain alt text.
    """
    kind: str
    style: frozenset = frozenset()
    char: str = ""


HIDDEN = Role("hidden")


def parse_line(line, gfm=False):
    """Parse one line as a paragraph: (paragraph node, source offset)."""
    stripped = line.strip(" \t")
    offset = len(line) - len(line.lstrip(" \t"))
    return InlineParser(stripped, offset, gfm).parse(), offset


def to_html(line, gfm=False):
    node, _ = parse_line(line, gfm)
    return render_html(node)


def roles(line, code_padding=False, gfm=False):
    """The Role of each character of `line`, read as a paragraph. With
    `code_padding`, the space CommonMark strips at each end of a code span
    counts as code (the font shows it as padding) rather than hidden."""
    node, offset = parse_line(line, gfm)
    out = [HIDDEN] * len(line)
    end = offset + len(line.strip(" \t"))
    for i in [*range(offset), *range(end, len(line))]:
        out[i] = Role("text")
    assign(node, out, frozenset(), code_padding)
    return out


NAMES = {"emph": "em", "strong": "strong", "link": "link", "del": "strike"}


def assign(node, out, style, code_padding=False):
    """Set out[i] for the source characters of an inline node's children."""
    for c in node.children():
        if c.type == "text":
            for i, ent in zip(c.src, c.ent):
                if ent:
                    out[i] = Role("entity", style, ent)
                elif ent is None:
                    out[i] = Role("text", style)
        elif c.type == "code":
            st = style | {"code"} if "image" not in style else style
            for i in c.src:
                out[i] = Role("text", st)
            if code_padding:
                for i in c.padding:
                    out[i] = Role("text", st)
        elif c.type == "html_inline":
            for i in c.src:
                out[i] = Role("dim")
        elif c.type in NAMES:
            assign(c, out, style if "image" in style else style | {NAMES[c.type]}, code_padding)
        elif c.type == "image":
            assign(c, out, frozenset({"image"}), code_padding)
