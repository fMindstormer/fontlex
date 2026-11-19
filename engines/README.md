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
| Fontlex Math | none (19, not wrapped since November 2026) | 438 of 439 lines the same (327 of 345 differed with them wrapped); the other, `\vec{αβ}`, mixes Greek and Latin letters in a construct (script runs, below) |
| Fontlex Relaxed Math | none (51, not wrapped since November 2026) | 372 of 387 lines the same (142 with them wrapped, 337 before the font placed a fraction's end, below); the others mix Greek and Latin letters in a construct (script runs, below) |
| Fontlex Markdown (both editions) | none (59, not wrapped since November 2026) | 438 of 447 spec examples, all 23 GFM ones, 914 of 916 README lines and 279 of 292 random lines the same (with them wrapped, it took over 60 seconds on one line, `>\t\tfoo`); what differs is below |
| Fontlex English, French | none (1, not wrapped since November 2026) | 99.4% and 99.9% of words in context right (59% and 65% with it wrapped); every line of the English READMEs, and 15 of the 16 French sample lines; what differs is below |
| Fontlex Python, JavaScript | none (1, not wrapped) | right, apart from script runs (below) |
| Fontlex German, German Syllables | none | every random and transition case right; one hand-written case each differs, not yet looked at |

**It attaches a mark only to a base glyph that starts its cluster.** In
`a+b/c` the fraction's closing brace isn't in the text: the font inserts
it after `c`, so its base glyph (`_fendbase*`, which the bar's last piece
attached to) is inside `c`'s cluster. DirectWrite left the piece
unattached, at the end of the line, where HarfBuzz puts it 60 units back;
its glyphs were the same (`compare.py`). After `(c+d)` the closer is the
`)`, which starts a cluster, and the bar was right. Of the 387 lines
checked, 39 ended a fraction on an inserted closer. The math fonts now
place that piece instead of attaching it: an offset back from the pen,
which is past the base, and the base's height (`gpos` in
`math/mathfont.py`). Their other marks on bases, at a root's start and an
overline's end, sit on glyphs that start their clusters.

**It shapes each script run on its own,** as Chrome does: a Greek or
Cyrillic letter starts a new run, so a lexer font's state starts over after
`π` or `ж`, and the Python font's column ruler counts from there. Apart from
that, the Python and JavaScript fonts color as HarfBuzz does, and every
positioning check is the same.

The English, French and math fonts avoid the first problem by keeping their
reverse chaining lookups out of extension lookups (`unwrapped` in
`markdown/fontbuild.py`'s `build_gsub`): Fontlex Math's 19 come to 28 KB,
and fit under 16-bit offsets. Relaxed Math's came to 386 KB, too much for
that: saving the font put them back inside extension lookups, so the math
build checks that it didn't. A right-to-left pass maps every pair of a
value and a state, and most passes tell few of their values apart (the
slash's `right_step` sees 1,160 values and needs 20 kinds of them), so the
compiler now runs such a pass on those kinds (`keyed_rtl` in
`math/mathfont.py`), which brings Relaxed Math's to 40 KB. Markdown's came
to 548 KB, 85% of it from two passes over glyphs that hold a character and
its state at once, so there was no other glyph for the state to go on. Now
such a pass puts a companion mark after each glyph it reads, one for each
kind of glyph the pass tells apart, runs on those, and ligates each back
into its glyph (`rtl_keyed` in `markdown/passes.py`). With the
link-destination passes minimized first (1,459 states to 172), Markdown's
come to 39 KB. They also need room. HarfBuzz's packer, which saves these fonts, keeps a
lookup out of an extension lookup only while 8 bytes for every Extension
subtable, and the unwrapped subtables, come to under 64 KB. Markdown had
9,242 subtables, 74 KB of such records, so none fitted, however small.
Class-based rules for the emphasis rounds (a subtable per group of
closers, not per rule) and nested substitutions shared across passes
bring that to 3,844 (Markdown Sans: 10,341 to 4,943), and about 40 KB of
reverse chaining lookups now fit: all 59 of Markdown's stay out, and the
build checks that they do.

What still differs in Markdown:

- **A tab is a run of its own.** DirectWrite's script analysis gives a tab
  its own run, as a text layout does for tab stops, so nothing a pass
  learns crosses it: a tab-indented code block, `#\tFoo`, `*\t*\t*`. 15
  of the 29 lines that differ in Fontlex Markdown have a tab, 12 mix Greek
  or Cyrillic letters into a construct (script runs, below).
- **It counts a rule's substitution positions after the earlier ones
  apply.** A rule that matches an opener, a run between and a closer
  substitutes at three positions; once the run between is discarded, it
  leaves the sequence the lookup sees, and DirectWrite's third position
  fell past the closer (`*foo**bar*`). HarfBuzz keeps the positions it
  matched. The emphasis rounds now substitute the closer first.
- An entity in a link title (`[a](url &quot;tit&quot;)`) has the same
  glyphs, but DirectWrite gives the visible one the next character's
  cluster. One random line with an accent on a `*` differs, not yet
  looked at.

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
