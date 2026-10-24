# Fontlex Math: formulas typeset by a font

A font that typesets a little LaTeX as you type it, in any text box:
fractions, square roots, superscripts and subscripts, Greek letters and
symbols. The text engine that lays out the letters does the layout. The
characters stay exactly as typed, so copying them gives back the LaTeX, and
with the font's `calt` feature off you see them all. `math/demo.html` is a
page with the font in a text box.

A second font, Fontlex Relaxed Math, reads math the way people type it in
plain text, `(a+b)/(c+d)` or `x^2`, and leaves ordinary text alone: see
[the relaxed notation](#the-relaxed-notation) below, and
`math/relaxed.html`.

- `\frac{a}{b}`, with the numerator and denominator centered over a bar.
- `\sqrt{x}`, with a sign as tall as its contents need (one height for
  text, one over superscripts, one over fractions) and an overbar.
- `x^2`, `x_1` and `x^{n+1}`, and both scripts at once, stacked over each
  other (`x_1^2` or `x^2_1`).
- Braces as groups: `{a+b}^2`.
- `\alpha` … `\Omega`, operators and relations such as `\pm`, `\le`,
  `\to`, `\infty` and `\sum`: the list is `SYMBOLS` in `layout.py`.

Constructs nest 3 deep, with at most 2 fractions inside one another and at
most 24 characters in a construct that isn't inside another. Text inside a
fraction or a script is set smaller, in three sizes. Anything incomplete
(`\frac{a}{`), or past those limits, stays as its characters until it isn't,
so a formula appears as you finish typing it. A space inside a construct
also leaves it as characters: WebKit gives every glyph of a space character
a space's width, which would break the layout. Spaces between formulas are
fine. Each line is read on its own.

## Results

Each line is shaped with the font. What it draws is read back from the
glyphs (characters by name and size, rules from their outlines) and
compared with `layout.py`, a separate Python model of the layout, to the
font unit.

| Lines | Count | HarfBuzz 15.0.0 | Core Text (macOS 27) |
|---|---:|---:|---:|
| Edge cases (`samples.EDGES`: incomplete and broken input) | 44 | 100% | 100% |
| Random formulas, some mistyped | 20,000 | 100% | 100% |

The passes themselves, run in Python by `program.py`, match the model on
40,000 more random lines.

In browsers I checked by screenshot. A page draws each line as text in the
font and, in the same place, as the font's outlines placed where HarfBuzz
places them. Two screenshots, one with each, are compared pixel by pixel
with 2 px of tolerance at 100 px per em, where the layout's smallest step
(30 units) is 3 px. Results on 340 lines:

- **Chrome 155:** the same on all of them.
- **WebKit (macOS 27):** the same on all 235 lines narrow enough to
  snapshot.

Typing a formula into a text box key by key in Chrome ends with the same
pixels as setting the text at once. Firefox and Windows are not checked yet.

The font has 47,653 glyphs, 1,097 substitution lookups (about 700 of them
nested lookups shared by every pass, in 2,052 subtables) and 301 positioning
lookups. It is 7.1 MB as TrueType and 0.79 MB as WOFF2. Shaping takes about 0.3 ms per
character in HarfBuzz (12 ms for a 40-character line).

## How it works

`layout.py` is the reference: it lexes a line, parses it, decides which
constructs are complete and within the limits, and lays them out. The font
does the same with substitutions and positioning:

1. **Tracks.** Every character's glyph is followed by four empty marks,
   tracks S, A, B and C. A pass reads and rewrites one track and sees, through
   mark filtering sets, only that track's glyphs. Commands are recognized
   first: `\frac` and `\sqrt` get their own glyphs, and a symbol's
   backslash becomes the symbol (its letters are hidden).
2. **Passes.** `program.py` holds 238 passes as Python functions, with a
   simulator that runs them on a line. They:
   - count brace depth, and decide what each brace opens (a numerator,
     denominator, root, script or group);
   - check for spaces, fractions in fractions, and length;
   - decide, a level at a time from the inside, which constructs are laid
     out (right to left, since a construct is valid only once its end is
     seen);
   - give every character its role, size and height;
   - add up widths, innermost level first. Numerators, denominators, roots
     and stacked scripts are counted in two base-16 digits: one pass adds
     the low digits and leaves each glyph its carry, the next adds the high
     digits. A pass's rules then grow with a digit's states, not a whole
     width's;
   - carry each fraction's difference of widths back to its start (right to
     left, in two digits as well), and turn every glyph into what it
     finally draws.
