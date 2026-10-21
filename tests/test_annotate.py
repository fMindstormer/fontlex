"""Unit tests for markers/annotate.py: where it puts reading markers.

    python -m unittest discover tests

Skipped unless spaCy and the models are installed (markers/README.md).
"""

import importlib.util
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "markers"))
import annotate  # noqa: E402

FONT_WORD = {"en": r"[^\W\d_]+(?:['’][^\W\d_]+)*", "fr": r"[^\W\d_]+"}
TEXTS = {
    "en": ["We record a new record.", "The record's age; I record'em.", "Records record records.",
           "They object, but the object stays. A present to present.", "Keep a record︁ of it."],
    "fr": ["Le président préside. Ils président la séance.", "Un homme content, ils content une histoire.",
           "Les très excellents présidents excellent.", "Le sens du bus, je sens que tu bus."],
}


def installed(lang):
    if importlib.util.find_spec("spacy") is None:
        return False
    return importlib.util.find_spec(annotate.LANGS[lang][1]) is not None


class Placement(unittest.TestCase):
    def check(self, lang):
        if not installed(lang):
            self.skipTest(f"spaCy or {annotate.LANGS[lang][1]} is not installed")
        a = annotate.Annotator(lang)
        for text in TEXTS[lang]:
            marked = a.annotate(text)
            self.assertEqual(annotate.strip(marked), annotate.strip(text))
            for m in re.finditer("[︀︁]", marked):
                before = re.search(f"({FONT_WORD[lang]})$", marked[:m.start()])
                after = marked[m.end():]
                self.assertTrue(before and before.group(1).lower() in a.pairs, (marked, m.start()))
                self.assertFalse(re.match(FONT_WORD[lang], after) or re.match(r"['’][^\W\d_]", after)
                                 and lang == "en", (marked, m.start()))

    def test_english(self):
        self.check("en")

    def test_french(self):
        self.check("fr")


if __name__ == "__main__":
    unittest.main()
