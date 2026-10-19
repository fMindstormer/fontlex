"""What CommonMark makes of one line read as a whole document, character by
character: its block structure (block quotes, list items, headings,
thematic breaks, code and HTML blocks, link reference definitions, or a
paragraph) and the inline content of its paragraph or heading.

A port of commonmark.js 0.31.2's block parser (lib/blocks.js) for a single
line. With `gfm`, GitHub's extensions come in as cmark-gfm 0.29.0.gfm.13
has them: task list items (`- [ ]`, `- [x]`), and strikethrough and
extended autolinks in the inline content (cm_inline). A line alone can't
make a table, a setext heading or a lazy continuation, and a fenced code
block opened on it holds nothing else.
"""

import re
import unicodedata
from dataclasses import dataclass, field

import cm_inline as cm

CODE_INDENT = 4
RE_HTML_BLOCK_OPEN = [
    None,
    re.compile(r"<(?:script|pre|textarea|style)(?:\s|>|$)", re.I),
    re.compile(r"<!--"),
    re.compile(r"<[?]"),
    re.compile(r"<![A-Za-z]"),
    re.compile(r"<!\[CDATA\["),
    re.compile(r"<[/]?(?:address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|"
               r"details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|"
               r"h[123456]|head|header|hr|html|iframe|legend|li|link|main|menu|menuitem|nav|noframes|ol|"
               r"optgroup|option|p|param|section|search|summary|table|tbody|td|tfoot|th|thead|title|tr|"
               r"track|ul)(?:\s|[/]?[>]|$)", re.I),
]
# Type 7: a whole open or closing tag, then only whitespace (JavaScript's \s).
_JS_SPACE = "\t\n\x0b\x0c\r    -     　﻿"
RE_HTML_BLOCK_7 = re.compile(r"(?:<[A-Za-z][A-Za-z0-9-]*" + cm._ATTRIBUTE + r"*" + r"[ \t\n\r]*/?>"
                             r"|</[A-Za-z][A-Za-z0-9-]*[ \t\n\r]*>)[" + _JS_SPACE + r"]*$", re.I)
RE_THEMATIC_BREAK = re.compile(r"(?:\*[ \t]*){3,}$|(?:_[ \t]*){3,}$|(?:-[ \t]*){3,}$")
RE_MAYBE_SPECIAL = re.compile(r"[#`~*+_=<>0-9-]")
RE_NON_SPACE = re.compile(r"[^ \t\f\v\r\n]")
RE_BULLET = re.compile(r"[*+-]")
RE_ORDERED = re.compile(r"(\d{1,9})([.)])")
RE_ATX = re.compile(r"#{1,6}(?:[ \t]+|$)")
RE_FENCE = re.compile(r"`{3,}(?!.*`)|~{3,}")
# cmark-gfm's tasklist scanner, matched from the start of the line:
# spacechar* ("-"|"+"|"*"|[0-9]+.) spacechar+ ("[ ]"|"[x]") spacechar+.
RE_TASK = re.compile(r"[ \t\x0b\x0c]*(?:[-+*]|[0-9]+[^\n])[ \t\x0b\x0c]+\[[ xX]\][ \t\x0b\x0c]+")


def js_trim(s):
    """JavaScript's String.prototype.trim."""
    ws = lambda c: c in "\t\n\x0b\x0c\r﻿  " or unicodedata.category(c) == "Zs"
    a, b = 0, len(s)
    while a < b and ws(s[a]):
        a += 1
    while b > a and ws(s[b - 1]):
        b -= 1
    return a, b


@dataclass
class Block:
    type: str            # quote, list, item, heading, hr, code, html, paragraph
    marker: tuple = ()   # source indices of the block's own markup
    data: dict = field(default_factory=dict)
    children: list = field(default_factory=list)


