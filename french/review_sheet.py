#!/usr/bin/env python3
"""Build the French review sheet: a page where a fluent reviewer marks the
font's hints right or wrong, for the most frequent words, the verb/noun
pairs, the liaison rules and the compounds.

    python french/review_sheet.py LEXIQUE --font build/Fontlex-French.woff2 --top 500 --out review.html

LEXIQUE is Lexique383.tsv (fetch_data.sh), for each word's pronunciations
and the verb readings of the pairs. Each item is drawn in the font, with its
pronunciation in IPA and its hints spelled out. Verdicts are saved by the
published page in its `db` store (collection `reviews`, one document per
item), with what was judged, so they can be read back and turned into fixes.
Document ids are `w:`, `pair:`, `t:` (liaison trigger), `b:` (blocker) or
`c:` (compound) and the text, with every character but a-z, 0-9 and the
hyphen written as `~` and its UTF-8 bytes in hex (`pr~C3~A9sident`).
"""

import argparse
import base64
import csv
import json
import string
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import frfont  # noqa: E402

IPA = {"a": "a", "i": "i", "y": "y", "u": "u", "o": "o", "O": "ɔ", "e": "e", "E": "ɛ", "°": "ə", "2": "ø",
       "9": "œ", "5": "ɛ̃", "1": "œ̃", "@": "ɑ̃", "§": "ɔ̃", "p": "p", "b": "b", "t": "t", "d": "d", "k": "k",
       "g": "ɡ", "f": "f", "v": "v", "s": "s", "z": "z", "S": "ʃ", "Z": "ʒ", "m": "m", "n": "n", "N": "ɲ",
       "G": "ŋ", "l": "l", "R": "ʁ", "w": "w", "j": "j", "8": "ɥ", "x": "x"}
# A natural phrase for each liaison trigger, in which the liaison is obligatory.
EXAMPLES = {
    "les": "les amis", "des": "des enfants", "ces": "ces arbres", "mes": "mes amis", "tes": "tes yeux",
    "ses": "ses oncles", "nos": "nos enfants", "vos": "vos idées", "leurs": "leurs histoires", "aux": "aux armes",
    "un": "un homme", "aucun": "aucun ami", "mon": "mon ami", "ton": "ton école", "son": "son histoire",
    "quels": "quels amis", "quelles": "quelles idées", "quelques": "quelques heures",
    "plusieurs": "plusieurs années", "certains": "certains auteurs", "certaines": "certaines écoles",
    "deux": "deux ans", "trois": "trois enfants", "six": "six heures", "dix": "dix euros", "vingt": "vingt ans",
    "vingts": "quatre-vingts ans", "cent": "cent ans", "cents": "deux cents euros", "nous": "nous avons",
    "vous": "vous êtes", "ils": "ils ont", "elles": "elles arrivent", "on": "on a", "en": "en avion",
    "dans": "dans une heure", "chez": "chez elle", "sans": "sans arrêt", "sous": "sous un arbre",
    "très": "très utile", "tout": "tout à fait", "quand": "quand il",
}
PERSONS = {"1s": "je", "2s": "tu", "3s": "il", "1p": "nous", "2p": "vous", "3p": "ils"}
PARTS = {"NOM": "noun", "ADJ": "adjective", "ADV": "adverb", "ONO": "interjection"}
SAFE = set(string.ascii_lowercase + string.digits + "-")


def ipa(phon):
    return "/" + "".join(IPA[c] for c in phon) + "/"


def key(prefix, text):
    return prefix + ":" + "".join(c if c in SAFE else "".join(f"~{b:02X}" for b in c.encode()) for c in text)


def read_lexique(path):
    """spelling -> [(phonemes, part of speech, gender, frequency, inflections)]."""
    out = defaultdict(list)
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            freq = float(r["freqfilms2"] or 0) + float(r["freqlivres"] or 0)
            out[r["ortho"]].append((r["phon"], r["cgram"], r["genre"], freq, r["infover"]))
    return out


def entries(lexique, word):
    return lexique.get(word) or lexique.get(word.replace("œ", "oe"), [])


def prons(lexique, word):
    """Its pronunciations, the most frequent first, each with 5% of the uses."""
    by = defaultdict(float)
    for phon, _, _, freq, _ in entries(lexique, word):
        by[phon] += freq
    total = sum(by.values())
    return [p for p, f in sorted(by.items(), key=lambda kv: -kv[1]) if f >= 0.05 * total]


