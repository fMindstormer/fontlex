"""Tests of the Markdown font's reference model and of the algorithms the
font is compiled from (the font itself is checked by markdown/verify.py)."""

import json
import random
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "markdown"))
sys.path.insert(0, str(ROOT))
import bounds  # noqa: E402
import cm_block  # noqa: E402
import cm_inline as cm  # noqa: E402
import htmlauto  # noqa: E402
import mdfont  # noqa: E402
import tails  # noqa: E402

SPEC = json.loads((ROOT / "markdown" / "spec-0.31.2.json").read_text())
GFM_SPEC = json.loads((ROOT / "markdown" / "gfm-spec-0.29-extensions.json").read_text())


class ModelTest(unittest.TestCase):
    def test_single_line_examples(self):
        n = 0
        for e in SPEC:
            m = re.fullmatch(r"<p>(.*)</p>\n", e["html"], re.S)
            if e["markdown"].count("\n") == 1 and m and "\n" not in m.group(1):
                self.assertEqual(cm.to_html(e["markdown"][:-1]), m.group(1), f"example {e['example']}")
                n += 1
        self.assertEqual(n, 252)

    def test_paragraph_examples(self):
        n = 0
        for e in SPEC:
            lines = e["markdown"].split("\n")[:-1]
            m = re.fullmatch(r"<p>(.*)</p>\n", e["html"], re.S)
            if len(lines) < 2 or not m or "<p>" in m.group(1) or e["section"] == "Link reference definitions" \
                    or any(not line.strip() for line in lines):
                continue
            content = "\n".join(line.lstrip(" \t") for line in lines).strip(" \t")
            self.assertEqual(cm.render_html(cm.InlineParser(content).parse()), m.group(1), f"example {e['example']}")
            n += 1
        self.assertEqual(n, 51)

    def test_roles(self):
        r = cm.roles("*a* `b` [c](d) &copy; <e>")
        kinds = "".join({"text": "t", "hidden": ".", "dim": "h", "entity": "E"}[x.kind] for x in r)
        self.assertEqual(kinds, ".t.t.t.t.t....tE.....thhh")
        self.assertEqual(r[1].style, {"em"})
        self.assertEqual(r[5].style, {"code"})
        self.assertEqual(r[9].style, {"link"})
        self.assertEqual(r[15].char, "©")

    def test_code_padding(self):
        self.assertEqual(cm.roles("` a `")[1], cm.HIDDEN)
        self.assertEqual(cm.roles("` a `", code_padding=True)[1].style, {"code"})


class BlockTest(unittest.TestCase):
    def test_one_line_documents(self):
        """Every one-line spec example, as a whole document."""
        n = 0
        for e in SPEC:
            if e["markdown"].count("\n") == 1 and e["markdown"].endswith("\n"):
                self.assertEqual(cm_block.to_html(e["markdown"][:-1]), e["html"], f"example {e['example']}")
                n += 1
        self.assertEqual(n, 290)

    def test_gfm_examples(self):
        """GFM's strikethrough and autolink examples, paragraph by paragraph
        (each is one line), and its task list examples item by item."""
        for e in GFM_SPEC:
            md = e["markdown"][:-1]
            if e["extension"] == "tasklist":
                items = re.findall(r"<li>(<input [^>]*/>) ([^<\n]*)", e["html"])
                for line, (box, text) in zip(md.split("\n"), items):
                    html = cm_block.to_html(line.lstrip(), gfm=True)
                    self.assertIn(f"<li>{box} {text}</li>", html, f"example {e['example']}: {line!r}")
            else:
                got = "".join(cm_block.to_html(p, gfm=True) for p in md.split("\n\n"))
                self.assertEqual(got, e["html"], f"example {e['example']}")

    def test_roles(self):
        kinds = {"text": ".", "hidden": "_", "dim": "d", "entity": "E", "bullet": "B", "quote": "Q", "rule": "R",
                 "box": "O", "checked": "X"}
        for line, want in [("## Title *em* ##", "dd......._.._.dd"), ("- [ ] task", "B._O_....."),
                           ("> - [x] a", "Q.B......"),            # cmark-gfm: no task inside a quote
                           ("- [ ] a [x]", "B._X_......"),        # any [x] in the line checks it
                           ("* * *", "RRRRR"), ("   ---  ", "...RRR.."), ("```js", "ddddd"), ("<div>*a*", "dddddddd"),
                           ('[a]: /u "t"', "ddddddddddd"), ("1. item", "......."), ("-", "B")]:
            self.assertEqual("".join(kinds[r.kind] for r in cm_block.roles(line)), want, line)
        r = cm_block.roles("# a *b*")
        self.assertEqual((r[2].style, r[5].style), ({"heading"}, {"heading", "em"}))
        self.assertEqual(cm_block.roles("    x")[4].style, {"code"})

    def test_gfm_inline(self):
        cases = {
            "~~a~~ ~b~ ~~~c~~~ ~d~~": "<del>a</del> <del>b</del> ~~~c~~~ ~d~~",
            "**/*~": "*<em>/</em>~",             # tildes are transparent to flanking
            "*a ~b* c~": "<em>a ~b</em> c~",
            "see www.x.com/a_(b)). ok": 'see <a href="http://www.x.com/a_(b)">www.x.com/a_(b)</a>). ok',
            "[www.x.com](y)": '<a href="y">www.x.com</a>',
            "x https://a.b/c?d=1. y": 'x <a href="https://a.b/c?d=1">https://a.b/c?d=1</a>. y',
            "a _b_@c.com d@e.fr.": 'a <em>b</em>@c.com <a href="mailto:d@e.fr">d@e.fr</a>.',
            "www.x.com/&amp;": '<a href="http://www.x.com/">www.x.com/</a>&amp;',
        }
        for md, html in cases.items():
            self.assertEqual(cm.to_html(md, gfm=True), html, md)


