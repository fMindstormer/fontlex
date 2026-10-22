# Fontlex Markdown: GitHub Flavored Markdown rendered by a font

A font that renders Markdown as you type it, in any text box: the text
engine that lays out the letters runs GitHub Flavored Markdown's rules, a
line at a time, hides the markup and styles the text. The characters stay
exactly as typed (copy them and you get Markdown back); with the font's
`calt` feature off you see them all. `markdown/demo.html` is a page with the
font in a text box.

- *Emphasis* and **strong emphasis** by CommonMark's full rules: left- and
  right-flanking runs judged with Unicode whitespace and punctuation, so in
  any script; `_` inside words; the rule of three; nesting.
- `Code spans` with a background, for any number of backticks.
- [Inline links](https://commonmark.org) and images, shown as styled text
  (blue and underlined, or purple for an image's description), their
  destinations and titles hidden. Links can't contain links; images can.
- Autolinks, raw HTML (dimmed), entity and numeric character references
  (drawn as their characters), backslash escapes.
- GitHub's extensions: ~~strikethrough~~ (a line drawn through the text,
  spaces included), bare URLs such as www.commonmark.org or
  https://github.com, with the trailing punctuation GitHub leaves out of
  them, and bare email addresses.
- Each line's block markup, read as GitHub reads a one-line document:
  headings (bold, their `#`s dimmed), block quotes (a bar), list items (a
  bullet; numbers stay), task boxes (drawn checked or not), thematic breaks
  (a rule), and lines that are indented code, code fences, HTML blocks or
  link reference definitions, which inline syntax leaves alone.

Bold and italic come from JetBrains Mono's own bold and italic; code, link,
image and HTML styles, bullets, bars, boxes and rules are color glyphs
(COLR) with light and dark palettes. A proportional edition, Fontlex
Markdown Sans, sets the text in Noto Sans and code in JetBrains Mono, so a
text box looks like the rendered page; the demo's menu switches between
them.

## Results

Each character's glyph (hidden, or drawn in some style) is compared with
what GitHub makes of that character when the line is a document on its own,
as computed by ports of the reference implementations: `cm_inline.py` and
`cm_block.py` follow commonmark.js 0.31.2 (its inline parser, and its block
parser for one line), and `gfm.py` the extensions of cmark-gfm
0.29.0.gfm.13, the parser github.com uses, byte for byte. HarfBuzz (Chrome,
Firefox) and Core Text (Safari) give identical results.

| Lines | Within the font's bounds | Rendered as GitHub does |
|---|---|---|
| CommonMark's 514 spec examples that are one line, or one-line blocks apart | 447 | 447 |
| The GFM spec's 24 extension examples of that kind | 23 | 23 |
| 20,000 random lines of Markdown syntax | 19,526 | 19,526 |
| 5,000 random lines behind random block markup | 4,902 | 4,902 |
| 10,725 lines of 65 Markdown documents (npm's documentation, Python package READMEs) | 10,723 | 10,723 |

Of the 642 lines past a bound (the spec's are mostly link reference
definitions), 445 still come out right. The model itself matches all 290
one-line CommonMark spec examples as documents and the GFM spec's
extension examples, and the reference implementations on random lines
(`crosscheck.py`): commonmark.js on 220,000 inline lines and 50,000 block
lines, cmark-gfm on 50,000 lines with its extensions, apart from places
where the two disagree with each other or with the spec (cmark-gfm's core
follows an older CommonMark; commonmark.js counts a no-break space as
whitespace inside HTML tags).

Both editions give exactly these results. The font has 63,367 glyphs (of
OpenType's 65,535) and is 722 KB as WOFF2; the proportional edition has
54,841 and is 743 KB.

## The proportional edition

Every character the text can hold is copied for each style (bold, italic,
code, link, ...) and for each state of the passes that read it, about 37
times, so the base font's size decides whether the font fits in 65,535
glyphs. `sans_base.py` makes the base from Google Fonts' variable Noto Sans:
the four styles, subset to the 761 characters Noto Sans and JetBrains Mono
share (Latin, Greek, Cyrillic and common punctuation; JetBrains Mono's box
drawing and APL symbols are left out, and come from another font). Code is
drawn with JetBrains Mono's outlines in its four styles at 90% (GitHub sets
code at 85% of the text size), without the text's kerning. Noto Sans's own
kerning and mark positioning carry over to every styled glyph. Bullets,
boxes, bars and rules are a figure wide.

Three things only showed up with the second base font:

- **HarfBuzz 12.3.1 to 14.6.0 never matches a glyph with id 32,512 to 32,767
  in a context lookup of format 2** (harfbuzz/harfbuzz#6418, fixed by
  #6419 in HarfBuzz 15.0.0). Its
  per-subtable coverage cache
  (`hb_cache_t<14, 1, 8>`) stores 7 bits per byte and starts each byte as
  0xFF, but checks for an empty slot only when the stored bits fill the
  byte; and it stores only ids below 16,384. So an id whose bits above the
  lowest 8 are 127 reads an empty slot as a hit, saying "not covered". The
  mono edition had no such glyph by chance; the proportional one had six,
  one of them the `>` that ends raw HTML. `fontbuild.py` now inserts empty
  glyphs before the first such glyph, moving it and every later glyph past
  the window (244 glyphs here).
- Noto Sans gives Devanagari different GPOS features from other scripts, and
  then Core Text shapes each script as its own run, which restarts the
  passes at every change between Latin, Greek and Cyrillic. The scripts'
  features are unified, as `fontlex.py --unify-scripts` does.
- A task box is drawn on the character inside its brackets, usually a
  space, and WebKit gives a space character a space's width whatever the
  font says. So the box takes a space's width and reaches back over the
  hidden `[` before it, which takes the rest of the box's width.

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

Passes in one direction compose without changing direction, so CommonMark's
inline rules take 103 lookups: 38 right to left, then 23 left to right, with
42 plain substitutions among them that tidy up between passes.

GitHub's extensions cost more changes of direction, though none is needed in
principle; they buy glyphs. The whole font runs 151 lookups (60 right to
left, 31 left to right, 60 plain substitutions) with seven changes of
direction:

| Direction | Lookups | What for |
|---|---|---|
| Right to left | 55 | the inline passes above, and the block markup's own right-to-left checks |
| Left to right | 1 | each line's block prefix: where its inline content starts |
| Right to left | 3 | where bare URLs can start (which needs the prefix: `www.` counts after a bullet) |
| Left to right | 1 | a mark before each such start |
| Right to left | 1 | each URL's trailing punctuation |
| Left to right | 23 | URLs' ends (counting parentheses), the scan, links, emphasis |
| Right to left | 1 | email addresses, whose local part must be followed by `@` and a domain |
| Left to right | 5 | the style, references, the paint, strikethrough |

Moving the URL and email passes into the first right-to-left block would
save the changes of direction, but there each pass's states multiply the
variants of every glyph the later passes read, and the font is 2,168 glyphs
short of OpenType's limit as it is.

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
| A bare URL's `(` against its `)` | 3 out of balance | random lines only |

Two rarer cases are simplified rather than bounded. A `](...)` after link
text that contains a link (which CommonMark disallows) is assumed to be a
link destination while scanning, so Markdown inside it isn't recognized
(spec examples 518 to 520 still come out right). And references are drawn
only if they stand for one character the font has, without leading zeros
(`&#0065;`).

GitHub's extensions add bounds of their own, `bounds.py` names them all: a
bare URL inside another one's word (`http://a.b/www.c.d`), two `@` in one
email-like word, an escape or reference next to an email address, a
reference ending a URL's word, a `*` or `_` right after four or more `~`,
`mailto:` and `xmpp:` addresses, and combining marks in a URL's or email's
domain (HarfBuzz composes them with the letter before). Link reference
definitions are recognized and left as typed, but the links that use them
aren't drawn: their definitions are elsewhere in the document.

## How the font does it

`mdfont.py` builds the passes from Python state machines (`passes.py`
compiles them to lookups, `tails.py` and `htmlauto.py` hold the automata):

1. **Right to left.** Escapes, and runs of backticks, `*` and `_` (from small
   windows); for each length of backtick run, whether a closing run follows;
   for each `]`, whether a link destination of each form follows; for each
   `<`, which kind of autolink or raw HTML starts there. And the block
   markup: whether a line is a heading, a rule, a fence or a reference
   definition depends on how it ends (`--- a` is no rule).
2. **Left to right, once.** The block prefix (`blocks.py` has the automaton:
   quote markers, list markers, task boxes, indentation), which gives each
   line the point where its inline content starts, or none.
3. **Bare URLs**, in three short alternations. Right to left, which `www.`
   and `http://` can start a URL (its domain must be valid up to the next
   `/`, `?` or `#`); a mark goes before each. Right to left again, the zone
   of trailing punctuation at each URL's end. Left to right, each URL's end:
   a space or `<`, or the start of its trailing zone unless a `)` there is
   still matched by a `(` (counted from the URL's start).
4. **Left to right.** A scan through code spans, raw HTML, autolinks, link
   destinations and the bare URLs, which also counts open brackets (inside
   brackets nothing is a bare URL). Rounds of bracket matching (links,
   images, and no links in links), then of emphasis matching, at each level
   of link and image text.
5. **Right to left, once more**, for email addresses, then **left to right**:
   each run's characters learn their roles, one pass works out the style
   after each marker (strikethrough included), entity references become
   ligatures, the paint gives every glyph its final glyph (a styled one, or
   an invisible one for markup), and struck text gets its line.

Markers that one pass inserts for the next (a URL's start, an email's ends)
are empty glyphs that later passes see only through filtering sets; at a
space, which WebKit always widens to a space, the end is carried by the
space glyph itself instead.

Only characters that can matter take part: an ASCII character joins the HTML
passes only if a `>` follows it, a space joins the link passes only if a `)`
follows it. Most text goes through untouched, which keeps shaping fast.

## Limits

- One line at a time: each line is read as GitHub reads it alone. Nothing
  spans lines: a fence's code, a paragraph continued from the line before, a
  setext heading's underline (`---` under text draws a rule), reference
  links (their definitions are elsewhere in the document).
- Tabs inside strikethrough aren't struck.
- Browsers cut a line into pieces before the font sees it, and the font
  can't see across them. Safari reshapes each visual line, so a construct
  broken by a soft wrap isn't recognized (the demo's box doesn't wrap).
  Chrome shapes each script separately, so `*мир*` right after Latin text, or
  a Latin URL after Cyrillic link text, stays as typed there; Safari renders
  both. Chrome also cuts at every tab, so a construct with a tab inside stays
  as typed there; in Safari it renders, though the tab's gap gets no code
  background or underline. A line in one script, without tabs, renders in
  both.
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
python markdown/sans_base.py NOTO_DIR --out fonts      # Google Fonts' ofl/notosans: already in fonts/
python markdown/mdfont.py --base fonts/NotoSans-Regular.ttf --bold fonts/NotoSans-Bold.ttf \
    --italic fonts/NotoSans-Italic.ttf --bold-italic fonts/NotoSans-BoldItalic.ttf \
    --mono fonts/JetBrainsMono-{Regular,Bold,Italic,BoldItalic}.ttf --family "Fontlex Markdown Sans" --out build
python markdown/build_page.py --font build/Fontlex-Markdown.ttf --sans build/Fontlex-MarkdownSans.ttf \
    --out markdown/demo.html
python markdown/check_webkit.py markdown/demo.html        # macOS
npm install --prefix /tmp/cm commonmark@0.31.2               # to check the model itself
python markdown/crosscheck.py /tmp/cm/node_modules/commonmark --n 100000
```

```sh
pip install cmarkgfm==2025.10.22                           # cmark-gfm 0.29.0.gfm.13
python markdown/crosscheck.py /tmp/cm/node_modules/commonmark --mode block --n 50000
python markdown/crosscheck.py /tmp/cm/node_modules/commonmark --mode gfm --n 50000
```

Each build takes about a minute; `./check.sh markdown` builds and verifies
both editions and makes the demo page.

## Licenses

`spec-0.31.2.json` holds the examples of the CommonMark Spec 0.31.2 by John
MacFarlane, and `gfm-spec-0.29-extensions.json` those of the GitHub Flavored
Markdown Spec's extensions, both under CC BY-SA 4.0 (see `SPEC-LICENSE.txt`).
The base fonts are under the SIL Open Font License: JetBrains Mono in four
styles (`fonts/OFL.txt`), and Noto Sans, instanced and subset in four styles
(`fonts/OFL-NotoSans.txt`).
