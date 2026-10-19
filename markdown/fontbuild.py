"""Assembling the Markdown font: styled glyphs, color layers and lookups.

A styled glyph is named `<base>__<style>`, the styles being OUTLINE_STYLES
and COLOR_STYLES. The bold, italic and bold italic outlines come from the
base font's family (matched by glyph name); glyphs a sibling lacks are
composites of the regular (or bold) glyph, slanted for italics. Code, link,
image and HTML styles are COLR glyphs layered over those outlines, so they
follow the palette (light or dark) the app picks. Code can instead be drawn
with another family's outlines (import_by_char): a monospaced one, for a
proportional base.
"""

import copy
import math
from fontTools.colorLib.builder import buildCOLR, buildCPAL
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables import otTables as ot
from fontTools.ttLib.tables import ttProgram
from fontTools.ttLib.tables._g_l_y_f import Glyph, GlyphComponent

# Outline styles, then color styles: (suffix, outline suffix, layers).
OUTLINE_STYLES = {"b": "bold", "i": "italic", "bi": "bold italic"}
COLOR_STYLES = {}
for _w in ("", "b", "i", "bi"):
    COLOR_STYLES["c" + _w] = (_w, ("bg", "fg", None))           # code: background, text
    COLOR_STYLES["l" + _w] = (_w, (None, "link", "underline"))   # link: colored, underlined
    COLOR_STYLES["lc" + _w] = (_w, ("bg", "link", "underline"))  # code in a link
COLOR_STYLES["im"] = ("", (None, "image", None))                 # image description
COLOR_STYLES["h"] = ("", (None, "html", None))                   # raw HTML
PALETTE_ENTRIES = ("bg", "link", "image", "html")
PALETTES = {  # CPAL palette type: 1 = usable with light backgrounds, 2 = dark
    "light": {"bg": "#E9ECF1", "link": "#0B63D6", "image": "#8250DF", "html": "#8A8F98"},
    "dark": {"bg": "#2A303B", "link": "#58A6FF", "image": "#C297FF", "html": "#7D8590"},
}
SEP = "__"


def styled(base, style):
    return base if not style else f"{base}{SEP}{style}"


def _rgba(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)) + (1.0,)