class AlgorithmTest(unittest.TestCase):
    def test_flanking(self):
        examples = {"W": " ", "P": ".", "O": "a", "S": None}
        p = cm.InlineParser("")
        for c in "*_":
            for b, bc in examples.items():
                for a, ac in examples.items():
                    if a == "S":
                        continue
                    s = (bc or "") + c + ac
                    p.subject, p.pos = s, 1 if bc else 0
                    _, o, cl = p.scan_delims(c)
                    self.assertEqual(mdfont.flanking(c, b, a), (o, cl), s)

    def test_peeling_matches_commonmark(self):
        rng = random.Random(1)
        pieces = ["*", "*", "**", "_", "__", "***", "a", "b", " ", " ", ".", "é", "«"]
        for _ in range(3000):
            line = "".join(rng.choice(pieces) for _ in range(rng.randint(1, 16))).strip() or "a"
            self.assertEqual(bounds.emphasis_roles(line), cm.roles(line), line)

    def test_destination_forms(self):
        def accepts(f, s):
            q = "S0"
            for c in s:
                q = f(q, c)
                if q in (tails.ACC, None):
                    return q == tails.ACC
            return False
        autos = [tails.Automaton(f, 3) for f in tails.FORMS]
        rng = random.Random(3)
        for _ in range(20000):
            s = "".join(rng.choice(["(", ")", '"', "'", "<", ">", " ", "\t", "O", "O"]) for _ in range(rng.randint(1, 12)))
            self.assertEqual(accepts(lambda q, c: tails.step(q, c, 3), s), any(accepts(a.fwd, s) for a in autos), s)

    def test_html_automata(self):
        pieces = ["<", ">", "a", "Z", "N", "1", "-", "_", ":", ".", "@", "/", "!", "?", "]", "=", '"', "'", " ", "é",
                  "--", "!--", "![CDATA[", "]]", "?>", "-->", "http:", "x=", "`"]
        prefix = {"open": r"<[A-Za-z]", "close": "</", "comment": "<!--", "pi": r"<\?", "decl": "<![A-Za-z]",
                  "cdata": r"<!\[CDATA\["}
        rng = random.Random(5)
        for _ in range(20000):
            s = "<" + "".join(rng.choice(pieces) for _ in range(rng.randint(0, 9)))
            for name, step in htmlauto.KINDS:
                q, end = "<", None
                for i, c in enumerate(s[1:]):
                    q = step(q, c if ord(c) < 128 else htmlauto.NONASCII)
                    if q in (htmlauto.ACC, None):
                        end = i + 2 if q == htmlauto.ACC else None
                        break
                if name in ("email", "uri"):
                    m = (cm.RE_EMAIL_AUTOLINK if name == "email" else cm.RE_AUTOLINK).match(s)
                else:
                    m = cm.RE_HTML_TAG.match(s) if re.match(prefix[name], s) else None
                self.assertEqual(end, m.end() if m else None, (name, s))

    def test_bounds(self):
        self.assertEqual(bounds.exceeds("*a* `b` [c](d)"), set())
        self.assertIn("a delimiter run longer than 6", bounds.exceeds("*******a*******"))
        self.assertIn("more than 3 open brackets", bounds.exceeds("[[[[a](b)"))


if __name__ == "__main__":
    unittest.main()
