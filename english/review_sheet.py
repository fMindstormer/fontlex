#!/usr/bin/env python3
"""Build the review sheet: a page where a reviewer marks the font's hints for
the most frequent words, and the noun/verb pairs, right or wrong.

    python english/review_sheet.py CMUDICT --font build/Fontlex-English.woff2 --top 500 --out review.html

Each word is drawn in the font, with its CMUdict pronunciations in IPA and
its hints spelled out. Verdicts are saved by the published page in its `db`
store (collection `reviews`, one document per word, keyed `w:<word>` or
`pair:<word>`, apostrophes as `~`), with the hints that were judged, so they
can be read back and turned into fixes.
"""

import argparse
import base64
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import align  # noqa: E402
import verify  # noqa: E402

IPA = {"AA": "ɑ", "AE": "æ", "AO": "ɔ", "AW": "aʊ", "AY": "aɪ", "EH": "ɛ", "EY": "eɪ", "IH": "ɪ",
       "IY": "i", "OW": "oʊ", "OY": "ɔɪ", "UH": "ʊ", "UW": "u", "B": "b", "CH": "tʃ", "D": "d",
       "DH": "ð", "F": "f", "G": "ɡ", "HH": "h", "JH": "dʒ", "K": "k", "L": "l", "M": "m", "N": "n",
       "NG": "ŋ", "P": "p", "R": "ɹ", "S": "s", "SH": "ʃ", "T": "t", "TH": "θ", "V": "v", "W": "w",
       "Y": "j", "Z": "z", "ZH": "ʒ"}


def ipa(phones):
    """HTML: the pronunciation in IPA, the primary-stressed vowel bold."""
    out = []
    for p in phones:
        base, stress = re.sub(r"\d", "", p), p[-1] if p[-1].isdigit() else ""
        if base == "AH":
            sym = "ʌ" if stress in "12" else "ə"
        elif base == "ER":
            sym = "ɝ" if stress in "12" else "ɚ"
        else:
            sym = IPA[base]
        out.append(f"<b>{sym}</b>" if stress == "1" else sym)
    return "/" + "".join(out) + "/"


def stress_index(phones):
    vowels = [p for p in phones if p[-1].isdigit()]
    return next((i for i, p in enumerate(vowels) if p.endswith("1")), -1)


def key(prefix, word):
    return f"{prefix}:{word.replace(chr(39), '~')}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmudict")
    ap.add_argument("--font", required=True, help="the font as WOFF2")
    ap.add_argument("--lexicon", default=str(HERE / "lexicon"))
    ap.add_argument("--top", type=int, default=500)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    lex = verify.Lexicon(args.lexicon)
    prons = align.read_cmudict(args.cmudict)
    words = []
    for rank, (w, hints) in enumerate(list(lex.words.items())[:args.top], 1):
        words.append({"id": key("w", w), "rank": rank, "word": w, "hints": hints,
                      "ipa": [ipa(p) for p in prons[w]]})
    pairs = []
    for w, (noun, verb) in lex.homographs.items():
        ps = sorted(prons[w], key=stress_index)
        pairs.append({"id": key("pair", w), "word": w, "noun": noun, "verb": verb,
                      "nounIpa": ipa(ps[0]), "verbIpa": ipa(ps[-1])})
    font = base64.b64encode(Path(args.font).read_bytes()).decode()
    page = (HERE / "review_template.html").read_text(encoding="utf-8")
    page = page.replace("{{FONT}}", font).replace("{{DATA}}", json.dumps(
        {"words": words, "pairs": pairs, "total": len(lex.words)}, ensure_ascii=False).replace("</", "<\\/"))
    Path(args.out).write_text(page, encoding="utf-8")
    print(f"wrote {args.out}: {len(words)} words, {len(pairs)} pairs, {len(page) // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