class LineParser:
    """commonmark.js's Parser state while it reads the first line."""

    def __init__(self, line, gfm=False):
        self.ln = line.replace("\0", "�")
        self.gfm = gfm
        self.offset = self.column = 0
        self.partially_consumed_tab = False
        self.blank = False
        self.next_nonspace = self.next_nonspace_column = self.indent = 0
        self.indented = False

    def peek(self, pos):
        return self.ln[pos] if pos < len(self.ln) else None

    def find_next_nonspace(self):
        i, cols = self.offset, self.column
        while i < len(self.ln):
            c = self.ln[i]
            if c == " ":
                i, cols = i + 1, cols + 1
            elif c == "\t":
                i, cols = i + 1, cols + 4 - cols % 4
            else:
                break
        c = self.ln[i] if i < len(self.ln) else ""
        self.blank = c in ("\n", "\r", "")
        self.next_nonspace, self.next_nonspace_column = i, cols
        self.indent = cols - self.column
        self.indented = self.indent >= CODE_INDENT

    def advance_offset(self, count, columns):
        while count > 0 and self.offset < len(self.ln):
            if self.ln[self.offset] == "\t":
                to_tab = 4 - self.column % 4
                if columns:
                    self.partially_consumed_tab = to_tab > count
                    step = min(to_tab, count)
                    self.column += step
                    self.offset += 0 if self.partially_consumed_tab else 1
                    count -= step
                else:
                    self.partially_consumed_tab = False
                    self.column += to_tab
                    self.offset += 1
                    count -= 1
            else:
                self.partially_consumed_tab = False
                self.offset += 1
                self.column += 1
                count -= 1

    def advance_next_nonspace(self):
        self.offset, self.column = self.next_nonspace, self.next_nonspace_column
        self.partially_consumed_tab = False

    # block starts: None, or ("container" | "leaf", Block) -------------------

    def block_quote(self):
        if self.indented or self.peek(self.next_nonspace) != ">":
            return None
        self.advance_next_nonspace()
        at = self.offset
        self.advance_offset(1, False)
        if self.peek(self.offset) in (" ", "\t"):
            self.advance_offset(1, True)
        return "container", Block("quote", (at,))

    def atx_heading(self):
        m = RE_ATX.match(self.ln, self.next_nonspace)
        if self.indented or not m:
            return None
        self.advance_next_nonspace()
        level = len(m.group(0).strip(" \t"))
        opening = tuple(range(self.offset, self.offset + level))
        self.advance_offset(len(m.group(0)), False)
        start = self.offset
        rest = self.ln[start:]
        # Remove the closing sequence: the content ends before it.
        if re.fullmatch(r"[ \t]*#+[ \t]*", rest):
            end = start
        else:
            mm = re.search(r"[ \t]+#+[ \t]*$", rest)
            end = start + mm.start() if mm else len(self.ln)
        closing = tuple(i for i in range(end, len(self.ln)) if self.ln[i] == "#")
        self.offset = len(self.ln)
        return "leaf", Block("heading", opening + closing, {"level": level, "content": (start, end)})

    def fenced_code(self):
        m = RE_FENCE.match(self.ln, self.next_nonspace)
        if self.indented or not m:
            return None
        start = self.next_nonspace
        self.advance_next_nonspace()
        self.advance_offset(len(m.group(0)), False)
        a, b = js_trim(self.ln[self.offset:])
        info = cm.unescape_string(self.ln[self.offset:][a:b])
        return "leaf", Block("code", tuple(range(start, len(self.ln))), {"fenced": True, "info": info})

    def html_block(self):
        if self.indented or self.peek(self.next_nonspace) != "<":
            return None
        s = self.ln[self.next_nonspace:]
        for kind in range(1, 8):
            pattern = RE_HTML_BLOCK_7 if kind == 7 else RE_HTML_BLOCK_OPEN[kind]
            if pattern.match(s):
                # The spaces before it are part of the block.
                return "leaf", Block("html", tuple(range(self.next_nonspace, len(self.ln))))
        return None

    def thematic_break(self):
        if self.indented or not RE_THEMATIC_BREAK.match(self.ln, self.next_nonspace):
            return None
        start = self.next_nonspace
        self.offset = len(self.ln)
        return "leaf", Block("hr", tuple(range(start, len(self.ln))))     # drawn as a rule to the end

    def list_item(self):
        if self.indent >= 4:
            return None
        rest = self.ln[self.next_nonspace:]
        m = RE_BULLET.match(rest)
        if m:
            data = {"type": "bullet", "char": m.group(0)}
        else:
            m = RE_ORDERED.match(rest)
            if not m:
                return None
            data = {"type": "ordered", "start": int(m.group(1)), "delimiter": m.group(2)}
        nextc = self.peek(self.next_nonspace + len(m.group(0)))
        if nextc not in (None, "\t", " "):
            return None
        self.advance_next_nonspace()
        marker = tuple(range(self.offset, self.offset + len(m.group(0))))
        self.advance_offset(len(m.group(0)), True)
        spaces_start_col, spaces_start_offset = self.column, self.offset
        while True:
            self.advance_offset(1, True)
            nextc = self.peek(self.offset)
            if not (self.column - spaces_start_col < 5 and nextc in (" ", "\t")):
                break
        blank_item = self.peek(self.offset) is None
        spaces_after_marker = self.column - spaces_start_col
        if spaces_after_marker >= 5 or spaces_after_marker < 1 or blank_item:
            self.column, self.offset = spaces_start_col, spaces_start_offset
            if self.peek(self.offset) in (" ", "\t"):
                self.advance_offset(1, True)
        return "container", Block("item", marker, data)

    def indented_code(self):
        if not self.indented or self.blank:
            return None
        self.advance_offset(CODE_INDENT, True)
        return "leaf", Block("code", (), {"fenced": False})

    def parse(self):
        """The line's blocks, outermost first; the last is its leaf."""
        blocks, leaf = [], None
        while True:
            self.find_next_nonspace()
            r = None
            if self.indented or RE_MAYBE_SPECIAL.match(self.ln, self.next_nonspace):
                for start in (self.block_quote, self.atx_heading, self.fenced_code, self.html_block,
                              self.thematic_break, self.list_item, self.indented_code):
                    r = start()
                    if r is not None:
                        break
            if r is None:
                if self.gfm and blocks and blocks[-1].type == "item":
                    self.task(blocks[-1])
                self.advance_next_nonspace()
                break
            kind, block = r
            blocks.append(block)
            if kind == "leaf":
                leaf = block
                break
        if leaf is None:
            if self.offset < len(self.ln) and not self.blank:
                self.advance_next_nonspace()
                blocks.append(Block("paragraph", (), {"content": (self.offset, len(self.ln))}))
        elif leaf.type == "html" or (leaf.type == "code" and not leaf.data["fenced"]):
            # addLine: the rest of a tab the prefix took part of becomes spaces.
            pad = 0
            if self.partially_consumed_tab:
                pad = 4 - self.column % 4
                self.offset += 1
            leaf.data["content"] = (self.offset, len(self.ln))
            leaf.data["literal"] = " " * pad + self.ln[self.offset:]
        return blocks

    def task(self, item):
        """cmark-gfm's open_tasklist_item: tried where nothing else starts in
        a list item; its scanner reads from the start of the line, and any
        "[x]" anywhere in the line checks the box."""
        if not RE_TASK.match(self.ln) or self.ln[self.offset:self.offset + 1] != "[":
            return
        item.data["task"] = (self.offset, self.offset + 1, self.offset + 2)
        item.data["checked"] = "[x]" in self.ln or "[X]" in self.ln
        self.advance_offset(3, False)
        self.find_next_nonspace()


