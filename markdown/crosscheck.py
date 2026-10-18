#!/usr/bin/env python3
"""Compare the CommonMark model with the reference implementations on random lines.

    npm install --prefix /tmp/cm commonmark@0.31.2
    pip install cmarkgfm==2025.10.22          # for --mode gfm (cmark-gfm 0.29.0.gfm.13)
    python markdown/crosscheck.py /tmp/cm/node_modules/commonmark --mode inline --n 100000

Modes:
- inline: each line through commonmark.js's inline parser alone, against
  cm_inline. The one known difference: inside HTML tags commonmark.js counts
  any JavaScript \\s (such as a no-break space) as whitespace, where the spec
  allows spaces, tabs and line endings only.
- block: each line as a whole document through commonmark.js, against
  cm_block (block quotes, lists, headings, code and HTML blocks, ...).
- gfm: each line through cmark-gfm with its strikethrough, autolink and
  tasklist extensions, against cm_block with `gfm`. cmark-gfm's core follows
  an older CommonMark (0.29), so lines where its core and commonmark.js
  disagree are left out; link destinations (which the font hides) aren't
  compared, as the two escape URLs differently. The one known difference
  left: between a link reference definition's parts, cmark-gfm also skips
  tabs where commonmark.js reads only spaces.
"""

import argparse
import json
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cm_block  # noqa: E402
import cm_inline  # noqa: E402

INLINE_SCRIPT = """
import InlineParser from "{lib}/inlines.js";
import Node from "{lib}/node.js";
import HtmlRenderer from "{lib}/render/html.js";
let input = "";
process.stdin.on("data", d => input += d);
process.stdin.on("end", () => {{
  const out = JSON.parse(input).map(s => {{
    const doc = new Node("document"), p = new Node("paragraph");
    doc.appendChild(p); p._string_content = s;
    InlineParser().parse(p);
    return new HtmlRenderer().render(doc).replace(/^<p>/, "").replace(/<\\/p>\\n$/, "");
  }});
  process.stdout.write(JSON.stringify(out));
}});
"""

DOCUMENT_SCRIPT = """
import {{ Parser, HtmlRenderer }} from "{lib}/index.js";
let input = "";
process.stdin.on("data", d => input += d);
process.stdin.on("end", () => {{
  const p = new Parser(), r = new HtmlRenderer();
  process.stdout.write(JSON.stringify(JSON.parse(input).map(s => r.render(p.parse(s)))));
}});
"""

TOKENS = ["*", "*", "**", "_", "__", "***", "`", "``", "[", "]", "(", ")", "![", "](", "!", "<", ">", "\\", "&",
          ";", "#", '"', "'", " ", " ", "  ", "a", "b", "xy", "1", ":", "/", ".", "@", "-", "=", "?", "é", "жи",
          "α", "«", "»", "—", " ", "　", "http:", "mailto:", "<a", "</a>", "<b>", "<!--", "-->", "<?",
          "?>", "<![CDATA[", "]]>", "&amp;", "&copy;", "&#", "&#x", "41;", "\t", "~", "$", "+", "a@b.c"]
# Block starts, in front of inline text.
PREFIXES = [">", "> ", ">>", "- ", "-", "* ", "+ ", "1. ", "2) ", "123456789. ", "1234567890. ", "# ", "## ",
            "###### ", "####### ", "#", "```", "``` js", "~~~", "~~~ a`b", "    ", "\t", " ", "  ", "   ", "<div>",
            "<div ", "</p>", "<!--", "<?", "<!X", "<![CDATA[", "<script>", "<a href='x'>", "<b>", "[a]: /u",
            "[a]: <x y> 't'", "[ ]: x", "***", "---", "___", "* * *", "- - -", "-- -", "**", "=", "==", "- [ ] ",
            "- [x] ", "[x] ", "-\t", ">\t", "1.\t", "#\t", " \t", "\t\t", "-  ", "-     ", "1.      "]
BLOCK_TOKENS = ["a", "b", " ", " ", "*", "**", "_", "`", "#", "##", "-", ">", "<", "[", "]", "(", ")", "!", "\\",
                "&amp;", "x", "\t", "'", '"', ":", "/", "1", ".", "é", "~", "=", "[a](b)"]