3. **Glyphs.** Outside fractions, text keeps its advance and is raised or
   lowered. Inside a fraction nothing advances: every glyph is a mark,
   attached to the one before it by a mark-to-mark chain. Movers between
   them (empty marks a fixed distance from the link before) carry the chain
   to the numerator, back over the bar, and down to the denominator. Bars
   and overbars are pieces hung off the chain, in two lengths per rule.
   `assemble.py` says what each token's glyphs are and emulates GPOS
   placing them, so the simulator checks the whole layout before any font
   is built.
4. **Compiling.** `mathfont.py` turns the passes into lookups:
   - transducers through `markdown/passes.py`;
   - per-token passes as class-based chaining contexts (format 2);
   - context passes as reverse chaining.

   It keeps the values each kind of token's glyphs can hold, grouped by
   their S track, and compiles rules only for those.

The main constraint is OpenType's lookup list. It addresses lookups with
16-bit offsets, so a font holds only a few thousand lookups, or about
6,500 subtables. The first compiler emitted reverse chaining rules (one per
subtable) and needed 178,000. Three changes brought it under:

- class-based rules;
- one pool of nested lookups, shared by all passes;
- a two-step substitution for any glyph that one pass could send to more
  than 32 different glyphs.

A step's count, not a pass's, is what costs lookups. The finals read only
what each glyph needs of the tracks (`assemble.slot_key`, `assemble.need`),
which keeps their rules few.

## Building and checking

    python math/verify.py --simulate --n 20000        # the passes, in Python
    python math/mathfont.py build/Fontlex-Math.ttf    # a few minutes
    python math/verify.py build/Fontlex-Math.ttf --shaper harfbuzz --shaper coretext --n 20000
    python math/build_page.py --font build/Fontlex-Math.ttf --out math/demo.html

`./check.sh math` runs these, and the same for the relaxed notation (each
with `--relaxed`). The build sets `PYTHONHASHSEED=0` for itself, so the same
sources give the same font.

## Known limits

- The limits above. More depth, more fractions or longer constructs would
  mean more passes and more glyphs, and the lookup list is the budget.
- In a fraction, the caret stays at the fraction's start while its glyphs
  are drawn where they belong, since they take no room of their own.
  Selecting part of a fraction highlights nothing visible.
- Chrome keeps the old shaping of text before an edit. A keystroke that
  completes a construct changes glyphs before the caret. With this font
  Chrome reshaped them in my test, but with a simpler test font it didn't,
  so the demo page makes it lay the box out again on every input by
  switching `font-kerning`.
- Chrome shapes canvas text (`fillText`, `measureText`) word by word, so on
  a canvas a construct can't span a space. Text boxes and other page text
  are shaped whole.
- Firefox and Windows (DirectWrite) are not checked yet.

## The relaxed notation

Fontlex Relaxed Math typesets what plain-text math looks like:

- fractions: `1/2`, `x/2`, `2a/3`, `(a+b)/(c+d)`, `f(x)/2`, `sin(x)/x`,
  `1/(1+1/x)`;
- scripts: `x^2`, `x^(n+1)`, `x^-1`, `x_1`, `H_2O`, and stacked, `x_i^2`;
- roots: `sqrt(x^2+1)`;
- `<=` `>=` `!=` `->` `=>` `+-` as ≤ ≥ ≠ → ⇒ ±.

Parentheses around all of a fraction's part, a script's argument or a
root's contents go; with a script after them they stay, as in
`(a+b)^2/c`. Limits, sizes and layout are Fontlex Math's.

What matters as much is what it leaves alone. A font like this runs on
every line of every text box it is used in, and slashes, carets and
underscores are common in prose and code. The rules, in `relaxed.py`:

- A fraction's part is a number (`12`, `3.5`), a number and one letter
  (`2a`), one letter, a group in parentheses, a call (`f(x)`, `sin(x)`) or
  a root, each with its scripts. A longer word is never one: `and/or`,
  `km/h`, `page/2` stay text.
