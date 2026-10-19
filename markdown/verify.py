#!/usr/bin/env python3
"""Check the Markdown font against the CommonMark model, character by character.

    python markdown/verify.py build/Fontlex-Markdown.ttf [--shaper coretext] [--n 20000]

Shapes CommonMark's single-line spec examples and random lines, reads each
glyph's role back (hidden, or text in some style, or a block marker) and
compares it with what cm_block.roles says GitHub Flavored Markdown makes of
that character, the line read as a whole document.
"""

import argparse
import io
import json
import random
import re
import unicodedata
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import bounds  # noqa: E402
import cm_block  # noqa: E402
import cm_inline  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402

LETTERS = {"c": "code", "b": "strong", "i": "em", "l": "link", "e": "link"}     # (e: in an email)
OVERLAY = cm_inline.Role("overlay")      # a strikethrough line drawn back over the glyph before


class FontView:
    """Reads a shaped glyph back as a cm_inline.Role."""

    def __init__(self, data):
        tt = TTFont(io.BytesIO(data))
        self.order = tt.getGlyphOrder()
        self.cmap = tt.getBestCmap()

    def role(self, gid):
        name = self.order[gid]
        if name.endswith(".st"):             # a struck space
            role, base = self.named(name[:-3])
            return cm_inline.Role(role.kind, role.style | {"strike"}, role.char), base
        return self.named(name)

    def named(self, name):
        if name.startswith(("_hid", "_hs", "_hu")):
            return cm_inline.HIDDEN, None
        if name.startswith("_st"):
            return OVERLAY, None
        if name.startswith("_mk_"):          # a block marker: bullet, quote, rule, box, checked
            return cm_inline.Role(name[4:].rstrip("0123456789")), None
        base, _, suffix = name.partition("__")
        if base.startswith("_"):
            return cm_inline.Role("leak", char=name), None
        if suffix[:1] == "h":    # h; h<n>, a `>` ending raw HTML that restores the style; hb, a heading's #s
            return cm_inline.Role("dim"), base
        if suffix == "k":        # the last column of a code block's indentation
            return cm_inline.Role("text"), base
        if suffix == "im":
            return cm_inline.Role("text", frozenset({"image"})), base
        return cm_inline.Role("text", frozenset(LETTERS[ch] for ch in suffix)), base


def drawn(role):
    """A role as the font draws it: a heading's text is strong."""
    if "heading" in role.style:
        return cm_inline.Role(role.kind, role.style - {"heading"} | {"strong"}, role.char)
    return role


def check(view, shaper, line):
    """None if the font draws `line` as GitHub would, else a description."""
    glyphs, _ = shaper.shape(line)
    want = [drawn(r) for r in cm_block.roles(line, gfm=True, code_padding=True)]
    seen = []
    for gid, i, _, _ in glyphs:
        if gid is not None and view.role(gid)[0] == OVERLAY:
            # (Core Text gives an overlay after a ligature, an entity, the
            # index of a later character of the ligature.)
            ends = [c for g, c, _, _ in glyphs if c > i and (g is None or view.role(g)[0] != OVERLAY)]
            if not seen or not seen[-1][1] <= i < min(ends, default=len(line)):
                return f"char {i}: a strikethrough overlay without its glyph"
            g0, i0, got0, b0 = seen[-1]
            if got0.kind in ("text", "entity", "dim"):
                seen[-1] = (g0, i0, cm_inline.Role(got0.kind, got0.style | {"strike"}, got0.char), b0)
            continue
        seen.append((gid, i) + (view.role(gid) if gid is not None else (None, None)))
    # A hidden marker the font put in (a bare URL's start or end) shares
    # its cluster with the character next to it.
    runs = {}
    for x in seen:
        runs.setdefault(x[1], []).append(x)
    seen = [next((x for x in run if x[2] != cm_inline.HIDDEN), run[-1]) if len(run) > 1 else run[0]
            for run in runs.values()]
    clusters = [cl for _, cl, _, _ in seen]
    if clusters != sorted(set(clusters)):
        return f"clusters out of order: {clusters}"
    for gid, i, got, base in seen:
        if gid is None:
            continue    # drawn from a fallback font (a character the font lacks)
        # A shaper may compose a character with a following combining mark into
        # one glyph; that glyph is compared with the first character's role.
        if base is not None and ord(line[i]) not in view.cmap:
            base = None    # no glyph of its own (a tab): compare the role only
        w = want[i]
        if w.kind == "entity":
            ok = got.kind == "text" and got.style == w.style and base == view.cmap.get(ord(w.char[0]))
        elif got.kind == "text":
            ok = w == got and (base is None or base == view.cmap.get(ord(line[i]))
                                or i + 1 < len(line) and unicodedata.combining(line[i + 1]))
        else:
            ok = w == got
        if not ok:
            return f"char {i} {line[i]!r}: font {fmt(got)}, CommonMark {fmt(w)}"
    return None


def fmt(r):
    return r.kind + ("(" + "+".join(sorted(r.style)) + ")" if r.style else "") + (f" {r.char!r}" if r.char else "")


