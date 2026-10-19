"""Compile a Markdown font: GitHub Flavored Markdown, line by line, rendered
by the shaper.

    python markdown/mdfont.py --base fonts/JetBrainsMono-Regular.ttf \\
        --bold ...-Bold.ttf --italic ...-Italic.ttf --bold-italic ...-BoldItalic.ttf --out build

The lookups run in two groups. Right to left, what lies ahead of each
character: which kind of raw HTML or autolink starts at each `<`, escapes
and the shape of runs (from small windows), whether a code span's closing
backticks follow, whether a link destination follows a `]`, and what the
line's block markup needs to know (a thematic break, a fence, a task box).
Then left to right: the line's block markup (blocks.py), where bare URLs
start and end; the scan that settles code spans, raw HTML, autolinks, bare
URLs and link destinations; rounds of matching for brackets and for
emphasis and strikethrough (matched pairs drop out of the sequence the next
round sees, so a pair is always adjacent there); emails; the style after
each marker; entity references, as ligatures; the paint that gives every
glyph its final glyph; and the strikethrough's line. build() runs the
stages in order (STAGES). Every bound is a constant below.
"""

import argparse
import html.entities
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import blocks  # noqa: E402
import cm_inline  # noqa: E402
import fontbuild as fb  # noqa: E402
import gfm  # noqa: E402
import htmlauto  # noqa: E402
import passes  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402
from fontTools.ttLib.tables import otTables as ot  # noqa: E402
import tails  # noqa: E402

MAX_BACKSLASHES = 8   # a longer run of backslashes counts as this many
MAX_TICKS = 8         # backtick runs up to this long open and close code spans
MAX_DELIMS = 6        # `*`/`_` runs up to this long are emphasis delimiters
ROUNDS = 6            # rounds of emphasis matching: the nesting depth handled
SEARCH = 3            # unmatchable openers a closer looks past for its opener
INNER_ROUNDS = 3      # rounds of emphasis matching inside link and image text
MAX_DEPTH = 3         # em and strong nesting depths counted
MAX_BRACKETS = 3      # open brackets counted at once, and rounds of bracket matching
MAX_LINKS_INSIDE = 3  # links inside one pair of brackets, for the no-links-in-links rule
LEVELS = 3            # emphasis inside links and images, nested this deep
PARENS = 3            # parentheses nested in a link destination
URL_PARENS = 3        # how far a bare URL's `(` and `)` are counted out of balance
CODE_SCALE = 0.9      # code's size in the proportional edition (GitHub's is 85% of a system font)

STRUCTURAL = "\\`*_~[]!()\"'<>&"
TAIL = "()\"'<>] \t"          # what the link destination automaton reads
ASCII_PUNCT = cm_inline.ASCII_PUNCTUATION
JS_SPACE = "\t\n\x0b\x0c\r \u00a0\u1680" + "".join(map(chr, range(0x2000, 0x200B))) + "\u2028\u2029\u202f\u205f\u3000\ufeff"
# HTML block starts of type 1 and 6 (cm_block.RE_HTML_BLOCK_OPEN).
HTML_BLOCK_NAMES = {1: ("script", "pre", "textarea", "style"), 6: (
    "address", "article", "aside", "base", "basefont", "blockquote", "body", "caption", "center", "col", "colgroup",
    "dd", "details", "dialog", "dir", "div", "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form", "frame",
    "frameset", "h1", "h2", "h3", "h4", "h5", "h6", "head", "header", "hr", "html", "iframe", "legend", "li", "link",
    "main", "menu", "menuitem", "nav", "noframes", "ol", "optgroup", "option", "p", "param", "section", "search",
    "summary", "table", "tbody", "td", "tfoot", "th", "thead", "title", "tr", "track", "ul")}
# Leaf blocks that make a whole line inert to inline syntax.
DEAD_LINES = ("code", "fence", "html", "def", "hr")


def _bk(kind):
    """The block marks at the end of a kind: ("bk", names)."""
    return kind[-1][1] if kind and isinstance(kind[-1], tuple) and kind[-1][:1] == ("bk",) else frozenset()


def _with_bk(kind, names):
    core = kind[:-1] if _bk(kind) else kind
    names = _bk(kind) | frozenset(names)
    return core + (("bk", names),) if names else core


def flanking(c, before, after):
    """(can open, can close) for a run of `c` between character classes."""
    bw, bp = before in "WS", before == "P"
    aw, ap = after == "W", after == "P"
    left = not aw and (not ap or bw or bp)
    right = not bw and (not bp or aw or ap)
    if c == "_":
        return left and (not right or bp), right and (not left or ap)
    return left, right


