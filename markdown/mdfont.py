"""Compile a Markdown font: CommonMark inline syntax rendered by the shaper.

    python markdown/mdfont.py --base fonts/JetBrainsMono-Regular.ttf \\
        --bold ...-Bold.ttf --italic ...-Italic.ttf --bold-italic ...-BoldItalic.ttf --out build

The lookups run in two groups. Right to left, what lies ahead of each
character: which kind of raw HTML or autolink starts at each `<`, escapes
and the shape of runs (from small windows), whether a code span's closing
backticks follow, and whether a link destination follows a `]`. Then left
to right: the scan that settles code spans, raw HTML, autolinks and link
destinations; rounds of matching for brackets and for emphasis (matched
pairs drop out of the sequence the next round sees, so a pair is always
adjacent there); the style after each marker; entity references, as
ligatures; and the paint that gives every glyph its final glyph. build()
runs the stages in order. Every bound is a constant below.
"""

import argparse
import html.entities
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import cm_inline  # noqa: E402
import fontbuild as fb  # noqa: E402
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

STRUCTURAL = "\\`*_[]!()\"'<>&"
TAIL = "()\"'<>] \t"          # what the link destination automaton reads
ASCII_PUNCT = cm_inline.ASCII_PUNCTUATION


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
    def __init__(self, base, bold, italic, bold_italic):
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
        self.b.add_color_styles(self.text)
        self.pl = passes.Pipeline(self.b)
        self.g = {c: cmap[ord(c)] for c in STRUCTURAL + " \t" if ord(c) in cmap}
        self.alive = set(self.text)     # glyphs that can be in the buffer at this point
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

        def before_gt(seen, g):
            new = seen or pl.base_of(g) == gt
            return (("hx0",) + (("s", new),), new) if new else None
        self.pl.begin_temp()
        out, _ = self.transduce("rtl", {g: g for g in a0.values()}, before_gt, False)
        marked = set(out.values())
        note = {o: (lambda nb, o=o: pl.var(pl.base_of(o), ("hx", nb) + ((frozenset(),) if pl.base_of(o) == lt
                                                                        else ()))) for o in marked}
        self.reverse([({o: f(True) for o, f in note.items()}, [nonascii], ()),
                      ({o: f(False) for o, f in note.items()}, (), ())])
        self.pl.end_temp()
        found_k = lambda k: k[-1] if k and isinstance(k[-1], frozenset) else frozenset()
        for name, step in htmlauto.KINDS:
            if name == "uri":
                self.uri_autolinks()
                continue
            auto = htmlauto.Backward(step)

            def back(R, sym, auto=auto, name=name):
                ch, kind = sym
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
            kinds = [n for n in order if n in found_k(pl.kind_of(g))] if pl.base_of(g) == lt else []
            final[g] = pl.var(lt, ("lt", kinds[0])) if kinds else pl.base_of(g)
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
        close); n = MAX_DELIMS + 1 for longer runs, which never delimit."""
        pl, cap = self.pl, MAX_DELIMS + 1
        for c in "*_":
            d = self.g[c]
            others = {g for g in self.alive if g != d}
            js = {(j, a): pl.var(d, ("dlj", j, a)) for j in range(cap + 1) for a in "WPO"}
            rules = [({d: js[(min(j + 1, cap), a)]}, (), [{js[(j, a)]}]) for (j, a) in js]
            for a in "WPO":
                rules.append(({d: js[(0, a)]}, (), [{g for g in others if self.flank_class(g) == a}]))
            rules.append(({d: js[(0, "W")]}, (), ()))
            self.reverse(rules)
            rules = []
            for i in range(cap, -1, -1):
                for b in ("WPOS" if i < cap else "S"):
                    m = {js[(j, a)]: pl.var(d, ("dl", i, min(i + j + 1, cap)) + flanking(c, b, a))
                         for (j, a) in js}
                    back = [set(js.values())] * i
                    if b != "S":
                        back = [{g for g in others if self.flank_class(g) == b}] + back
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

    # left to right ------------------------------------------------------

    def main_scan(self):
        """Code spans, brackets and link destinations, left to right. The
        state is (mode, open brackets); every character it reads becomes
        ("m", role, state), except `*`/`_`, which gain the state when outside
        code spans and destinations and become ("m", "dead", state) inside."""
        pl = self.pl
        inputs = {g: (self.char(g), pl.kind_of(g)) for g in self.kinded(
            lambda k: k[0] in ("bt", "dl", "tk", "br", "img", "amp") or k == ("bs", "escaping"))}
        self.transduce("ltr", inputs, _main_step, ("N", 0))

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
        live = self.kinded(lambda k: k[0] == "dl" and k[-1][0] == "N")
        proj = {}
        for g in live:
            _, i, n, o, c, _st = pl.kind_of(g)
            if n >= cap or not (o or c):
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
        out, _ = self.transduce("ltr", {g: pl.kind_of(g)[:-1] if pl.kind_of(g)[0] == "fol" else pl.kind_of(g)
                                        for g in runs}, dist, None)
        # Only the role matters from here on.
        roles = {o: pl.var(o, ("dr", pl.kind_of(o)[1])) for o in set(out.values())}
        pl.single(roles)
        self.replace(roles.items())

    def universe(self):
        """Every state a run's first character can reach while matching."""
        pl = self.pl
        reps, todo = set(), []
        for c in "*_":
            for n in range(1, MAX_DELIMS + 1):
                for o, cl in ((True, False), (False, True), (True, True)):
                    todo.append(pl.var(self.g[c], ("rep", n, o, cl, n, (), (), "u" if cl else "s")))
        self.moves = {}
        while todo:
            g = todo.pop()
            if g in reps:
                continue
            reps.add(g)
            for move, k in _rep_moves(pl.kind_of(g)).items():
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
                for j in range(SEARCH + 1):
                    for o2 in (True, False):
                        part = {g for g in elig if (kind[g][4] >= 2) == o2}
                        if part:
                            u = 2 if r2 and o2 else 1
                            match.append(([], [part] + [other] * j + [closers], [],
                                          [(0, nest[("open", u)])]
                                          + [(t, nest["discard"]) for t in range(1, j + 1)]
                                          + [(j + 1, nest[("close", u)])]))
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
        """The em, strong, link and image state after every delimiter
        character and bracket marker, left to right."""
        pl = self.pl
        marks = self.kinded(lambda k: k[0] == "dr" or (k[0] == "B" and k[1] in (
            "link-open", "img-open", "L", "Lm", "img-close"))
            or (k[0] == "m" and k[1] in ("auto-start", "auto-end", "html-end")))

        def step(st, kind):
            em, strong, link, image = st
            if kind[0] == "dr":
                role = kind[1]
                if role[0] in "oc" and role[2]:
                    d = 1 if role[0] == "o" else -1
                    if role[1] == 1:
                        em = max(0, min(MAX_DEPTH, em + d))
                    else:
                        strong = max(0, min(MAX_DEPTH, strong + d))
                ns = (em, strong, link, image)
                return ("ds", role[0] != "lit") + ns, ns
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
            ns = (em, strong, link, image)
            return ("bm", r) + ns, ns
        self.transduce("ltr", {g: pl.kind_of(g) for g in marks}, step, (0, 0, 0, 0))

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
        pl.chain([([], [amps], [{g_of(c)} for c in k], [(0, pl.nested({a: g for a in amps}))])
                  for k, g in keyed.items()])
        lig = ot.LigatureSubst()
        lig.ligatures = {}
        for ref, value in sorted(refs.items(), key=lambda rv: -len(rv[0])):
            L = ot.Ligature()
            L.Component = [g_of(c) for c in ref[1:]]
            L.LigGlyph = pl.var(g_of(value), ("ent",))
            L.CompCount = len(L.Component) + 1
            lig.ligatures.setdefault(keyed[key(ref)], []).append(L)
        pl.add(fb.lookup(4, [lig]))
        # A `&` that starts no reference goes back to being an `&`.
        pl.single({g: self.g["&"] for g in keyed.values()})
        self.alive |= {pl.var(g_of(v), ("ent",)) for v in set(refs.values())} | {self.g["&"]}

    def paint(self):
        """Every glyph becomes its final glyph: a styled glyph or, for
        markup, an invisible one that records the state after it. The state
        is (em, strong, code, link, image, html, tail); glyphs in image or
        HTML style record a fixed state, and the next marker restores the
        rest."""
        pl, b = self.pl, self.b
        made = {}

        def hid(state):
            if ("hid", state) not in made:
                made[("hid", state)] = b.empty(f"_hid{len(made)}", 0)
                self.styled_key[made[("hid", state)]] = ("hidden", state)
            return made[("hid", state)]

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

        def shown(g, state):
            em, strong, code, link, image, html, tail = state
            if html:
                return fb.styled(pl.base_of(g), "h"), (False,) * 5 + (True, None)
            if image:
                return fb.styled(pl.base_of(g), "im"), (False,) * 4 + (True, False, None)
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
                proj[g] = pl.var(g, ("P", k[0], k[1]) + tuple(d > 0 for d in k[2:]))
            elif k[:2] in (("m", "OPEN"), ("m", "CLOSE"), ("m", "html-start"), ("m", "tail-end"), ("m", "bs-hide")):
                proj[g] = pl.var(g, ("P", k[1]))
            elif k == ("B", "ip-hide"):
                proj[g] = pl.var(g, ("P", "ip-hide"))
            else:
                proj[g] = pl.base_of(g)
        pl.single(proj)
        self.replace(proj.items())
        out, _ = pl.ltr({g: g for g in self.alive},
                        lambda s, g: _paint_step(s, g, pl.kind_of(g), hid, shown, html_end),
                        (False,) * 6 + (None,), skeleton=False, fill_backtrack=True)
        self.alive = set(out.values())


