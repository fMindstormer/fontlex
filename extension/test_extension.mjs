// Load the packaged extension (build/extension/) into Chromium and check it on
// local test pages: the font each page gets, what keeps its own font, the
// palette, a strict Content-Security-Policy, the popup's settings, and that
// the hints are drawn (their colors appear on screen) or hidden.
//
//   npm install playwright-core            # once, anywhere on NODE_PATH
//   CHROMIUM=/path/to/Chromium node extension/test_extension.mjs
//
// Branded Chrome no longer loads unpacked extensions from the command line;
// use Chromium or Chrome for Testing.

import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright-core");
const root = resolve(new URL("..", import.meta.url).pathname);
const ext = join(root, "build", "extension");
const sample = readFileSync(join(root, "french", "sample.txt"), "utf8").split("\n").slice(3, 6).join(" ");

const PAGES = {
  "/fr": `<!doctype html><html lang="fr"><meta charset="utf-8">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
    <body style="background:#fff;color:#111;font:24px Georgia"><p id="t">${sample}</p>
    <code id="code">les amis</code> <span id="icon" class="material-icons" style="font-family: IconFont">home</span></body></html>`,
  "/en": `<!doctype html><html lang="en-GB"><meta charset="utf-8">
    <body style="background:#111;color:#eee;font:24px Georgia"><p id="t">Which letters are silent in knife,
    write, island and listen? Where does the stress fall in photograph and photography?</p></body></html>`,
  "/de": `<!doctype html><html lang="de"><meta charset="utf-8"><body><p id="t">Der Hund, die Katze und das Haus.</p></body></html>`,
  "/none": `<!doctype html><html><meta charset="utf-8"><body><p id="t">Les amis sont arrivés.</p></body></html>`,
};
// Each palette's colors (frfont.PALETTES, enfont.PALETTES): some must be on screen.
const COLORS = {
  "fr-light": { liaison: [0x16, 0x85, 0x5a], nasal: [0x94, 0x47, 0xb0] },
  "en-dark": { stress: [0xff, 0x7b, 0x7b], reduced: [0x86, 0xa8, 0xe6] },
};

// Chromium's id for an unpacked extension: the path's SHA-256, hex digits as a-p.
const id = createHash("sha256").update(ext).digest("hex").slice(0, 32)
  .replace(/./g, (c) => String.fromCharCode(97 + parseInt(c, 16)));

const server = createServer((req, res) => {
  res.writeHead(PAGES[req.url] ? 200 : 404, { "content-type": "text/html; charset=utf-8" });
  res.end(PAGES[req.url] ?? "");
}).listen(0);
const base = `http://localhost:${server.address().port}`;
const context = await chromium.launchPersistentContext(mkdtempSync(join(tmpdir(), "fontlex-")), {
  executablePath: process.env.CHROMIUM,
  headless: true,
  args: [`--disable-extensions-except=${ext}`, `--load-extension=${ext}`],
});

let failed = 0;
function check(name, ok, detail = "") {
  console.log(`${ok ? "ok  " : "FAIL"} ${name}${detail ? ": " + detail : ""}`);
  failed += !ok;
}

async function state(page) {
  await page.waitForTimeout(800);
  return page.evaluate(() => {
    const family = (sel) => (document.querySelector(sel) ? getComputedStyle(document.querySelector(sel)).fontFamily : "");
    return { font: document.documentElement.dataset.fontlex ?? null, palette: document.documentElement.dataset.fontlexPalette,
             text: family("#t"), code: family("#code"), icon: family("#icon") };
  });
}

async function colorsOnScreen(page, wanted) {
  const png = await page.locator("#t").screenshot();
  const shot = await context.newPage();
  const counts = await shot.evaluate(async ({ data, wanted }) => {
    const img = new Image();
    img.src = "data:image/png;base64," + data;
    await img.decode();
    const c = new OffscreenCanvas(img.width, img.height).getContext("2d");
    c.drawImage(img, 0, 0);
    const px = c.getImageData(0, 0, img.width, img.height).data;
    const out = {};
    for (const [name, [r, g, b]] of Object.entries(wanted)) {
      out[name] = 0;
      for (let i = 0; i < px.length; i += 4)
        if (Math.abs(px[i] - r) + Math.abs(px[i + 1] - g) + Math.abs(px[i + 2] - b) < 30) out[name]++;
    }
    return out;
  }, { data: png.toString("base64"), wanted });
  await shot.close();
  return counts;
}

