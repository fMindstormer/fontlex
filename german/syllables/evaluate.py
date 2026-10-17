#!/usr/bin/env python3
"""Score the syllable font against hand-labeled reading syllables.

Shapes each word through the compiled font, reads the syllables back from
the colors (a new syllable starts where the color changes), and compares
them with word lists like words-dev.txt ("Ba-na-ne Zu-cker ...").

    python german/syllables/evaluate.py build/Fontlex-German-Syllables.ttf \\
        german/syllables/words-heldout.txt [--shaper coretext]
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from fontTools.ttLib import TTFont  # noqa: E402

import fontlex  # noqa: E402
import test_fontlex  # noqa: E402


def syllables(font_data, order, shaper, word):
    glyphs, _ = shaper.shape(word)
    out, prev = "", None
    for (gid, ci, *_), ch in zip(glyphs, word):
        name = order[gid] if gid is not None else ""
        color = name.split(fontlex.WORD_SUFFIX)[1] if fontlex.WORD_SUFFIX in name else None
        if prev and color != prev:
            out += "-"
        out += ch
        prev = color
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("font")
    ap.add_argument("lists", nargs="+")
    ap.add_argument("--shaper", default="harfbuzz", choices=["harfbuzz", "coretext"])
    args = ap.parse_args()
    data = open(args.font, "rb").read()
    order = TTFont(args.font).getGlyphOrder()
    shaper = test_fontlex.SHAPERS[args.shaper](data)
    for path in args.lists:
        gold = Path(path).read_text(encoding="utf-8").split()
        wrong = []
        for g in gold:
            got = syllables(data, order, shaper, g.replace("-", ""))
            if got != g:
                wrong.append(f"{g} (font: {got})")
        print(f"{args.shaper}: {Path(path).name}: {len(gold) - len(wrong)}/{len(gold)} words right"
              + (": wrong " + ", ".join(wrong) if wrong else ""))


if __name__ == "__main__":
    main()
