# Fontlex Math: formulas typeset by a font

A font that typesets a little LaTeX as you type it, in any text box:
fractions, square roots, superscripts and subscripts, Greek letters and
symbols. The text engine that lays out the letters does the layout. The
characters stay exactly as typed, so copying them gives back the LaTeX, and
with the font's `calt` feature off you see them all. `math/demo.html` is a
page with the font in a text box.

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

`./check.sh math` runs these. The build sets `PYTHONHASHSEED=0` for itself,
so the same sources give the same font.

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
