"""Compile synchronous annotation machines, flat or as checked cascades.

The supported font domain is printable ASCII in one left-to-right shaping
run. The machine scans that text right to left. Labels color characters;
None preserves their normal appearance. This is not a general string-output
transducer backend or a proof about a shaping engine.
"""

import colorsys
import io
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "markdown"))

import fontbuild as fb  # noqa: E402
import passes  # noqa: E402
from machines import decompose, require_equivalent  # noqa: E402

BASE = HERE.parent / "fonts" / "JetBrainsMono-Regular.ttf"


@dataclass
class Compiled:
    data: bytes
    annotations: dict
    metrics: dict
    encoding: str


def build(machine, partition=None, *, encoding="variants", base=BASE):
    if encoding not in ("variants", "slots"):
        raise ValueError("encoding must be variants or slots")
    if any(len(c) != 1 or not 0x20 <= ord(c) <= 0x7e for c in machine.alphabet):
        raise ValueError("the font backend supports printable ASCII in one shaping run")
    model = None if partition is None else decompose(machine, partition)
    require_equivalent(machine, model or machine)
    b = fb.FontBuilder(str(base))
    pl = passes.Pipeline(b)
    cmap = b.font.getBestCmap()
    if any(ord(c) not in cmap for c in machine.alphabet):
        raise ValueError("base font lacks an input character")
    letters = {i: cmap[ord(c)] for i, c in enumerate(machine.alphabet)}
    if len(set(letters.values())) != len(letters):
        raise ValueError("input characters must have distinct base glyphs")
    annotations = {g: (machine.alphabet[c], None) for c, g in letters.items()}
    labels = sorted({o for row in machine.outputs for o in row if o is not None})
    palette = {}
    for i, label in enumerate(labels):
        rgb = colorsys.hsv_to_rgb((i * 0.61803398875 + 0.58) % 1, 0.7, 0.75)
        palette[label] = "#" + "".join(f"{round(v * 255):02x}" for v in rgb)
    # FontBuilder writes both light and dark palettes, even without labels.
    b.palettes = {"light": palette or {"plain": "#000000"}, "dark": palette or {"plain": "#FFFFFF"}}
    shown = {}

    def result(c, label):
        original = letters[c]
        if label is None:
            return original
        key = (c, label)
        if key not in shown:
            name = b.composite(f"_result{len(shown)}", [(original, 0, 0)], b.advance(original))
            b.colr[name] = [(original, label)]
            b.alias.setdefault(original, []).append(name)
            annotations[name] = (machine.alphabet[c], label)
            shown[key] = name
        return shown[key]

    glyphs = {}

    def mark(key):
        if key not in glyphs:
            glyphs[key] = b.empty(f"_machine{len(glyphs)}", 0, gdef_class=3)
        return glyphs[key]

    # Slots can share a character class when the whole machine treats its
    # members identically. Variants retain the character to restore it later.
    classes, representative = {}, {}
    for c in range(len(machine.alphabet)):
        signature = (tuple(row[c] for row in machine.table), tuple(row[c] for row in machine.outputs),
                     machine.alphabet[c] == " ")
        cls = classes.setdefault(signature, len(classes)) if encoding == "slots" else c
        representative.setdefault(cls, c)
        if encoding == "variants":
            representative[cls] = c
    symbol_class = {}
    for c in letters:
        signature = (tuple(row[c] for row in machine.table), tuple(row[c] for row in machine.outputs),
                     machine.alphabet[c] == " ")
        symbol_class[c] = classes[signature] if encoding == "slots" else c
    initial = {mark(("input", cls)): representative[cls] for cls in set(symbol_class.values())}
    if encoding == "variants":
        pl.single({g: mark(("input", symbol_class[c])) for c, g in letters.items()})
    else:
        # A space is its own slot: WebKit otherwise widens its inserted mark.
        pl.add(fb.lookup(2, [fb.multiple({g: ([g] if machine.alphabet[c] != " " else [])
                                        + [mark(("input", symbol_class[c]))] for c, g in letters.items()})]))

    current = initial
    if model is not None:
        front_values = {}

        def front_step(state, c):
            nxt = model.front[state][c]
            g = mark(("front", symbol_class[c], state, nxt))
            front_values[g] = (c, state)
            return g, nxt

        pl.rtl(current, front_step, model.start[0])
        current = front_values

    final_values = {}

    def last_step(state, value):
        if model is None:
            c = value
            nxt, label = machine.step(state, c)
        else:
            c, block = value
            cell = model.back[state][block][c]
            if cell is None:
                return passes.IMPOSSIBLE
            nxt, label = cell
        space = machine.alphabet[c] == " "
        identity = c if encoding == "variants" or space else None
        g = mark(("final", identity, nxt, label))
        final_values[g] = (identity, label)
        return g, nxt

    pl.rtl(current, last_step, machine.start if model is None else model.start[1])
    if encoding == "variants":
        pl.single({g: result(c, label) for g, (c, label) in final_values.items()})
    else:
        rules = []
        for c, original in letters.items():
            if machine.alphabet[c] == " ":
                continue
            for label in labels:
                following = {g for g, (identity, out) in final_values.items() if identity is None and out == label}
                if following:
                    rules.append(([], [{original}], [following],
                                  [(0, pl.nested({original: result(c, label)}))]))
        if rules:
            pl.chain(rules)
        pl.single({g: result(c, label) for g, (c, label) in final_values.items() if c is not None})
    if len(b.order) > 65535:
        raise ValueError(f"font exceeds glyph limit: {len(b.order)} > 65535")
    font = b.finish(pl.gsub(), pl.mark_sets, family="Fontlex Machine")
    buf = io.BytesIO()
    font.save(buf)
    data = buf.getvalue()
    from fontTools.ttLib import TTFont
    saved = TTFont(io.BytesIO(data))
    return Compiled(data, annotations,
                    dict(glyphs=len(saved.getGlyphOrder()), added_glyphs=len(saved.getGlyphOrder()) - len(b.base_names),
                         font_bytes=len(data), gsub_bytes=saved.reader.tables["GSUB"].length,
                         lookups=len(pl.lookups)), encoding)