class MarkdownFont:
    def __init__(self, base, bold, italic, bold_italic, mono=None):
        self.b = fb.FontBuilder(base)
        if 9 not in self.b.font.getBestCmap():
            self.b.add_base_glyph("tab", 9, self.b.advance(self.b.font.getBestCmap()[32]))
        self.b.import_style("b", bold)
        self.b.import_style("i", italic, slant=9)
        self.b.import_style("bi", bold_italic, fallback="b", slant=9)
        cmap = self.b.font.getBestCmap()
        self.chars = {}
        for cp, g in sorted(cmap.items()):
            self.chars.setdefault(g, chr(cp))
        self.text = sorted(self.chars, key=self.b.gid)      # every glyph text can hold
        if mono:    # code in a monospaced family's four styles, as GitHub draws it
            for suffix, path in zip(("m", "mb", "mi", "mbi"), mono):
                self.b.import_by_char(suffix, path, self.text, CODE_SCALE, fallback=suffix[1:])
        self.b.add_color_styles(self.text, code="m" if mono else "")
        self.pl = passes.Pipeline(self.b)
        self.g = {c: cmap[ord(c)] for c in STRUCTURAL + " \t" if ord(c) in cmap}
        self.alive = set(self.text)     # glyphs that can be in the buffer at this point
        self.url_base = self.b.empty("_url", 0, gdef_class=3)    # the base of a bare URL's markers
        self.styled_key = {}
        for g in self.text:
            for s in [""] + list(fb.OUTLINE_STYLES) + list(fb.COLOR_STYLES):
                self.styled_key[fb.styled(g, s)] = ("styled", s)
        self.pl.key = lambda o: self.styled_key.get(o) or self.pl.kind_of(o) or o

    # glyph sets ---------------------------------------------------------

    def char(self, g):
        return self.chars.get(self.pl.base_of(g), "\uFFFF")

    def flank_class(self, g):
        c = self.char(g)
        if cm_inline.is_unicode_whitespace(c):
            return "W"
        return "P" if cm_inline.is_unicode_punctuation(c) else "O"

    def kinded(self, test):
        return {g for g in self.alive if self.pl.kind_of(g) and test(self.pl.kind_of(g))}

    def replace(self, pairs):
        """Record that a lookup turned some glyphs into others."""
        pairs = list(pairs)
        self.alive = (self.alive - {a for a, b in pairs if a != b}) | {b for _, b in pairs}

    def reverse(self, rules, sees=None):
        """Add reverse chaining rules (mapping, backtrack, lookahead). A glyph
        stops being possible only where a rule without context replaces it."""
        self.pl.reverse(rules, sees)
        always = {a for m, back, ahead in rules if not back and not ahead for a, b in m.items() if a != b}
        self.alive = (self.alive - always) | {b for m, _, _ in rules for b in m.values()}

    def transduce(self, direction, inputs, step, init, **kw):
        out, states = getattr(self.pl, direction)(inputs, step, init, **kw)
        self.alive = (self.alive - set(inputs)) | set(out.values()) | self.pl.unchanged
        return out, states

    def strip_state(self, outputs):
        """Map the outputs of a pass to their kinds without the pass's state."""
        strip = {o: self.pl.var(o, self.pl.kind_of(o)[:-1]) if self.pl.kind_of(o)[:-1] else self.pl.base_of(o)
                 for o in set(outputs)}
        self.pl.single(strip)
        self.replace(strip.items())

    def temporary(self, direction, inputs, step, init):
        """A pass whose outputs (kind + ("s", state)) are stripped right after
        it, so they can be pool glyphs shared with every other such pass."""
        self.pl.begin_temp()
        out, states = self.transduce(direction, inputs, step, init)
        self.strip_state(out.values())
        self.pl.end_temp()
        return out, states

    # right to left ------------------------------------------------------

    def html_validity(self):
        """Which kind of autolink or raw HTML starts at each `<`, if any: a
        right-to-left pass per kind over the ASCII characters, on the raw
        text before anything else gives them variants. Only characters with
        a `>` somewhere after them can be part of either, so only those take
        part: they become ("hx", nb), nb noting non-ASCII text before them,
        and `<` ("hx", nb, kinds found so far). URI autolinks are checked from
        both ends instead (uri_autolinks). `<` ends up ("lt", kind)."""
        pl, lt, gt = self.pl, self.g["<"], self.g[">"]
        ascii_ = {g for g in self.text if " " <= self.char(g) <= "~" or self.char(g) == "\t"}
        nonascii = set(self.text) - ascii_

        # ASCII characters become marks, so that passes can skip the rest.
        a0 = {g: pl.var(g, ("a0",)) for g in ascii_}
        pl.single(a0)
        self.replace(a0.items())
        # A `>` with only whitespace after it may end a tag alone on its line
        # (an HTML block of type 7).
        spaces = {g for g in self.alive if self.char(g) in JS_SPACE}

        def eol(R, g):
            if self.char(g) == ">":
                return (("a0", "eol", ("s", "g")), "g") if R in (False, "w") else None
            return (("a0", ("s", "w")) if pl.kind_of(g) else ("s", "w"), "w") if R in (False, "w") else None
        self.pl.begin_temp()
        out, _ = self.transduce("rtl", {g: g for g in spaces | {a0[gt]}}, eol, False, skeleton=False,
                                anchored=True)
        self.strip_state(out.values())
        self.pl.end_temp()
        a0 = {g: g for g in self.kinded(lambda k: k[0] == "a0")}

        def before_gt(seen, g):
            new = seen or pl.base_of(g) == gt
            eol = ("eol",) if "eol" in pl.kind_of(g) else ()
            return (("hx0",) + eol + (("s", new),), new) if new else None
        self.pl.begin_temp()
        out, _ = self.transduce("rtl", {g: g for g in a0.values()}, before_gt, False)
        marked = set(out.values())
        note = {o: (lambda nb, o=o: pl.var(pl.base_of(o), ("hx", nb) + ((frozenset(),) if pl.base_of(o) == lt
                                                                        else ("eol",) if "eol" in pl.kind_of(o)
                                                                        else ()))) for o in marked}
        self.reverse([({o: f(True) for o, f in note.items()}, [nonascii], ()),
                      ({o: f(False) for o, f in note.items()}, (), ())])
        self.pl.end_temp()
        found_k = lambda k: k[-1] if k and isinstance(k[-1], frozenset) else frozenset()
        for name, step in htmlauto.KINDS + htmlauto.LINE_KINDS:
            if name == "uri":
                self.uri_autolinks()
                continue
            auto = htmlauto.Backward(step)

            def back(R, sym, auto=auto, name=name, line=name.endswith("7")):
                ch, kind = sym
                if line and ch == ">" and "eol" not in kind:
                    ch = htmlauto.GT_NO
                new = auto.back(R, ch)
                if kind[1]:
                    new = auto.back(new, htmlauto.NONASCII)
                out = kind[:2] + (found_k(kind) | {name},) if ch == "<" and "<" in R else kind
                return None if not new and out == kind else (out + (("s", new),), new)
            self.temporary("rtl", {g: (self.char(g), pl.kind_of(g))
                                   for g in self.kinded(lambda k: k[0] == "hx")}, back, frozenset())
        order = [name for name, _ in htmlauto.KINDS]
        final = {g: pl.base_of(g) for g in a0.values()}
        for g in self.kinded(lambda k: k[0] == "hx"):
            found = found_k(pl.kind_of(g)) if pl.base_of(g) == lt else frozenset()
            kinds = [n for n in order if n in found]
            # open7 and close7: also a whole line's HTML block.
            x = kinds[0] + "7" if kinds and kinds[0] + "7" in found else kinds[0] if kinds else None
            final[g] = pl.var(lt, ("lt", x)) if x else pl.base_of(g)
        pl.single(final)
        self.replace(final.items())

    def uri_autolinks(self):
        """A `:` learns whether the next `>`, `<`, space or tab after it is a
        `>`; then rules at `<` read a scheme of 2 to 32 characters up to such
        a `:` (the kinds `<` has found gain "uri")."""
        pl, lt = self.pl, self.g["<"]
        hx = self.kinded(lambda k: k[0] == "hx")
        skel = {g for g in hx if self.char(g) in "<> \t:"}

        def body(ok, sym):
            ch, kind = sym
            new = True if ch == ">" else False if ch in "< \t" else ok
            out = kind[:2] + (("uri", ok),) if ch == ":" else kind
            return out + (("s", new),), new
        self.pl.begin_temp()
        out, _ = self.transduce("rtl", {g: (self.char(g), pl.kind_of(g)) for g in skel}, body, False)
        self.strip_state(out.values())
        self.pl.end_temp()
        hx = self.kinded(lambda k: k[0] == "hx")
        of = lambda chars: {g for g in hx if self.char(g) in chars}
        letters = of(set(htmlauto.LETTER))
        scheme = of(set(htmlauto.ALNUM) | set("+.-"))
        colon = {g for g in hx if self.char(g) == ":" and pl.kind_of(g)[2:] == (("uri", True),)}
        more = {g: pl.var(lt, pl.kind_of(g)[:2] + (pl.kind_of(g)[2] | {"uri"},)) for g in of({"<"})}
        self.reverse([(more, (), [letters] + [scheme] * (k - 1) + [colon]) for k in range(2, 33)])
        # The `:` notes go back to plain `:` with the rest of the ("hx", ...) glyphs.

    def gt_ends(self):
        """Each `>` notes what precedes it, for constructs that end at the
        first "-->", "?>" or "]]>": ("gt", "--" | "?" | "]]" | None)."""
        pl, gt = self.pl, self.g[">"]
        of = lambda c: {g for g in self.alive if self.char(g) == c}
        mk = lambda a: {gt: pl.var(gt, ("gt", a))}
        self.reverse([(mk("--"), [of("-"), of("-")], ()), (mk(None), [of("<"), of("?")], ()),
                      (mk("?"), [of("?")], ()), (mk("]]"), [of("]"), of("]")], ()), (mk(None), (), ())])

    def escapes(self):
        """A character is escaped after an odd run of backslashes: a
        structural character's glyph g becomes var(g, kind + ("esc",));
        backslashes become ("bs", "esc"), ("bs", "escaping") before ASCII
        punctuation, or ("bs", "act")."""
        pl, bs = self.pl, self.g["\\"]
        structural = {g for g in self.alive if self.char(g) in STRUCTURAL and self.char(g) != "\\"}
        esc = {g: pl.var(g, pl.kind_of(g) + ("esc",)) for g in structural}
        same = {g: g for g in structural}
        punct = {g for g in self.alive if self.char(g) in ASCII_PUNCT}
        after = punct | set(esc.values()) | {pl.var(bs, ("bs", "esc"))}
        rules = []
        for k in range(MAX_BACKSLASHES, -1, -1):
            if k % 2:
                rules.append(({**esc, bs: pl.var(bs, ("bs", "esc"))}, [{bs}] * k, ()))
            else:
                rules.append(({**same, bs: pl.var(bs, ("bs", "escaping"))}, [{bs}] * k, [after]))
                rules.append(({**same, bs: pl.var(bs, ("bs", "act"))}, [{bs}] * k, ()))
        self.reverse(rules)

    def backtick_runs(self):
        """Each backtick learns its run: ("bt", i, n, fe), i its index, n the
        run length (MAX_TICKS + 1 for anything longer), fe whether the run's
        first backtick is escaped."""
        pl, bt = self.pl, self.g["`"]
        btesc = pl.var(bt, ("esc",))
        cap = MAX_TICKS + 1
        js = {j: pl.var(bt, ("btj", j)) for j in range(cap + 1)}
        jesc = {j: pl.var(bt, ("btj", j, "esc")) for j in range(cap + 1)}  # only a run's first can be
        rules = [({bt: js[min(j + 1, cap)], btesc: jesc[min(j + 1, cap)]}, (), [{js[j]}])
                 for j in range(cap + 1)]
        rules.append(({bt: js[0], btesc: jesc[0]}, (), ()))
        self.reverse(rules)
        rules = []
        for i in range(cap, 0, -1):
            for fe in (True, False):
                m = {js[j]: pl.var(bt, ("bt", i, min(i + j + 1, cap), fe)) for j in range(cap + 1)}
                first = set(jesc.values()) if fe else set(js.values())
                rules.append((m, [first] + [set(js.values())] * (i - 1), ()))
        m = {js[j]: pl.var(bt, ("bt", 0, min(j + 1, cap), False)) for j in range(cap + 1)}
        m.update({jesc[j]: pl.var(bt, ("bt", 0, min(j + 1, cap), True)) for j in range(cap + 1)})
        rules.append((m, (), ()))
        self.reverse(rules)

    def code_closers(self):
        """For each length m, a right-to-left pass gives every run that could
        open a code span of length m ("v", bit): whether a run of exactly m
        backticks follows somewhere to its right."""
        for m in range(1, MAX_TICKS + 1):
            ticks = self.kinded(lambda k: k[0] == "bt")

            def step(seen, kind, m=m):
                _, i, n, fe = kind[:4]
                opener = n <= MAX_TICKS and ((i == 0 and not fe and n == m) or (i == 1 and fe and n == m + 1))
                new = seen or (i == 0 and n == m)
                out = kind[:4] + (("v", seen),) if opener else kind
                return None if not new and out == kind else (out + (("s", new),), new)
            self.temporary("rtl", {g: self.pl.kind_of(g) for g in ticks}, step, False)

    def delimiter_runs(self):
        """Each `*` and `_` learns its run and flanking: ("dl", i, n, open,
        close); n = MAX_DELIMS + 1 for longer runs, which never delimit. So
        does each `~` (GFM's strikethrough): ("tl", i, n, open, close, b, a),
        with the classes b and a of the characters around its run and n = 3
        for runs of 3 or more. As in cmark-gfm, flanking looks past tildes:
        next to a `~`, the character beyond its run counts."""
        pl = self.pl

        def side(g, after):
            k = pl.kind_of(g)
            if k[:1] == ("tl",):
                cls = k[6 if after else 5]
                return "W" if cls == "S" else cls
            return self.flank_class(g)
        for c in "~*_":
            cap, tag = (3, "tl") if c == "~" else (MAX_DELIMS + 1, "dl")
            d = self.g[c]
            others = {g for g in self.alive if g != d}
            js = {(j, a): pl.var(d, (tag + "j", j, a)) for j in range(cap + 1) for a in "WPO"}
            rules = [({d: js[(min(j + 1, cap), a)]}, (), [{js[(j, a)]}]) for (j, a) in js]
            for a in "WPO":
                rules.append(({d: js[(0, a)]}, (), [{g for g in others if side(g, True) == a}]))
            rules.append(({d: js[(0, "W")]}, (), ()))
            self.reverse(rules)
            rules = []
            for i in range(cap, -1, -1):
                for b in ("WPOS" if i < cap else "S"):
                    m = {js[(j, a)]: pl.var(d, (tag, i, min(i + j + 1, cap)) + flanking(c, b, a)
                                            + ((b, a) if c == "~" else ())) for (j, a) in js}
                    back = [set(js.values())] * i
                    if b != "S":
                        back = [{g for g in others if side(g, False) == b}] + back
                    rules.append((m, back, ()))
            self.reverse(rules)

    def brackets_and_tails(self):
        """Unescaped `[` become ("br",), or ("ip",) after an image's `!`, which
        becomes ("img",). The characters the link destination automaton reads
        become ("tk", po, esc, x): po, an unread character precedes them; esc,
        escaped; x, the kind of a `<`, what precedes a `>` (gt_ends), or (for
        `]`, from tail_validity) whether a link destination follows."""
        pl = self.pl
        lb, bang = self.g["["], self.g["!"]
        ip, img, br = pl.var(lb, ("ip",)), pl.var(bang, ("img",)), pl.var(lb, ("br",))
        self.reverse([({lb: ip}, [{bang}], ()), ({lb: br}, (), ()), ({bang: img}, (), [{ip}])])
        amp = self.g["&"]
        pl.single({amp: pl.var(amp, ("amp",))})
        self.replace([(amp, pl.var(amp, ("amp",)))])
        chars = {g for g in self.alive if self.char(g) in TAIL}
        # Spaces and tabs only matter to a destination if a `)` follows them;
        # only those take part (most text has none, and stays untouched). To
        # find them, spaces, tabs and `)` become marks ("sp",) for a moment.
        sp = {g: pl.var(g, ("sp",) + pl.kind_of(g)) for g in chars if self.char(g) in " \t)"}
        pl.single(sp)

        def before_paren(seen, g):
            new = seen or self.char(g) == ")"
            return (pl.kind_of(g) + (("s", new),), new) if new else None
        pl.begin_temp()
        out, _ = self.pl.rtl({g: g for g in sp.values()}, before_paren, False)
        marked = set(out.values())
        was = {g: pl.kind_of(g)[1:] for g in sp.values()}          # what each ("sp", ...) glyph was
        was.update({o: pl.kind_of(o)[1:-1] for o in marked})
        read = {g for g in chars if "esc" not in pl.kind_of(g)} | set(sp.values()) | marked
        anything = (set(self.alive) - read) | {g for g in sp if g not in read}
        ins = {g for g in chars if self.char(g) not in " \t)"} | marked
        base = lambda g: pl.base_of(g)

        def tk(g, po):
            k = was[g] if g in was else pl.kind_of(g)
            x = k[1] if k[:1] in (("lt",), ("gt",)) else None
            return pl.var(base(g), ("tk", po, "esc" in k, x))
        back = {g: (pl.var(base(g), was[g]) if was[g] else base(g)) for g in sp.values()}
        self.pl.reverse([({g: tk(g, False) for g in ins}, [read], ()),
                         ({g: tk(g, True) for g in ins}, [anything], ()),
                         ({g: tk(g, False) for g in ins}, (), ())])
        pl.single(back)    # spaces and `)` that no `)` follows: back to what they were
        outs = {tk(g, po) for g in ins for po in (False, True)}
        pl.end_temp()
        self.alive = (self.alive - ins) | outs

    def tail_validity(self):
        """Eight right-to-left passes, one per form of destination and title,
        each telling every `]` whether a link destination of that form starts
        right after it (its x)."""
        pl, rb = self.pl, self.g["]"]
        fix = {g: pl.var(g, pl.kind_of(g)[:3] + (False,))
               for g in self.kinded(lambda k: k[0] == "tk") if pl.base_of(g) == rb}
        pl.single(fix)
        self.replace(fix.items())
        for form in tails.FORMS:
            auto = tails.Automaton(form, PARENS)
            inputs = {g: (self.char(g), pl.kind_of(g)) for g in self.kinded(lambda k: k[0] == "tk")}

            def step(R, sym, auto=auto):
                ch, kind = sym
                _, po, esc, x = kind
                new = auto.back(R, "O" if esc or ch == "]" else ch)
                if po:
                    new = auto.back(new, "O")
                out = kind[:3] + (x or auto.start in R,) if ch == "]" and not esc else kind
                return None if not new and out == kind else (out + (("s", new),), new)
            self.temporary("rtl", inputs, step, frozenset())

    # line blocks, right to left ----------------------------------------

    def bk(self, g):
        return _bk(self.pl.kind_of(g))

    def with_marks(self, g, names):
        return self.pl.var(self.pl.base_of(g), _with_bk(self.pl.kind_of(g), names))

    def glyphs_of(self, cs, test=None):
        return {g for g in self.alive if self.char(g) in cs and (test is None or test(self.pl.kind_of(g)))}

    def mark_ahead(self, glyphs, name, ahead):
        """Mark the glyphs followed by one of `ahead`, or by the end of the line."""
        m = {g: self.with_marks(g, {name}) for g in glyphs}
        self.reverse([(m, (), [ahead]), ({g: g for g in glyphs}, (), [set(self.b.order)]), (m, (), ())])

    def mark_pass(self, glyphs, step, skeleton=False, init="eol"):
        """A right-to-left pass over `glyphs`, anchored unless `skeleton`:
        step(state, (char, kind)) -> (names to mark, new state), or None.
        The state goes once the pass is done; the marks stay."""
        def wrapped(R, sym):
            r = step(R, sym)
            if r is None:
                return None
            names, new = r
            return _with_bk(sym[1], names) + (("s", new),), new
        self.pl.begin_temp()
        out, _ = self.transduce("rtl", {g: (self.char(g), self.pl.kind_of(g)) for g in glyphs}, wrapped, init,
                                skeleton=skeleton, anchored=not skeleton)
        self.strip_state(out.values())
        self.pl.end_temp()

    def block_marks(self):
        """What the line-start pass (block_prefix) needs to know about what
        follows a character, as marks at the end of its kind (blocks.marks
        computes the same from text)."""
        other = passes.OTHER
        ws = lambda: self.glyphs_of(" \t")
        self.mark_ahead(self.glyphs_of("-+.)#") | self.glyphs_of("*", lambda k: k[:2] == ("dl", 0)), "wsnext", ws())

        def blank(R, sym):                    # only spaces and tabs after this one
            return ({"blank"}, "b") if R in ("eol", "b") else None
        self.mark_pass(ws(), blank)

        # A thematic break from here: only c, spaces and tabs, 3 or more c.
        def hr(R, sym):
            ch, kind = sym
            if ch in " \t":
                return (set(), ("e",) if R == "eol" else R) if R != other else None
            if R in ("eol", ("e",)):
                n = 1
            elif R[0] == ch:
                n = min(R[1] + 1, 3)
            else:
                return None
            return ({"hr"} if n == 3 else set()), (ch, n)
        self.mark_pass(ws() | self.glyphs_of("-") | self.glyphs_of("*_", lambda k: k[:1] == ("dl",)), hr)

        # A heading's opening #s: at most 6, then a space, a tab or the end.
        def atx(R, sym):
            ch, kind = sym
            n, after = (R[0] + 1, R[1]) if R not in ("eol", other) else (1, "wsnext" in _bk(kind))
            n = min(n, 7)
            return ({"atx"} if n <= 6 and after else set()), (n, after)
        self.mark_pass(self.glyphs_of("#"), atx)

        # A closing sequence: the last run of #s, after a space or a tab and
        # with only spaces and tabs after it.
        def tail(R, sym):
            ch, kind = sym
            if ch == "#":
                return ({"tail"}, "h") if R in ("eol", "w", "h") else None
            if R in ("eol", "w"):
                return set(), "w"
            return (set(), "p") if R in ("h", "p") else None
        self.mark_pass(ws() | self.glyphs_of("#"), tail)
        tails = self.glyphs_of("#", lambda k: "tail" in _bk(k))
        hashes = self.glyphs_of("#")
        close = {g: self.with_marks(g, {"close"}) for g in tails}
        self.reverse([(close, [ws()] + [hashes] * j, ()) for j in range(8)])

        # Code fences: 3 or more backticks with no other backtick after them
        # on the line, or 3 or more tildes.
        def ticks(R, sym):
            ch, kind = sym
            _, i, n = kind[:3]
            fence = i == 0 and 3 <= n <= MAX_TICKS and R == n - 1
            return ({"fence"} if fence else set()), min(R + 1, MAX_TICKS + 2)
        self.mark_pass(self.kinded(lambda k: k[0] == "bt"), ticks, skeleton=True, init=0)

        fence = {g: self.with_marks(g, {"fence"})
                 for g in self.glyphs_of("~", lambda k: k[:1] == ("tl",) and k[1] == 0 and k[2] == 3)}
        self.pl.single(fence)
        self.replace(fence.items())

        # HTML blocks: type 7 (a whole tag alone on its line) was found with
        # the other HTML; types 1 to 6 start with set text.
        lts = self.glyphs_of("<", lambda k: k[:1] == ("tk",) and not k[2])
        seven = {g: self.with_marks(g, {"html"}) for g in lts if self.pl.kind_of(g)[3] in ("open7", "close7")}
        self.pl.single(seven)
        self.replace(seven.items())
        lts = self.glyphs_of("<", lambda k: k[:1] == ("tk",) and not k[2])
        html = {g: self.with_marks(g, {"html"}) for g in lts}
        keep = {g: g for g in lts}
        seq = lambda text: [self.glyphs_of({c.lower(), c.upper()}) for c in text]
        rules = [(html, (), seq(start)) for start in ("!--", "?", "![CDATA[")]
        rules.append((html, (), [self.glyphs_of("!"), self.glyphs_of(set(htmlauto.LETTER))]))
        names = [(n, k) for k, ns in HTML_BLOCK_NAMES.items() for n in ns]
        for name, k in sorted(names, key=lambda nk: (-len(nk[0]), nk)):
            for slash in ("", "/") if k == 6 else ("",):
                body = seq(slash + name)
                rules += [(html, (), body + [self.glyphs_of(JS_SPACE)]), (html, (), body + [self.glyphs_of(">")])]
                if k == 6:
                    rules.append((html, (), body + [self.glyphs_of("/"), self.glyphs_of(">")]))
                rules += [(keep, (), body + [set(self.b.order)]), (html, (), body)]
        self.reverse(rules)

        # Task boxes, and whether an [x] comes later (any checks the box).
        boxed = lambda: self.glyphs_of("[")
        task = {g: self.with_marks(g, {"task"}) for g in boxed()}
        self.reverse([(task, (), [self.glyphs_of(" xX"), self.glyphs_of("]"), self.glyphs_of(" \t\x0b\x0c")])])
        x = {g: self.with_marks(g, {"x"}) for g in boxed()}
        self.reverse([(x, (), [self.glyphs_of("xX"), self.glyphs_of("]")])])

        def checked(R, sym):
            seen = R or "x" in _bk(sym[1])
            return ({"xbox"} if seen else set()), seen
        self.mark_pass(boxed(), checked, skeleton=True, init=False)

        # Ordered list markers: up to 9 digits, `.` or `)`, then a space, a tab
        # or the end.
        def ordinal(R, sym):
            ch, kind = sym
            if ch in ".)":
                return (set(), "d") if "wsnext" in _bk(kind) else None
            n = 1 if R == "d" else min(R + 1, 10) if isinstance(R, int) else None
            return None if n is None else (({"ordinal"} if n <= 9 else set()), n)
        self.mark_pass(self.glyphs_of("0123456789.)"), ordinal)

    def block_prefix(self):
        """The line's block markup, read from its start (blocks.step): each
        character the automaton reads becomes ("bp", role). Then the marks
        go, except that a heading's closing #s keep ("hc",)."""
        inputs = {g: (self.char(g), self.pl.kind_of(g)) for g in self.alive if self.char(g) in blocks.PREFIX}

        def step(state, sym):
            if state == passes.OTHER:
                return None
            r = blocks.step(state, sym[0], _bk(sym[1]))
            return None if r is None else (("bp", r[0], ("s", r[1])), r[1])
        self.pl.begin_temp()
        out, _ = self.transduce("ltr", inputs, step, blocks.INIT, skeleton=False, anchored=True)
        self.strip_state(out.values())
        self.pl.end_temp()
        strip = {}
        for g in self.alive:
            names = self.bk(g)
            if names:
                core = self.pl.kind_of(g)[:-1] + (("hc",) if "close" in names else ())
                strip[g] = self.pl.var(g, core) if core else self.pl.base_of(g)
        self.pl.single(strip)
        self.replace(strip.items())

    # bare URLs (GitHub's extended autolinks) -----------------------------

    def url_starts(self):
        """Where a www. or http://, https:// or ftp:// link can start (gfm.py
        has cmark-gfm's rules): its first letter becomes ("us", form), and a
        hidden marker, ("um", "cand"), goes in before it. A right-to-left
        pass first reads the domain that starts at each character: as
        cmark-gfm checks it, it is invalid with an `_` in its last two
        labels (a domain with more than 10 dots is a bound), and the line's
        last character never counts."""
        pl, b = self.pl, self.b
        ascii_ = {g for g in self.alive if self.char(g) < "\x80"}
        dom = {g for g in ascii_ if self.char(g) in htmlauto.ALNUM or self.char(g) in "-_."}
        ends = {g for g in self.alive if self.char(g) in JS_SPACE or self.char(g) == "#" and pl.kind_of(g)[-1:] == ("hc",)}

        def step(R, sym):
            ch, kind = sym
            if R in ("eol", "eolw"):     # trailing whitespace and a closing #s: not the inline text
                new = "eolw" if ch in JS_SPACE or kind[-1:] == ("hc",) else "x"
            else:
                r = ("F", 0) if R in (passes.OTHER, "x") else R
                if ch in JS_SPACE or ch == "#":
                    new = ("F", 0)
                elif ch == "_":
                    new = "T" if r != "T" and r[1] < 2 else r
                elif ch == ".":
                    new = r if r == "T" else ("F", min(r[1] + 1, 2))
                else:
                    new = r
            return kind + (("s", new),), new
        pl.begin_temp()
        out, _ = self.transduce("rtl", {g: (self.char(g), pl.kind_of(g)) for g in dom | ends}, step, "eol",
                                skeleton=False, anchored=True)
        state = lambda o: pl.kind_of(o)[-1][1]
        outs = set(out.values())
        of = lambda chars: {g for g in self.alive if self.char(g) in chars}
        w2 = {o for o in outs if self.char(o) == "w" and state(o) in (("F", 1), ("F", 2))}
        dots = {o for o in outs if self.char(o) == "." and state(o) != "x"}
        before_www = of(" \t*_~(") | self.kinded(lambda k: k[0] == "bp")
        everything = set(b.order)
        w = of("w")
        www = (w2, w, dots)
        self.reverse([({g: pl.var(g, ("us", "www")) for g in w}, [before_www], www),
                      ({g: g for g in w}, [everything], www),
                      ({g: pl.var(g, ("us", "www")) for g in w}, (), www)])
        alpha = of(htmlauto.LETTER)
        # (Rules run right to left: a later link's start has its variant already.)
        host_ascii = of(htmlauto.ALNUM) | {pl.var(g, ("us", "url")) for g in of("hHfF")}
        host = host_ascii | {g for g in self.alive if self.char(g) >= "\x80"
                             and not gfm.is_unicode_space(ord(self.char(g)))
                             and not gfm.is_unicode_punct(ord(self.char(g)))}
        bad = {o for o in outs if state(o) == "T"}
        rules = [], [], []
        for scheme in ("http", "https", "ftp"):
            first = of({scheme[0], scheme[0].upper()})
            ahead = [of({c, c.upper()}) for c in scheme[1:]] + [of(":"), of("/"), of("/")]
            keep, mark = {g: g for g in first}, {g: pl.var(g, ("us", "url")) for g in first}
            rules[0].append((keep, [alpha], ahead + [host]))
            rules[1].append((keep, (), ahead + [host_ascii, bad]))
            rules[2].append((mark, (), ahead + [host]))
        self.reverse(rules[0] + rules[1] + rules[2])
        self.strip_state(outs)
        pl.end_temp()
        starts = self.kinded(lambda k: k[:1] == ("us",))
        cand = pl.var(self.url_base, ("um", "cand"))
        lk = pl.add(fb.lookup(2, [fb.multiple({g: [cand, pl.base_of(g)] for g in starts})]), top=False)
        pl.chain([([], [starts], [], [(0, lk)])])
        self.alive = (self.alive - starts) | {cand} | {pl.base_of(g) for g in starts}

    def url_ends(self):
        """Where each candidate link ends, as cmark-gfm finds it: at the next
        space, tab or `<` (or where the inline text ends), less the trailing
        punctuation it drops, `?!.,:*_~'"` and `;` (with the `&` and letters
        before it, if they make one), which takes a `)` only while the link
        has more `(` than `)` (counted to URL_PARENS either way). Right to
        left, characters learn whether they are trailing punctuation, and
        whether a `)` comes in it; a marker ("ts", any `)`) goes in before
        each run of it that doesn't start with `;`. Left to right, from each
        candidate's marker, a pass counts parentheses and puts in an end
        marker where the link ends: ("ue",) before a character, ("ue",
        "after") after a `)`; nested candidates become ("um", "nested"). A
        second pass then marks the characters main_scan reads that lie
        inside a candidate: ("u", "first") for the first, ("u", "in") after
        it."""
        pl, b = self.pl, self.b
        trim = set("?!.,:*_~'\");")
        past = set(JS_SPACE) - set(" \t")      # after the inline text, these end the line too

        def tail(R, sym):
            ch, kind = sym
            if ch in past or ch == "#":          # (a heading's closing #s)
                return (kind + (("s", "eolw"),), "eolw") if R in ("eol", "eolw") else None
            if ch in " \t<":
                new = "end"
            elif ch in htmlauto.LETTER:          # before a `;`: an entity's name, if an `&` comes
                if R[:1] == ("P",) or R[:1] == ("T",) and R[3:] == (";",):
                    new = ("P", R[1])
                else:
                    return None
            elif ch == "&":
                if R[:1] != ("P",):
                    return None
                new = ("T", R[1], R[1])
            elif R in ("eol", "eolw", "end") or R[:1] == ("T",):
                after = R[:1] == ("T",) and R[1]
                new = ("T", ch == ")" or after, after) + ((";",) if ch == ";" else ())
            else:
                return None
            return kind + (("s", new),), new
        pl.begin_temp()
        ins = {g: (self.char(g), pl.kind_of(g)) for g in self.alive if self.char(g) in trim | set(" \t<&") | past
               | htmlauto.LETTER or self.char(g) == "#" and pl.kind_of(g)[-1:] == ("hc",)}
        out, _ = self.transduce("rtl", ins, tail, "eol", skeleton=False, anchored=True)
        tails = set(out.values())

        def cstate(g):
            for x in reversed(pl.kind_of(g)):
                if isinstance(x, tuple) and x[:1] == ("s",) and (x[1] in ("end", "eolw") or x[1][:1] in (("T",), ("P",))):
                    return x[1]
            return None
        in_t = {o for o in tails if cstate(o)[:1] == ("T",)}
        word_end = {o for o in tails if cstate(o) in ("end", "eolw")}
        pending = {o for o in tails if cstate(o)[:1] == ("P",)}
        ts = {hp: pl.var(self.url_base, ("ts", hp)) for hp in (False, True)}
        # The count below ends a link at a `;` (a marker before it could
        # split a reference, which Core Text's ligatures don't skip).
        first = {g: [ts[cstate(g)[1]], g] for g in in_t if self.char(g) != ";"}
        lk = pl.add(fb.lookup(2, [fb.multiple(first)]), top=False)
        pl.chain([([in_t | word_end | pending], [in_t], [], []), ([set(b.order)], [set(first)], [], [(0, lk)])])
        self.alive |= set(ts.values())

        cand = pl.var(self.url_base, ("um", "cand"))
        end = pl.var(self.url_base, ("ue",))
        end_out = pl.var(self.url_base, ("ue", ("s", "out")))
        after_out = pl.var(self.url_base, ("ue", "after", ("s", "out")))   # (after a `)`, not before a space)
        counted = {g for g in self.alive if self.char(g) in "()"} | {g for g in in_t if self.char(g) == ";"}

        def count(st, sym):
            ch, kind, c, g = sym
            if kind == ("um", "cand"):
                if st == "out":
                    return kind + (("s", ("in", 0)),), ("in", 0)
                return ("um", "nested", ("s", st)), st
            if st == "out":
                return None
            depth = st[1]
            if kind[:1] == ("ts",):
                if kind[1] and depth >= 1:
                    return kind + (("s", st),), st
                return end_out, "out"
            if c in ("end", "eolw"):                           # the next space, tab or `<`, or the end
                if ch not in " \t":
                    return passes.Seq((end, pl.var(g, kind + (("s", "out"),)))), "out"
                # (A space carries the end itself: WebKit widens every glyph of a space.)
                core = tuple(x for x in kind if not (isinstance(x, tuple) and x[:1] == ("s",)))
                return core + (("ue",), ("s", "out")), "out"
            if ch == "(":
                ns = ("in", min(depth + 1, URL_PARENS))
                return kind + (("s", ns),), ns
            if ch == ";":                                      # a `;` that starts the trailing punctuation
                if c[1] and depth >= 1:
                    return kind + (("s", st),), st
                return passes.Seq((end, pl.var(g, kind + (("s", "out"),)))), "out"
            if c is None:                                      # a `)` before the trailing punctuation
                ns = ("in", max(depth - 1, -URL_PARENS))
                return kind + (("s", ns),), ns
            # A `)` in the trailing punctuation: kept while `)` outnumber `(`.
            if depth < 1:
                return passes.Seq((end, pl.var(g, kind + (("s", "out"),)))), "out"
            ns = ("in", depth - 1)
            if depth == 1 or not c[2]:
                return passes.Seq((g, after_out)), "out"
            return kind + (("s", ns),), ns
        inputs = {g: (self.char(g), pl.kind_of(g), cstate(g), g)
                  for g in ({cand} | set(ts.values()) | word_end | counted)}
        out, _ = self.pl.ltr(inputs, count, "out")
        flat = {x for o in out.values() for x in (o if isinstance(o, passes.Seq) else (o,))}
        self.alive = (self.alive - set(inputs)) | flat | self.pl.unchanged
        ours = lambda x: x == "out" or isinstance(x, tuple) and x[:1] == ("in",)
        self.strip_state({o for o in flat if pl.kind_of(o)[-1:] and pl.kind_of(o)[-1][:1] == ("s",)
                          and ours(pl.kind_of(o)[-1][1])})

        scanned = self.kinded(lambda k: k[0] in ("bt", "dl", "tl", "tk", "br", "img", "amp") or k[:2] == ("bs", "escaping"))
        opened = pl.var(self.url_base, ("um", "open"))

        def cstate_kind(kind):
            return bool(kind) and isinstance(kind[-1], tuple) and kind[-1][:1] == ("s",)

        def inside(st, sym):
            ch, kind = sym
            core = kind[:-1] if cstate_kind(kind) else kind
            if core == ("um", "cand"):
                return opened, "start"
            if core[:1] == ("ue",) or core[-1:] == (("ue",),) or st == "out":
                return None
            return core + (("u", "first" if st == "start" else "in"),), "in"
        after = pl.var(self.url_base, ("ue", "after"))
        ends = self.kinded(lambda k: k[-1:] == (("ue",),) or k[-2:-1] == (("ue",),))
        self.transduce("ltr", {g: (self.char(g), pl.kind_of(g)) for g in scanned | ends | {cand, end, after}},
                       inside, "out")
        self.strip_state({g for g in self.alive if cstate_kind(pl.kind_of(g))})
        pl.end_temp()

    # left to right ------------------------------------------------------

    def main_scan(self):
        """Code spans, brackets and link destinations, left to right. The
        state is (mode, open brackets); every character it reads becomes
        ("m", role, state), except `*`/`_`, which gain the state when outside
        code spans and destinations and become ("m", "dead", state) inside."""
        pl = self.pl
        inputs = {g: (self.char(g), pl.kind_of(g)) for g in self.kinded(
            lambda k: k[0] in ("bt", "dl", "tl", "tk", "br", "img", "amp") or k[:2] == ("bs", "escaping")
            or k[:1] == ("bp",) and k[1] in DEAD_LINES)}
        out, _ = self.transduce("ltr", inputs, _url_step, ("N", 0))
        self.scanned = set(out.values())
        self.scan_clear = {o for (g, st), o in out.items() if _url_step(st, inputs[g])[1] in (("N", 0), ("U", 0))}

    def url_live(self):
        """A candidate URL is a link where main_scan is outside everything
        with no bracket open: its marker becomes ("um", "live"), others
        ("um", "dead"). main_scan's state there is the one its last output
        before the marker records."""
        pl = self.pl
        opened = pl.var(self.url_base, ("um", "open"))
        live, dead = pl.var(self.url_base, ("um", "live")), pl.var(self.url_base, ("um", "dead"))
        clear = self.scan_clear      # outputs that leave nothing open (U: a URL, which is over by now)
        to_live, to_dead = pl.nested({opened: live}), pl.nested({opened: dead})
        pl.chain([([clear], [{opened}], [], [(0, to_live)]), ([self.scanned], [{opened}], [], [(0, to_dead)]),
                  ([], [{opened}], [], [(0, to_live)])], sees=self.scanned | {opened})
        self.alive = (self.alive - {opened}) | {live, dead}

    def brackets(self):
        """Links and images by rounds of matching: in each round an opener
        and the closer right after it (in the sequence of unmatched brackets
        and link markers) pair up."""
        pl = self.pl
        proj = {}
        for g in self.kinded(lambda k: k[0] == "m" and k[1] in ("bro", "brc-tail", "brc-pair")):
            role = pl.kind_of(g)[1]
            if role == "bro":
                proj[g] = pl.var(g, ("B", "o", self.char(g) == "!"))
            else:
                proj[g] = pl.var(g, ("B", "c", role == "brc-tail"))
        pl.single(proj)
        self.replace(proj.items())
        lb, rb, bang = self.g["["], self.g["]"], self.g["!"]
        link_o, img_o = pl.var(lb, ("B", "o", False)), pl.var(bang, ("B", "o", True))
        tail_c, pair_c = pl.var(rb, ("B", "c", True)), pl.var(rb, ("B", "c", False))
        L, Lm = pl.var(rb, ("B", "L")), pl.var(rb, ("B", "Lm"))
        res = {name: pl.var(base, ("B", name)) for name, base in (
            ("link-open", lb), ("img-open", bang), ("img-close", rb), ("lit-tail", rb))}
        lit = {g: pl.var(g, ("B", "lit")) for g in (link_o, img_o, tail_c, pair_c)}
        to = lambda m: pl.nested(m)
        n_lit = to(lit)
        n_link = to({link_o: res["link-open"], tail_c: L})
        n_img = to({img_o: res["img-open"], tail_c: res["img-close"]})
        n_littail = to({tail_c: res["lit-tail"]})
        n_merge = to({L: Lm})
        rules = []
        for j in range(MAX_LINKS_INSIDE + 1):
            last = j + 1
            rules.append(([], [{img_o}] + [{L}] * j + [{tail_c}], [], [(0, n_img), (last, n_img)]))
            rules.append(([], [{link_o}] + [{L}] * j + [{tail_c}], [],
                          [(0, n_link), (last, n_link)] if j == 0 else [(0, n_lit), (last, n_littail)]))
            rules.append(([], [{link_o, img_o}] + [{L}] * j + [{pair_c}], [], [(0, n_lit), (last, n_lit)]))
        rules.append(([], [{L}, {L}], [], [(0, n_merge)]))
        for _ in range(MAX_BRACKETS):
            pl.chain(rules, sees={link_o, img_o, tail_c, pair_c, L})
        self.alive |= set(res.values()) | set(lit.values()) | {L, Lm}
        # The `[` of an image's `![` follows its `!`.
        ip = pl.var(lb, ("ip",))
        hide = pl.var(lb, ("B", "ip-hide"))
        pl.chain([([{res["img-open"]}], [{ip}], [], [(0, pl.nested({ip: hide}))])])
        self.alive.add(hide)

    def emphasis(self):
        """Emphasis by rounds of matching over the first characters of
        delimiter runs, separately at each level of link and image text."""
        pl, cap = self.pl, MAX_DELIMS + 1
        live = self.kinded(lambda k: k[0] in ("dl", "tl") and k[-1][0] == "N")
        proj = {}
        for g in live:
            _, i, n, o, c = pl.kind_of(g)[:5]
            if n >= (3 if self.char(g) == "~" else cap) or not (o or c):
                proj[g] = pl.var(g, ("lit",))
            elif i == 0:
                proj[g] = pl.var(g, ("park", n, o, c))
            else:
                proj[g] = pl.var(g, ("fol", i, n))
        pl.single(proj)
        self.replace(proj.items())
        # Levels: how many link or image texts enclose each run.
        opens = {"link-open", "img-open"}
        closes = {"L", "Lm", "img-close"}
        markers = self.kinded(lambda k: k[0] == "B" and k[1] in opens | closes)
        runs = self.kinded(lambda k: k[0] in ("park", "fol"))

        def level(lv, sym):
            kind = sym
            if kind[0] == "B":
                if kind[1] in opens:
                    nl = min(lv + 1, LEVELS)
                    return kind[:2] + (nl, nl), nl
                nl = max(lv - 1, 0)
                return kind[:2] + (lv, nl), nl
            return kind + (lv, lv), lv
        out, _ = self.transduce("ltr", {g: pl.kind_of(g) for g in markers | runs}, level, 0)
        # Drop the recorded state, keeping the level each glyph belongs to.
        self.strip_state(out.values())
        reps = self.universe()
        for lv in range(LEVELS):
            parked = self.kinded(lambda k, lv=lv: k[0] == "park" and k[-1] == lv)
            pl.single({g: pl.var(g, ("rep",) + pl.kind_of(g)[1:4] + (pl.kind_of(g)[1], (), (),
                                                                      "u" if pl.kind_of(g)[3] else "s"))
                       for g in parked})
            barriers = self.kinded(lambda k, lv=lv: k[0] == "B" and len(k) == 3 and k[2] == lv and lv > 0)
            for lk in self.round_lookups(reps, barriers, ROUNDS if lv == 0 else INNER_ROUNDS):
                pl.add(lk)
            done = {g: pl.var(g, ("done",) + pl.kind_of(g)[1:2] + pl.kind_of(g)[5:7]) for g in reps}
            pl.single(done)
        self.alive = (self.alive - self.kinded(lambda k: k[0] == "park")) | \
            {pl.var(g, ("done",) + pl.kind_of(g)[1:2] + pl.kind_of(g)[5:7]) for g in reps}
        # Every character of a run learns its role.
        runs = self.kinded(lambda k: k[0] in ("done", "fol"))

        def dist(state, kind):
            if kind[0] == "done":
                _, n, closes, opens = kind
                ns = (n, closes, opens, 0)
            elif state is None:
                return ("dd", ("lit",), None), None
            else:
                ns = state[:3] + (kind[1],)
            return ("dd", _role(ns[3], ns[0], ns[1], ns[2]), ns), ns
        def dist_char(state, sym):
            ch, kind = sym
            r = dist(state, kind)
            return r if ch != "~" or r[0][1] == ("lit",) else (("dd", r[0][1] + ("~",), r[0][2]), r[1])
        out, _ = self.transduce("ltr", {g: (self.char(g), pl.kind_of(g)[:-1] if pl.kind_of(g)[0] == "fol"
                                            else pl.kind_of(g)) for g in runs}, dist_char, None)
        # Only the role matters from here on.
        roles = {o: pl.var(o, ("dr", pl.kind_of(o)[1])) for o in set(out.values())}
        pl.single(roles)
        self.replace(roles.items())

    def universe(self):
        """Every state a run's first character can reach while matching."""
        pl = self.pl
        reps, todo = set(), []
        for c in "*_~":
            for n in range(1, (2 if c == "~" else MAX_DELIMS) + 1):
                for o, cl in ((True, False), (False, True), (True, True)):
                    todo.append(pl.var(self.g[c], ("rep", n, o, cl, n, (), (), "u" if cl else "s")))
        self.moves = {}
        while todo:
            g = todo.pop()
            if g in reps:
                continue
            reps.add(g)
            for move, k in _rep_moves(pl.kind_of(g), self.char(g) == "~").items():
                o = pl.var(g, k)
                self.moves.setdefault(move, {})[g] = o
                todo.append(o)
        return reps

    def round_lookups(self, reps, barriers, rounds):
        """The lookups of the matching rounds (the same rules each round)."""
        pl = self.pl
        if not hasattr(self, "_round_rules"):
            nest = {move: pl.nested(m) for move, m in self.moves.items()}
            cc = {g: pl.base_of(g) for g in reps}
            kind = {g: pl.kind_of(g) for g in reps}
            settled = {g for g in reps if kind[g][7] == "s"}
            unsettled = {g for g in reps if kind[g][7] == "u"}
            groups = {}
            for g in unsettled:
                _, n, o, c, r = kind[g][:5]
                groups.setdefault((cc[g], o, n % 3, r >= 2), set()).add(g)
            match, settle = [], []
            for (base, _, _, r2), closers in sorted(groups.items(), key=str):
                probe = next(iter(closers))
                elig = {g for g in settled if _eligible(cc[g], kind[g], base, kind[probe])}
                other = settled - elig
                tilde = self.char(base) == "~"
                for j in range(SEARCH + 1):
                    for o2 in (True, False):
                        part = {g for g in elig if (kind[g][4] >= 2) == o2}
                        if part:
                            u = 2 if r2 and o2 else 1
                            # A `~` pair is whole: strikethrough if both have
                            # the same length, else both stay text.
                            first, last = ((("open", u), ("close", u)) if not tilde or o2 == r2
                                           else ("kill", "kill"))
                            match.append(([], [part] + [other] * j + [closers], [],
                                          [(0, nest[first])]
                                          + [(t, nest["discard"]) for t in range(1, j + 1)]
                                          + [(j + 1, nest[last])]))
                for t in range(SEARCH + 1):
                    settle.append(([unsettled | elig] + [other] * t, [closers], [], []))
                settle.append(([other] * (SEARCH + 1), [closers], [], []))
                settle.append(([], [closers], [], [(0, nest["settle"])]))
            self._round_rules = [pl.chain_rule(*r) for r in match + settle]
            self._pending = settled | unsettled
        out = []
        ms = pl.mark_set(self._pending | set(barriers))
        for _ in range(rounds):
            out.append(fb.lookup(6, self._round_rules, passes.SKELETON, ms))
        return out

    def style(self):
        """The em, strong, link, image and strikethrough state after every
        delimiter character and bracket marker, left to right."""
        pl = self.pl
        marks = self.kinded(lambda k: k[0] == "dr" or (k[0] == "B" and k[1] in (
            "link-open", "img-open", "L", "Lm", "img-close"))
            or (k[0] == "m" and k[1] in ("auto-start", "auto-end", "html-end")) or k[:2] == ("bp", "atx")
            or k in (("um", "live"), ("ue",), ("ue", "after")) or k[-1:] == (("ue",),))

        def step(st, kind):
            em, strong, link, image, strike, url = st
            if kind == ("um", "live"):          # a bare URL: a link up to its end marker, the next mark
                ns = (em, strong, min(link + 1, 2), image, strike, True)
                return ("bm", "url-start") + ns, ns
            if kind[:1] == ("ue",) or kind[-1:] == (("ue",),):
                ns = (em, strong, link - 1 if url else link, image, strike, False)
                role = "url-end" if kind == ("ue",) else "url-end-after" if kind[:1] == ("ue",) else "url-end-space"
                return ("bm", role) + ns, ns
            if kind[0] == "bp":                 # a heading's text is strong throughout
                ns = (em, max(strong, 1), link, image, strike, False)
                return ("bp", "atx") + ns, ns
            if kind[0] == "dr":
                role = kind[1]
                tilde = role[-1] == "~"
                if role[0] in "oc" and role[2]:
                    d = 1 if role[0] == "o" else -1
                    if tilde:                   # (an image's text is never struck by its own `~`s)
                        strike = strike if image else max(0, min(MAX_DEPTH, strike + d))
                    elif role[1] == 1:
                        em = max(0, min(MAX_DEPTH, em + d))
                    else:
                        strong = max(0, min(MAX_DEPTH, strong + d))
                ns = (em, strong, link, image, strike, False)
                return ("dsx" if tilde else "ds", role[0] != "lit") + ns, ns
            r = kind[1]
            if r in ("link-open", "auto-start"):
                link = min(link + 1, 2)      # an autolink in link text is the deepest
            elif r in ("L", "Lm", "auto-end"):
                link = max(link - 1, 0)
            elif r == "html-end":
                pass
            elif r == "img-open":
                image = min(image + 1, 2)
            else:
                image = max(image - 1, 0)
            ns = (em, strong, link, image, strike, False)
            return ("bm", r) + ns, ns
        self.transduce("ltr", {g: pl.kind_of(g) for g in marks}, step, (0, 0, 0, 0, 0, False))

    def entities(self):
        """Entity and numeric character references, after everything that
        reads structure and before the paint: each becomes one glyph, a
        ligature of its characters drawn as the character it stands for (a
        ("ent",) variant, which the paint styles like that character). A live
        `&` first learns what follows it, so a shaper tries few ligatures."""
        pl, cmap = self.pl, self.b.font.getBestCmap()
        g_of = lambda c: cmap.get(ord(c))
        refs = {}
        for name, value in html.entities.html5.items():
            if name.endswith(";") and len(value) == 1 and g_of(value) and all(g_of(c) for c in name):
                refs["&" + name] = value
        numbers = {cp: chr(cp) for cp in cmap}
        numbers.update({n: chr(cp) for n, cp in cm_inline.C1_REPLACEMENTS.items() if cp in cmap})
        for n, value in numbers.items():
            refs[f"&#{n};"] = value
            h = f"{n:x}"
            letters = [i for i, c in enumerate(h) if c in "abcdef"]
            for x in "xX":
                for case in range(2 ** len(letters)):     # hex digits in either case
                    d = list(h)
                    for b, i in enumerate(letters):
                        if case >> b & 1:
                            d[i] = d[i].upper()
                    refs[f"&#{x}{''.join(d)};"] = value
        amps = self.kinded(lambda k: k[:2] == ("m", "amp"))
        key = lambda ref: ref[1:3] if ref[1] == "#" else ref[1]
        keyed = {k: pl.var(self.g["&"], ("amp", k)) for k in sorted({key(r) for r in refs})}
        # A bare URL's markers may sit between a reference's characters.
        ms = pl.mark_set({g for g in self.alive | set(keyed.values())
                          if pl.base_of(g) != g and pl.base_of(g) != self.url_base})
        pl.add(fb.lookup(6, [pl.chain_rule([], [amps], [{g_of(c)} for c in k], [(0, pl.nested({a: g for a in amps}))])
                             for k, g in keyed.items()], 0, ms))
        lig = ot.LigatureSubst()
        lig.ligatures = {}
        for ref, value in sorted(refs.items(), key=lambda rv: -len(rv[0])):
            L = ot.Ligature()
            L.Component = [g_of(c) for c in ref[1:]]
            L.LigGlyph = pl.var(g_of(value), ("ent",))
            L.CompCount = len(L.Component) + 1
            lig.ligatures.setdefault(keyed[key(ref)], []).append(L)
        pl.add(fb.lookup(4, [lig], 0, ms))
        # A `&` that starts no reference goes back to being an `&`.
        pl.single({g: self.g["&"] for g in keyed.values()})
        self.alive |= {pl.var(g_of(v), ("ent",)) for v in set(refs.values())} | {self.g["&"]}

    def emails(self):
        """GFM's email autolinks, found as cmark-gfm finds them in plain text
        once emphasis is settled: a local part of letters, digits and
        `.+-_`, an `@`, and a domain of letters, digits, `-`, `_` and dots
        between them, with a dot and ending in a letter. Right to left,
        characters learn whether they end a domain run, whether a valid
        domain follows an `@`, and whether they lie in the local part before
        one; then left to right, markers go in before an email and after
        it: ("em", "start") and ("em", "end"). Whatever is not one of these
        characters (a hidden delimiter, a reference) ends the text."""
        pl = self.pl
        local = set(htmlauto.ALNUM) | set(".+-_")
        text = {g for g in self.alive if self.char(g) in local | {"@"}
                and pl.kind_of(g) in ((), ("lit",), ("dr", ("lit",)), ("esc",))}   # (a literal `_`)
        # A live URL's start marker ends the text; the other markers aren't in it.
        markers = {g for g in self.alive if pl.base_of(g) == self.url_base and pl.kind_of(g) != ("um", "live")}
        empty = (False,)

        def scan(R, sym):
            ch, kind = sym
            dom, loc = (empty, False) if R in ("eol", passes.OTHER) else R
            if ch is None:
                return kind + (("e", None, False), ("s", (dom, loc))), (dom, loc)
            if ch == "@":
                ok = dom != empty and dom[1] and dom[2]
                return kind + (("e", "at", ok), ("s", (empty, "at" if ok else False))), (empty, "at" if ok else False)
            if ch == ".":
                new = (True, True, dom[2], False) if dom != empty and dom[3] else empty
            elif ch in "+":
                new = empty
            else:                                  # a letter, a digit, `-` or `_`
                new = (True, dom[1], dom[2], ch in htmlauto.ALNUM) if dom != empty else \
                    (True, False, ch in htmlauto.LETTER, ch in htmlauto.ALNUM)
            last = ch not in ".+" and dom == empty
            st = (new, loc in (True, "at"))
            return kind + (("e", st[1], last), ("s", st)), st
        pl.begin_temp()
        out, _ = self.transduce("rtl", {g: (None if g in markers else self.char(g), pl.kind_of(g))
                                        for g in text | markers}, scan, "eol", skeleton=False, anchored=True)
        start, end = pl.var(self.url_base, ("em", "start")), pl.var(self.url_base, ("em", "end"))
        note = lambda k: next(x for x in reversed(k) if isinstance(x, tuple) and x[:1] == ("e",))

        def mark(st, sym):
            ch, kind, g = sym
            e = note(kind)
            core = tuple(x for x in kind if not (isinstance(x, tuple) and x[:1] in (("s",), ("e",))))
            if e[1] is None:                       # a marker: as if it weren't there
                return (None if st in ("out", passes.OTHER) else (core + (("s", st),), st))
            if st in ("out", passes.OTHER):
                if e[1] is True:                   # the local part's first character
                    return passes.Seq((start, pl.var(g, core + (("s", "loc"),)))), "loc"
                return None
            if st == "loc":
                if e[1] is True:
                    return core + (("s", "loc"),), "loc"
                if e[1:] == ("at", True):
                    return core + (("s", "dom"),), "dom"
                return None
            if e[2]:                               # the domain's last character
                return passes.Seq((pl.var(g, core + (("s", "end"),)), end)), "out"
            return core + (("s", "dom"),), "dom"
        scanned = set(out.values())
        out, _ = self.pl.ltr({g: (self.char(g), pl.kind_of(g), g) for g in scanned}, mark, "out",
                             skeleton=False, anchored=True)
        flat = {x for o in out.values() for x in (o if isinstance(o, passes.Seq) else (o,))}
        self.alive = (self.alive - scanned) | flat | self.pl.unchanged
        temp = {g for g in self.alive if pl.kind_of(g)[-1:] and isinstance(pl.kind_of(g)[-1], tuple)
                and pl.kind_of(g)[-1][:1] == ("s",)}
        # Back to what they were: the pass's state and the scan's notes go.
        strip = {}
        for g in temp | scanned:
            k = tuple(x for x in pl.kind_of(g) if not (isinstance(x, tuple) and x[:1] in (("s",), ("e",))))
            strip[g] = pl.var(g, k) if k else pl.base_of(g)
        pl.single(strip)
        self.replace(strip.items())
        pl.end_temp()

    def paint(self):
        """Every glyph becomes its final glyph: a styled glyph or, for
        markup, an invisible one that records the state after it. The state
        is (em, strong, code, link, image, html, tail, rule); glyphs in image
        or HTML style record a fixed state, and the next marker restores the
        rest. A heading is strong throughout, a code line all code, a line of
        HTML, a code fence or a definition all HTML style, and a thematic
        break a rule."""
        pl, b = self.pl, self.b
        made = {}

        figure = b.advance(b.font.getBestCmap()[ord("0")])
        # A task box is drawn on the character inside its brackets, often a
        # space, which WebKit always gives a space's width: the box takes that
        # width and reaches back over the hidden `[`, which takes the rest.
        box_left = max(0, figure - b.advance(self.g[" "]))

        def mark(kind):
            """A block marker's glyph (fontbuild.marker), one per kind, a
            figure wide (a space would be narrow in a proportional font)."""
            if ("mk", kind) not in made:
                made[("mk", kind)] = b.marker(kind, figure, box_left if kind in ("box", "checked") else 0)
                self.styled_key[made[("mk", kind)]] = ("marker", kind)
            return made[("mk", kind)]

        def copy(g, suffix, src_style, key):
            """A copy of a styled glyph that records another state."""
            name = fb.styled(pl.base_of(g), suffix)
            if name not in b.ids:
                src = fb.styled(pl.base_of(g), src_style)
                glyph = b.glyphs.get(src) or b.glyf[src]
                if glyph.isComposite() or glyph.numberOfContours > 0:
                    b.composite(name, [(src, 0, 0)], b.advance(src))
                else:
                    b.empty(name, b.advance(src))
                if src in b.colr:
                    b.colr[name] = list(b.colr[src])
                self.styled_key[name] = key
            return name

        def hid_url(state):
            """A bare URL's marker, hidden."""
            if ("hu", state) not in made:
                made[("hu", state)] = b.empty(f"_hu{len(made)}", 0)
                self.styled_key[made[("hu", state)]] = ("hidden-url", state)
            return made[("hu", state)]

        def hid(state):
            if ("hid", state) not in made:
                made[("hid", state)] = b.empty(f"_hid{len(made)}", 0)
                self.styled_key[made[("hid", state)]] = ("hidden", state)
            return made[("hid", state)]

        def box_pad(state):
            """A task box's hidden `[`, as wide as the box reaches over it."""
            if ("pad", state) not in made:
                made[("pad", state)] = b.empty(f"_hidpad{len(made)}", box_left)
                self.styled_key[made[("pad", state)]] = ("hidden-pad", state)
            return made[("pad", state)]

        def hid_strike(state, struck):
            """A hidden `~`, which also says whether the text after it is
            struck through (for the strike pass)."""
            if ("hs", state, struck) not in made:
                made[("hs", state, struck)] = b.empty(f"_hs{int(struck)}x{len(made)}", 0)
                self.styled_key[made[("hs", state, struck)]] = ("hidden-strike", state, struck)
            return made[("hs", state, struck)]

        def html_end(state):
            # The `>` ending raw HTML is drawn in HTML style but restores the
            # style around the HTML: a copy of that glyph for each state.
            if ("he", state) not in made:
                src = fb.styled(self.g[">"], "h")
                name = b.composite(fb.styled(self.g[">"], f"h{len(made)}"), [(src, 0, 0)],
                                   b.advance(self.g[">"]))
                b.colr[name] = list(b.colr[src])
                made[("he", state)] = name
                self.styled_key[name] = ("html-end", state)
            return made[("he", state)]

        rule_state = (False,) * 6 + (None, True)

        def shown(g, state):
            em, strong, code, link, image, html, tail, rule = state
            if rule:
                return mark("rule"), rule_state
            if html:
                return fb.styled(pl.base_of(g), "h"), (False,) * 5 + (True, None, False)
            if image:
                return fb.styled(pl.base_of(g), "im"), (False,) * 4 + (True, False, None, False)
            suffix = ("l" if link else "") + ("c" if code else "") + ("b" if strong else "") + ("i" if em else "")
            return fb.styled(pl.base_of(g), suffix), state
        # First every glyph becomes what the paint needs to know of it: its
        # character, or a few kinds of markup ("P", ...).
        proj = {}
        for g in self.alive:
            k = pl.kind_of(g)
            if not k:
                continue
            if k[0] in ("ds", "bm"):
                proj[g] = pl.var(g, ("P", k[0], k[1]) + tuple(d > 0 for d in k[2:6]))
            elif k[0] == "dsx":                 # a `~`: the strikethrough after it goes with it
                proj[g] = pl.var(g, ("P", "dsx", k[1]) + tuple(d > 0 for d in k[2:7]))
            elif k[:2] in (("m", "OPEN"), ("m", "CLOSE"), ("m", "html-start"), ("m", "tail-end"), ("m", "bs-hide")):
                proj[g] = pl.var(g, ("P", k[1]))
            elif k == ("B", "ip-hide"):
                proj[g] = pl.var(g, ("P", "ip-hide"))
            elif k[0] == "bp":
                proj[g] = pl.var(g, ("P", "blk", k[1]))
            elif k == ("hc",):
                proj[g] = pl.var(g, ("P", "hc"))
            elif pl.base_of(g) == self.url_base and k[:1] == ("em",):
                proj[g] = pl.var(g, ("P", "email", k[1]))
            elif pl.base_of(g) == self.url_base:   # a URL marker no pass made anything of
                proj[g] = pl.var(g, ("P", "url"))
            else:
                proj[g] = pl.base_of(g)
        pl.single(proj)
        self.replace(proj.items())
        heading = (False, True) + (False,) * 4 + (None, False)

        start = (False,) * 6 + (None, False)

        def block(state, g, r):
            """A glyph of a line's block markup: only ever at the start of a
            line, or after a heading's #s."""
            if state not in (start, heading) or state == heading and r not in ("indent", "atx"):
                return passes.IMPOSSIBLE
            if r in ("indent", "number"):
                return shown(g, state)
            if r == "box-open" and box_left:
                return box_pad(state), state
            if r in ("box-open", "box-close"):
                return hid(state), state
            if r in ("quote", "bullet", "box", "checked"):
                return mark(r), state
            if r == "atx":
                return copy(g, "hb", "h", ("dim", "heading")), heading
            if r == "code":                     # the last column of indentation; code follows
                ns = state[:2] + (True,) + state[3:]
                return copy(g, "k", "", ("code-start",)), ns
            if r == "hr":
                return mark("rule"), rule_state
            return shown(g, (False,) * 5 + (True, None, False))      # fence, html, def: dimmed

        def step(s, g):
            k = pl.kind_of(g)
            if s == rule_state:                 # a thematic break: a rule to the end of the line
                return mark("rule"), rule_state
            if k[:2] == ("P", "dsx"):
                _, _, hide, e, st, lk, im, struck = k
                if s[6] == "hide":
                    return _paint_step(s, g, (), hid, shown, html_end)
                ns = (e, st, s[2], lk, im, s[5], s[6], s[7])
                return (hid_strike(ns, struck), ns) if hide else shown(g, ns)
            if k[:2] == ("P", "blk"):
                return block(s, g, k[2])
            if k[:2] == ("P", "email"):          # an email: a link where nothing else is open
                if k[2] == "start" and s[2:] == (False, False, False, False, None, False):
                    ns = s[:3] + ("e",) + s[4:]
                    return hid(ns), ns
                if k[2] == "end" and s[3] == "e":
                    ns = s[:3] + (False,) + s[4:]
                    return hid(ns), ns
                return hid(s), s
            if s[3] == "e":                     # inside one: its characters only, in copies that say so
                if k == ("P", "url") or k[:3] in (("P", "bm", "url-end"), ("P", "bm", "url-end-after")):
                    return (hid if k[2:3] == ("url-end-after",) else hid_url)(s), s    # (a dead URL's marker)
                if k[:2] == ("P", "ds") and not k[2]:
                    k = ()
                if k or self.char(g) not in email_chars:
                    return passes.IMPOSSIBLE
                suffix = "l" + ("b" if s[1] else "") + ("i" if s[0] else "")
                return copy(g, suffix + "e", suffix, ("email", suffix)), s
            if k == ("P", "url"):
                return (hid_url(s), s) if s != rule_state else (mark("rule"), rule_state)
            if k[:3] == ("P", "bm", "url-end-space"):    # a space that ends a URL
                if s[6] == "hide":
                    return _paint_step(s, g, (), hid, shown, html_end)
                return shown(g, s if k[5] == s[3] else s[:3] + (k[5],) + s[4:])
            if k[:3] in (("P", "bm", "url-start"), ("P", "bm", "url-end"), ("P", "bm", "url-end-after")):
                lk, h = k[5], hid if k[2] == "url-end-after" else hid_url
                if lk == s[3] or s[6] == "hide":
                    return h(s), s
                ns = s[:3] + (lk,) + s[4:]
                return h(ns), ns
            if k == ("P", "hc"):                # a heading's closing #s (only a heading is strong there)
                if s[1] and s[6] is None:
                    return copy(g, "hb", "h", ("dim", "heading")), heading
                k = ()
            return _paint_step(s, g, k, hid, shown, html_end)
        email_chars = set(htmlauto.ALNUM) | set(".+-_@")
        out, _ = pl.ltr({g: g for g in self.alive}, step, start, skeleton=False, fill_backtrack=True)
        self.alive = set(out.values())

    def strike(self):
        """GFM's strikethrough, drawn last: after a hidden `~` that says so,
        every glyph up to one that says otherwise gets the line, as a glyph
        after it with no advance that draws back over it. A space gets a
        struck copy instead: WebKit gives everything a space character
        shapes to a space's width. One rule per kind of glyph, each reading
        whether the glyph before is struck (an overlay, a struck space, or a
        hidden `~` that starts the line)."""
        pl, b = self.pl, self.b

        def char(g):
            return self.chars.get(g.partition("__")[0], "")
        glyphs = [g for g in sorted(self.alive, key=b.gid) if not g.startswith(("_mk_", "_hs"))]
        spaces = [g for g in glyphs if char(g) in (" ", "\t", "\u00a0")]
        struck = {g: b.struck(g) for g in spaces}
        by_advance = {}
        for g in glyphs:
            if g not in struck:
                by_advance.setdefault(b.advance(g), []).append(g)
        on = {g for g in self.alive if g.startswith("_hs1")} | set(struck.values())
        rules = []
        for adv, gs in sorted(by_advance.items()):
            overlay = b.strike_overlay(adv)
            on.add(overlay)
            for k in range(0, len(gs), 4000):        # keeps each subtable's offsets in 16 bits
                part = gs[k:k + 4000]
                lk = pl.add(fb.lookup(2, [fb.multiple({g: [g, overlay] for g in part})]), top=False)
                rules.append((part, lk))
        lk = pl.nested(struck)
        rules.append((spaces, lk))
        pl.chain([([on], [set(gs)], [], [(0, lk)]) for gs, lk in rules])
        self.alive |= on


