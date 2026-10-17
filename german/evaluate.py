#!/usr/bin/env python3
"""Score a German gender font against a gender-annotated treebank.

Shapes every sentence through the compiled font and reads the color of each
token's last letter (for "E-Mail-Adresse" that is the color of "Adresse"),
then compares it with the treebank's noun gender.

    python german/evaluate.py specs/german.yaml build/Fontlex-German.ttf \\
        german/data/hdt/de_hdt-ud-test.conllu [--shaper coretext] [--errors 20]

Inputs can also be word lists (.tsv, word<TAB>gender), scored word by word.
--shaper model scores the reference lexer instead of a shaped font.
"""

import argparse
import collections
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fontTools.ttLib import TTFont  # noqa: E402

import fontlex  # noqa: E402
from german.learn import GENDERS, LETTERS, font_word  # noqa: E402

COLORS = set(GENDERS.values())


def sentences(path):
    """(text, [(form, upos, feats)]) per sentence; surface tokens only, so a
    contraction like "zum" is one token without features."""
    text, toks, covered = None, [], set()
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if line.startswith("# text = "):
            text = line[len("# text = "):]
        elif not line:
            if text is not None:
                yield text, toks
            text, toks, covered = None, [], set()
        elif not line.startswith("#"):
            cols = line.split("\t")
            if "." in cols[0]:
                continue
            if "-" in cols[0]:
                a, b = map(int, cols[0].split("-"))
                covered.update(range(a, b + 1))
                toks.append((cols[1], "MWT", {}))
            elif int(cols[0]) not in covered:
                feats = dict(f.split("=", 1) for f in cols[5].split("|")) if cols[5] != "_" else {}
                toks.append((cols[1], cols[3], feats))
    if text is not None:
        yield text, toks


def word_list(path):
    """A word<TAB>gender list as one-word sentences in treebank form."""
    feats = {v: k for k, v in GENDERS.items()}
    for line in open(path, encoding="utf-8"):
        if line.strip() and not line.startswith("#"):
            word, gender = line.rstrip("\n").split("\t")
            yield word, [(word, "NOUN", {"Gender": feats[gender]})]


def evaluate(spec, font_data: bytes, inputs, shaper="harfbuzz", max_errors=0):
    """Score a compiled font on treebank files and word lists. Returns a dict
    of counts and metrics (see main for what they mean)."""
    tt = TTFont(io.BytesIO(font_data))
    order = tt.getGlyphOrder()
    model = fontlex.Model(spec, tt.getBestCmap())
    args = argparse.Namespace(shaper=shaper, errors=max_errors, conllu=inputs)
    if args.shaper == "model":
        def colors(text):
            return [ws for _, ws in model.lex(text)]
    else:
        import test_fontlex
        shaper = test_fontlex.SHAPERS[args.shaper](font_data)

        def colors(text):
            out = [None] * len(text)
            glyphs, _ = shaper.shape(text)
            for gid, ci, *_ in glyphs:
                if gid is not None and fontlex.WORD_SUFFIX in order[gid]:
                    out[ci] = order[gid].split(fontlex.WORD_SUFFIX)[1]
            return out

    n = collections.Counter()
    confusion = collections.Counter()          # (gold, predicted)
    by_source = collections.Counter()          # (source, correct?)
    spurious = collections.Counter()           # upos of colored non-nouns
    errors = collections.defaultdict(list)
    for path in args.conllu:
        for text, toks in (word_list(path) if path.endswith(".tsv") else sentences(path)):
            spans, pos = [], 0
            for form, upos, feats in toks:
                i = text.find(form, pos)
                if i < 0:
                    break
                spans.append((i, i + len(form)))
                pos = i + len(form)
            else:
                color = colors(text)
                n["sentences"] += 1
                for (form, upos, feats), (a, b) in zip(toks, spans):
                    last = max((k for k in range(a, b) if LETTERS.match(text[k])), default=None)
                    pred = color[last] if last is not None else None
                    pred = pred if pred in COLORS else None
                    gold = GENDERS.get(feats.get("Gender")) if upos == "NOUN" else None
                    if upos == "NOUN" and not gold:
                        continue                # a noun without a gender to check against
                    word = font_word(form)
                    source = "word" if word in model.words else "suffix"
                    if gold:
                        n["nouns"] += 1
                        confusion[(gold, pred)] += 1
                        if pred:
                            by_source[(source, pred == gold)] += 1
                            if pred != gold and len(errors["wrong"]) < args.errors:
                                errors["wrong"].append(f"{form} ({gold}, colored {pred} by {source})")
                        elif len(errors["uncolored"]) < args.errors:
                            errors["uncolored"].append(f"{form} ({gold})")
                    elif pred:
                        spurious[upos] += 1
                        if len(errors["spurious"]) < args.errors:
                            errors["spurious"].append(f"{form} ({upos}, colored {pred} by {source})")
                continue
            n["skipped sentences"] += 1

    colored = sum(k for (g, p), k in confusion.items() if p)
    correct = sum(k for (g, p), k in confusion.items() if p == g)
    false_colored = sum(spurious.values())
    return {"sentences": n["sentences"], "skipped": n["skipped sentences"], "nouns": n["nouns"],
            "colored": colored, "correct": correct, "false_colored": false_colored,
            "coverage": colored / n["nouns"], "accuracy": correct / colored,
            "precision": correct / (colored + false_colored),
            "confusion": confusion, "by_source": by_source, "spurious": spurious, "errors": errors}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("spec")
    ap.add_argument("font")
    ap.add_argument("conllu", nargs="+")
    ap.add_argument("--shaper", default="harfbuzz", choices=["harfbuzz", "coretext", "model"])
    ap.add_argument("--errors", type=int, default=0, help="print this many errors of each kind")
    args = ap.parse_args()

    r = evaluate(fontlex.load_spec(args.spec), open(args.font, "rb").read(), args.conllu, args.shaper,
                 args.errors)
    nouns, colored, correct, false_colored = r["nouns"], r["colored"], r["correct"], r["false_colored"]
    confusion, by_source, spurious, errors = r["confusion"], r["by_source"], r["spurious"], r["errors"]
    print(f"{args.shaper}: {r['sentences']:,} sentences ({r['skipped']} skipped), {nouns:,} nouns")
    print(f"  coverage:  {colored / nouns:6.1%} of nouns colored")
    print(f"  accuracy:  {correct / colored:6.1%} of colored nouns have the right gender")
    print(f"  precision: {correct / (colored + false_colored):6.1%} of all colored words are nouns "
          f"colored right ({false_colored:,} non-nouns colored)")
    for source in ("word", "suffix"):
        ok, bad = by_source[(source, True)], by_source[(source, False)]
        if ok + bad:
            print(f"  by {source + ' list' if source == 'word' else 'ending'}: {ok + bad:,} nouns colored, "
                  f"{ok / (ok + bad):.1%} right")
    print("  gold \\ colored   " + "  ".join(f"{p or 'none':>6}" for p in ("masc", "fem", "neut", None)))
    for g in ("masc", "fem", "neut"):
        print(f"  {g:16} " + "  ".join(f"{confusion[(g, p)]:6,}" for p in ("masc", "fem", "neut", None)))
    print("  non-nouns colored, by UPOS: " + ", ".join(f"{u} {k:,}" for u, k in spurious.most_common(6)))
    for kind, items in errors.items():
        print(f"  {kind}: " + "; ".join(items))


if __name__ == "__main__":
    main()