class FontBuilder:
    """Adds glyphs to a TrueType base font and writes the finished font."""

    def __init__(self, base_path):
        self.font = TTFont(base_path, recalcTimestamp=False)
        for tag in ("GSUB", "morx", "mort", "feat", "fpgm", "prep", "cvt ", "hdmx", "LTSH", "VDMX"):
            if tag in self.font:
                del self.font[tag]
        self.glyf, self.hmtx = self.font["glyf"], self.font["hmtx"]
        self.order = list(self.font.getGlyphOrder())
        self.ids = {name: i for i, name in enumerate(self.order)}
        self.glyphs = {}      # new name -> Glyph
        self.metrics = {}     # new name -> (advance, lsb)
        self.classes = {}     # new name -> GDEF class
        self.alias = {}       # base glyph -> styled variants, for GPOS
        self.colr = {}        # glyph -> [(layer glyph, palette entry or None for text color)]
        self.upem = self.font["head"].unitsPerEm
        self.palettes = PALETTES     # {light, dark: {entry: color}}; another font may set its own
        self.base_names = list(self.order)   # the base font's glyphs and add_base_glyph's
        gdef = self.font["GDEF"].table
        self.base_class = dict(gdef.GlyphClassDef.classDefs)
        for name in self.order:
            g = self.glyf[name]
            if g.isComposite() or g.numberOfContours > 0:
                g.program = ttProgram.Program()
                g.program.fromBytecode(b"")

    def gid(self, name):
        return self.ids[name]

    def advance(self, name):
        return self.metrics[name][0] if name in self.metrics else self.hmtx[name][0]

    def gdef_class(self, name):
        if name in self.classes:
            return self.classes[name]
        return self.base_class.get(name, 1) or 1

    def add(self, name, glyph, advance, lsb, gdef_class=1):
        assert name not in self.glyphs and name not in self.hmtx.metrics, name
        if glyph.isComposite() or glyph.numberOfContours > 0:
            glyph.program = ttProgram.Program()
            glyph.program.fromBytecode(b"")
        self.ids[name] = len(self.order)
        self.order.append(name)
        self.glyphs[name], self.metrics[name], self.classes[name] = glyph, (advance, lsb), gdef_class
        return name

    def composite(self, name, components, advance, gdef_class=1):
        """A glyph drawing `components`: (glyph, dx, dy[, 2x2 transform])."""
        g = Glyph()
        g.numberOfContours = -1
        g.components = []
        for i, (base, dx, dy, *tr) in enumerate(components):
            c = GlyphComponent()
            c.glyphName, c.x, c.y = base, dx, dy
            c.flags = 0x0002 | 0x0004 | (0x0200 if i == 0 and not tr and dx == dy == 0 else 0)
            if tr:
                c.transform = tr[0]
            g.components.append(c)
        lsb = self.metrics[components[0][0]][1] if components[0][0] in self.metrics \
            else self.hmtx[components[0][0]][1]
        return self.add(name, g, advance, lsb, gdef_class)

    def empty(self, name, advance=0, gdef_class=1):
        g = Glyph()
        g.numberOfContours = 0
        return self.add(name, g, advance, 0, gdef_class)

    def add_base_glyph(self, name, codepoint, advance):
        """An empty glyph for a character the base font lacks (a tab)."""
        self.empty(name, advance)
        self.base_names.append(name)
        for t in self.font["cmap"].tables:
            if t.isUnicode():
                t.cmap[codepoint] = name

    def rect(self, name, x0, y0, x1, y1):
        pen = TTGlyphPen(None)
        pen.moveTo((x0, y0)); pen.lineTo((x0, y1)); pen.lineTo((x1, y1)); pen.lineTo((x1, y0))
        pen.closePath()
        return self.add(name, pen.glyph(), 0, x0)

    def metric(self, name, default):
        os2 = self.font["OS/2"]
        return getattr(os2, name, 0) or default

    def marker(self, kind, adv, left=0):
        """The glyph a block marker is drawn as: a bullet, a block quote's bar
        and a thematic break's rule (both in the HTML palette color), a task
        box, checked or not. Drawn from the font's metrics, `adv` wide; with
        `left`, that much of it lies left of the glyph, over the hidden glyph
        before it, and the glyph's advance is the rest."""
        name = f"_mk_{kind}{adv}"
        if name in self.ids:
            return name
        x_height = self.metric("sxHeight", self.upem // 2)
        cap = self.metric("sCapHeight", self.upem * 7 // 10)
        stroke = max(self.font["post"].underlineThickness, self.upem // 20)
        glyph_pen = TTGlyphPen(None)
        pen = TransformPen(glyph_pen, (1, 0, 0, 1, -left, 0)) if left else glyph_pen

        def box(x0, y0, x1, y1, hole=False):
            pts = [(x0, y0), (x0, y1), (x1, y1), (x1, y0)]
            for i, pt in enumerate(reversed(pts) if hole else pts):
                (pen.moveTo if i == 0 else pen.lineTo)(tuple(round(v) for v in pt))
            pen.closePath()

        def segment(p, q, w):
            (x1, y1), (x2, y2) = p, q
            d = math.hypot(x2 - x1, y2 - y1)
            nx, ny = -(y2 - y1) / d * w / 2, (x2 - x1) / d * w / 2
            pts = [(x1 + nx, y1 + ny), (x2 + nx, y2 + ny), (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)]
            for i, pt in enumerate(pts):
                (pen.moveTo if i == 0 else pen.lineTo)(tuple(round(v) for v in pt))
            pen.closePath()

        mid = x_height / 2
        if kind == "bullet":
            r = adv * 0.15
            pts = [(adv / 2 + r * math.cos(t * math.pi / 8), mid + r * math.sin(t * math.pi / 8)) for t in range(16)]
            for i, pt in enumerate(reversed(pts)):
                (pen.moveTo if i == 0 else pen.lineTo)(tuple(round(v) for v in pt))
            pen.closePath()
        elif kind == "quote":
            descender = self.font["hhea"].descent
            box(adv * 0.2, max(descender, -cap // 3), adv * 0.2 + max(stroke * 2, adv * 0.12), cap * 1.15)
        elif kind == "rule":
            box(0, mid + cap * 0.1 - stroke / 2, adv, mid + cap * 0.1 + stroke / 2)
        else:                                   # box, checked
            side = min(adv * 0.9, cap * 0.8)
            x0, y0 = (adv - side) / 2, mid + cap * 0.1 - side / 2
            w = stroke * 1.3
            box(x0, y0, x0 + side, y0 + side)
            box(x0 + w, y0 + w, x0 + side - w, y0 + side - w, hole=True)
            if kind == "checked":
                a, c = (x0 + side * 0.24, y0 + side * 0.52), (x0 + side * 0.78, y0 + side * 0.76)
                bmid = (x0 + side * 0.43, y0 + side * 0.28)
                segment(a, bmid, w * 1.3)
                segment(bmid, c, w * 1.3)
        glyph = glyph_pen.glyph()
        if left:
            glyph.recalcBounds(None)
            return self.add(name, glyph, adv - left, glyph.xMin)
        if kind in ("quote", "rule"):           # in the HTML palette color
            shape = self.add(name + ".shape", glyph, 0, 0)
            self.composite(name, [(shape, 0, 0)], adv)
            self.colr[name] = [(shape, "html")]
            return name
        return self.add(name, glyph, adv, 0)

    def strikeout(self):
        os2 = self.font["OS/2"]
        size = getattr(os2, "yStrikeoutSize", 0) or max(self.font["post"].underlineThickness, self.upem // 20)
        pos = getattr(os2, "yStrikeoutPosition", 0) or self.metric("sxHeight", self.upem // 2) // 2
        return pos, size

    def _bar(self, name, x0, x1, advance):
        pos, size = self.strikeout()
        pen = TTGlyphPen(None)
        pen.moveTo((x0, pos)); pen.lineTo((x0, pos + size)); pen.lineTo((x1, pos + size)); pen.lineTo((x1, pos))
        pen.closePath()
        return self.add(name, pen.glyph(), advance, x0)

    def strike_overlay(self, adv):
        """A glyph with no advance that draws the strikethrough line back over
        the `adv` before it, in the text color (with adv 0, nothing)."""
        name = f"_st{adv}"
        if name in self.ids:
            return name
        if not adv:
            return self.empty(name, 0)
        return self._bar(name, -adv, 0, 0)

    def struck(self, name):
        """A copy of `name` (a space, which WebKit always draws a space wide)
        with the strikethrough line on it, over its own layers."""
        new = name + ".st"
        if new in self.ids:
            return new
        adv = self.advance(name)
        line = f"_stline{adv}"
        if line not in self.ids:
            self._bar(line, 0, adv, 0)
        self.composite(new, [(line, 0, 0)], adv, self.gdef_class(name))
        self.colr[new] = list(self.colr.get(name, [])) + [(line, None)]
        return new

    def import_style(self, suffix, sibling_path, fallback=None, slant=0.0):
        """Copy every glyph of a sibling font as `<name>__<suffix>`. Glyphs the
        sibling lacks are composites of `fallback`-styled glyphs, slanted by
        `slant` degrees."""
        sib = TTFont(sibling_path)
        sglyf, shmtx = sib["glyf"], sib["hmtx"]
        names = sib.getGlyphOrder()
        for name in names:
            g = copy.deepcopy(sglyf[name])
            if g.isComposite():
                for c in g.components:
                    c.glyphName = styled(c.glyphName, suffix)
            self.add(styled(name, suffix), g, shmtx[name][0], shmtx[name][1], self.gdef_class(name)
                     if name in self.hmtx.metrics else 1)
        missing = [n for n in self.base_names if n not in set(names)]
        shear = math.tan(math.radians(slant))
        for name in missing:
            src = styled(name, fallback) if fallback else name
            g = self.glyphs.get(name) or self.glyf[name]
            if g.numberOfContours == 0 and not g.isComposite():
                self.empty(styled(name, suffix), self.advance(name), self.gdef_class(name))
            else:
                self.composite(styled(name, suffix), [(src, 0, 0, [[1, 0], [shear, 1]])],
                               self.advance(name), self.gdef_class(name))
        return missing

    def import_by_char(self, suffix, path, bases, scale=1.0, fallback=""):
        """Copy another font's glyph for each of `bases`' characters as
        `<name>__<suffix>`, decomposed and scaled. Characters it lacks get a
        composite of the `fallback`-styled glyph."""
        other = TTFont(path)
        cmap, glyphs, hmtx = other.getBestCmap(), other.getGlyphSet(), other["hmtx"]
        chars = {}
        for cp, name in sorted(self.font.getBestCmap().items()):
            chars.setdefault(name, cp)
        for name in bases:
            theirs = cmap.get(chars.get(name))
            if theirs is None:
                src = styled(name, fallback)
                self.composite(styled(name, suffix), [(src, 0, 0)], self.advance(src), self.gdef_class(name))
                continue
            rec = DecomposingRecordingPen(glyphs)
            glyphs[theirs].draw(rec)
            pen = TTGlyphPen(None)
            rec.replay(TransformPen(pen, (scale, 0, 0, scale, 0, 0)))
            g = pen.glyph()
            g.recalcBounds(None)
            self.add(styled(name, suffix), g, round(hmtx[theirs][0] * scale),
                     g.xMin if g.numberOfContours else 0, self.gdef_class(name))

    def add_color_styles(self, bases, bg=(-230, 860), underline=None, code=""):
        """Code, link, image and HTML variants of each glyph in `bases`. Code
        styles draw the outlines styled `code` + their outline style (from
        import_by_char) if `code` is given; those get no GPOS of the base."""
        post = self.font["post"]
        uy, ut = (underline or (post.underlinePosition, post.underlineThickness))
        rects = {}
        for style, (outline, layers) in COLOR_STYLES.items():
            is_code = layers[0] == "bg"
            for name in bases:
                body = styled(name, code + outline if is_code else outline)
                adv = self.advance(body)
                vname = self.composite(styled(name, style), [(body, 0, 0)], adv, self.gdef_class(name))
                stack = []
                back, text, line = layers
                if back and adv:
                    if ("bg", adv) not in rects:
                        rects[("bg", adv)] = self.rect(f"_bg{adv}", 0, bg[0], adv, bg[1])
                    stack.append((rects[("bg", adv)], "bg"))
                stack.append((body, None if text == "fg" else text))
                if line and adv:
                    if ("ul", adv) not in rects:
                        rects[("ul", adv)] = self.rect(f"_ul{adv}", 0, uy - ut // 2, adv,
                                                       uy + (ut + 1) // 2)
                    stack.append((rects[("ul", adv)], "link"))
                self.colr[vname] = stack
                if not (code and is_code):
                    self.alias.setdefault(name, []).append(vname)
        for name in bases:
            for suffix in OUTLINE_STYLES:
                self.alias.setdefault(name, []).append(styled(name, suffix))

    def _clear_bad_window(self, gsub):
        """Keep glyphs that context lookups match out of glyph ids BAD_WINDOW.
        HarfBuzz 14 caches coverage of context and chain context format 1 and
        2 subtables in bytes that start as 0xFF and stores only ids below
        16384, so an id from 32512 to 32767 reads an empty slot as "not
        covered" (hb_cache_t<14, 1, 8> skips its empty-slot check): such a
        glyph never matches. Empty glyphs inserted before the first one move
        it and every later glyph past the window, keeping their order."""
        covered = _context_coverage(gsub)
        first = next((i for i in BAD_WINDOW if i < len(self.order) and self.order[i] in covered), None)
        if first is None:
            return
        pad = []
        for k in range(BAD_WINDOW.stop - first):
            g = Glyph()
            g.numberOfContours = 0
            name = f"_pad{k}"
            self.glyphs[name], self.metrics[name], self.classes[name] = g, (0, 0), 1
            pad.append(name)
        self.order[first:first] = pad
        self.ids = {name: i for i, name in enumerate(self.order)}

    def finish(self, gsub=None, mark_sets=(), family="Fontlex Markdown"):
        """Write the glyphs and tables; returns the TTFont."""
        import fontlex
        font = self.font
        if gsub is not None:
            self._clear_bad_window(gsub)
        font.setGlyphOrder(self.order)
        self.glyf.glyphOrder = self.order
        for name, g in self.glyphs.items():
            self.glyf[name] = g
            self.hmtx[name] = self.metrics[name]
        gdef = font["GDEF"].table
        cd = gdef.GlyphClassDef.classDefs
        for name in self.order:
            cd[name] = self.classes.get(name, cd.get(name) or 1)
        if mark_sets:
            if gdef.Version < 0x00010002 or gdef.MarkGlyphSetsDef is None:
                gdef.Version = 0x00010002
                gdef.MarkGlyphSetsDef = ot.MarkGlyphSetsDef()
                gdef.MarkGlyphSetsDef.MarkSetTableFormat = 1
                gdef.MarkGlyphSetsDef.Coverage = []
            for glyphs in mark_sets:
                cov = ot.Coverage()
                cov.glyphs = sorted(glyphs, key=self.gid)
                gdef.MarkGlyphSetsDef.Coverage.append(cov)
            gdef.MarkGlyphSetsDef.MarkSetCount = len(gdef.MarkGlyphSetsDef.Coverage)
        fontlex.alias_layout(font, self.alias)
        if fontlex._splits_script_runs(font):     # Core Text would restart the passes at each script
            fontlex._unify_gpos_scripts(font)
        if gsub is not None:
            font["GSUB"] = gsub
        entries = list(self.palettes["light"])
        ids = {e: i for i, e in enumerate(entries)}
        font["CPAL"] = buildCPAL([[_rgba(self.palettes[p][e]) for e in entries] for p in self.palettes],
                                 paletteTypes=[1, 2])
        font["COLR"] = buildCOLR({g: [(l, 0xFFFF if e is None else ids[e]) for l, e in layers]
                                  for g, layers in self.colr.items()}, version=0)
        gasp = newTable("gasp")
        gasp.version, gasp.gaspRange = 1, {0xFFFF: 0x000A}
        font["gasp"] = gasp
        font["post"].formatType = 2.0
        if not hasattr(font["post"], "mapping"):
            font["post"].mapping = {}
        fontlex.set_family_name(font, family)
        return font


BAD_WINDOW = range(32512, 32768)


def _context_coverage(gsub):
    """The glyphs some context or chain context format 1 or 2 subtable covers."""
    covered = set()
    for lk in gsub.table.LookupList.Lookup:
        for st in lk.SubTable:
            kind = st.ExtensionLookupType if lk.LookupType == 7 else lk.LookupType
            st = st.ExtSubTable if lk.LookupType == 7 else st
            if kind in (5, 6) and st.Format in (1, 2):
                covered |= set(st.Coverage.glyphs)
    return covered


def lookup(lookup_type, subtables, flag=0, mark_set=None):
    lk = ot.Lookup()
    lk.LookupType, lk.LookupFlag, lk.SubTable = lookup_type, flag, list(subtables)
    lk.SubTableCount = len(lk.SubTable)
    if mark_set is not None:
        lk.LookupFlag |= 0x0010
        lk.MarkFilteringSet = mark_set
    return lk


def single(mapping):
    st = ot.SingleSubst()
    st.mapping = dict(mapping)
    return st


def multiple(mapping):
    st = ot.MultipleSubst()
    st.mapping = {g: list(seq) for g, seq in mapping.items()}
    return st


def extension(lk):
    """The lookup as an Extension lookup: its subtables move behind 32-bit
    offsets, so thousands of lookups fit the lookup list's 16-bit ones."""
    if lk.LookupType == 7:
        return lk
    subs = []
    for st in lk.SubTable:
        ext = ot.ExtensionSubst()
        ext.Format, ext.ExtensionLookupType, ext.ExtSubTable = 1, lk.LookupType, st
        subs.append(ext)
    lk.LookupType, lk.SubTable = 7, subs
    return lk


def build_gsub(lookups, top=None, feature="calt", scripts=("DFLT", "latn")):
    gsub = newTable("GSUB")
    t = gsub.table = ot.GSUB()
    t.Version = 0x00010000
    t.LookupList = ot.LookupList()
    t.LookupList.Lookup = [extension(lk) for lk in lookups]
    t.LookupList.LookupCount = len(lookups)
    fr = ot.FeatureRecord()
    fr.FeatureTag = feature
    fr.Feature = ot.Feature()
    fr.Feature.LookupListIndex = list(range(len(lookups))) if top is None else list(top)
    fr.Feature.LookupCount = len(fr.Feature.LookupListIndex)
    t.FeatureList = ot.FeatureList()
    t.FeatureList.FeatureRecord = [fr]
    t.FeatureList.FeatureCount = 1
    t.ScriptList = ot.ScriptList()
    t.ScriptList.ScriptRecord = []
    for tag in scripts:
        sr = ot.ScriptRecord()
        sr.ScriptTag = tag
        sr.Script = ot.Script()
        ls = sr.Script.DefaultLangSys = ot.LangSys()
        ls.ReqFeatureIndex, ls.FeatureIndex, ls.FeatureCount = 0xFFFF, [0], 1
        sr.Script.LangSysRecord, sr.Script.LangSysCount = [], 0
        t.ScriptList.ScriptRecord.append(sr)
    t.ScriptList.ScriptCount = len(t.ScriptList.ScriptRecord)
    return gsub
