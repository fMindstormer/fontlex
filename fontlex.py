#!/usr/bin/env python3
"""Fontlex: compile a lexer spec into a syntax-highlighting font.

The font does the lexing itself, inside the text shaper, so highlighting works
in any app that renders OpenType color fonts: a plain <textarea>, a code block
in a doc, a design tool. No editor support or JavaScript required.

How the compilation works
-------------------------
A lexer spec is a deterministic finite automaton (DFA) over character classes,
where each state has a token type, plus optional word lists.

1. Glyph variants. For every (state, character) pair the DFA can produce, the
   compiler adds a variant glyph `<base>.lx_<state>`: a composite that reuses
   the base outline, so the font stays small. The start state uses the base
   glyphs themselves.

2. The lexer lookup (one GSUB chaining-contextual lookup). The shaper walks the
   text left to right, and the backtrack context of each rule sees glyphs that
   were already substituted earlier in the same pass. So the previous glyph's
   variant *is* the DFA state, and one rule per (state, class) pair
       sub @STATE_s @CLASS_k' lookup TO_<delta(s,k)>;
   runs the automaton. Rules whose result equals the start-state transition
   are dropped, because the final no-context rules already produce it.

3. The word lookup. A second contextual lookup recolors maximal runs of glyphs
   in the word state (identifiers) that spell a listed word, using one glyph
   of lookahead to rule out longer identifiers.

4. Color. Each colored variant gets a COLR v0 record that paints the base
   outline with a CPAL palette entry, one palette per theme.

Usage:
    python fontlex.py specs/python.yaml --base Font.ttf --out build/
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from fontTools.colorLib.builder import buildCOLR, buildCPAL
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import Glyph, GlyphComponent

OTHER = "other"
SUFFIX = ".lx_"
WORD_SUFFIX = ".lxw_"


# --------------------------------------------------------------------------
# Spec
# --------------------------------------------------------------------------

class SpecError(Exception):
    pass


def _expand_class(pattern: str) -> list[str]:
    """Expand 'a-zA-Z_' style patterns into a list of characters."""
    chars: list[str] = []
    i = 0
    while i < len(pattern):
        if i + 2 < len(pattern) and pattern[i + 1] == "-":
            lo, hi = ord(pattern[i]), ord(pattern[i + 2])
            if lo > hi:
                raise SpecError(f"bad range {pattern[i:i + 3]!r}")
            chars.extend(chr(c) for c in range(lo, hi + 1))
            i += 3
        else:
            chars.append(pattern[i])
            i += 1
    return chars


@dataclass
class Spec:
    name: str
    classes: list[tuple[str, list[str]]]       # ordered; `other` is implicit
    start: str
    states: dict[str, dict]
    word_state: str | None = None
    word_sets: list[tuple[str, list[str]]] = field(default_factory=list)
    themes: list[tuple[str, dict[str, str]]] = field(default_factory=list)

    # -- derived ---------------------------------------------------------
    @property
    def class_names(self) -> list[str]:
        return [n for n, _ in self.classes] + [OTHER]

    def token(self, state: str) -> str | None:
        return self.states[state].get("token")

    def delta(self, state: str, cls: str, _seen=None) -> str:
        """Transition function, resolving `on`, `default` and `like`."""
        st = self.states[state]
        on = st.get("on") or {}
        if cls in on:
            return on[cls]
        if "default" in st:
            return st["default"]
        if "like" in st:
            seen = _seen or set()
            if state in seen:
                raise SpecError(f"`like` cycle through state {state!r}")
            return self.delta(st["like"], cls, seen | {state})
        raise SpecError(f"state {state!r} has no transition for class {cls!r}")

    def table(self) -> dict[str, dict[str, str]]:
        return {s: {k: self.delta(s, k) for k in self.class_names} for s in self.states}


def load_spec(path: str | Path) -> Spec:
    raw = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, dict):
        raise SpecError("spec must be a mapping")

    classes = []
    for name, pattern in (raw.get("classes") or {}).items():
        if name == OTHER:
            raise SpecError("`other` is implicit; don't define it")
        classes.append((str(name), _expand_class(str(pattern))))

    states = raw.get("states") or {}
    if not states:
        raise SpecError("spec has no states")
    # YAML 1.1 reads a bare `on:` key as boolean True.
    states = {str(k): {("on" if kk is True else str(kk)): vv for kk, vv in (v or {}).items()}
              for k, v in states.items()}
    start = str(raw.get("start") or next(iter(states)))

    words = raw.get("words") or {}
    word_sets = [(str(k), [str(w) for w in v]) for k, v in (words.get("sets") or {}).items()]

    themes = [(str(k), {str(t): str(c) for t, c in (v or {}).items()})
              for k, v in (raw.get("themes") or {}).items()]

    spec = Spec(
        name=str(raw.get("name") or "Fontlex"),
        classes=classes,
        start=start,
        states=states,
        word_state=words.get("state"),
        word_sets=word_sets,
        themes=themes,
    )
    _validate(spec)
    return spec


def _validate(spec: Spec) -> None:
    names = set(spec.class_names)
    if spec.start not in spec.states:
        raise SpecError(f"start state {spec.start!r} is not defined")
    for s, st in spec.states.items():
        for key in st:
            if key not in {"on", "default", "like", "token"}:
                raise SpecError(f"state {s!r}: unknown key {key!r}")
        for k, t in (st.get("on") or {}).items():
            if k not in names:
                raise SpecError(f"state {s!r}: unknown class {k!r}")
            if t not in spec.states:
                raise SpecError(f"state {s!r}: unknown target {t!r}")
        for key in ("default", "like"):
            if key in st and st[key] not in spec.states:
                raise SpecError(f"state {s!r}: {key} {st[key]!r} is not a state")
    spec.table()  # raises on missing transitions or like-cycles
    if spec.word_sets:
        if spec.word_state not in spec.states:
            raise SpecError("words.state must name a state")
        if spec.word_state == spec.start:
            raise SpecError("words.state can't be the start state")
    for s in spec.states:
        if not re.fullmatch(r"[A-Za-z0-9_]+", s):
            raise SpecError(f"state name {s!r} must be [A-Za-z0-9_]+")


# --------------------------------------------------------------------------
# Reference lexer (what the font is supposed to compute)
# --------------------------------------------------------------------------

class Model:
    """The spec bound to a concrete font's cmap, at glyph level."""

    def __init__(self, spec: Spec, cmap: dict[int, str]):
        self.spec = spec
        self.cmap = cmap
        self.glyph_class: dict[str, str] = {}
        for cname, chars in spec.classes:
            for ch in chars:
                g = cmap.get(ord(ch))
                if g and g not in self.glyph_class:
                    self.glyph_class[g] = cname
        for cp in sorted(cmap):
            g = cmap[cp]
            if g != ".notdef" and g not in self.glyph_class:
                self.glyph_class[g] = OTHER
        self.delta = spec.table()

    def lex(self, text: str) -> list[tuple[str | None, str | None]]:
        """Per character: (DFA state or None for unknown chars, word set)."""
        states: list[str | None] = []
        prev: str | None = None
        for ch in text:
            g = self.cmap.get(ord(ch))
            if g is None or g not in self.glyph_class:
                states.append(None)
                prev = None
                continue
            cur = self.delta[prev if prev is not None else self.spec.start][self.glyph_class[g]]
            states.append(cur)
            prev = cur
        sets: list[str | None] = [None] * len(text)
        ws = self.spec.word_state
        lookup = {}
        for sname, words in self.spec.word_sets:
            for w in words:
                lookup.setdefault(w, sname)
        i = 0
        while i < len(text):
            if states[i] == ws:
                j = i
                while j < len(text) and states[j] == ws:
                    j += 1
                sname = lookup.get(text[i:j])
                if sname is not None:
                    for t in range(i, j):
                        sets[t] = sname
                i = j
            else:
                i += 1
        return list(zip(states, sets))


