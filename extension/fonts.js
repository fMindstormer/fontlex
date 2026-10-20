// The hint fonts: what the popup offers and what the content script loads.
// `lang` is the page language that "Match the page's language" maps to the font.
const FONTLEX_FONTS = {
  en: { label: "English pronunciation", family: "fontlex-hints-en", file: "fonts/Fontlex-English.woff2", lang: "en" },
  fr: { label: "French pronunciation", family: "fontlex-hints-fr", file: "fonts/Fontlex-French.woff2", lang: "fr" },
  de: { label: "German noun genders", family: "fontlex-hints-de", file: "fonts/Fontlex-German.woff2", lang: "de" },
  "de-syl": { label: "German syllables", family: "fontlex-hints-de-syl", file: "fonts/Fontlex-German-Syllables.woff2" },
};
// mode: "auto" (by the page's language), "off" or a font key; palette: "auto", "light" or "dark";
// off: host names where the extension does nothing.
const FONTLEX_DEFAULTS = { mode: "auto", palette: "auto", off: [] };