GFM_PREFIXES = ["", "", "", "> ", "- ", "* ", "1. ", "# ", "- [ ] ", "- [x] ", "* [X] ", "  ", "    "]
GFM_TOKENS = ["a", "b", "xy", " ", " ", "~", "~~", "~~~", "*", "**", "_", "`", "www.", "www.a.com", "http://",
              "https://", "ftp://", "HTTP://", "example.org", ".", ",", ":", ";", "?", "!", "(", ")", "@", "x@y.z",
              "mailto:", "xmpp:", "/", "-", "_", "&amp;", "&", "<", ">", "[", "]", "[a](b)", "<a>", "\\", "'", '"',
              "é", "1", "a.b", "c_d", "\t", "[x]", "w", "ww"]


def run_node(script, lib, lines):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "run.mjs"
        path.write_text(script.format(lib=(Path(lib) / "lib").resolve()))
        return json.loads(subprocess.run(["node", str(path)], input=json.dumps(lines), capture_output=True,
                                         text=True, check=True).stdout)


def random_lines(rng, n, prefixes, tokens, most):
    for _ in range(n):
        p = "".join(rng.choice(prefixes) for _ in range(rng.randint(0, 3))) if prefixes else ""
        yield p + "".join(rng.choice(tokens) for _ in range(rng.randint(1 if not prefixes else 0, most)))


def report(pairs, known=lambda s, ref: False, label="the reference"):
    differ = [(s, r, m) for s, r, m in pairs if r != m]
    known_n = sum(1 for s, r, m in differ if known(s, r))
    print(f"{len(pairs)} lines: {len(pairs) - len(differ)} the same, {known_n} known differences, "
          f"{len(differ) - known_n} differ otherwise")
    for s, r, m in [d for d in differ if not known(d[0], d[1])][:10]:
        print(f"  {s!r}\n    {label}: {r!r}\n    model: {m!r}")
    return 1 if len(differ) > known_n else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("commonmark", help="the commonmark.js package directory (node_modules/commonmark)")
    ap.add_argument("--mode", choices=("inline", "block", "gfm"), default="inline")
    ap.add_argument("--n", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    if args.mode == "inline":
        lines = [s.strip(" \t 　") or "a" for s in random_lines(rng, args.n, None, TOKENS, 14)]
        js = run_node(INLINE_SCRIPT, args.commonmark, lines)
        return report([(s, j, cm_inline.to_html(s)) for s, j in zip(lines, js)],
                      lambda s, j: any(c in s for c in " 　") and "<" in s, "commonmark.js")
    if args.mode == "block":
        lines = list(random_lines(rng, args.n, PREFIXES, BLOCK_TOKENS, 8))
        js = run_node(DOCUMENT_SCRIPT, args.commonmark, lines)
        return report([(s, j, cm_block.to_html(s)) for s, j in zip(lines, js)], label="commonmark.js")
    import cmarkgfm
    from cmarkgfm.cmark import Options
    unsafe = Options.CMARK_OPT_UNSAFE
    blank = lambda h: re.sub(r'(href|src)="[^"]*"', r'\1=""', h)
    lines = [rng.choice(GFM_PREFIXES) + "".join(rng.choice(GFM_TOKENS) for _ in range(rng.randint(1, 12)))
             for _ in range(args.n)]
    js = run_node(DOCUMENT_SCRIPT, args.commonmark, lines)
    pairs, skipped = [], 0
    for s, j in zip(lines, js):
        if blank(j) != blank(cmarkgfm.markdown_to_html(s, options=unsafe)):
            skipped += 1
            continue
        g = cmarkgfm.markdown_to_html_with_extensions(s, options=unsafe,
                                                      extensions=["strikethrough", "autolink", "tasklist"])
        pairs.append((s, blank(g), blank(cm_block.to_html(s, gfm=True))))
    print(f"(left out {skipped} lines where cmark-gfm's core and commonmark.js disagree)")
    return report(pairs, lambda s, g: "]:" in s and "\t" in s, "cmark-gfm")


if __name__ == "__main__":
    sys.exit(main())
