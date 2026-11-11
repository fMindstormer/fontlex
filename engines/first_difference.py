#!/usr/bin/env python3
"""Find the first substitution lookup where another shaper parts from
HarfBuzz on a text: copies of the font with only the first k lookups of its
GSUB features on, searched by bisection.

    python engines/first_difference.py FONT.ttf directwrite TEXT

The copies patch the features' lookup counts in the font's bytes, so each
is made at once; a feature's lookup indices must be in increasing order,
as they are in the Fontlex fonts.
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import test_fontlex as T  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402


def table_offset(data, tag):
    n = struct.unpack(">H", data[4:6])[0]
    for i in range(n):
        rec = data[12 + 16 * i:28 + 16 * i]
        if rec[:4] == tag:
            return struct.unpack(">I", rec[8:12])[0]
    raise KeyError(tag)


def features(data):
    """(offset of LookupIndexCount, the lookup indices) for each GSUB feature."""
    gsub = table_offset(data, b"GSUB")
    flist = gsub + struct.unpack(">H", data[gsub + 6:gsub + 8])[0]
    out = []
    for i in range(struct.unpack(">H", data[flist:flist + 2])[0]):
        rec = flist + 2 + 6 * i
        feat = flist + struct.unpack(">H", data[rec + 4:rec + 6])[0]
        n = struct.unpack(">H", data[feat + 2:feat + 4])[0]
        out.append((feat + 2, struct.unpack(f">{n}H", data[feat + 4:feat + 4 + 2 * n])))
    return out


def first_k(data, feats, k):
    """The font with only lookups below k on (checksums aren't fixed; shapers don't check them)."""
    b = bytearray(data)
    for at, indices in feats:
        b[at:at + 2] = struct.pack(">H", sum(1 for i in indices if i < k))
    return bytes(b)


def shaped(shaper_class, data, text):
    glyphs, width = shaper_class(data).shape(text)
    return [(g, round(x), round(y)) for g, _, x, y in glyphs], round(width)


def main():
    path, other, text = sys.argv[1:4]
    data = Path(path).read_bytes()
    feats = features(data)
    top = max(max(ix) for _, ix in feats) + 1
    same = lambda k: shaped(T.HarfBuzz, first_k(data, feats, k), text) == \
        shaped(T.SHAPERS[other], first_k(data, feats, k), text)  # noqa: E731
    if same(top):
        print(f"{text!r}: the same with every lookup")
        return
    lo, hi = 0, top          # same with lookups < lo, differs with lookups < hi
    while hi - lo > 1:
        mid = (lo + hi) // 2
        lo, hi = (mid, hi) if same(mid) else (lo, mid)
    f = TTFont(path)
    lookup = f["GSUB"].table.LookupList.Lookup[lo]
    sub = lookup.SubTable[0]
    inner = sub.ExtSubTable if lookup.LookupType == 7 else sub
    print(f"{text!r}: differs from lookup {lo} on: type {lookup.LookupType}"
          f"{' (extension of type ' + str(sub.ExtensionLookupType) + ')' if lookup.LookupType == 7 else ''}, "
          f"format {getattr(inner, 'Format', '?')}, flag 0x{lookup.LookupFlag:04x}, "
          f"mark filtering set {getattr(lookup, 'MarkFilteringSet', None)}, {lookup.SubTableCount} subtables")
    order = f.getGlyphOrder()
    for k in (lo, lo + 1):
        for cls in (T.HarfBuzz, T.SHAPERS[other]):
            gl, w = shaped(cls, first_k(data, feats, k), text)
            print(f"  lookups < {k}, {cls.name}: {' '.join(order[g] for g, _, _ in gl)}")


if __name__ == "__main__":
    main()
