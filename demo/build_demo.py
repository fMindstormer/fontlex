#!/usr/bin/env python3
"""Build the self-contained demo page from a spec and its compiled font.

    python demo/build_demo.py specs/python.yaml --base Font.ttf --out demo/fontlex-demo.html
"""

import argparse
import base64
import html
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fontlex import compile_font, load_spec  # noqa: E402
from test_fontlex import verify  # noqa: E402

SAMPLE = '''# This box has no highlighter attached.
# Every color comes from the font's own substitution rules.
import json
from dataclasses import dataclass
from pathlib import Path

@dataclass
class Point:
    x: float = 0.0
    y: float = 0.0

def load(path, limit=100):
    """Read up to `limit` points from a JSON file."""
    data = json.loads(Path(path).read_text())
    if not isinstance(data, list):
        raise ValueError("expected a list, got " + str(type(data)))
    return [Point(**d) for d in data[:limit]]

for i, p in enumerate(load('points.json')):
    if p.x is None or p.y < 0:  # skip "bad" rows, don't stop
        continue
    print(i, p.x * 2.5e3, 'it\\'s fine', 0xFF)
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--fuzz", type=int, default=20000, help="number of random cases to verify")
    args = ap.parse_args()

    spec = load_spec(args.spec)
    res = compile_font(spec, args.base)
    buf = io.BytesIO()
    res.font.save(buf)
    # The page reports these numbers, so they come from checking this font.
    checks = verify(spec, buf.getvalue(), args.base, n=args.fuzz)
    fuzz_pass, fuzz_total = checks["harfbuzz: random cases"]
    res.font.flavor = "woff2"
    buf = io.BytesIO()
    res.font.save(buf)
    woff2 = buf.getvalue()

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

    # Real excerpts from the generated feature file.
    lines = res.fea.splitlines()
    lex_start = lines.index("lookup LEX {")
    lex_end = lines.index("} LEX;")
    lex_body = lines[lex_start + 1:lex_end]
    wanted = [
        "  sub @S_ident @C_digit' lookup TO_ident;",
        "  sub @S_dq @C_dq' lookup TO_dq_end;",
        "  sub @S_dq @C_backslash' lookup TO_dq_esc;",
        "  sub @S_dq_esc @C_backslash' lookup TO_dq;",
        "  sub @S_comment @C_dq' lookup TO_comment;",
        "  sub @C_digit' lookup TO_number;",
        "  sub @C_dq' lookup TO_dq;",
        "  sub @C_hash' lookup TO_comment;",
    ]
    pick = [l for l in wanted if l in lex_body]
    assert len(pick) == len(wanted), set(wanted) - set(lex_body)
    fea_lex = "lookup LEX {\n  …\n" + "\n".join(pick[:5]) + "\n  …\n  # fallbacks: the start state's row\n" + "\n".join(pick[5:]) + "\n  …\n} LEX;"

    def word_lines(word, sname):
        seq = [f"\\{c}.lx_ident'" for c in word]
        ign = f"  ignore sub {' '.join(seq)} @WORDLIKE;"
        sub = "  sub " + " ".join(f"{g} lookup W_{sname}" for g in seq) + ";"
        assert ign in lines and sub in lines, word
        return [ign, sub]

    w_start = lines.index("lookup WORDS {")
    fea_words = "\n".join(["lookup WORDS {", lines[w_start + 1], "  …"]
                          + word_lines("isinstance", "builtin") + ["  …"]
                          + word_lines("is", "keyword") + ["} WORDS;"])

    legend = " ".join(f'<span style="--c: var(--t-{t})">{t}</span>' for t in toks)
    tokens_json = json.dumps([{"name": t, "light": light.get(t, "#888888"), "dark": dark.get(t, "#888888")} for t in toks])

    st = res.stats
    page = (ROOT / "demo" / "template.html").read_text()
    repl = {
        "{{FONT_B64}}": base64.b64encode(woff2).decode(),
        "{{TOKENS_LIGHT}}": tok_css(light),
        "{{TOKENS_DARK}}": tok_css(dark),
        "{{SAMPLE}}": html.escape(SAMPLE),
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
        "{{FEA_LEX}}": html.escape(fea_lex),
        "{{FEA_WORDS}}": html.escape(fea_words),
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
