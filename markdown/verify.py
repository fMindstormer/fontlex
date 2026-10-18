#!/usr/bin/env python3
"""Check the Markdown font against the CommonMark model, character by character.

    python markdown/verify.py build/Fontlex-Markdown.ttf [--shaper coretext] [--n 20000]

Shapes CommonMark's single-line spec examples and random lines, reads each
glyph's role back (hidden, or text in some style) and compares it with what
cm_inline.roles says CommonMark makes of that character.
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
import cm_inline  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402

LETTERS = {"c": "code", "b": "strong", "i": "em", "l": "link"}


class FontView:
    """Reads a shaped glyph back as a cm_inline.Role."""

    def __init__(self, data):
        tt = TTFont(io.BytesIO(data))
        self.order = tt.getGlyphOrder()
        self.cmap = tt.getBestCmap()

    def role(self, gid):
        name = self.order[gid]
        if name.startswith("_hid"):
            return cm_inline.HIDDEN, None
        base, _, suffix = name.partition("__")
        if base.startswith("_"):
            return cm_inline.Role("leak", char=name), None
        if suffix[:1] == "h":    # h, or h<n>: a `>` ending raw HTML that restores the style
            return cm_inline.Role("html"), base
        if suffix == "im":
            return cm_inline.Role("text", frozenset({"image"})), base
        return cm_inline.Role("text", frozenset(LETTERS[ch] for ch in suffix)), base


def check(view, shaper, line):
    """None if the font draws `line` as CommonMark would, else a description."""
    glyphs, _ = shaper.shape(line)
    want = cm_inline.roles(line, code_padding=True)
    clusters = [cl for _, cl, _, _ in glyphs]
    if clusters != sorted(set(clusters)):
        return f"clusters out of order: {clusters}"
    for gid, i, _, _ in glyphs:
        if gid is None:
            continue    # drawn from a fallback font (a character the font lacks)
        # A shaper may compose a character with a following combining mark into
        # one glyph; that glyph is compared with the first character's role.
        got, base = view.role(gid)
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
    for e in json.load(open(path)):
        md = e["markdown"]
        if md.count("\n") == 1 and md.endswith("\n") and not any(c in md for c in exclude):
            yield e["example"], md[:-1]


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


TOKENS = ["*", "*", "**", "_", "__", "***", "`", "``", "\\", "a", "b", "xy", " ", " ", ".", "!",
          "(", ")", "é", "жи", "α", "«", "»", "\u00a0", "\u0301", "#", "-", "1",
          "[", "[", "]", "]", "](", "![", '"', "'", "](/u)", "[a](b)", "](<x>)", ' "t"', "(c)",
          "<", ">", "&", "&amp;", ";", "\t", "/", ":", "http:", "<a>", "@"]


def main(argv=None):
    import test_fontlex as T
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("font")
    ap.add_argument("--shaper", action="append", choices=sorted(T.SHAPERS),
                    help="harfbuzz (the default) and/or coretext; repeatable")
    ap.add_argument("--spec", default=str(HERE / "spec-0.31.2.json"))
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
            ("random lines", ((repr(l), l) for l in random_lines(args.n, args.seed, [
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