def _paint_step(state, g, k, hid, shown, html_end):
    em, strong, code, link, image, html, tail = state
    role = k[1] if k[:1] == ("P",) else None
    if tail == "hide":                     # a link destination: hidden up to its end
        ns = state[:6] + (None,) if role == "tail-end" else state
        return hid(ns), ns
    if role == "ds":
        _, _, hide, e, st, lk, im = k
        ns = (e, st, code, lk, im, html, tail)
        return (hid(ns), ns) if hide else shown(g, ns)
    if role == "bm":
        _, _, r, e, st, lk, im = k
        ns = (e, st, code, lk, im, False, "hide" if r in ("L", "Lm", "img-close") else tail)
        if r == "html-end":
            return html_end(ns), ns
        return hid(ns), ns
    if role == "html-start":
        return shown(g, state[:5] + (True, tail))
    if role in ("ip-hide", "bs-hide"):
        return hid(state), state
    if role in ("OPEN", "CLOSE"):
        ns = (em, strong, role == "OPEN", link, image, html, tail)
        return hid(ns), ns
    return shown(g, state)


# What precedes the `>` that ends each kind of raw HTML (None: the first `>`).
HTML_END = {"close": None, "decl": None, "comment": "--", "pi": "?", "cdata": "]]"}


def _main_step(state, sym):
    ch, kind = sym
    mode, cnt = state
    tag = kind[0]
    back = ("N", cnt)
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
    if tag == "dl":
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


def _rep_moves(kind):
    """What can happen to an emphasis run's first character in a round."""
    _, n, o, c, r, closes, opens, st = kind
    out = {}
    for u in (1, 2):
        if r >= u and st == "s":
            out[("open", u)] = ("rep", n, o, c, r - u, closes, opens + (u,), "d" if r == u else "s")
        if r >= u and st == "u":
            out[("close", u)] = ("rep", n, o, c, r - u, closes + (u,), opens, "d" if r == u else "u")
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


def build(base, bold, italic, bold_italic):
    mf = MarkdownFont(base, bold, italic, bold_italic)
    for stage in ("html_validity", "gt_ends", "escapes", "backtick_runs", "code_closers", "delimiter_runs",
                  "brackets_and_tails", "tail_validity", "main_scan", "brackets", "emphasis", "style",
                  "entities", "paint"):
        getattr(mf, stage)()
    font = mf.b.finish(mf.pl.gsub(), mf.pl.mark_sets)
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
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    font, mf = build(args.base, args.bold, args.italic, args.bold_italic)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "Fontlex-Markdown.ttf"
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
