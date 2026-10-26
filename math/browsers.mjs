// Screenshots for math/browsers.py: node math/browsers.mjs OUT chromium|firefox
//
// For each page browsers.py wrote, a full-page screenshot showing the text, and
// one showing HarfBuzz's outlines. Then the demo page's text box twice: with
// lines typed key by key, and with the same lines set at once (Chrome has kept
// stale shaping while typing before; the demos work around it).
// Chromium runs through playwright-core (CHROMIUM=path), Firefox through
// puppeteer-core over WebDriver BiDi (FIREFOX=path), as extension/test_extension.mjs does.
import { createRequire } from "module";
import { readFileSync } from "fs";
import { join } from "path";
import { pathToFileURL } from "url";

const require = createRequire(import.meta.url);
const [out, kind] = process.argv.slice(2);
const index = JSON.parse(readFileSync(join(out, "index.json"), "utf8"));

async function launch() {
  if (kind === "firefox") {
    const browser = await require("puppeteer-core").launch({ browser: "firefox", executablePath: process.env.FIREFOX });
    return { close: () => browser.close(), version: () => browser.version(),
             async page(width, height) { const p = await browser.newPage(); await p.setViewport({ width, height }); return p; } };
  }
  const browser = await require("playwright-core").chromium.launch({ executablePath: process.env.CHROMIUM });
  return { close: () => browser.close(), version: () => browser.version(), page: (width, height) => browser.newPage({ viewport: { width, height } }) };
}

const settle = (p) => p.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
const browser = await launch();
for (const pg of index.pages) {
  const width = Math.ceil(Math.max(...pg.rows.map((r) => r.width)) * index.px / 1000) + 80;
  const p = await browser.page(width, 400);
  await p.goto(pathToFileURL(pg.page).href);
  await p.evaluate(() => document.fonts.ready);
  await p.evaluate(() => align());
  await settle(p);
  for (const cls of ["text", "ref"]) {
    await p.evaluate((c) => { document.body.className = c; }, cls);
    await settle(p);
    await p.screenshot({ path: pg.page.replace(".html", `.${kind}.${cls}.png`), fullPage: true });
  }
  await p.close();
}
for (const mode of ["typed", "fresh", "kerning"]) {
  const p = await browser.page(1000, 1400);
  await p.goto(pathToFileURL(index.demo).href);
  await p.evaluate(() => document.fonts.ready);
  await p.evaluate(() => { const c = document.getElementById("code"); c.value = ""; c.style.caretColor = "transparent"; });
  await p.focus("#code");
  if (mode === "typed") {
    for (const [i, line] of index.typed.entries()) {
      await p.keyboard.type(line, { delay: 5 });
      if (i < index.typed.length - 1) await p.keyboard.press("Enter");
    }
  } else {
    // set at once; "kerning" also leaves font-kerning where the demo's workaround leaves it after
    // an odd number of keys (it flips the setting on every input to make Chrome shape the box again)
    await p.evaluate(([text, kerning]) => { const c = document.getElementById("code"); c.value = text;
      if (kerning) c.style.fontKerning = "normal"; }, [index.typed.join("\n"), mode === "kerning"]);
  }
  await new Promise((r) => setTimeout(r, 300));
  await settle(p);
  await (await p.$("#code")).screenshot({ path: join(out, `type.${kind}.${mode}.png`) });
  await p.close();
}
console.log(`${kind}: ${await browser.version()}: ${index.pages.length} pages and the typing check shot in ${out}`);
await browser.close();
