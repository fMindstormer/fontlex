# Fontlex

Compile a lexer spec into a syntax-highlighting font. The font runs the lexer
inside the text shaper, so highlighting works in any app that renders OpenType
color fonts: a plain `<textarea>`, an `<input>`, a doc, a design tool. No
editor plugin, no JavaScript.

## Quick start

```sh
pip install fonttools brotli pyyaml uharfbuzz
python fontlex.py specs/python.yaml --base fonts/JetBrainsMono-Regular.ttf --out build
python test_fontlex.py specs/python.yaml build/Fontlex-Python.ttf --base fonts/JetBrainsMono-Regular.ttf --n 20000
python demo/build_demo.py specs/python.yaml --base fonts/JetBrainsMono-Regular.ttf --out demo/fontlex-demo.html
```

On macOS, also test with Core Text, the shaper behind Safari and native apps:

```sh
pip install pyobjc-framework-CoreText
python test_fontlex.py specs/python.yaml build/Fontlex-Python.ttf --base fonts/JetBrainsMono-Regular.ttf \
    --shaper harfbuzz --shaper coretext
```

Then use the font in CSS:

```css
@font-face { font-family: "Fontlex Python"; src: url(Fontlex-Python.woff2) format("woff2"); }
textarea { font-family: "Fontlex Python", monospace; font-palette: light; }
```

## The spec

`specs/python.yaml` is a commented example. A spec has:

- `classes`: named character classes (`"a-zA-Z_"`). Every other character in
  the base font falls into the implicit class `other`.
- `states`: a DFA. Each state has an optional `token`, an `on` map from class to
  next state, and either `default` (target for unlisted classes) or `like`
  (behave as another state for unlisted classes).
- `words`: word lists recolored when a whole run of glyphs in `words.state`
  spells one of them.
- `themes`: token colors. Each theme becomes a CPAL palette; themes named
  `light` and `dark` are tagged so CSS `font-palette: light|dark` picks them.

## How it compiles

1. **Variant glyphs.** For each (state, character) pair the DFA can produce, add
   `<glyph>.lx_<state>`, a composite of the original outline. The start state
   uses the original glyphs.
2. **Lexer lookup.** One chaining contextual GSUB lookup. HarfBuzz and other
   shapers let a rule's backtrack context see glyphs already replaced earlier in
   the same pass, so the previous glyph's variant carries the DFA state. Each
   table cell becomes `sub @S_<state> @C_<class>' lookup TO_<next>;`. Cells
   that agree with the start state's row are dropped, since the final
   no-context rules produce the same result.
3. **Word lookup.** Recolors maximal identifier runs that spell a listed word.
   Longest words first; one glyph of lookahead rejects longer identifiers.
4. **Color.** COLR v0 paints each colored variant with the original outline in
   a palette color.
5. **Positioning.** The base font's GPOS and GDEF are kept, and every variant
   is added wherever its original glyph appears, so kerning and mark anchors
   still apply to lexed glyphs.

`build/*.fea` is the generated feature file, if you want to read the rules.

## Testing

`test_fontlex.py` shapes hand-written and random strings and compares each
output glyph's state against `Model.lex`, a direct simulation of the spec.
With `--base`, it also checks that every glyph is positioned exactly as the
base font positions the same glyph, over the same strings plus random strings
full of combining marks. `--shaper` picks HarfBuzz (Chrome, Firefox, Android)
or Core Text (Safari, native Mac apps); repeat it to run both.

With JetBrains Mono, both shapers pass 22/22 hand cases, 20,000/20,000 random
cases and 40,000/40,000 positioning cases. Core Text improvises positions for
marks the base font has no anchor for, and does so only for unsubstituted
glyphs, so the Core Text check skips those marks and reports how many.

With HarfBuzz, everything also passes with Arial, Times New Roman Italic,
STIX Two, SF Pro and Trattatello as base fonts. With Core Text, STIX Two,
SF Pro and Trattatello pass; Arial and Times fail on mixed-script text (see
below). The demo page highlights correctly in Safari 27 on macOS 27, checked
by eye, and was rendered in headless Chromium before the positioning fix.

## Known limits

- State lives within one shaping run. Browsers start new runs at line breaks,
  script changes and font fallback, so multi-line constructs and some
  mixed-script strings reset.
- Colors are decided left to right with one glyph of lookahead for words.
  Constructs that need more lookahead (`f"` prefixes, `"""` as a unit) need
  more passes.
- The base font's substitution tables (GSUB, AAT `morx`) are removed, which
  takes its ligatures, `ccmp`, `locl` and stylistic sets with them.
- Contextual GPOS lookups in format 1 are only partly aliased; the compiler
  lists them under `layout_notes`. The legacy `kern` table is not aliased, so
  a shaper that uses it instead of GPOS loses kerning on lexed glyphs.
- A font holds at most 65,535 glyphs, and each state costs one variant per
  glyph that can enter it. Large base fonts or many-state specs don't fit.
- With some base fonts, including Arial and Times, Core Text splits text into
  separate shaping runs at script changes (Latin, Greek, Cyrillic). The lexer
  resets at each split, so in Safari `# жук x` stops being a comment at `x`.
  The font's per-script GSUB/GPOS entries trigger it, but the exact rule isn't
  known. JetBrains Mono, STIX Two, SF Pro and Trattatello don't trigger it.
- In Core Text, a mark the base font has no anchor for is drawn unpositioned
  when it or its base glyph has been lexed, where the base font alone would
  get Core Text's improvised position. HarfBuzz never improvises when GPOS is
  present, so there both fonts draw it unpositioned.

## Research questions this opens

- Which languages can a font recognize with k chained-contextual lookups of
  bounded context? (Relates to locally testable languages and sliding-window
  automata.) How many lookup passes does a given lexer need?
- Minimizing glyph count and rule count for a given DFA, for example by merging
  states that are indistinguishable for both color and future transitions.

## License

The base font is JetBrains Mono, under the SIL Open Font License 1.1
(`fonts/OFL.txt`). Fonts built from it are under the same license.