# --------------------------------------------------------------------------
# Compiler
# --------------------------------------------------------------------------

def _hex_to_rgba(h: str) -> tuple[float, float, float, float]:
    h = h.lstrip("#")
    if len(h) not in (6, 8):
        raise SpecError(f"bad color {h!r}")
    vals = [int(h[i:i + 2], 16) / 255 for i in range(0, len(h), 2)]
    return tuple(vals + [1.0] * (4 - len(vals)))  # type: ignore[return-value]


def _fea_glyphs(names) -> str:
    return " ".join("\\" + n for n in names)


@dataclass
class Result:
    font: TTFont
    fea: str
    glyphmap: dict[str, dict]
    stats: dict


def compile_font(spec: Spec, base_path: str | Path) -> Result:
    font = TTFont(str(base_path))
    if "glyf" not in font:
        raise SpecError("base font must be a TrueType (glyf) font")
    cmap = font.getBestCmap()
    model = Model(spec, cmap)
    delta = model.delta
    order = font.getGlyphOrder()
    base_glyphs = [g for g in order if g in model.glyph_class]
    by_class: dict[str, list[str]] = {k: [] for k in spec.class_names}
    for g in base_glyphs:
        by_class[model.glyph_class[g]].append(g)

    # Which (state, class) pairs can occur: state t is entered by class k.
    entering: dict[str, set[str]] = {s: set() for s in spec.states}
    for s in spec.states:
        for k in spec.class_names:
            entering[delta[s][k]].add(k)

    # 1. Variant glyphs, grouped by state so each state's glyph set is one
    #    contiguous run of glyph IDs (keeps coverage tables tiny).
    variant: dict[tuple[str, str], str] = {}     # (state, base) -> name
    glyphmap: dict[str, dict] = {}
    new_glyphs: list[tuple[str, str]] = []       # (name, base)
    for s in spec.states:
        if s == spec.start:
            continue
        for g in base_glyphs:
            if model.glyph_class[g] in entering[s]:
                name = f"{g}{SUFFIX}{s}"
                variant[(s, g)] = name
                new_glyphs.append((name, g))
                glyphmap[name] = {"base": g, "state": s, "set": None}

    word_variant: dict[tuple[str, str], str] = {}   # (set, base) -> name
    word_glyph_sets: dict[str, list[tuple[str, str]]] = {}
    skipped_words: list[str] = []
    usable_words: list[tuple[str, str, list[str]]] = []   # (word, set, bases)
    seen_words: set[str] = set()
    for sname, words in spec.word_sets:
        pairs = []
        for w in words:
            if w in seen_words:
                continue
            bases = [cmap.get(ord(c)) for c in w]
            if not w or any(b is None or (spec.word_state, b) not in variant for b in bases):
                skipped_words.append(w)
                continue
            # The run must actually be reachable in the word state.
            if [st for st, _ in model.lex(w)] != [spec.word_state] * len(w):
                skipped_words.append(w)
                continue
            seen_words.add(w)
            usable_words.append((w, sname, bases))  # type: ignore[arg-type]
            for b in bases:
                if (sname, b) not in word_variant:
                    name = f"{b}{WORD_SUFFIX}{sname}"
                    word_variant[(sname, b)] = name
                    pairs.append((variant[(spec.word_state, b)], name))
                    new_glyphs.append((name, b))
                    glyphmap[name] = {"base": b, "state": spec.word_state, "set": sname}
        word_glyph_sets[sname] = pairs

    _add_glyphs(font, new_glyphs)

    # 2. Features.
    old_scripts = set()
    for tag in ("GSUB", "GPOS"):
        if tag in font:
            sl = font[tag].table.ScriptList
            if sl:
                old_scripts |= {r.ScriptTag for r in sl.ScriptRecord}
    if "GSUB" in font:
        del font["GSUB"]   # drop the base font's ligatures; they'd break the lexer
    scripts = ["DFLT"] + sorted(old_scripts - {"DFLT"} | {"latn"})

    fea: list[str] = [f"# Generated by fontlex from spec {spec.name!r}"]
    fea += [f"languagesystem {sc} dflt;" for sc in scripts]
    fea.append("")
    for k in spec.class_names:
        if by_class[k]:
            fea.append(f"@C_{k} = [{_fea_glyphs(by_class[k])}];")
    for s in spec.states:
        members = base_glyphs if s == spec.start else [v for (st, _), v in variant.items() if st == s]
        if members:
            fea.append(f"@S_{s} = [{_fea_glyphs(members)}];")
    fea.append("")

    for s in spec.states:
        if s == spec.start:
            continue
        pairs = [(g, v) for (st, g), v in variant.items() if st == s]
        fea.append(f"lookup TO_{s} {{")
        fea.append(f"  sub [{_fea_glyphs(p[0] for p in pairs)}] by [{_fea_glyphs(p[1] for p in pairs)}];")
        fea.append(f"}} TO_{s};")
    for sname, pairs in word_glyph_sets.items():
        if not pairs:
            continue
        fea.append(f"lookup W_{sname} {{")
        fea.append(f"  sub [{_fea_glyphs(p[0] for p in pairs)}] by [{_fea_glyphs(p[1] for p in pairs)}];")
        fea.append(f"}} W_{sname};")
    fea.append("")

    # The lexer: one rule per (previous state, class) whose result differs
    # from the start-state transition, then the no-context fallbacks.
    rules = 0
    dropped = 0
    fea.append("lookup LEX {")
    for s in spec.states:
        if s == spec.start:
            continue
        for k in spec.class_names:
            if not by_class[k]:
                continue
            t, t0 = delta[s][k], delta[spec.start][k]
            if t == t0:
                dropped += 1
                continue
            if t == spec.start:
                fea.append(f"  ignore sub @S_{s} @C_{k}';")
            else:
                fea.append(f"  sub @S_{s} @C_{k}' lookup TO_{t};")
            rules += 1
    for k in spec.class_names:
        t0 = delta[spec.start][k]
        if by_class[k] and t0 != spec.start:
            fea.append(f"  sub @C_{k}' lookup TO_{t0};")
            rules += 1
    fea.append("} LEX;")

    features = ["LEX"]
    if usable_words:
        word_like = [variant[(spec.word_state, g)] for g in base_glyphs
                     if (spec.word_state, g) in variant]
        word_like += [n for n in word_variant.values()]
        fea.append(f"@WORDLIKE = [{_fea_glyphs(word_like)}];")
        fea.append("lookup WORDS {")
        fea.append(f"  ignore sub @WORDLIKE @S_{spec.word_state}';")
        # Longest first, so 'isinstance' is tried before 'is'.
        for w, sname, bases in sorted(usable_words, key=lambda x: -len(x[0])):
            seq = [variant[(spec.word_state, b)] for b in bases]
            marked = " ".join(f"\\{g}'" for g in seq)
            fea.append(f"  ignore sub {marked} @WORDLIKE;")
            fea.append("  sub " + " ".join(f"\\{g}' lookup W_{sname}" for g in seq) + ";")
        fea.append("} WORDS;")
        features.append("WORDS")

    fea.append("")
    fea.append("feature calt {")
    fea += [f"  lookup {name};" for name in features]
    fea.append("} calt;")
    fea_text = "\n".join(fea) + "\n"
    addOpenTypeFeaturesFromString(font, fea_text)

    # 3. Color.
    tokens: list[str] = []
    for s in spec.states:
        t = spec.token(s)
        if t and t not in tokens:
            tokens.append(t)
    for sname, _ in spec.word_sets:
        if sname not in tokens:
            tokens.append(sname)
    colored_tokens = [t for t in tokens if any(t in th for _, th in spec.themes)]
    color_glyphs = {}
    for name, info in glyphmap.items():
        tok = info["set"] or spec.token(info["state"])
        if tok in colored_tokens:
            color_glyphs[name] = [(info["base"], colored_tokens.index(tok))]
    if color_glyphs and spec.themes:
        first = spec.themes[0][1]
        palettes, types, = [], []
        for tname, th in spec.themes:
            palettes.append([_hex_to_rgba(th.get(t) or first.get(t) or "#000000") for t in colored_tokens])
            types.append({"light": 1, "dark": 2}.get(tname.lower(), 0))
        font["CPAL"] = buildCPAL(palettes, paletteTypes=types)
        font["COLR"] = buildCOLR(color_glyphs, version=0)

    _rename(font, spec.name)

    stats = {
        "states": len(spec.states),
        "classes": len(spec.class_names),
        "base_glyphs": len(base_glyphs),
        "variant_glyphs": len(new_glyphs),
        "total_glyphs": len(font.getGlyphOrder()),
        "lex_rules": rules,
        "lex_rules_dropped": dropped,
        "words": len(usable_words),
        "skipped_words": skipped_words,
        "tokens": colored_tokens,
    }
    return Result(font, fea_text, glyphmap, stats)