const page = await context.newPage();
await page.goto(`${base}/fr`);
let s = await state(page);
check("French page, matched by lang=fr", s.font === "fr" && s.text.replace(/"/g, "").startsWith("fontlex-hints-fr"), s.text);
check("light palette on a light background", s.palette === "light");
check("code keeps its font", !s.code.includes("fontlex"), s.code);
check("an icon font keeps its font", s.icon.replace(/"/g, "") === "IconFont", s.icon);
let seen = await colorsOnScreen(page, COLORS["fr-light"]);
check("French hints drawn, despite the page's CSP", Object.values(seen).every((n) => n > 20), JSON.stringify(seen));

await page.goto(`${base}/en`);
s = await state(page);
check("English page, matched by lang=en-GB", s.font === "en" && s.text.replace(/"/g, "").startsWith("fontlex-hints-en"), s.text);
check("dark palette on a dark background", s.palette === "dark");
seen = await colorsOnScreen(page, COLORS["en-dark"]);
check("English hints drawn in the dark palette", Object.values(seen).every((n) => n > 20), JSON.stringify(seen));

await page.goto(`${base}/de`);
s = await state(page);
check("German page, matched by lang=de: genders", s.font === "de" && s.text.replace(/"/g, "").startsWith("fontlex-hints-de,"), s.text);
check("its font loaded", await page.evaluate(() => document.fonts.check("16px fontlex-hints-de")));

await page.goto(`${base}/none`);
s = await state(page);
check("no lang: left alone", s.font === null, s.text);

const popup = await context.newPage();
await popup.goto(`chrome-extension://${id}/popup.html`);
check("popup: no site switch on the browser's own pages", !(await popup.isVisible("#site-row")));
await popup.check('input[value="fr"]');
s = await state(page);
check("popup: French for every page applies live", s.font === "fr");
await popup.check('input[value="de-syl"]');
s = await state(page);
check("popup: German syllables", s.font === "de-syl" && await page.evaluate(() => document.fonts.check("16px fontlex-hints-de-syl")));
await popup.check('input[value="fr"]');
await popup.selectOption("#palette", "dark");
s = await state(page);
check("popup: dark palette", s.palette === "dark");
await popup.check('input[value="off"]');
s = await state(page);
check("popup: off", s.font === null);
await popup.check('input[value="auto"]');
await popup.selectOption("#palette", "auto");
await page.goto(`${base}/fr`);
await popup.evaluate(() => chrome.storage.sync.set({ off: ["localhost"] }));    // what "Off on <site>" saves
s = await state(page);
check("off on this site", s.font === null);
await popup.evaluate(() => chrome.storage.sync.set({ off: [] }));
s = await state(page);
check("back on", s.font === "fr");

// Hiding a kind of hint: its stylistic set goes on, its color goes away, the others stay.
const features = () => page.evaluate(() => getComputedStyle(document.getElementById("t")).fontFeatureSettings);
await popup.uncheck('input[name="hint"][value="liaison"]');
await state(page);
seen = await colorsOnScreen(page, COLORS["fr-light"]);
check("popup: liaisons hidden", (await features()) === '"ss05"' && seen.liaison === 0 && seen.nasal > 20,
      `${await features()} ${JSON.stringify(seen)}`);
await popup.check('input[name="hint"][value="liaison"]');
await state(page);
seen = await colorsOnScreen(page, COLORS["fr-light"]);
check("popup: liaisons shown again", (await features()) === "normal" && seen.liaison > 20, JSON.stringify(seen));
await page.goto(`${base}/en`);
await popup.uncheck('input[name="hint"][value="stress"]');
await popup.uncheck('input[name="hint"][value="silent"]');
await state(page);
seen = await colorsOnScreen(page, COLORS["en-dark"]);
check("popup: English stress and silent letters hidden", (await features()) === '"ss03", "ss01"'
      && seen.stress === 0 && seen.reduced > 20, `${await features()} ${JSON.stringify(seen)}`);
await popup.check('input[name="hint"][value="stress"]');
await popup.check('input[name="hint"][value="silent"]');

await context.close();
server.close();
console.log(failed ? `${failed} failed` : "all extension checks passed");
process.exit(failed ? 1 : 0);