def check(machine, compiled, texts, shapers=("harfbuzz",)):
    """Check every output annotation and original character in real engines."""
    from fontTools.ttLib import TTFont
    from test_fontlex import SHAPERS
    font = TTFont(io.BytesIO(compiled.data))
    order = font.getGlyphOrder()
    scratch = {g for g in order if g.startswith("_machine")}
    # The same font without substitutions is an independent layout baseline:
    # annotation and state slots must not change the run's advance.
    del font["GSUB"]
    plain = io.BytesIO()
    font.save(plain)
    texts = tuple(texts)
    counts = {}
    for name in shapers:
        shaper = SHAPERS[name](compiled.data)
        baseline = SHAPERS[name](plain.getvalue())
        count = 0
        for text in texts:
            expected = tuple(reversed(machine.trace(reversed(text))))
            got = {}
            shaped, advance = shaper.shape(text)
            for gid, cluster, *_ in shaped:
                if gid is None or not 0 <= gid < len(order):
                    raise ValueError(f"{name}: fallback or invalid glyph for {text!r}")
                glyph = order[gid]
                if glyph in compiled.annotations:
                    got.setdefault(cluster, []).append(compiled.annotations[glyph])
                elif glyph not in scratch:
                    raise ValueError(f"{name}: unexpected glyph {glyph!r} for {text!r}")
            want = {i: [(c, label)] for i, (c, label) in enumerate(zip(text, expected))}
            if got != want:
                raise ValueError(f"{name}: wrong annotation for {text!r}: expected {want!r}, got {got!r}")
            if abs(advance - baseline.shape(text)[1]) > 0.01:
                raise ValueError(f"{name}: annotation changed the advance for {text!r}")
            count += 1
        counts[name] = count
    return counts
