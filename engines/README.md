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
`useExtension`. Every Fontlex font that computes right to left has such
lookups, and so breaks in DirectWrite:

| Font | Reverse chaining lookups, wrapped | In DirectWrite |
|---|---|---|
| Fontlex Math, Relaxed Math | 19 and 50 | 327 of 345 and 315 of 351 lines differ; in each line bisected, the first right-to-left pass is the first to differ (`first_difference.py`) |
| Fontlex Markdown (both editions) | 60 | not measured: DirectWrite took over 60 seconds on one line, `>\t\tfoo`, and the check stopped |
| Fontlex English, French | 1 | most hints missing: 59% and 65% of words in context right |
| Fontlex Python, JavaScript | none (1, not wrapped) | right, apart from script runs (below) |
| Fontlex German, German Syllables | none | every random and transition case right; one hand-written case each differs, not yet looked at |

**It shapes each script run on its own,** as Chrome does: a Greek or
Cyrillic letter starts a new run, so a lexer font's state starts over after
`π` or `ж`, and the Python font's column ruler counts from there. Apart from
that, the Python and JavaScript fonts color as HarfBuzz does, and every
positioning check is the same.

A font could avoid the first problem by keeping its reverse chaining lookups
out of extension lookups: their subtables would have to sit within 64 KB of
the lookup list. That is likely possible for the English and French fonts,
which have one such lookup each, and not for the math fonts.

## Running it

On Windows with Visual Studio's x64 tools:

```sh
cl /nologo /std:c++20 /O2 /EHsc /utf-8 engines\dwshape.cpp dwrite.lib /Fe:build\dwshape.exe
PYTHONUTF8=1 engines/check_directwrite.sh
python engines/probes.py directwrite
python engines/first_difference.py build/Fontlex-Math.ttf directwrite "x^2"
```