def _paint_step(state, g, k, hid, shown, html_end):
    em, strong, code, link, image, html, tail, rule = state
    role = k[1] if k[:1] == ("P",) else None
    if tail == "hide":                     # a link destination: hidden up to its end
        ns = state[:6] + (None, rule) if role == "tail-end" else state
        return hid(ns), ns
    if role == "ds":
        _, _, hide, e, st, lk, im = k
        ns = (e, st, code, lk, im, html, tail, rule)
        return (hid(ns), ns) if hide else shown(g, ns)
    if role == "bm":
        _, _, r, e, st, lk, im = k
        ns = (e, st, code, lk, im, False, "hide" if r in ("L", "Lm", "img-close") else tail, rule)
        if r == "html-end":
            return html_end(ns), ns
        return hid(ns), ns
    if role == "html-start":
        return shown(g, state[:5] + (True, tail, rule))
    if role in ("ip-hide", "bs-hide"):
        return hid(state), state
    if role in ("OPEN", "CLOSE"):
        ns = (em, strong, role == "OPEN", link, image, html, tail, rule)
        return hid(ns), ns
    return shown(g, state)


# What precedes the `>` that ends each kind of raw HTML (None: the first `>`).
HTML_END = {"close": None, "decl": None, "comment": "--", "pi": "?", "cdata": "]]"}


