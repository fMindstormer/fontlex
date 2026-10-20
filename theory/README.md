# What a font can compute

Fontlex compiles lexers, a learner's grammar and GitHub Flavored Markdown into
OpenType fonts. This note works out what that kind of compilation can reach
in principle, what actually limits it, and what follows from fonts being
programs. The claims marked *measured* come from the two scripts here and the
fonts in this repository; the theory is classical automata theory applied to
OpenType's lookups.

## The machine

A text engine cuts text into runs (one font, one script, one direction), maps
each run's characters to glyph ids, and applies the font's GSUB lookups in
order. Each lookup is one pass over the run:

- **Contextual lookups (types 5 and 6)** go left to right. At each position a
  rule can read what is behind (already rewritten by this pass), the input
  and what is ahead (not yet rewritten), then rewrite the input. That is a
  left-sequential transducer with a finite lookahead.
- **Reverse chaining (type 8)** goes right to left, reading the rewritten
  glyphs on its right: a right-sequential transducer.
- **Mark filtering sets** let a lookup see only some glyphs, skipping all
  others. The lookahead is then finite in the filtered view but unbounded in
  the text: matching `*` against the next `*` skips any number of letters.
  That is still a sequential transducer, with regular lookahead.
- **Multiple and ligature substitutions** change the run's length. Nested
  lookups apply other lookups at matched positions, up to a fixed depth.

Between passes, the only memory is the glyph at each position. A pass that
needs state *s* at a letter writes a variant of that letter recording *s*;
the next pass reads the variant.

**Upper bound.** Every lookup computes a rational (finite-state) function of
the run, and rational functions are closed under composition, so a font with
any number of lookups computes a rational function of each run. Engines
bound nesting (HarfBuzz at 64), so nested lookups add nothing beyond that.

**Lower bound.** By Elgot and Mezei's theorem (1965), every rational function
is a right-to-left sequential function followed by a left-to-right one. So
with enough glyphs, any finite-state transformation is a font with **one
change of direction**. A lexer, a transliterator, a finite-state
morphological analyzer, a regular-expression highlighter or GitHub's line
syntax within bounds all qualify.

So, as an idealization: **a font computes exactly the rational functions of
its runs.** It can't decide whether brackets balance, reverse a word, copy a
string or see another line. Everything else in this note is about how far
the real budgets let you get toward that class, and past it on bounded
inputs.

## The three budgets

| Resource | What it limits | Limit | Fontlex Markdown uses |
|---|---|---|---|
| Glyph ids | states: a pass with *s* states over *a* letters needs up to *s*·*a* variants | 65,535 | 63,367 (97%) |
| Lookup headers | passes: every lookup's header lies within 16-bit offsets of the LookupList | 4,681 lookups of one filtered subtable (*measured*) | 1,945 lookups, 52% of the window |
| Engine work | passes × run length | HarfBuzz: about 4,096 glyph operations per character | 0.3 ms a line, about 15× a plain font |

**Glyphs are the scarce resource, passes the cheap one.** The 65,535 glyph
ids are shared by every letter's variants, so a run carries about 16 bits
per position from one pass to the next, and fewer when many letters need
variants. Passes, by contrast, cost bytes of lookup data and time. A font
compiler's main job is therefore to trade states for passes. Fontlex
Markdown matches emphasis with a stack of three openers in six rounds of
O(1) states instead of one pass of about 14,000 states. It splits link
destinations into eight passes of 6 to 35 states instead of one of 364. In
automata terms this is a cascade decomposition (Krohn and Rhodes): a big
machine as a chain of small ones, each reading the previous one's output.

