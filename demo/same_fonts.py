"""Whether a rebuilt file is the committed one but for how Brotli compressed
its fonts, which can differ by machine with the same Brotli (Fontlex Math's
WOFF2 did by 280 bytes; a page embedding Fontlex Markdown did too): a .woff2
file, or a page with fonts in data:font/woff2 URLs, compared by the fonts
they hold. Exits 0 if it is.

    python demo/same_fonts.py COMMITTED REBUILT
"""

import base64
import re
import sys
from io import BytesIO

from fontTools.ttLib import TTFont

URL = re.compile(rb"data:font/woff2;base64,([A-Za-z0-9+/=]+)")


def ttf(data):
    font = TTFont(BytesIO(data), recalcTimestamp=False)
    font.flavor = None
    out = BytesIO()
    font.save(out)
    return out.getvalue()


def held(data):
    """The fonts a file holds, and the rest of it."""
    if data[:4] == b"wOF2":
        return [ttf(data)], b""
    return [ttf(base64.b64decode(m.group(1))) for m in URL.finditer(data)], URL.sub(b"data:font/woff2;base64,", data)


def main(argv):
    committed, rebuilt = (open(p, "rb").read() for p in argv[1:3])
    return 0 if held(committed) == held(rebuilt) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