def _url_step(state, sym):
    """main_scan's step, with bare URLs: the first character it reads in a
    candidate URL starts one ("U" mode) where nothing else is open, and
    inside it every character is text."""
    ch, kind = sym
    if kind[-1:] == (("ue",),):          # a space that ends a candidate URL
        kind = kind[:-1]
        # Live if main_scan is in it, or is still where it started with
        # nothing open (a URL it reads nothing of); the style pass ignores the
        # end of one that isn't live.
        if state[0] == "U" or state == ("N", 0):
            k, ns = _main_step(("N", 0), (ch, kind))
            return k + (("ue",),), ns
        return _main_step(state, (ch, kind))
    u = kind[-1][1] if kind and isinstance(kind[-1], tuple) and kind[-1][:1] == ("u",) else None
    if u:
        kind = kind[:-1]
    if state[0] == "U":                  # (a URL's end has passed if this is not inside it)
        if u == "in":
            return ("m", "dead", state), state
        state = ("N", 0)
        if u == "first":
            return ("m", "dead", ("U", 0)), ("U", 0)
    elif u == "first" and state == ("N", 0):
        return ("m", "dead", ("U", 0)), ("U", 0)
    return _main_step(state, (ch, kind))


def _main_step(state, sym):
    ch, kind = sym
    mode, cnt = state
    tag = kind[0]
    back = ("N", cnt)
    if tag == "bp":                      # a code, HTML or rule line, or a definition: no inline syntax
        return kind + (("D", 0),), ("D", 0)
    if mode == "D":
        return ("m", "dead", state), state
    if isinstance(mode, tuple) and mode[0] in ("O", "L", "X", "Cc") and tag != "bt":
        return passes.IMPOSSIBLE    # inside a run of backticks: only backticks come next
    if isinstance(mode, tuple) and mode[0] == "T":        # inside a link destination
        if tag != "tk":
            # Text inside a destination: impossible where the destination
            # automaton would reject another character.
            if tails.step(mode[1], "O", PARENS) is None:
                return passes.IMPOSSIBLE
            return ("m", "dead", state), state
        _, po, esc, x = kind
        q = tails.step(mode[1], "O", PARENS) if po else mode[1]
        q = q and tails.step(q, "O" if esc or ch == "]" else ch, PARENS)
        if q == tails.ACC or q is None:
            return ("m", "tail-end", back), back
        return ("m", "dead", (("T", q), cnt)), (("T", q), cnt)
    if isinstance(mode, tuple) and mode[0] == "A":        # autolink: ends at the first ">"
        if tag == "tk" and ch == ">":
            return ("m", "auto-end", back), back
        return ("m", "dead", state), state
    if isinstance(mode, tuple) and mode[0] == "H":        # raw HTML (escapes don't apply)
        if tag != "tk":
            return ("m", "dead", state), state
        if mode[1] == "open":
            q = mode[2]
            if ch == ">" and q == "out":
                return ("m", "html-end", back), back
            if ch in "\"'" and q in ("out", "dq" if ch == '"' else "sq"):
                q = "out" if q != "out" else ("dq" if ch == '"' else "sq")
            ns = (("H", "open", q), cnt)
            return ("m", "dead", ns), ns
        if ch == ">" and HTML_END[mode[1]] in (None, kind[3]):
            return ("m", "html-end", back), back
        return ("m", "dead", state), state
    if tag == "bt":
        role, nm = _tick(mode, kind)
        return ("m", role, (nm, cnt)), (nm, cnt)
    if mode != "N":                                        # inside a code span
        return ("m", "dead", state), state
    if tag in ("dl", "tl"):
        return kind + (state,), state
    if tag == "bs":
        return ("m", "bs-hide", state), state
    if tag == "amp":
        return ("m", "amp", state), state
    if tag in ("br", "img"):
        if cnt < MAX_BRACKETS:
            return ("m", "bro", ("N", cnt + 1)), ("N", cnt + 1)
        return ("m", "lit", state), state
    _, po, esc, x = kind
    x = {"open7": "open", "close7": "close"}.get(x, x)
    if esc:
        return ("m", "txt", state), state
    if ch == "<" and x:
        ns = ((("A",) if x in ("email", "uri") else ("H", "open", "out") if x == "open" else ("H", x)), cnt)
        return ("m", "auto-start" if x in ("email", "uri") else "html-start", ns), ns
    if ch == "]":
        if cnt == 0:
            return ("m", "lit", state), state
        if x:
            ns = (("T", "S0"), cnt - 1)
            return ("m", "brc-tail", ns), ns
        return ("m", "brc-pair", ("N", cnt - 1)), ("N", cnt - 1)
    return ("m", "txt", state), state


