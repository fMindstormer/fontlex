#!/usr/bin/env python3
"""Shape texts with HarfBuzz and another shaper and print both: glyph
names and positions, side by side, to see where they part.

    python engines/compare.py FONT.ttf directwrite [--features ss01,calt [--only]] TEXT ...

--only passes DirectWrite just those features, not the defaults with them.

A text may spell characters as \\uXXXX (`research\\uFE00`).
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import test_fontlex as T  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402


def main():
    font, other, *texts = sys.argv[1:]
    features, only = (), {}
    if texts[:1] == ["--features"]:
        features, texts = tuple(texts[1].split(",")), texts[2:]
    if texts[:1] == ["--only"]:
        only, texts = {"only": True}, texts[1:]
    data = Path(font).read_bytes()
    order = TTFont(font).getGlyphOrder()
    shapers = [T.HarfBuzz(data, features=features), T.SHAPERS[other](data, features=features, **only)]
    label = f" with {'+'.join(features)}{' only' if only else ''}" if features else ""
    for text in (re.sub(r"\\u([0-9A-Fa-f]{4})", lambda m: chr(int(m[1], 16)), t) for t in texts):
        (a, wa), (b, wb) = (s.shape(text) for s in shapers)
        print(f"{text!r}{label}: harfbuzz {len(a)} glyphs, width {wa}; {other} {len(b)} glyphs, width {wb}")
        for i in range(max(len(a), len(b))):
            ga = f"{order[a[i][0]]} {a[i][1]} {a[i][2]:.0f},{a[i][3]:.0f}" if i < len(a) else ""
            gb = f"{order[b[i][0]] if b[i][0] is not None else None} {b[i][1]} {b[i][2]:.0f},{b[i][3]:.0f}" if i < len(b) else ""
            print(f"  {'  ' if ga == gb else '≠ '}{ga:40} {gb}")


if __name__ == "__main__":
    main()