**OpenType says 65,535 lookups; the format allows about 4,700.** The lookup
count is 16-bit, but the LookupList reaches each lookup's header through a
16-bit offset. So all headers must fit in 64 KB, at 8 + 2 bytes per subtable
(+2 for a mark filtering set) plus 2 for the list entry. Identical lookups
can share a header, which is why `depth.py` packs 16,000 identical rounds
but only 4,681 distinct ones (*measured*; fontTools stops with "all lookups
are already Extension lookups"). The Sans edition of Fontlex Markdown uses
62% of the window. The 24-bit glyph ids and offsets proposed for a future
OpenType would lift both this budget and the glyph budget.

**Engines bound the work.** HarfBuzz charges about one operation per glyph
per pass, plus one per nested lookup call, and gives up when a run exceeds
max(4,096 × length, 65,536) operations (`hb-limits.hh`). It also bounds
nesting at 64, and a rule whose input is longer than 64 glyphs never applies. Core Text documents no
limits. *Measured*: its line API applies no GSUB at all to a line longer
than 10,240 characters, even for a font with two lookups. Safari isn't
affected: WebKit renders emphasis whose markers are 12,000 characters apart.

## Counting: a font can't count, but it can count to 4,000

Balanced brackets aren't a regular language, so no font decides them. A
bounded version costs almost nothing, though. `depth.py` builds a font in
which each of *R* lookups is one round of peeling. Each round sees only the
unmatched brackets (a mark filtering set) and matches every `(` that comes
right before a `)` in that view. Matched brackets leave the view, so round
*k* matches the brackets nested *k* deep. The font needs eight extra glyphs
whatever *R* is.

*Measured* (`depth.py --distinct`; the time is to shape the deepest line,
`(` × *R*, a letter, `)` × *R*):

| Rounds *R* | Deepest matched, HarfBuzz | Core Text | ms, HarfBuzz | ms, Core Text |
|---|---|---|---|---|
| 10 | 10 | 10 | 0.0 | 0.1 |
| 100 | 100 | 100 | 0.2 | 0.6 |
| 1,000 | 1,000 | 1,000 | 13 | 40 |
| 2,000 | 2,000 | 2,000 | 52 | 153 |
| 4,000 | 4,000 | 4,000 | 201 | 610 |
| 4,678 | the most distinct rounds that fit the lookup list | | | |

Both engines match exactly *R* deep, every time. With identical rounds (one
shared header), HarfBuzz matches 6,000 deep. Core Text stops at 5,119,
because that line is 10,239 characters long and a longer one gets no GSUB.
At 12,000 rounds HarfBuzz runs out of its budget and stops shaping.

In both Chrome 155 and Safari's WebKit, a line of 1,001 `(`, a letter and
1,000 `)` renders with the 1,000 matched pairs as `[` `]` and the first `(`
alone left round. So matching across 2,000 characters at depth 1,000 works
in a text box.

The cost model is passes × run length: depth *d* in a run of *n* glyphs
costs about *d*·*n* glyph visits. For anything people write, the bound is
invisible: nesting deeper than a few dozen is rare. A font can validate
JSON's brackets, color brackets by depth (Lisp's rainbow parentheses), or
match quotes, at any depth a human produces. The impossibility theorem
still holds; it just sits at depth 4,000, past the edge of a text box.

**Positions count without a bound.** The glyph channel can't count, but the
layout channel can. GPOS gives each glyph an advance, which can be negative,
chosen by the same rational machinery, and an engine places each glyph at
the sum of the advances before it. Give `(` an extra +*w* and `)` an extra
−*w*, and a glyph's position records the nesting depth exactly, for any
depth. A font can't *decide* that brackets balance, but it can *draw* the
depth, and the total width of the line encodes the balance. This follows
from the format and isn't built here. It matters below, because positions
are observable.

**Past rational, on bounded inputs.** Peeling is one instance of a general
trick: a non-regular function restricted to bounded inputs becomes a
composition of many small passes. Another would be odd-even transposition
sort, where *n* rounds of compare-and-swap on adjacent glyph pairs sort *n*
glyphs. Each round needs a position-parity bit and one rule per pair of
letters. That would give a font that displays each word's letters in
alphabetical order, up to the pass budget. It isn't built here; the
argument is the same as for peeling.

## Past the edge

- **Another run, another program.** The engine, not the font, decides
  where runs start. *Measured*:
  - Chrome restarts shaping at every script change and every tab.
  - Safari's WebKit restarts at soft line wraps, and keeps going across
    scripts.
  - Core Text's line API stops applying GSUB past 10,240 characters.
  - Fallback fonts cut runs everywhere.

  A font program's behaviour is therefore partly defined by the browser,
  much as undefined behaviour makes a C program's meaning depend on the
  compiler. Portable font programs must keep their context within a run.
- **No lines, no documents.** A font never sees the next line. Reference
  links, setext headings and fenced code are out of reach for Fontlex
  Markdown, and no budget changes that.
- **Turing completeness requires leaving OpenType.** HarfBuzz's
  experimental WebAssembly shaper runs arbitrary code from a font. llama.ttf
  (2024) runs a language model that way. Browsers don't enable it. Within
  OpenType's tables, the theory above is the whole story.

Prior work shows the range of what fonts have been made to do: Sans Bullshit
Sans (2015) replaces buzzwords with ligatures, AtF Spark (2017) draws
sparklines from numbers, Numderline groups digits, and Fontemon (2021) is a
game. Fontlex's contribution is compiling exact specifications (a lexer,
CommonMark) and checking the fonts against a reference model, which is what
surfaced the next point.

## Unexpected consequences

### 1. A font compiler is a shaping engine's test oracle

Fontlex's fonts come with an exact reference model (`cm_inline.py`, the
lexers), so every glyph can be checked in every engine. That makes each
compiled font a large differential test. The proportional edition of
Fontlex Markdown failed in HarfBuzz, and only there, on lines like `<a>x`.

*Measured*: HarfBuzz from 12.3.1 (released 2026-01-20) through at least
14.6.0 never matches a glyph with id **32,512 to 32,767** in a context or
chain context subtable of format 2; formats 1 and 3 are fine, and 12.3.0
is too. The cause is HarfBuzz commit a78994395, which enlarged the format 2
coverage cache to `hb_cache_t<14, 1, 8>`. That cache stores 7 bits per byte
and starts each byte at 0xFF.
Its empty-slot check applies only when the stored bits fill the byte, and it
stores only ids below 16,384. So an id whose high byte is 127 reads an empty
slot as a cached "not covered". `hbcache.py` shows it with seven one-rule
fonts: ids 32,511 and 32,768 work, and 32,512 to 32,767 don't. Chrome 155,
the current stable release, draws "aaa" where it should draw "BBB" (Core
Text gets all seven right).

