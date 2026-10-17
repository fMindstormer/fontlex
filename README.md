# Fontlex

Compile a lexer spec into a syntax-highlighting font. The font runs the lexer
inside the text shaper, so highlighting works in any app that renders OpenType
color fonts: a plain `<textarea>`, an `<input>`, a doc, a design tool. No
editor plugin, no JavaScript.

## Quick start

```sh
pip install fonttools brotli pyyaml uharfbuzz
python fontlex.py specs/python.yaml --base fonts/JetBrainsMono-Regular.ttf --out build
python test_fontlex.py specs/python.yaml build/Fontlex-Python.ttf --n 20000
python demo/build_demo.py specs/python.yaml --base fonts/JetBrainsMono-Regular.ttf --out demo/fontlex-demo.html
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

`build/*.fea` is the generated feature file, if you want to read the rules.

## Testing

`test_fontlex.py` shapes hand-written and random strings with HarfBuzz and
compares each output glyph's state against `Model.lex`, a direct simulation of
the spec. It currently passes 20/20 hand cases and 20,000/20,000 random cases.
The page has also been rendered in headless Chromium.

## Known limits

- State lives within one shaping run. Browsers start new runs at line breaks,
  script changes and font fallback, so multi-line constructs and some
  mixed-script strings reset.
- Colors are decided left to right with one glyph of lookahead for words.
  Constructs that need more lookahead (`f"` prefixes, `"""` as a unit) need
  more passes.
- The base font's ligatures are removed.
- Not yet checked in Safari (Core Text).

## Research questions this opens

- Which languages can a font recognize with k chained-contextual lookups of
  bounded context? (Relates to locally testable languages and sliding-window
  automata.) How many lookup passes does a given lexer need?
- Minimizing glyph count and rule count for a given DFA, for example by merging
  states that are indistinguishable for both color and future transitions.

## License

The base font is JetBrains Mono, under the SIL Open Font License 1.1
(`fonts/OFL.txt`). Fonts built from it are under the same license.