- Two lone letters make a fraction only next to an operator with an
  operand past it (`a+b/c`, `x = a/b`), so `w/o`, `n/a`, `I/O-conversion`
  and `C/C++` stay text.
- A fraction's neighbors are spaces, operators, punctuation or nothing:
  slashes in a row (`a/b/c`, `10/23/2026`, `//`) make no fraction. Nor does
  any slash in a run of characters without a space where some slash touches
  a longer word (`tr/a-z/A-Z/`, `s/x/y/g`).
- No script touches another underscore, and a number takes no subscript:
  `T_U_INT`, `1_000_000`, `1.09_01` stay text.
- A number has at most one point, so an IP address is no fraction.

`prose.py` reads text the way the font would and lists what it would
typeset. Over this project's READMEs and every macOS man page (461,327
lines, rendered with `mandoc`), 311 lines get a construct. About half are
real math (`2^63 - 1`, `1/9 the page length`, `-1/2`); the rest are mostly
numbers over numbers (`7/8 bit`, `27/811 test scripts`, a date like
`6/14`), which can't be told from `1/2`, and some code (`^G` for a control
character, `A-Z_a-z` in a regular expression).

### How it works

`front.py` has 122 passes that read a line as `relaxed.py` does and leave
it as the tokens of the LaTeX that lays out the same: `(a+b)/(c+d)` becomes
`\frac{a+b}{c+d}`, with the parentheses as the braces. What the line
doesn't have, the `\frac` and the braces around `1` and `2` in `1/2`, is
inserted, by a multiple substitution, as tokens whose glyphs draw nothing
and count no characters. The slash stays between the fraction's parts, as a
token that hides. Then program.py's passes (`program(relaxed=True)`) lay
the line out as they do LaTeX.

The front end works a parenthesis level at a time, outermost first, as
the passes after it work a brace level at a time:

- paren depth, which parentheses match, and words with their kinds;
- the poisoned runs;
- then, per level: each script's argument (right to left), the scripts
  (left to right), where elements end, each slash's left and right side,
  the verdict, and the parts' ends.

Two things kept it within the font's limits. Values that no token can hold
any more give their glyphs to new ones (`Font.recycle`). Each pass reads a
small view of a token on a scratch track, and a level's results go to a
track of their own, not into S, where every combination of them would have
been a value. A brace opened past `BRACE_LIMIT`, which deep relaxed formulas
reach without as many parentheses, is text with its closer, instead of
ending the line's structure as in LaTeX: nothing that deep is laid out
anyway.

| Lines | Count | HarfBuzz 14.6.0 | Core Text (macOS 27) |
|---|---:|---:|---:|
| Edge cases (`samples.RELAXED_EDGES`: incomplete input, prose) | 51 | 100% | 100% |
| Random formulas and words, some mistyped | 20,000 | 100% | 100% |

The passes, run in Python, match `relaxed.py` on 100,000 more random lines.
By screenshot, as for Fontlex Math:

- **Chrome 155:** 348 of 349 lines the same. The exception is a line that
  mixes Greek and Latin letters inside a construct (see below).
- **WebKit:** the same on 322 of the 323 lines narrow enough to snapshot,
  and 1 pixel apart on the other.

The font has 55,176 glyphs, 2,044 substitution lookups (1,596 of them
nested, in 3,149 subtables) and 301 positioning lookups. It is 10.1 MB as
TrueType and 1.3 MB as WOFF2. Shaping takes 0.34 ms per character in
HarfBuzz.

### Its limits

- Fontlex Math's limits, and its caret and selection behavior.
- A space inside a construct leaves it as its characters: `(a + b)/2`
  stays text, `(a+b)/2` doesn't.
- `a/b` on its own stays text (as `w/o` does); `(a)/(b)` or `x = a/b`
  doesn't.
- Chrome shapes runs of Greek and Latin letters apart, and a construct
  can't span two runs, so `e^(iπ)` stays text there. HarfBuzz and WebKit
  lay it out.
- A part is a whole word, so `2/3x` is 2 over 3x, and `x^2y` is x² y.
- Firefox and Windows are not checked yet.
