#!/usr/bin/env python3
"""Compare cm_inline with commonmark.js 0.31.2 on random lines.

    npm install --prefix /tmp/cm commonmark@0.31.2
    python markdown/crosscheck.py /tmp/cm/node_modules/commonmark --n 200000

Feeds each line to commonmark.js's inline parser directly (no block
parsing) and compares the HTML. The one known difference: inside HTML tags
commonmark.js counts any JavaScript \\s (such as a no-break space) as
whitespace, where the spec allows spaces, tabs and line endings only; those
lines are counted apart.
"""

import argparse
import json
import random
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cm_inline  # noqa: E402

SCRIPT = """
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

TOKENS = ["*", "*", "**", "_", "__", "***", "`", "``", "[", "]", "(", ")", "![", "](", "!", "<", ">", "\\", "&",
          ";", "#", '"', "'", " ", " ", "  ", "a", "b", "xy", "1", ":", "/", ".", "@", "-", "=", "?", "é", "жи",
          "α", "«", "»", "—", " ", "　", "http:", "mailto:", "<a", "</a>", "<b>", "<!--", "-->", "<?",
          "?>", "<![CDATA[", "]]>", "&amp;", "&copy;", "&#", "&#x", "41;", "\t", "~", "$", "+", "a@b.c"]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("commonmark", help="the commonmark.js package directory (node_modules/commonmark)")
    ap.add_argument("--n", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    lines = []
    for _ in range(args.n):
        s = "".join(rng.choice(TOKENS) for _ in range(rng.randint(1, 14))).strip(" \t 　")
        lines.append(s or "a")
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "inline.mjs"
        script.write_text(SCRIPT.format(lib=(Path(args.commonmark) / "lib").resolve()))
        js = json.loads(subprocess.run(["node", str(script)], input=json.dumps(lines), capture_output=True,
                                       text=True, check=True).stdout)
    differ = [(s, j) for s, j in zip(lines, js) if cm_inline.to_html(s) != j]
    known = [(s, j) for s, j in differ if any(c in s for c in " 　") and "<" in s]
    print(f"{len(lines)} lines: {len(lines) - len(differ)} the same, {len(known)} differ only where "
          f"commonmark.js counts other whitespace inside HTML tags, {len(differ) - len(known)} differ otherwise")
    for s, j in [d for d in differ if d not in known][:10]:
        print(f"  {s!r}\n    commonmark.js: {j!r}\n    cm_inline:     {cm_inline.to_html(s)!r}")
    return 1 if len(differ) > len(known) else 0


if __name__ == "__main__":
    sys.exit(main())
