// Puts the page's text in the chosen hint font. The font is fetched from the
// extension and registered with document.fonts, so a page's font-src policy
// doesn't block it; content.css applies it once <html> has data-fontlex. Hidden
// kinds of hint are the stylistic sets in --fontlex-features.
(() => {
  const api = globalThis.browser ?? globalThis.chrome;
  const html = document.documentElement;
  const loading = {};
  let latest = 0;            // settings can change while a font loads: only the latest call applies

  function fontFor(settings) {
    if (settings.off.includes(location.hostname)) return null;
    if (settings.mode === "off") return null;
    if (settings.mode !== "auto") return FONTLEX_FONTS[settings.mode] ? settings.mode : null;
    const lang = (html.lang || document.body?.lang || "").toLowerCase().split("-")[0];
    return Object.keys(FONTLEX_FONTS).find((k) => FONTLEX_FONTS[k].lang === lang) ?? null;
  }

  function load(key) {
    const font = FONTLEX_FONTS[key];
    loading[key] ??= fetch(api.runtime.getURL(font.file))
      .then((r) => r.arrayBuffer())
      .then((data) => {
        const face = new FontFace(font.family, data);
        document.fonts.add(face);
        return face.load();
      });
    return loading[key];
  }

  // The page's own background: the first opaque one from <body> up.
  function darkPage() {
    for (const el of [document.body, html]) {
      if (!el) continue;
      const m = getComputedStyle(el).backgroundColor.match(/[\d.]+/g);
      if (m && (m.length < 4 || Number(m[3]) > 0.5)) {
        const [r, g, b] = m.map(Number);
        return 0.2126 * r + 0.7152 * g + 0.0722 * b < 128;
      }
    }
    return matchMedia("(prefers-color-scheme: dark)").matches;
  }

  async function apply(settings) {
    const call = ++latest;
    const key = fontFor(settings);
    if (!key) {
      delete html.dataset.fontlex;
      return;
    }
    try {
      await load(key);
    } catch (e) {
      console.warn("Fontlex: could not load the font", e);
      return;
    }
    if (call !== latest) return;
    html.dataset.fontlexPalette = settings.palette === "auto" ? (darkPage() ? "dark" : "light") : settings.palette;
    // Sorted, as Firefox lists them in the computed style (Chromium keeps the order given).
    const hide = settings.hide.filter((h) => FONTLEX_HINTS[h]).map((h) => `"${FONTLEX_HINTS[h].feature}" 1`).sort();
    if (hide.length) {
      html.style.setProperty("--fontlex-features", hide.join(", "));
      html.dataset.fontlexHide = "";
    } else {
      html.style.removeProperty("--fontlex-features");
      delete html.dataset.fontlexHide;
    }
    html.dataset.fontlex = key;
  }

  const refresh = () => api.storage.sync.get(FONTLEX_DEFAULTS).then(apply);   // promises: Firefox's browser.* takes no callbacks
  refresh();
  api.storage.onChanged.addListener(refresh);
})();
