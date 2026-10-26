#!/usr/bin/env python3
"""Pack the Relaxed Math demo for a release:
build/fontlex-relaxed-math-demo-<version>.zip.

    python math/package_demo.py 0.4.0

The zip holds the demo page (math/relaxed.html, which carries the font and
its styles inside, so it opens from disk with no server: browsers won't load
a font file next to a page opened from disk), the font as TTF and WOFF2, a
stylesheet for using the font on your own site, the licenses and a README
naming the commit it was built from. Entries are sorted and dated by that
commit, so the same commit gives the same zip.
"""

import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "fontlex-relaxed-math-demo"

CSS = """/* Fontlex Relaxed Math on your own page. Serve this file with the WOFF2
   next to it (a page opened from disk can't load font files: see README.txt). */
@font-face {
  font-family: "Fontlex Relaxed Math";
  src: url(Fontlex-RelaxedMath.woff2) format("woff2");
}
textarea.relaxed-math {
  font: 1.6rem/2.7 "Fontlex Relaxed Math", ui-monospace, monospace;
  white-space: pre;
}
"""

README = """Fontlex Relaxed Math {version}
https://github.com/fMindstormer/fontlex

A font that typesets math the way people type it in plain text:
(a+b)/(c+d) becomes a fraction, x^2 a superscript, sqrt(x^2+1) a square
root, as you type, in an ordinary text box. No script processes the text:
the font's OpenType substitution and positioning rules do the work, and the
characters stay exactly as typed.

Try it
------
Open index.html in Chrome, Edge or Safari, and type into the box. The page
holds the font and its styles inside, so it needs no server and no build
step. "Font rules" turns the font's rules off and on.

Use it on your own page
-----------------------
Serve Fontlex-RelaxedMath.woff2 and relaxed-math.css together, link the
stylesheet, and give a text box the class relaxed-math. (Browsers won't
load a font file for a page opened from disk, which is why index.html
carries its own copy.) Fontlex-RelaxedMath.ttf is the same font for desktop
apps that use HarfBuzz or Core Text.

What it typesets
----------------
- Fractions: 1/2, x/2, 2a/3, (a+b)/(c+d), f(x)/2, 1/(1+1/x)
- Scripts: x^2, x^(n+1), x^-1, x_1, H_2O, and both at once, x_i^2
- Roots: sqrt(x^2+1)
- <= >= != -> => +- as the symbols they stand for

Ordinary text stays text: and/or, w/o, km/h, C/C++, 10/23/2026.

Limits
------
- Not LaTeX, and not a general math engine: only the constructs above.
- Constructs nest 3 deep, with at most 2 fractions inside one another and at
  most 24 characters in a construct that isn't inside another.
- A space inside a construct leaves it as its characters: (a+b)/2 is
  typeset, (a + b)/2 isn't.
- Chrome shapes Greek and Latin letters as separate runs, so a construct
  that mixes them, like e^(iπ), stays as its characters there. Safari
  lays it out.
- A part is a whole word: 2/3x is 2 over 3x, and x^2y is x squared, then y.
  A number over a number is always a fraction, so 7/8 bit and a date like
  6/14 are typeset too.
- Each line is read on its own. Inside a fraction the caret stays at the
  fraction's start.

Tested
------
20,051 lines compared glyph by glyph with a separate model of the notation,
in HarfBuzz 14.6.0 (the shaper in Chrome, Edge and Firefox) and Core Text
(Safari, macOS): all the same. In Chrome 155, 348 of 349 lines draw the
same pixels as HarfBuzz's layout (the other mixes Greek and Latin); in
Safari's WebKit, 322 of 323, and the last is 1 pixel apart. Firefox itself
and Windows are not tested yet.

Built from commit {commit}.

Licenses
--------
The font is a modified version of JetBrains Mono, under the SIL Open Font
License 1.1 (OFL-JetBrainsMono.txt). The page's code is under the MIT
License (LICENSE.txt).
"""


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    version = sys.argv[1]
    commit = git("rev-parse", "HEAD")
    if git("status", "--porcelain", "--", "math/relaxed.html", "build/Fontlex-RelaxedMath.ttf",
           "build/Fontlex-RelaxedMath.woff2"):
        sys.exit("the page or the font differs from the commit: commit them first")
    date = time.gmtime(int(git("show", "-s", "--format=%ct", "HEAD")))[:6]
    files = {
        "index.html": (ROOT / "math" / "relaxed.html").read_bytes(),
        "Fontlex-RelaxedMath.ttf": (ROOT / "build" / "Fontlex-RelaxedMath.ttf").read_bytes(),
        "Fontlex-RelaxedMath.woff2": (ROOT / "build" / "Fontlex-RelaxedMath.woff2").read_bytes(),
        "relaxed-math.css": CSS.encode(),
        "README.txt": README.format(version=version, commit=commit).encode(),
        "LICENSE.txt": (ROOT / "LICENSE").read_bytes(),
        "OFL-JetBrainsMono.txt": (ROOT / "fonts" / "OFL.txt").read_bytes(),
    }
    out = ROOT / "build" / f"{NAME}-{version}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            info = zipfile.ZipInfo(f"{NAME}-{version}/{name}", date)
            info.external_attr = 0o644 << 16
            z.writestr(info, files[name], zipfile.ZIP_DEFLATED, 9)
    print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB), commit {commit[:7]}")


if __name__ == "__main__":
    main()