def parse(line, gfm=False):
    """(blocks, definition, inline): the line's blocks (outermost first), the
    span of a link reference definition it is, if any, and the parsed inline
    content (paragraph node and source offset) of its paragraph or heading."""
    p = LineParser(line, gfm)
    blocks = p.parse()
    leaf = blocks[-1] if blocks else None
    definition, inline = None, None
    if leaf is not None and leaf.type in ("paragraph", "heading"):
        start, end = leaf.data["content"]
        content = p.ln[start:end]
        if leaf.type == "paragraph":
            n = reference_definition(content)
            if n:
                definition = (start, start + n)
                if not RE_NON_SPACE.search(content[n:]):
                    blocks.pop()
                    leaf = None
                    return blocks, definition, None
                start += n
                content = p.ln[start:end]
        a, b = js_trim(content)
        node = cm.InlineParser(content[a:b], start + a, gfm=gfm).parse()
        inline = (node, start + a, start + b)
    return blocks, definition, inline


def reference_definition(s):
    """commonmark.js's parseReference on a paragraph's content (one line):
    the length of the link reference definition it starts with, or 0."""
    p = cm.InlineParser(s + "\n")
    m = re.match(r"\[(?:[^\\\[\]]|\\.){0,1000}\]", p.subject, re.S)
    if not m or len(m.group(0)) > 1001:
        return 0
    p.pos = m.end()
    if p.peek() != ":":
        return 0
    p.pos += 1
    p.spnl()
    if p.parse_link_destination() is None:
        return 0
    before_title = p.pos
    p.spnl()
    title = p.parse_link_title() if p.pos != before_title else None
    if title is None:
        p.pos = before_title
    at_end = re.compile(r" *(?:\n|$)")
    if not at_end.match(p.subject, p.pos):
        if title is None:
            return 0
        p.pos = before_title
        if not at_end.match(p.subject, p.pos):
            return 0
    label = m.group(0)[1:-1]
    a, b = js_trim(label)
    if not re.sub(r"[ \t\r\n]+", " ", label[a:b]):
        return 0
    return min(p.pos, len(s))