def _tick(mode, kind):
    """A backtick's role and the code span mode after it."""
    cap = MAX_TICKS + 1
    _, i, n, fe = kind[:4]
    v = dict(kind[4:]).get("v")
    if mode == "N":
        if n >= cap or (i == 0 and fe):
            return "LIT", "N"
        m = n - i
        if not v:
            return "LIT", (("L", m - 1) if m > 1 else "N")
        return "OPEN", (("O", m, m - 1) if m > 1 else ("C", m))
    tag, *a = mode
    if tag == "C":
        (m,) = a
        if n >= cap:
            return "CODE", mode
        if n == m:
            return "CLOSE", (("X", n - 1) if n > 1 else "N")
        return "CODE", (("Cc", m, n - 1) if n > 1 else mode)
    if tag == "O":
        m, k = a
        return "OPEN", (("O", m, k - 1) if k > 1 else ("C", m))
    if tag in ("L", "X"):
        (k,) = a
        return ("LIT" if tag == "L" else "CLOSE"), ((tag, k - 1) if k > 1 else "N")
    m, k = a     # "Cc": inside a run of backticks that is code content
    return "CODE", (("Cc", m, k - 1) if k > 1 else ("C", m))


def _rep_moves(kind, tilde=False):
    """What can happen to an emphasis run's first character in a round. A
    `~` run is used whole or not at all ("kill": both runs stay text)."""
    _, n, o, c, r, closes, opens, st = kind
    out = {}
    for u in (1, 2):
        if tilde and u != n:
            continue
        if r >= u and st == "s":
            out[("open", u)] = ("rep", n, o, c, r - u, closes, opens + (u,), "d" if r == u else "s")
        if r >= u and st == "u":
            out[("close", u)] = ("rep", n, o, c, r - u, closes + (u,), opens, "d" if r == u else "u")
    if tilde and st in ("s", "u"):
        out["kill"] = ("rep", n, o, c, r, closes, opens, "d")
    if st == "s":
        out["discard"] = ("rep", n, o, c, r, closes, opens, "d")
    if st == "u":
        out["settle"] = ("rep", n, o, c, r, closes, opens, "s" if o else "d")
    return out


