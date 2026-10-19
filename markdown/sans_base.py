"""Make the proportional edition's base fonts from Noto Sans.

    python markdown/sans_base.py NOTO_DIR --out fonts

NOTO_DIR holds Google Fonts' variable Noto Sans, `NotoSans[wdth,wght].ttf`
and `NotoSans-Italic[wdth,wght].ttf` (github.com/google/fonts, ofl/notosans).
Each style is instanced at normal width (regular 400, bold 700) and subset to
the characters JetBrains Mono also has, since the Markdown font copies every
text glyph for each style and pass state and so can't afford Noto Sans's
3,000 characters. Kerning and mark positioning are kept; the base GSUB isn't
(the Markdown font replaces it).
"""

import argparse
import sys
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

HERE = Path(__file__).resolve().parent
STYLES = {"Regular": ("", 400), "Bold": ("", 700), "Italic": ("-Italic", 400), "BoldItalic": ("-Italic", 700)}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("noto_dir")
    ap.add_argument("--mono", default=str(HERE.parent / "fonts" / "JetBrainsMono-Regular.ttf"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    mono = set(TTFont(args.mono).getBestCmap())
    out = Path(args.out)
    for style, (file_suffix, weight) in STYLES.items():
        vf = TTFont(Path(args.noto_dir) / f"NotoSans{file_suffix}[wdth,wght].ttf")
        font = instancer.instantiateVariableFont(vf, {"wght": weight, "wdth": 100}, updateFontNames=True)
        opts = subset.Options()
        opts.layout_features = ["kern", "mark", "mkmk"]
        opts.drop_tables += ["GSUB"]
        opts.glyph_names = True
        opts.name_IDs = ["*"]
        opts.notdef_outline = True
        opts.hinting = False
        sub = subset.Subsetter(opts)
        sub.populate(unicodes=sorted(set(font.getBestCmap()) & mono))
        sub.subset(font)
        path = out / f"NotoSans-{style}.ttf"
        font.save(path)
        print(f"wrote {path}: {len(font.getBestCmap())} characters, {len(font.getGlyphOrder())} glyphs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
