#!/usr/bin/env python3
"""Check the Markdown demo page in WebKit, the engine Safari uses.

Renders the page in an offscreen WKWebView and snapshots the text box: with
each palette, the link and image colors and the code background must appear;
with "Render Markdown" off, the colors must not, and the background must be
mostly gone (antialiased text has some pixels of that gray). Raw HTML's gray
can't be told from antialiasing; verify.py checks it glyph by glyph. A page
with an edition menu is checked in each edition. macOS only; needs
pyobjc-framework-WebKit.

    python markdown/check_webkit.py markdown/demo.html [--out DIR]
"""

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import fontbuild  # noqa: E402
from demo.check_webkit import SETTLE, Page, near, pixels  # noqa: E402

PALETTE = "(() => {{ const p = document.getElementById('pal'); p.value = '{}'; p.dispatchEvent(new Event('change')); }})();"
TOGGLE = "(() => {{ const h = document.getElementById('hl'); h.checked = {}; h.dispatchEvent(new Event('change')); }})();"
EDITION = ("(() => {{ const e = document.getElementById('edition'); if (e) {{ e.value = '{}'; "
           "e.dispatchEvent(new Event('change')); }} }})();")
HAS_EDITIONS = "document.getElementById('edition') !== null"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("page")
    ap.add_argument("--out", help="directory to save snapshots in")
    args = ap.parse_args()
    page = Page(Path(args.page))
    failed = 0
    theme = "document.documentElement.dataset.theme = '{}';"
    editions = ("mono", "sans") if page.run(HAS_EDITIONS) else ("mono",)
    for edition in editions:
        shown = None
        for name, script, palette in (
                ("light", theme.format("light") + PALETTE.format("auto") + TOGGLE.format("true"), "light"),
                ("dark", theme.format("dark") + PALETTE.format("auto") + TOGGLE.format("true"), "dark"),
                ("source", theme.format("light") + PALETTE.format("auto") + TOGGLE.format("false"), None)):
            page.run(EDITION.format(edition) + script + SETTLE)
            page.spin(0.5)
            rep = page.snapshot_code()
            label = name if len(editions) == 1 else f"{edition}-{name}"
            if args.out:
                Path(args.out).mkdir(parents=True, exist_ok=True)
                rep.representationUsingType_properties_(4, {}).writeToFile_atomically_(f"{args.out}/{label}.png", True)
            px = list(pixels(rep))
            colors = fontbuild.PALETTES[palette or "light"]
            counts = {k: near(px, colors[k], 30 if k != "bg" else 8) for k in ("link", "image", "bg")}
            if palette:
                ok = all(counts.values())
                shown = shown or counts["bg"]
            else:
                ok = not counts["link"] and not counts["image"] and counts["bg"] < 0.2 * shown
            failed += not ok
            print(f"{label:12} {'ok' if ok else 'FAILED'}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