def _eligible(cc_o, ko, cc_c, kc):
    """Can the settled run `ko` open emphasis for the unsettled closer `kc`?"""
    if cc_o != cc_c:
        return False
    odd = (kc[2] or ko[3]) and kc[1] % 3 != 0 and (ko[1] + kc[1]) % 3 == 0
    return not odd


def _role(i, n, closes, opens):
    """The role of character i of a run that closed `closes` and opened `opens`."""
    p = 0
    for u in closes:
        if p <= i < p + u:
            return ("c", u, i == p)
        p += u
    q = n
    for u in opens:
        if q - u <= i < q:
            return ("o", u, i == q - u)
        q -= u
    return ("lit",)


STAGES = ("html_validity", "gt_ends", "escapes", "backtick_runs", "code_closers", "delimiter_runs",
          "brackets_and_tails", "tail_validity", "block_marks", "block_prefix", "url_starts", "url_ends",
          "main_scan", "url_live", "brackets", "emphasis", "emails", "style", "entities", "paint", "strike")


def build(base, bold, italic, bold_italic, mono=None, family="Fontlex Markdown"):
    mf = MarkdownFont(base, bold, italic, bold_italic, mono)
    for stage in STAGES:
        getattr(mf, stage)()
    font = mf.b.finish(mf.pl.gsub(), mf.pl.mark_sets, family)
    return font, mf