def pair_readings(lexique, word):
    """(noun cue, part of speech, phonemes), (verb cue, phonemes): the cue
    words the font reads (cues.tsv), picked from each reading's part of
    speech. The "noun" reading is the most frequent one that isn't a verb.
    Before a vowel, where French elides le and se, "un" and "vous" stand in."""
    es = entries(lexique, word)
    noun = max((e for e in es if e[1] in PARTS), key=lambda e: e[3])
    verb = max((e for e in es if e[1] == "VER"), key=lambda e: e[3])
    vowel = word[0] in frfont.LINKS_TO
    feminine = noun[2] == "f"
    noun_cue = {"ADJ": "très", "NOM": ("une" if feminine else "un") if vowel else ("la" if feminine else "le")}
    noun_cue = noun_cue.get(noun[1], "un")
    tags = [t.split(":") for t in verb[4].split(";") if t]
    if any(t[0] == "inf" for t in tags):
        verb_cue = "vous" if vowel else "se"
    else:
        verb_cue = next((PERSONS[t[2]] for t in tags if len(t) == 3 and t[2] in PERSONS), "ils")
    return (noun_cue, PARTS[noun[1]], noun[0]), (verb_cue, verb[0])


def blocker_reason(word):
    if word[0] == "h":
        return "h aspiré: no liaison and no elision before it (les héros, le héros)"
    if word[0] == "y":
        return "y said as a consonant: no liaison before it (les yachts)"
    return "no liaison before it"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("lexique")
    ap.add_argument("--font", required=True, help="the font as WOFF2")
    ap.add_argument("--lexicon", default=str(HERE / "lexicon"))
    ap.add_argument("--top", type=int, default=500)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    lex = frfont.Lexicon(args.lexicon)
    lexique = read_lexique(args.lexique)
    phon = {r[0]: r[2] for r in (l.rstrip("\n").split("\t") for l in open(Path(args.lexicon) / "words.tsv",
                                                                      encoding="utf-8")) if len(r) == 3}
    cues = {w for w in lex.cues}
    assert set(EXAMPLES) == set(lex.triggers), "every liaison trigger needs an example"
    words = []
    for rank, (w, hints) in enumerate(list(lex.words.items())[:args.top], 1):
        others = [p for p in prons(lexique, w) if p != phon[w]]
        words.append({"id": key("w", w), "rank": rank, "word": w, "hints": hints,
                      "ipa": [ipa(phon[w])] + [ipa(p) for p in others]})
    pairs = []
    for w, (noun, verb) in lex.homographs.items():
        (ncue, part, nphon), (vcue, vphon) = pair_readings(lexique, w)
        assert ncue in cues and vcue in cues, (w, ncue, vcue)
        pairs.append({"id": key("pair", w), "word": w, "noun": noun, "verb": verb, "nounCue": ncue,
                      "verbCue": vcue, "nounPart": part, "nounIpa": ipa(nphon), "verbIpa": ipa(vphon)})
    liaison = [{"id": key("t", t), "word": t, "kind": "trigger", "example": EXAMPLES[t]} for t in lex.triggers]
    liaison += [{"id": key("b", b), "word": b, "kind": "blocker", "reason": blocker_reason(b),
                 "ipa": [ipa(p) for p in prons(lexique, b)]} for b in sorted(lex.blockers)]
    compounds = [{"id": key("c", c), "word": c, "hints": h, "ipa": [ipa(p) for p in prons(lexique, c)]}
                 for c, h in sorted(lex.compounds.items())]
    font = base64.b64encode(Path(args.font).read_bytes()).decode()
    page = (HERE / "review_template.html").read_text(encoding="utf-8")
    data = {"words": words, "pairs": pairs, "liaison": liaison, "compounds": compounds, "total": len(lex.words)}
    page = page.replace("{{FONT}}", font).replace("{{DATA}}", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    Path(args.out).write_text(page, encoding="utf-8")
    n = len(words) + len(pairs) + len(liaison) + len(compounds)
    print(f"wrote {args.out}: {len(words)} words, {len(pairs)} pairs, {len(liaison)} liaison rules, "
          f"{len(compounds)} compounds ({n} items), {len(page) // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