Exposure:
- Hand-made large fonts mostly escape. Noto Sans CJK (65,535 glyphs) writes
  all 281 of its chain contexts as format 3, and none of the 15 fonts on
  this Mac with more than 32,512 glyphs puts a context-covered glyph in the
  window.
- Compiled fonts are exposed. Class-based rules compile to format 2, and a
  compiler's state variants fill the glyph space. The Sans edition had six
  glyphs there, one of them the `>` that ends raw HTML.

`fontbuild.py` now inserts padding glyphs to move such glyphs past the
window. The bug is reported upstream as
[harfbuzz/harfbuzz#6418](https://github.com/harfbuzz/harfbuzz/issues/6418).

The general point: an engine's fast paths are tuned on fonts that people
draw, and compiled fonts are far out of that distribution. They hit glyph-id
ranges, lookup counts, rule counts and pass depths that hand-made fonts
never reach. Checking them against a model, in several engines, finds
engine bugs as a by-product.

### 2. What you see is a computed function of what you have

The characters stay as typed. Copying, search, screen readers, diff and
language models see the source, and people see the rendering. For Fontlex
that is the point: Markdown stays Markdown, a German noun keeps its letters.

The same property cuts the other way, and the theory sharpens it. The
rendering can be **any rational function of the run**. So a font can draw
every string truthfully except ones matching a chosen pattern, such as one
account number or one clause, and only in a chosen context. No sample of
"normal" text would reveal it. Wherever people trust what a document *looks*
like more than what it *says* (contracts, code review, moderation), the
font is part of the trusted computing base. The defensive check is the one
Fontlex runs on itself: shape the text with the actual font and compare
what is drawn with what is encoded (`markdown/verify.py` does this glyph by
glyph). Or don't let untrusted fonts into contexts where text authenticity
matters.

### 3. Layout is observable, so a font can leak what it computes

Web pages can observe layout (widths, overflow, scrolling), and CSS can make
those observations trigger requests. A published technique (Michał
Bentkowski's "Stealing data in great style") injects a font whose ligatures make one fixed
string wide, then detects the width to learn whether a secret text contains
that string. The analysis above widens the class: a single injected font
can turn any **regular property** of a run, and integer sums such as a
count, into a width. That covers prefixes, character classes and
membership in a list, not only fixed strings. The defenses are the existing
ones, which this makes more pressing: restrict `font-src` in a Content
Security Policy, and keep secrets out of elements an attacker can style.

### 4. Computation where scripts can't run

A font runs wherever text is drawn: plain text boxes, document editors,
design tools, CMS fields, pages whose Content Security Policy forbids
script. `script-src 'none'` doesn't stop a font. That is what makes Fontlex
useful (syntax highlighting and Markdown in any textarea, with no
JavaScript), and also why consequences 2 and 3 apply in places that
consider themselves script-free. PDF export freezes the result: the PDF
stores the glyphs the font produced, so the computation happens once, when
the document is printed.

### 5. Cost scales with passes, not with what you write

Every pass visits the whole run, in every engine. Fontlex Markdown's 151
top-level lookups (1,945 in all) shape a line in about 0.3 ms in HarfBuzz,
roughly 15 times a plain font. The depth font at depth 1,000 takes 12 ms in
HarfBuzz and 40 ms in Core Text. That is fine for a line, but it grows with
paragraph length, because the run is the paragraph. Font programs belong in
text that breaks into short runs: lines of code, list items, form fields.

## Where to push next

- **Finite-state language tools, compiled directly.** Morphological
  analyzers built as transducers (HFST, Foma) are rational functions, so
  they compile in principle. The question is the glyph budget. A lexicon
  can avoid states altogether by matching whole words with literal context
  rules: that costs table bytes (a few per letter), not glyphs. By that
  estimate (not built), on the order of 100,000 words fits in a few
  megabytes of tables. That suits Russian
  stress marks, the next learner font proposed for this repository.
- **Structure checks at human depth**: brackets, quotes and tags to depth
  50, in any text box, with unmatched ones marked.
- **Bounded non-regular transformations by many small passes**: sorting
  letters, aligning digits for arithmetic on numbers of bounded length.
- **Positions as a second output**: drawing depth, indentation or bars from
  sums of advances, beyond what glyph states can count.
- **Engine conformance**: compiled fonts with reference models as a
  standing test suite for HarfBuzz, Core Text and DirectWrite.

## Reproducing

```sh
python theory/depth.py --distinct --rounds 10 100 1000 2000 4000 4678 --shaper harfbuzz --shaper coretext
python theory/depth.py --rounds 5119 6000 --shaper harfbuzz --shaper coretext   # identical rounds, shared
python theory/hbcache.py --page /tmp/hbcache.html                              # open in a browser
```

`./check.sh theory` runs both at small sizes.