def _add_glyphs(font: TTFont, new_glyphs: list[tuple[str, str]]) -> None:
    glyf, hmtx = font["glyf"], font["hmtx"]
    order = font.getGlyphOrder() + [n for n, _ in new_glyphs]
    font.setGlyphOrder(order)
    glyf.glyphOrder = order
    gdef = font["GDEF"].table if "GDEF" in font else None
    classdefs = gdef.GlyphClassDef.classDefs if gdef and gdef.GlyphClassDef else None
    for name, base in new_glyphs:
        src = glyf[base]
        g = Glyph()
        if src.numberOfContours == 0:
            g.numberOfContours = 0
        else:
            comp = GlyphComponent()
            comp.glyphName = base
            comp.x = comp.y = 0
            comp.flags = 0x0002 | 0x0004 | 0x0200   # XY values, round, USE_MY_METRICS
            g.numberOfContours = -1
            g.components = [comp]
        glyf[name] = g
        hmtx[name] = hmtx[base]
        if classdefs is not None and base in classdefs:
            classdefs[name] = classdefs[base]
    if "post" in font and hasattr(font["post"], "extraNames"):
        font["post"].formatType = 2.0


def _rename(font: TTFont, family: str) -> None:
    name = font["name"]
    ps = re.sub(r"[^A-Za-z0-9-]", "", family) + "-Regular"
    for rec_id in (16, 17, 21, 22):
        name.removeNames(nameID=rec_id)
    for rec_id, value in ((1, family), (2, "Regular"), (3, f"{ps};fontlex"),
                          (4, f"{family} Regular"), (6, ps)):
        name.setName(value, rec_id, 3, 1, 0x409)
        name.setName(value, rec_id, 1, 0, 0)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("spec")
    ap.add_argument("--base", required=True, help="base TrueType font")
    ap.add_argument("--out", default="build", help="output directory")
    args = ap.parse_args(argv)

    try:
        spec = load_spec(args.spec)
        res = compile_font(spec, args.base)
    except SpecError as e:
        print(f"spec error: {e}", file=sys.stderr)
        return 2

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9]+", "-", spec.name).strip("-")
    ttf = out / f"{stem}.ttf"
    res.font.save(str(ttf))
    res.font.flavor = "woff2"
    res.font.save(str(out / f"{stem}.woff2"))
    (out / f"{stem}.fea").write_text(res.fea)
    (out / f"{stem}.glyphmap.json").write_text(json.dumps(res.glyphmap))
    print(json.dumps({"font": str(ttf), **res.stats}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
