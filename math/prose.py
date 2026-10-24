#!/usr/bin/env python3
"""What the relaxed rules (relaxed.py) would typeset in ordinary text.

    python math/prose.py FILE ... [--show N]

Every line of the files is read the way the font would read it; the
constructs laid out and the symbols drawn are counted and listed, most
common first. In prose, each one is a false alarm unless it is math.
"""

import argparse
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import relaxed as R  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--show", type=int, default=40, help="distinct constructs to list")
    args = ap.parse_args()
    lines = hit = 0
    found = collections.Counter()
    symbols = collections.Counter()
    for path in args.files:
        for line in Path(path).read_text(errors="replace").splitlines():
            lines += 1
            got = R.constructs(line)
            if got:
                hit += 1
                found.update(got)
            symbols.update(t[3] for t in R.Parser(line).toks if t[0] == "sym")
    print(f"{lines:,} lines, {hit:,} with a construct ({sum(found.values()):,} constructs, "
          f"{len(found):,} distinct)")
    for (kind, src), n in found.most_common(args.show):
        print(f"  {n:6,}  {kind:5} {src}")
    print("symbols:", ", ".join(f"{s} {n:,}" for s, n in symbols.most_common()) or "none")


if __name__ == "__main__":
    main()