def to_html(line, gfm=False):
    """The HTML commonmark.js (or, with `gfm`, cmark-gfm) writes for the line."""
    blocks, _, inline = parse(line, gfm)
    out = []
    last = ["\n"]

    def lit(s):
        out.append(s)
        last[0] = s

    def cr():
        if last[0] != "\n":
            lit("\n")

    def render(i, tight):
        if i == len(blocks):
            return
        b = blocks[i]
        if b.type == "quote":
            cr(), lit("<blockquote>"), cr()
            render(i + 1, False)
            cr(), lit("</blockquote>"), cr()
        elif b.type == "item":
            tag = "ul" if b.data["type"] == "bullet" else "ol"
            start = b.data.get("start")
            cr(), lit(f'<{tag} start="{start}">' if start not in (None, 1) else f"<{tag}>"), cr()
            lit("<li>")
            if "task" in b.data:
                lit('<input type="checkbox" checked="" disabled="" /> ' if b.data["checked"]
                    else '<input type="checkbox" disabled="" /> ')
            render(i + 1, True)
            lit("</li>"), cr()
            cr(), lit(f"</{tag}>"), cr()
        elif b.type == "heading":
            level = b.data["level"]
            cr(), lit(f"<h{level}>"), lit(cm.render_html(inline[0]) if inline else ""), lit(f"</h{level}>"), cr()
        elif b.type == "hr":
            cr(), lit("<hr />"), cr()
        elif b.type == "code":
            info = [w for w in re.split("[" + _JS_SPACE + "]+", b.data.get("info", "")) if w]
            cls = f' class="language-{cm.escape_xml(info[0])}"' if info and not info[0].startswith("language-") \
                else (f' class="{cm.escape_xml(info[0])}"' if info else "")
            literal = "" if b.data["fenced"] else b.data["literal"] + "\n"
            cr(), lit(f"<pre><code{cls}>"), lit(cm.escape_xml(literal)), lit("</code></pre>"), cr()
        elif b.type == "html":
            cr(), lit(b.data["literal"]), cr()
        elif b.type == "paragraph":
            body = cm.render_html(inline[0])
            if tight:
                lit(body)
            else:
                cr(), lit("<p>"), lit(body), lit("</p>"), cr()

    render(0, False)
    return "".join(out)


def roles(line, gfm=True, code_padding=False):
    """The cm_inline.Role of each character of `line` read as a document."""
    blocks, definition, inline = parse(line, gfm)
    Role = cm.Role
    out = [Role("text")] * len(line)
    for b in blocks:
        if b.type == "quote":
            out[b.marker[0]] = Role("quote")
        elif b.type == "item":
            if b.data["type"] == "bullet":
                out[b.marker[0]] = Role("bullet")
            if "task" in b.data:
                left, mid, right = b.data["task"]
                out[left] = out[right] = cm.HIDDEN
                out[mid] = Role("checked" if b.data["checked"] else "box")
        elif b.type in ("heading", "html") or (b.type == "code" and b.data["fenced"]):
            for i in b.marker:
                out[i] = Role("dim")
        elif b.type == "hr":
            for i in b.marker:
                out[i] = Role("rule")
        elif b.type == "code":
            for i in range(*b.data["content"]):
                out[i] = Role("text", frozenset({"code"}))
    if definition:                      # dimmed to the end of the line
        for i in range(definition[0], len(line)):
            out[i] = Role("dim")
    if inline:
        node, a, z = inline
        style = frozenset()
        if blocks[-1].type == "heading":         # a heading's line is its text's style throughout
            style = frozenset({"heading"})
            heading = blocks[-1]
            for i in range(heading.marker[heading.data["level"] - 1] + 1, len(line)):    # after the opening #s
                if i not in heading.marker:
                    out[i] = Role("text", style)
        for i in range(a, z):
            out[i] = cm.HIDDEN
        cm.assign(node, out, style, code_padding)
    return out