def main(argv=None):
    # Glyphs are made while iterating over sets of glyph names, whose order
    # depends on string hashing: fix the hash seed so builds are reproducible.
    if argv is None and os.environ.get("PYTHONHASHSEED") != "0":
        os.environ["PYTHONHASHSEED"] = "0"
        os.execv(sys.executable, [sys.executable] + sys.argv)
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", required=True)
    ap.add_argument("--bold", required=True)
    ap.add_argument("--italic", required=True)
    ap.add_argument("--bold-italic", required=True)
    ap.add_argument("--mono", nargs=4, metavar=("REGULAR", "BOLD", "ITALIC", "BOLD_ITALIC"),
                    help="a monospaced family to draw code with (for a proportional base)")
    ap.add_argument("--family", default="Fontlex Markdown")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    font, mf = build(args.base, args.bold, args.italic, args.bold_italic, args.mono, args.family)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    first, *rest = args.family.split()
    path = out / f"{first}-{''.join(rest)}.ttf"
    font.save(path)
    # The web font goes without glyph names (verify.py reads them from the TTF).
    font = TTFont(path, recalcTimestamp=False)
    font["post"].formatType = 3.0
    font.flavor = "woff2"
    font.save(path.with_suffix(".woff2"))
    print(f"wrote {path} and .woff2: {len(font.getGlyphOrder())} glyphs, {len(mf.pl.top)} lookups")
    return 0


if __name__ == "__main__":
    sys.exit(main())
