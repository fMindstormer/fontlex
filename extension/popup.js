// The settings popup: which font, which hints, which palette, and off for the current site.
const api = globalThis.browser ?? globalThis.chrome;
const modes = document.getElementById("modes");
for (const [key, font] of [...Object.entries(FONTLEX_FONTS), ["off", { label: "Off" }]]) {
  const label = document.createElement("label");
  const input = Object.assign(document.createElement("input"), { type: "radio", name: "mode", value: key });
  label.append(input, " " + font.label);
  modes.append(label);
}
const hints = document.getElementById("hints");
for (const [key, hint] of Object.entries(FONTLEX_HINTS)) {
  const label = document.createElement("label");
  const input = Object.assign(document.createElement("input"), { type: "checkbox", name: "hint", value: key });
  label.append(input, " " + hint.label);
  hints.append(label);
}

api.storage.sync.get(FONTLEX_DEFAULTS).then((settings) => {
  const save = () => api.storage.sync.set(settings);
  for (const input of modes.querySelectorAll("input")) {
    input.checked = input.value === settings.mode;
    input.addEventListener("change", () => { settings.mode = input.value; save(); });
  }
  for (const input of hints.querySelectorAll("input")) {
    input.checked = !settings.hide.includes(input.value);
    input.addEventListener("change", () => {
      settings.hide = input.checked ? settings.hide.filter((h) => h !== input.value) : [...settings.hide, input.value];
      save();
    });
  }
  const palette = document.getElementById("palette");
  palette.value = settings.palette;
  palette.addEventListener("change", () => { settings.palette = palette.value; save(); });

  api.tabs.query({ active: true, currentWindow: true }).then(([tab]) => {
    let url = null;
    try { url = new URL(tab?.url ?? ""); } catch {}
    if (!url || !["http:", "https:"].includes(url.protocol)) return;      // a web page, not the browser's own
    const host = url.hostname;
    document.getElementById("host").textContent = host;
    document.getElementById("site-row").hidden = false;
    const site = document.getElementById("site");
    site.checked = settings.off.includes(host);
    site.addEventListener("change", () => {
      settings.off = site.checked ? [...settings.off, host] : settings.off.filter((h) => h !== host);
      save();
    });
  });
});
