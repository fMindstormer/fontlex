#!/usr/bin/env python3
"""Build the self-contained demo page from a spec and its compiled font.

    python demo/build_demo.py specs/python.yaml --base Font.ttf --out demo/fontlex-demo.html

The page's sample code comes from demo/samples/<spec name>.yaml (`file`,
`sample`, `oneliner`); everything else comes from the spec and the compiled
font. Compiler options (--unicodes, --unify-scripts) are passed through.
"""

import argparse
import base64
import html
import io
import json
import re
import sys
from pathlib import Path

import yaml
from fontTools import subset

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fontlex import START_SUFFIX, SUFFIX, compile_font, load_spec  # noqa: E402
from test_fontlex import verify  # noqa: E402


def fea_excerpts(spec, res, cmap):
    """Real rules from the generated feature file, for the "how" section."""
    lines = res.fea.splitlines()
    body = lines[lines.index("lookup LEX {") + 1:lines.index("} LEX;")]
    # One context rule per source state, for variety, then the fallbacks.
    context, seen = [], set()
    for line in body:
        if line.startswith("  sub @S_"):
            state = line.split()[1]
            if state not in seen:
                seen.add(state)
                context.append(line)
    fallbacks = [line for line in body if line.startswith("  sub @C_")]
    lex = ("lookup LEX {\n  …\n" + "\n".join(context[:5]) + "\n  …\n  # fallbacks: the start state's row\n"
           + "\n".join(fallbacks[:3]) + "\n  …\n} LEX;")

    if "lookup WORDS {" not in lines:
        return lex, None, None
    usable = {}
    for sname, words in spec.word_sets:
        for w in words:
            if w not in res.stats["skipped_words"]:
                usable.setdefault(w, sname)
    ws = spec.word_state

    def word_line(word):
        glyphs = [f"\\{cmap[ord(word[0])]}{START_SUFFIX}{ws}"]
        glyphs += [f"\\{cmap[ord(c)]}{SUFFIX}{ws}" for c in word[1:]]
        line = "  sub " + " ".join(glyphs) + f"' lookup W_{usable[word]};"
        assert "# " + line in lines, word
        return line

    # A short word that starts a longer one shows why longer words go first.
    pairs = [(long, short) for long in usable for short in usable
             if long != short and long.startswith(short)]
    long, short = max(pairs, key=lambda p: (len(p[0]), p)) if pairs else (max(usable, key=len), None)

    def shorten(line):
        return re.sub(r"\[[^\]]{40,}\]", "[…]", line)

    start = lines.index("lookup START {")
    words = lines.index("lookup WORDS {")
    shown = lines[start:start + 4] + [lines[words], shorten(lines[words + 1]), "  …", word_line(long)]
    if short:
        shown += ["  …", word_line(short)]
    return lex, "\n".join(shown + ["} WORDS;"]), (long, short)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sample", help="page content (default: demo/samples/<spec name>.yaml)")
    ap.add_argument("--fuzz", type=int, default=20000, help="number of random cases to verify")
    ap.add_argument("--unicodes", help="passed to the compiler")
    ap.add_argument("--unify-scripts", action="store_true", help="passed to the compiler")
    args = ap.parse_args()

    spec = load_spec(args.spec)
    content = yaml.safe_load(Path(args.sample or ROOT / "demo" / "samples" / f"{Path(args.spec).stem}.yaml")
                             .read_text())
    unicodes = subset.parse_unicodes(args.unicodes) if args.unicodes else None
    res = compile_font(spec, args.base, unify_scripts=args.unify_scripts, unicodes=unicodes)
    buf = io.BytesIO()
    res.font.save(buf)
    # The page reports these numbers, so they come from checking this font.
    checks = verify(spec, buf.getvalue(), args.base, n=args.fuzz, unify_scripts=args.unify_scripts)
    fuzz_pass, fuzz_total = checks["harfbuzz: random cases"]
    res.font.flavor = "woff2"
    buf = io.BytesIO()
    res.font.save(buf)
    woff2 = buf.getvalue()

    theme_names = [t for t, _ in spec.themes]
    themes = dict(spec.themes)
    light, dark = themes.get("light", {}), themes.get("dark", {})
    toks = res.stats["tokens"]

    def tok_css(theme):
        return " ".join(f"--t-{t}: {theme.get(t, '#888888')};" for t in toks)

    # Transition table: rows = previous state, cols = class.
    delta = spec.table()
    cols = spec.class_names
    order = [spec.start] + [s for s in spec.states if s != spec.start]
    rows = []
    head = "<tr><th>after \\ next</th>" + "".join(f"<th>{html.escape(c)}</th>" for c in cols) + "</tr>"
    for s in order:
        cells = []
        for c in cols:
            t = delta[s][c]
            tok = spec.token(t)
            style = f' style="--c: var(--t-{tok})"' if tok in toks else ""
            same = s != spec.start and t == delta[spec.start][c]
            cls = ' class="same"' if same else ""
            cells.append(f"<td{cls}><span class=\"t\"{style}>{html.escape(t)}</span></td>")
        label = f"{s} (start)" if s == spec.start else s
        rows.append(f"<tr{' class=\"start\"' if s == spec.start else ''}><th>{html.escape(label)}</th>{''.join(cells)}</tr>")
    table = f"<table><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table>"

    cmap = res.font.getBestCmap()
    fea_lex, fea_words, word_pair = fea_excerpts(spec, res, cmap)
    if word_pair and word_pair[1]:
        long, short = (html.escape(w) for w in word_pair)
        words_note = ("The first letter of every identifier is marked, and a word's rule runs from that "
                      f"letter to the identifier's last, so <code>{short}</code> can't match inside "
                      f"<code>{short}land</code>; a last pass spreads the color back over the word. "
                      f"Longer words go first, so <code>{long}</code> isn't read as <code>{short}</code>:")
    else:
        words_note = ("The first letter of every identifier is marked, and a word's rule runs from that "
                      "letter to the identifier's last, so a word can't match inside a longer one:")
    # A colored copy of a non-letter glyph, to name in the text.
    example = next(name for name, info in res.glyphmap.items()
                   if not info["set"] and spec.token(info["state"]) in toks and len(info["base"]) > 1)

    legend = " ".join(f'<span style="--c: var(--t-{t})">{t}</span>' for t in toks)
    tokens_json = json.dumps([{"name": t, "light": light.get(t, "#888888"), "dark": dark.get(t, "#888888")}
                              for t in toks])
    lang = spec.name.removeprefix("Fontlex ").strip() or spec.name

    st = res.stats
    page = (ROOT / "demo" / "template.html").read_text()
    repl = {
        "{{FONT_B64}}": base64.b64encode(woff2).decode(),
        "{{FAMILY}}": html.escape(spec.name),
        "{{LANG}}": html.escape(lang),
        "{{FILE}}": html.escape(content["file"]),
        "{{ONELINER}}": html.escape(content["oneliner"]),
        "{{PALETTE_LIGHT}}": str(theme_names.index("light") if "light" in theme_names else 0),
        "{{PALETTE_DARK}}": str(theme_names.index("dark") if "dark" in theme_names else 0),
        "{{TOKENS_LIGHT}}": tok_css(light),
        "{{TOKENS_DARK}}": tok_css(dark),
        "{{SAMPLE}}": html.escape(content["sample"]),
        "{{LEGEND}}": legend,
        "{{N_STATES}}": str(st["states"]),
        "{{N_CLASSES}}": str(st["classes"]),
        "{{N_RULES}}": str(st["lex_rules"]),
        "{{N_DROPPED}}": str(st["lex_rules_dropped"]),
        "{{N_WORDS}}": str(st["words"]),
        "{{N_GLYPHS}}": f"{st['variant_glyphs']:,}",
        "{{WOFF2_KB}}": str(round(len(woff2) / 1024)),
        "{{N_FUZZ}}": f"{fuzz_total:,}",
        "{{N_FUZZ_PASS}}": f"{fuzz_pass:,}",
        "{{TABLE}}": table,
        "{{VARIANT_EXAMPLE}}": html.escape(example),
        "{{FEA_LEX}}": html.escape(fea_lex),
        "{{WORDS_NOTE}}": words_note,
        "{{FEA_WORDS}}": html.escape(fea_words or ""),
        "{{TOKENS_JSON}}": tokens_json,
    }
    for k, v in repl.items():
        page = page.replace(k, v)
    assert "{{" not in page, "unfilled placeholder"
    Path(args.out).write_text(page)
    print(f"wrote {args.out} ({len(page) // 1024} KB)")
    failed = [label for label, (passed, total) in checks.items() if passed != total]
    if failed:
        print("checks failed: " + ", ".join(failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