def spec_lines(path, exclude=""):
    """Single-line examples, and each line of an example of one-line
    paragraphs."""
    for e in json.load(open(path)):
        md = e["markdown"]
        parts = md[:-1].split("\n\n") if md.endswith("\n") else []
        if parts and all(p and "\n" not in p for p in parts):
            for k, part in enumerate(parts):
                if not any(c in part for c in exclude):
                    yield (e["example"] if len(parts) == 1 else f"{e['example']}.{k + 1}"), part


def markdown_lines(paths):
    """The lines of Markdown files that hold inline text: fenced and
    indented code blocks and blank lines left out."""
    for path in paths:
        fence = None
        for line in Path(path).read_text(encoding="utf-8", errors="replace").split("\n"):
            m = re.match(r" {0,3}(`{3,}|~{3,})", line)
            if fence:
                if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                    fence = None
                continue
            if m:
                fence = m.group(1)
                continue
            if line.strip() and not line.startswith("    "):
                yield line.rstrip("\r")


def random_lines(n, seed, tokens):
    rng = random.Random(seed)
    for _ in range(n):
        s = "".join(rng.choice(tokens) for _ in range(rng.randint(1, 16))).strip(" \t") or "a"
        yield s


PREFIXES = ["", " ", "  ", "   ", "    ", "\t", "> ", ">", "> > ", "- ", "+ ", "* ", "1. ", "12) ", "-\t", "- [ ] ",
            "- [x] ", "* [X] ", "> - [x] ", "1. [ ] ", "# ", "## ", "###### ", "####### ", "#", "```", "~~~", "---",
            "***", "_ _ _", "<div>", "<!-- ", "<a href=x>", "[a]: /u ", "-", "- - ", "> 1. "]


def block_lines(n, seed, tokens):
    """Random lines behind random block markup (a few of them nested)."""
    rng = random.Random(seed)
    for line in random_lines(n, seed + 1, tokens):
        yield "".join(rng.choice(PREFIXES) for _ in range(rng.choice((1, 1, 2)))) + line


TOKENS = ["*", "*", "**", "_", "__", "***", "`", "``", "\\", "a", "b", "xy", " ", " ", ".", "!",
          "(", ")", "é", "жи", "α", "«", "»", "\u00a0", "\u0301", "#", "-", "1",
          "[", "[", "]", "]", "](", "![", '"', "'", "](/u)", "[a](b)", "](<x>)", ' "t"', "(c)",
          "<", ">", "&", "&amp;", ";", "\t", "/", ":", "http:", "<a>", "@",
          "~", "~~", "~", "> ", "- ", "+", "1.", "[ ]", "[x]", "    ", "---", "```",
          "www.", "http://", "https://", "x.y", "a_b", "a@b.c", ".", ")", "("]


def main(argv=None):
    import test_fontlex as T
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("font")
    ap.add_argument("--shaper", action="append", choices=sorted(T.SHAPERS),
                    help="harfbuzz (the default) and/or coretext; repeatable")
    ap.add_argument("--spec", default=str(HERE / "spec-0.31.2.json"))
    ap.add_argument("--gfm-spec", default=str(HERE / "gfm-spec-0.29-extensions.json"))
    ap.add_argument("--n", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--exclude", default="", help="leave out lines with these characters")
    ap.add_argument("--show", type=int, default=10)
    ap.add_argument("--corpus", nargs="*", default=[], help="Markdown files whose lines to check too")
    args = ap.parse_args(argv)
    data = Path(args.font).read_bytes()
    view = FontView(data)
    failed = 0
    for name in args.shaper or ["harfbuzz"]:
        failed += run(view, T.SHAPERS[name](data), name, args)
    return 1 if failed else 0


def run(view, shaper, shaper_name, args):
    failed = 0
    sets = [("spec examples", ((f"example {n}", l) for n, l in spec_lines(args.spec, args.exclude))),
            ("GFM extension examples", ((f"example {n}", l) for n, l in spec_lines(args.gfm_spec, args.exclude))),
            ("random lines", ((repr(l), l) for l in random_lines(args.n, args.seed, [
                t for t in TOKENS if not any(c in t for c in args.exclude)]))),
            ("block lines", ((repr(l), l) for l in block_lines(args.n // 4, args.seed, [
                t for t in TOKENS if not any(c in t for c in args.exclude)])))]
    if args.corpus:
        sets.append(("corpus lines", ((repr(l), l) for l in markdown_lines(args.corpus))))
    for label, lines in sets:
        total = bad = past = past_ok = 0
        for name, line in lines:
            total += 1
            err = check(view, shaper, line)
            over = bounds.exceeds(line, view.cmap)
            if over:
                past += 1
                past_ok += err is None
            elif err:
                bad += 1
                if bad <= args.show:
                    print(f"  {name}: {line!r}\n      {err}")
        within = total - past
        print(f"{label}: {within - bad}/{within} within the bounds as CommonMark; "
              f"{past} past them ({past_ok} of those still right) ({shaper_name})")
        failed += bad
    return failed


if __name__ == "__main__":
    sys.exit(main())
