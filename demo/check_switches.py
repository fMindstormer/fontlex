#!/usr/bin/env python3
"""Check a hint font's demo page in WebKit: each hint switch hides its hints.

Renders the page in an offscreen WKWebView (check_webkit.py), unticks each
hint switch in turn, and counts the text box's pixels in each hint color:
the unticked hint's color must fall to what the box shows with every hint
off (antialiased plain text can come near a pale color), and the others must
stay. macOS only; needs pyobjc-framework-WebKit.

    python demo/check_switches.py english/demo.html [--out DIR]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_webkit import RELAYOUT, SETTLE, Page, near, pixels  # noqa: E402

SWITCHES = ("[...document.querySelectorAll('input[data-feature]')].map((s) => [s.id, s.dataset.color,"
            " getComputedStyle(document.documentElement).getPropertyValue(s.dataset.color).trim()])")
SET = "(() => { const s = document.getElementById('%s'); s.checked = %s; s.dispatchEvent(new Event('change')); })();"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("page")
    ap.add_argument("--out", help="directory to save snapshots in")
    args = ap.parse_args()
    page = Page(Path(args.page))
    page.run(SETTLE + "document.documentElement.dataset.theme = 'light'; 1")
    switches = page.run(SWITCHES)
    if not switches:
        sys.exit(f"{args.page} has no hint switches")

    def counts(name, ticked):
        page.run("".join(SET % (i, "true" if i in ticked else "false") for i, _, _ in switches) + RELAYOUT + "1")
        page.spin(0.5)
        rep = page.snapshot_code()
        if args.out:
            Path(args.out).mkdir(parents=True, exist_ok=True)
            rep.representationUsingType_properties_(4, None).writeToFile_atomically_(f"{args.out}/{name}.png", True)
        px = list(pixels(rep))
        return {i: near(px, color) for i, _, color in switches}
    ids = [i for i, _, _ in switches]
    every, none = counts("all", ids), counts("none", [])
    failed = 0
    for i, var, _ in switches:
        got = counts(f"no-{i}", [j for j in ids if j != i])
        hidden = got[i] <= none[i] * 1.2 + 5 < every[i]
        kept = all(got[j] >= every[j] * 0.8 for j in ids if j != i)
        failed += not (hidden and kept)
        print(f"{'ok  ' if hidden and kept else 'FAIL'} {i} unticked: {var} pixels {got[i]} (all hints {every[i]}, "
              f"none {none[i]}); others {', '.join(f'{j} {got[j]}/{every[j]}' for j in ids if j != i)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
