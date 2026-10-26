// Records the Relaxed Math page being typed into: docs/images/relaxed-math-demo.mp4
// and .gif (the README's animation) and relaxed-math-poster.png (its last frame).
//
//     NODE_PATH=.../node_modules CHROMIUM=/path/to/chrome node demo/record_relaxed.mjs
//
// It needs playwright-core, a Chromium and ffmpeg. The page is math/relaxed.html with
// everything but its text box hidden and the text set larger. Frames are screenshots
// taken after each keystroke, held for the times below, so the timing doesn't depend
// on how fast the machine is.
import { createRequire } from "module";
import { execFileSync } from "child_process";
import { copyFileSync, mkdtempSync, rmSync, symlinkSync } from "fs";
import { tmpdir } from "os";
import { dirname, join, resolve } from "path";
import { fileURLToPath } from "url";

const { chromium } = createRequire(import.meta.url)(process.env.NODE_PATH + "/playwright-core");
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const OUT = join(ROOT, "docs", "images");
const KEY = 0.1;                         // seconds a keystroke shows
const dir = mkdtempSync(join(tmpdir(), "fontlex-rec-"));

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM });
const page = await browser.newPage({ viewport: { width: 500, height: 600 }, deviceScaleFactor: 2,
                                     colorScheme: "light" });
page.on("pageerror", (e) => { throw e; });
await page.goto("file://" + join(ROOT, "math", "relaxed.html"));
await page.evaluate(() => document.fonts.ready);
await page.addStyleTag({ content: `
  h1, h2, .lede, .tips, main > :not(.try) { display: none !important; }
  main { max-width: none; padding: 16px; }
  .try { display: block; }
  .bar { font-size: 1.25rem; padding: .8rem 1.2rem; }
  .bar .switch { font-size: 1.25rem; }
  .bar .switch input { width: 1.35rem; height: 1.35rem; }
  textarea#code { font-size: 2.3rem; line-height: 2.5; min-height: 0; height: 18.4rem; padding: .6rem 1.4rem;
                  overflow: hidden; resize: none; }` });
await page.fill("#code", "");
await page.focus("#code");

const frames = [];                       // [png, seconds]
async function frame(seconds) {
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
  const png = join(dir, `f${String(frames.length).padStart(4, "0")}.png`);
  await page.locator("#editor").screenshot({ path: png });
  frames.push([png, seconds]);
}
async function type(text, hold) {
  for (const ch of text) {
    if (ch === "\n") await page.keyboard.press("Enter"); else await page.keyboard.type(ch);
    await frame(KEY);
  }
  frames.at(-1)[1] = hold;               // pause on the result, longer than the typing
}

await frame(1.4);                        // an empty field
await type("(a+b)/(c+d)", 2.3);
await type("\n", 0.2);
await type("x^2", 1.9);
await type("\n", 0.2);
await type("sqrt(x^2+1)", 2.4);
await page.click("#hl"); await frame(3.4);   // font rules off: the characters as typed
await page.click("#hl"); await frame(3.0);   // and on again
await browser.close();

// An image sequence at 30 frames a second, each screenshot repeated for its time.
const seq = join(dir, "seq");
execFileSync("mkdir", [seq]);
let n = 0;
for (const [png, seconds] of frames)
  for (let i = 0; i < Math.round(seconds * 30); i++) symlinkSync(png, join(seq, `${String(n++).padStart(5, "0")}.png`));
const input = ["-loglevel", "error", "-y", "-framerate", "30", "-i", join(seq, "%05d.png")];
execFileSync("ffmpeg", [...input, "-vf", "format=yuv420p", "-c:v", "libx264", "-preset", "slow", "-crf", "20",
                        "-tune", "stillimage", "-movflags", "+faststart", join(OUT, "relaxed-math-demo.mp4")]);
execFileSync("ffmpeg", [...input, "-vf", "fps=10,split[a][b];[a]palettegen=max_colors=64:stats_mode=full[p];" +
                        "[b][p]paletteuse=dither=none", "-loop", "0", join(OUT, "relaxed-math-demo.gif")]);
copyFileSync(frames.at(-1)[0], join(OUT, "relaxed-math-poster.png"));
rmSync(dir, { recursive: true });
console.log(`${frames.length} screenshots, ${(n / 30).toFixed(1)} s`);
