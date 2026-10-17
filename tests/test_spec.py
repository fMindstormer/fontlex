"""Unit tests for spec loading, the reference lexer and compiler errors.

    python -m unittest discover tests
"""

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fontlex import Model, SpecError, _expand_class, compile_font, load_spec  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402

BASE = ROOT / "fonts" / "JetBrainsMono-Regular.ttf"
CMAP = TTFont(BASE).getBestCmap()

MINIMAL = {
    "name": "Fontlex Test",
    "classes": {"letter": "a-z", "dq": '"'},
    "states": {
        "code": {"default": "code", "on": {"letter": "ident", "dq": "str"}},
        "ident": {"on": {"letter": "ident"}, "like": "code"},
        "str": {"token": "string", "on": {"dq": "str_end"}, "default": "str"},
        "str_end": {"token": "string", "like": "code"},
    },
    "words": {"state": "ident", "sets": {"keyword": ["if"]}},
    "themes": {"light": {"string": "#3E7D1A", "keyword": "#8E3FB8"}},
}


def load(raw):
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(raw, f)
    try:
        return load_spec(f.name)
    finally:
        Path(f.name).unlink()


def changed(**states):
    """MINIMAL with some states replaced (None deletes one)."""
    raw = yaml.safe_load(yaml.safe_dump(MINIMAL))
    for name, st in states.items():
        if st is None:
            del raw["states"][name]
        else:
            raw["states"][name] = st
    return raw


class SpecErrors(unittest.TestCase):
    def assertSpecError(self, raw, fragment):
        with self.assertRaises(SpecError) as cm:
            load(raw)
        self.assertIn(fragment, str(cm.exception))

    def test_not_a_mapping(self):
        self.assertSpecError(["a"], "must be a mapping")

    def test_no_states(self):
        self.assertSpecError({"states": {}}, "no states")

    def test_other_is_implicit(self):
        self.assertSpecError({**MINIMAL, "classes": {"other": "x"}}, "implicit")

    def test_bad_range(self):
        self.assertSpecError({**MINIMAL, "classes": {"letter": "z-a"}}, "bad range")

    def test_unknown_start(self):
        self.assertSpecError({**MINIMAL, "start": "nope"}, "start state")

    def test_unknown_key(self):
        self.assertSpecError(changed(ident={"on": {"letter": "ident"}, "like": "code", "colour": 1}),
                             "unknown key")

    def test_unknown_class(self):
        self.assertSpecError(changed(ident={"on": {"digit": "ident"}, "like": "code"}), "unknown class")

    def test_unknown_target(self):
        self.assertSpecError(changed(ident={"on": {"letter": "nope"}, "like": "code"}), "unknown target")

    def test_default_not_a_state(self):
        self.assertSpecError(changed(str={"token": "string", "default": "nope"}), "is not a state")

    def test_missing_transition(self):
        self.assertSpecError(changed(ident={"on": {"letter": "ident"}}), "no transition")

    def test_like_cycle(self):
        self.assertSpecError(changed(code={"like": "ident"}, ident={"like": "code"}), "cycle")

    def test_bad_state_name(self):
        raw = changed()
        raw["states"]["bad-name"] = {"default": "code"}
        self.assertSpecError(raw, "must be [A-Za-z0-9_]+")

    def test_word_state_must_exist(self):
        self.assertSpecError({**MINIMAL, "words": {"state": "nope", "sets": {"k": ["if"]}}},
                             "words.state must name a state")

    def test_word_state_not_start(self):
        self.assertSpecError({**MINIMAL, "words": {"state": "code", "sets": {"k": ["if"]}}},
                             "can't be the start state")

    def test_bad_lookahead(self):
        self.assertSpecError(changed(str={"token": "string", "default": "str", "lookahead": {"nope": "str"}}),
                             "must name two states")

    def test_example_length(self):
        self.assertSpecError({**MINIMAL, "examples": {"legend": {".": None}, "cases": [["ab", "."]]}},
                             "1 codes for 2 characters")

    def test_example_legend(self):
        self.assertSpecError({**MINIMAL, "examples": {"legend": {".": None}, "cases": [["ab", ".x"]]}},
                             "not in legend")

    def test_example_unknown_token(self):
        self.assertSpecError({**MINIMAL, "examples": {"legend": {".": None, "z": "zzz"}, "cases": [["a", "z"]]}},
                             "unknown tokens")


class Lexer(unittest.TestCase):
    def test_expand_class(self):
        self.assertEqual(_expand_class("a-c_"), ["a", "b", "c", "_"])
        self.assertEqual(_expand_class("-a"), ["-", "a"])

    def test_tokens_and_words(self):
        m = Model(load(MINIMAL), CMAP)
        self.assertEqual(m.tokens('if "x" iff'),
                         ["keyword", "keyword", None, "string", "string", "string", None, None, None, None])

    def test_unknown_character_resets(self):
        m = Model(load(MINIMAL), CMAP)
        # U+E0000 isn't in the font: the string ends there, as it would on screen.
        self.assertEqual([st for st, _ in m.lex('"a\U000E0001b')], ["str", "str", None, "ident"])

    def test_lookahead(self):
        raw = changed(code={"default": "code", "on": {"letter": "ident", "dq": "q"}},
                      q={"default": "code", "on": {"dq": "str"}, "lookahead": {"str": "str"}})
        m = Model(load(raw), CMAP)
        # The first quote is in state q; once the next glyph is in str, it is
        # redrawn as str. Followed by anything else, it stays q.
        self.assertEqual([st for st, _ in m.lex('""')], ["str", "str"])
        self.assertEqual([st for st, _ in m.lex('"x')], ["q", "code"])

    def test_bundled_specs_examples(self):
        for name in ("python", "javascript"):
            spec = load_spec(ROOT / "specs" / f"{name}.yaml")
            m = Model(spec, CMAP)
            self.assertTrue(spec.examples, name)
            for text, expected in spec.examples:
                self.assertEqual(m.tokens(text), expected, f"{name}: {text!r}")


class Compiler(unittest.TestCase):
    def test_glyph_limit(self):
        raw = changed()
        # 60 string-like states that any character can enter: 60 x 1,363 glyphs.
        for i in range(60):
            raw["states"][f"s{i}"] = {"token": "string", "default": f"s{(i + 1) % 60}"}
        raw["states"]["code"]["on"]["dq"] = "s0"
        with self.assertRaises(SpecError) as cm:
            compile_font(load(raw), BASE)
        self.assertIn("65535 limit", str(cm.exception))

    def test_compile_and_verify_minimal(self):
        from test_fontlex import verify
        spec = load(MINIMAL)
        res = compile_font(spec, BASE, unicodes=list(range(0x20, 0x7F)))
        self.assertEqual(res.stats["words"], 1)
        import io
        buf = io.BytesIO()
        res.font.save(buf)
        results = verify(spec, buf.getvalue(), BASE, n=300, log=lambda *a: None)
        for label, (passed, total) in results.items():
            self.assertEqual(passed, total, label)


if __name__ == "__main__":
    unittest.main()
