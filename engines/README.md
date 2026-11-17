# Fontlex in DirectWrite

Native Windows apps shape text with DirectWrite; browsers on Windows use
HarfBuzz, and are checked by the Browsers workflow. This directory checks the
fonts in DirectWrite itself, on GitHub's Windows runners (the DirectWrite
workflow):

- `dwshape.cpp`, a small helper that shapes text as an app does: it splits a
  line into script runs (`AnalyzeScript`) and shapes each with `GetGlyphs`
  and `GetGlyphPlacements`, with the default features on.
  `test_fontlex.DirectWrite` talks to it, so every check that takes
  `--shaper` can run in DirectWrite (`check_directwrite.sh` runs them all).
- `probes.py`, small fonts that each use one OpenType mechanism the Fontlex
  fonts rely on, compared with HarfBuzz.
- `first_difference.py`, which finds the first lookup where an engine parts
  from HarfBuzz on a text: it turns on only the first k lookups by patching
  the font's bytes, and bisects.
- `compare.py`, a text's glyphs from two shapers, side by side.

## What DirectWrite does differently

Measured with DirectWrite 10.0.26100 on GitHub's windows-latest runner,
November 2026.

**It ignores reverse chaining lookups inside extension lookups.** A reverse
chaining contextual substitution (GSUB type 8) works on its own, and does
nothing when it is wrapped in an extension lookup (type 7), which a font
needs once its GSUB table is too large for 16-bit offsets. HarfBuzz and Core
Text apply both. The probes isolate it: the same rule, with and without
`useExtension`. The Fontlex fonts that compute right to left with many such
lookups have them wrapped, and so break in DirectWrite:

| Font | Reverse chaining lookups, wrapped | In DirectWrite |
|---|---|---|
| Fontlex Math | none (19, not wrapped since November 2026) | every line the same, 400 of 400 (327 of 345 differed with them wrapped) |
| Fontlex Relaxed Math | 51 | 245 of 387 lines differ; in each line bisected, the first right-to-left pass is the first to differ (`first_difference.py`) |
| Fontlex Markdown (both editions) | 60 | not measured: DirectWrite took over 60 seconds on one line, `>\t\tfoo`, and the check stopped |
| Fontlex English, French | none (1, not wrapped since November 2026) | 99.4% and 99.9% of words in context right (59% and 65% with it wrapped); every line of the English READMEs, and 15 of the 16 French sample lines; what differs is below |
| Fontlex Python, JavaScript | none (1, not wrapped) | right, apart from script runs (below) |
| Fontlex German, German Syllables | none | every random and transition case right; one hand-written case each differs, not yet looked at |

**It shapes each script run on its own,** as Chrome does: a Greek or
Cyrillic letter starts a new run, so a lexer font's state starts over after
`π` or `ж`, and the Python font's column ruler counts from there. Apart from
that, the Python and JavaScript fonts color as HarfBuzz does, and every
positioning check is the same.

The English, French and Fontlex Math fonts avoid the first problem by
keeping their reverse chaining lookups out of extension lookups (`unwrapped`
in `markdown/fontbuild.py`'s `build_gsub`): Fontlex Math's 19 come to 28 KB,
and fit under 16-bit offsets. Relaxed Math's come to 386 KB and Markdown's
to 548 KB, too much for that: saving the font puts them back inside
extension lookups, so the math build checks that it didn't.
Two things still differ in English and French, not yet looked at:

- **Noun/verb pairs** (`research`, `project`; `sens`, `président`), whose
  reading comes from the word before or an invisible marker after: 1,038 of
  170,817 English words in context and 175 of 202,190 French ones are wrong,
  and every miss the check prints is one of these words, drawn with the
  other reading's hints or none. The fonts have 128 and 32 such pairs.
- **One stylistic set on its own** (one kind of hint off) leaves most texts
  without their other hints too: 2,427 to 4,154 of 17,213 English texts
  right, and 2,613 to 11,909 of 20,221 French ones. With every set on,
  all are right. Wrapping the reverse chaining lookup or not changes none of
  these numbers. `dwshape.cpp` passes only the set, expecting the default
  features to stay on, as they do in HarfBuzz; DirectWrite may drop `calt`.

## Running it

On Windows with Visual Studio's x64 tools:

```sh
cl /nologo /std:c++20 /O2 /EHsc /utf-8 engines\dwshape.cpp dwrite.lib /Fe:build\dwshape.exe
PYTHONUTF8=1 engines/check_directwrite.sh
python engines/probes.py directwrite
python engines/first_difference.py build/Fontlex-Math.ttf directwrite "x^2"
```
