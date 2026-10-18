# Fontlex Markdown: CommonMark rendered by a font

A font that renders Markdown as you type it, in any text box: the text
engine that lays out the letters runs CommonMark's inline rules, hides the
markup and styles the text. The characters stay exactly as typed (copy them
and you get Markdown back); with the font's `calt` feature off you see them
all. `markdown/demo.html` is a page with the font in a text box.

- *Emphasis* and **strong emphasis** by CommonMark's full rules: left- and
  right-flanking runs judged with Unicode whitespace and punctuation, so in
  any script; `_` inside words; the rule of three; nesting.
- `Code spans` with a background, for any number of backticks.
- [Inline links](https://commonmark.org) and images, shown as styled text
  (blue and underlined, or purple for an image's description), their
  destinations and titles hidden. Links can't contain links; images can.
- Autolinks, raw HTML (dimmed), entity and numeric character references
  (drawn as their characters), backslash escapes.

Bold and italic come from JetBrains Mono's own bold and italic; code, link,
image and HTML styles are color glyphs (COLR) with light and dark palettes.

## Results

Each character's glyph (hidden, or drawn in some style) is compared with
what CommonMark makes of that character, as computed by `cm_inline.py`, a
port of the inline parser of commonmark.js 0.31.2, the reference
implementation. HarfBuzz (Chrome, Firefox) and Core Text (Safari) give
identical results.

| Lines | Within the font's bounds | Rendered as CommonMark |
|---|---|---|
| CommonMark's 290 one-line spec examples | 283 | 283 |
| 20,000 random lines of Markdown syntax | 19,901 | 19,901 |
| 10,725 lines of 65 Markdown documents (npm's documentation, Python package READMEs) | 10,725 | 10,725 |

Of the 106 lines past a bound (7 spec examples and 99 random lines), 67 still
come out right. The model itself matches all 303 spec examples that are
inline paragraphs (the other three need link reference definitions) and
commonmark.js on 220,000 random lines (`crosscheck.py`), apart from one
place where commonmark.js departs from the spec (it counts a no-break space
as whitespace inside HTML tags).

The font has 46,648 glyphs and is 490 KB as WOFF2. Shaping a line (52
characters on average, in the documents above) takes 0.11 ms in HarfBuzz and
0.27 ms in Core Text, against 0.03 and 0.14 ms for plain JetBrains Mono.

## How many alternating passes does CommonMark need?

**One change of direction**: right to left first, then left to right. That
is also the least there can be. Whether a run of backticks opens a code span
depends on what comes after it (a closing run of the same length) and on
what comes before it (whether it lies inside an earlier code span): in
`` `a``b` ``…, the second run is code if the first opened a span. A
left-to-right pass can't know the first, a right-to-left pass the second.

A font's passes are OpenType lookups, each a deterministic transducer: it
reads the glyphs in one direction and replaces each with a variant that
records its state, for the next glyph's rule to read. What makes one change
of direction enough is that a lookup can skip glyphs. With a GDEF mark
filtering set a lookup sees only some glyphs: the passes that match emphasis
see only `*` and `_`. In that sequence an opener and its closer are next to
each other, however much text lies between them, so a left-to-right rule can
match them by reading one glyph ahead. Nesting is handled in rounds: each
round is a lookup that pairs every opener with the closer right after it
(CommonMark's own choice of pairs, even with mixed `*` and `_`, partial runs
and the rule of three: the rounds agreed with CommonMark's stack algorithm
on 220,000 random lines), and matched pairs drop out of the sequence the
next round sees. Brackets are matched the same way. So "a marker is styled
only if a closing marker exists later" needs no right-to-left pass at all:
it becomes "the next glyph of the sequence is a closer". What does need one
is a regular language over a stretch of unbounded length: whether `(...)`
after a `]` is a valid link destination, whether a `<` starts valid raw HTML
or an autolink. The font also finds code spans' closing runs right to left,
because that is simpler there.

In theory two passes always suffice. Bound the nesting and CommonMark's
inline rules become a regular function, and every regular function is a
right-to-left pass followed by a left-to-right one (Elgot and Mezei's
theorem on bimachines). But a pass's states live in glyph variants and a
font has at most 65,535 glyphs, so the font spends passes to save states:

| Done as one pass | States | As the font does it |
|---|---|---|
| Emphasis with a stack of 3 openers of 24 kinds | 24³ ≈ 14,000 | 6 rounds over the runs' first characters |
| Link destinations | 364 | 8 passes, one per form of destination and title: 6 to 35 states each |
| Raw HTML and autolinks | 14,737 | 8 passes, one per kind: 2 to 52 states each |

Passes in one direction compose without changing direction, so the font
runs 103 lookups: 38 right to left, then 23 left to right, with 42 plain
substitutions among them that tidy up between passes.

And no number of passes is exact on everything: matching `*a *b *c d* e* f*`
means counting, which no composition of finite-state passes can do. So the
font has bounds, each a constant in `mdfont.py`:

| Bound | | Lines past it |
|---|---|---|
| Delimiter runs (`***`) | up to 6 characters | spec example 417 |
| Emphasis nesting | 6 rounds (3 in link text), looking past 3 openers | none above |
| Open brackets at once | 3 | random lines only |
| Backtick runs | up to 8 | none above |
| Parentheses in a link destination | 3 deep (CommonMark asks for at least 3) | none above |

Two rarer cases are simplified rather than bounded. A `](...)` after link
text that contains a link (which CommonMark disallows) is assumed to be a
link destination while scanning, so Markdown inside it isn't recognized
(spec examples 518 to 520 still come out right). And references are drawn
only if they stand for one character the font has, without leading zeros
(`&#0065;`).

## How the font does it

`mdfont.py` builds the passes from Python state machines (`passes.py`
compiles them to lookups, `tails.py` and `htmlauto.py` hold the automata):

1. **Right to left.** Escapes, and runs of backticks, `*` and `_` (from small
   windows); for each length of backtick run, whether a closing run follows;
   for each `]`, whether a link destination of each form follows; for each
   `<`, which kind of autolink or raw HTML starts there.
2. **Left to right.** A scan through code spans, raw HTML, autolinks and link
   destinations, which also counts open brackets. Rounds of bracket matching
   (links, images, and no links in links), then of emphasis matching, at each
   level of link and image text. Then each run's characters learn their roles,
   one pass works out the style after each marker, entity references become
   ligatures, and the paint gives every glyph its final glyph: a styled one,
   or an invisible one for markup.

Only characters that can matter take part: an ASCII character joins the HTML
passes only if a `>` follows it, a space joins the link passes only if a `)`
follows it. Most text goes through untouched, which keeps shaping fast.

## Limits

- Only inline syntax, and one line at a time: no headings, lists, block
  quotes or code blocks, no reference links (their definitions are elsewhere
  in the document), nothing that spans lines.
- Browsers cut a line into pieces before the font sees it, and the font
  can't see across them. Safari reshapes each visual line, so a construct
  broken by a soft wrap isn't recognized (the demo's box doesn't wrap).
  Chrome shapes each script separately, so `*мир*` right after Latin text, or
  a Latin URL after Cyrillic link text, stays as typed there; Safari renders
  both. A line in one script renders in both.
- In Safari a space inside a hidden link destination (before a title) still
  takes a space's width: WebKit gives every space character the font's space
  width.
- Characters the font doesn't have come from another font, which also cuts
  the line.

## Reproducing

```sh
python markdown/mdfont.py --base fonts/JetBrainsMono-Regular.ttf --bold fonts/JetBrainsMono-Bold.ttf \
    --italic fonts/JetBrainsMono-Italic.ttf --bold-italic fonts/JetBrainsMono-BoldItalic.ttf --out build
python markdown/verify.py build/Fontlex-Markdown.ttf --shaper harfbuzz --shaper coretext --n 20000 \
    --corpus README.md
python markdown/build_page.py --font build/Fontlex-Markdown.ttf --out markdown/demo.html
python markdown/check_webkit.py markdown/demo.html        # macOS
npm install --prefix /tmp/cm commonmark@0.31.2               # to check the model itself
python markdown/crosscheck.py /tmp/cm/node_modules/commonmark --n 100000
```

The build takes about 20 seconds; `./check.sh` runs all of it.

## Licenses

`spec-0.31.2.json` holds the examples of the CommonMark Spec 0.31.2 by John
MacFarlane, under CC BY-SA 4.0 (see `SPEC-LICENSE.txt`). The base fonts,
JetBrains Mono in four styles, are under the SIL Open Font License.
