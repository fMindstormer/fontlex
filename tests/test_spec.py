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
from fontlex import Model, SpecError, _expand_class, compile_font, load_spec, syllable_breaks  # noqa: E402
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


# German-like: capitalized words, colored by listed words and endings.
NOUNS = {
    "name": "Fontlex Test Nouns",
    "classes": {"upper": "A-Z", "lower": "a-z"},
    "start": "text",      # (yaml.safe_dump sorts keys, so the first state isn't text)
    "states": {
        "text": {"default": "text", "on": {"upper": "noun", "lower": "word"}},
        "noun": {"on": {"upper": "noun", "lower": "noun"}, "like": "text"},
        "word": {"on": {"upper": "word", "lower": "word"}, "like": "text"},
    },
    "words": {"state": "noun", "sets": {"masc": ["Sprung"], "none": ["Die"]}},
    "suffixes": {"state": "noun", "sets": {"fem": ["ung"], "neut": ["chen", "Ei"]}},
    "themes": {"light": {"masc": "#2E6FBF", "fem": "#C0392B", "neut": "#2E8B57"}},
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

    def test_suffix_state_must_exist(self):
        raw = {**NOUNS, "suffixes": {"state": "nope", "sets": {"fem": ["ung"]}}}
        self.assertSpecError(raw, "suffixes.state must name a state")

    def test_suffix_state_not_start(self):
        raw = {**NOUNS, "suffixes": {"state": "text", "sets": {"fem": ["ung"]}}}
        self.assertSpecError(raw, "can't be the start state")

    def test_suffix_state_matches_words(self):
        raw = {**NOUNS, "suffixes": {"state": "word", "sets": {"fem": ["ung"]}}}
        self.assertSpecError(raw, "suffixes.state must be the same as words.state")

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


class Suffixes(unittest.TestCase):
    def sets(self, text):
        m = Model(load(NOUNS), CMAP)
        return [ws for _, ws in m.lex(text)]

    def test_longest_ending_colors_the_whole_word(self):
        self.assertEqual(self.sets("Zeitung"), ["fem"] * 7)
        self.assertEqual(self.sets("Maedchen"), ["neut"] * 8)

    def test_listed_word_wins(self):
        self.assertEqual(self.sets("Sprung"), ["masc"] * 6)
        self.assertEqual(self.sets("Die Zeitung")[:3], ["none"] * 3)

    def test_word_matches_only_a_whole_word(self):
        # "Sprung" is listed, but "AbSprung" is a different word: its ending decides.
        self.assertEqual(self.sets("AbSprung"), ["fem"] * 8)

    def test_ending_can_be_the_whole_word(self):
        self.assertEqual(self.sets("Ei"), ["neut"] * 2)

    def test_lowercase_words_are_left_alone(self):
        self.assertEqual(self.sets("ungenau"), [None] * 7)


# Syllables from a few Liang patterns, one of each kind the compiler handles:
# inside a word (a1ba), before any letter (1na), after any letter (an1),
# anchored at a word's start (.ki2n) and end (ka1n.).
SYLLABLE_PATTERNS = "a1ba 1na an1 .ki2n ka1n. b1b"


def syllable_spec(d, min_left=2, **extra):
    Path(d, "p.txt").write_text(SYLLABLE_PATTERNS + "\n", encoding="utf-8")
    raw = {"name": "Fontlex Test Syllables", "classes": {"letter": "a-zA-Z"}, "start": "text",
           "states": {"text": {"default": "text"}},
           "syllables": {"letters": ["letter"], "patterns": ["p.txt"], "min_left": min_left,
                         "min_right": 2, "colors": ["s1", "s2"]},
           "themes": {"light": {"s1": "#2E6FBF", "s2": "#C0392B"}}, **extra}
    Path(d, "spec.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    return load_spec(Path(d, "spec.yaml"))


class Syllables(unittest.TestCase):
    def test_liang_highest_level_wins(self):
        pats = {"ab": [0, 1, 0], "abc": [0, 2, 0, 0]}
        self.assertEqual(syllable_breaks("abc", pats, 3), [])      # 2 beats 1: no break
        self.assertEqual(syllable_breaks("abd", pats, 3), [1])

    def test_edge_minimums(self):
        with tempfile.TemporaryDirectory() as d:
            spec = syllable_spec(d)
            m = Model(spec, CMAP)
            # "baba": a1ba breaks b-a|ba; min_left/right forbid b|aba and bab|a.
            self.assertEqual([s for _, s in m.lex("baba")], ["s1", "s1", "s2", "s2"])
            spec1 = syllable_spec(d, min_left=1)
            self.assertEqual(syllable_breaks("ana", spec1.syllables.patterns, spec1.syllables.longest), [1])

    def test_errors(self):
        with tempfile.TemporaryDirectory() as d:
            syllable_spec(d)
            good = yaml.safe_load(Path(d, "spec.yaml").read_text())
            for change, fragment in (({"letters": ["nope"]}, "unknown classes"),
                                     ({"colors": ["one"]}, "at least two colors"),
                                     ({"min_left": 3}, "must be 1 or 2"),
                                     ({"patterns": ["missing.txt"]}, "can't read")):
                spec_raw = yaml.safe_load(yaml.safe_dump(good))
                spec_raw["syllables"].update(change)
                Path(d, "bad.yaml").write_text(yaml.safe_dump(spec_raw), encoding="utf-8")
                with self.assertRaises(SpecError) as cm:
                    load_spec(Path(d, "bad.yaml"))
                self.assertIn(fragment, str(cm.exception))
            spec_raw = yaml.safe_load(yaml.safe_dump(good))
            spec_raw["states"]["other"] = {"default": "text"}
            Path(d, "bad.yaml").write_text(yaml.safe_dump(spec_raw), encoding="utf-8")
            with self.assertRaises(SpecError) as cm:
                load_spec(Path(d, "bad.yaml"))
            self.assertIn("one state", str(cm.exception))

    def test_compile_and_verify(self):
        from test_fontlex import SHAPERS, verify
        import io
        with tempfile.TemporaryDirectory() as d:
            spec = syllable_spec(d)
            res = compile_font(spec, BASE, unicodes=list(range(0x20, 0x7F)))
            buf = io.BytesIO()
            res.font.save(buf)
            data = buf.getvalue()
            results = verify(spec, data, BASE, n=500, log=lambda *a: None)
            for label, (passed, total) in results.items():
                self.assertEqual(passed, total, label)
            order = TTFont(io.BytesIO(data)).getGlyphOrder()
            m = Model(spec, CMAP)
            text = "Banane Kinkan ababab Abba"
            glyphs, _ = SHAPERS["harfbuzz"](data).shape(text)
            got = [order[g].split(".lxw_")[1] if ".lxw_" in order[g] else None for g, *_ in glyphs]
            self.assertEqual(got, [s for _, s in m.lex(text)])
            self.assertIn("s2", got)


class ListFiles(unittest.TestCase):
    def test_first_listing_wins(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "over.tsv").write_text("# overrides\nHaus\tnone\nTag\tmasc\n", encoding="utf-8")
            Path(d, "learned.tsv").write_text("Tag\tfem\nHaus\tneut\nBaum\tmasc\n", encoding="utf-8")
            raw = changed()
            raw["words"] = {"state": "ident", "sets": {"keyword": ["if"]},
                            "files": ["over.tsv", "learned.tsv"]}
            spec_path = Path(d, "spec.yaml")
            spec_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
            spec = load_spec(spec_path)
        listed = {w: k for k, ws in spec.word_sets for w in ws}
        self.assertEqual(listed, {"if": "keyword", "Haus": "none", "Tag": "masc", "Baum": "masc"})

    def test_bad_line(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "bad.tsv").write_text("no tab here\n", encoding="utf-8")
            raw = {**MINIMAL, "words": {"state": "ident", "files": ["bad.tsv"]}}
            Path(d, "spec.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
            with self.assertRaises(SpecError) as cm:
                load_spec(Path(d, "spec.yaml"))
        self.assertIn("bad.tsv:1: expected entry<TAB>set", str(cm.exception))


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

    def test_compile_and_verify_suffixes(self):
        from test_fontlex import SHAPERS, verify
        spec = load(NOUNS)
        res = compile_font(spec, BASE, unicodes=list(range(0x20, 0x7F)))
        self.assertEqual((res.stats["words"], res.stats["suffixes"]), (2, 3))
        import io
        buf = io.BytesIO()
        res.font.save(buf)
        results = verify(spec, buf.getvalue(), BASE, n=300, log=lambda *a: None)
        for label, (passed, total) in results.items():
            self.assertEqual(passed, total, label)
        # And the shaped font itself, on the cases above.
        order = TTFont(io.BytesIO(buf.getvalue())).getGlyphOrder()
        glyphs, _ = SHAPERS["harfbuzz"](buf.getvalue()).shape("Die Zeitung AbSprung Sprung Ei")
        sets = "".join({"masc": "m", "fem": "f", "neut": "n", "none": "_"}[order[g].split(".lxw_")[1]]
                       if ".lxw_" in order[g] else "." for g, *_ in glyphs)
        self.assertEqual(sets, "___.fffffff.ffffffff.mmmmmm.nn")

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
