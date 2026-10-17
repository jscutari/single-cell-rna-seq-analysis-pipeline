// Dev-only visual check: screenshots the app and the design reference side by side.
// Usage: npm run dev, then `node scripts/screenshot.ts [width] [height]`.
// Writes scripts/out/{app,reference,overlay,diff}.png
import { chromium } from "playwright";
import { PNG } from "pngjs";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const out = resolve(here, "out");
const width = Number(process.argv[2] ?? 1440);
const height = Number(process.argv[3] ?? 900);
const appUrl = process.env.APP_URL ?? "http://localhost:5173";
const reference = pathToFileURL(resolve(here, "../Reference/SCRAP_Lab_Notebook_Refined (1).html")).href;
const font = (w: number, style = "normal") =>
  pathToFileURL(resolve(here, `../node_modules/@fontsource/shantell-sans/files/shantell-sans-latin-${w}-${style}.woff2`)).href;

// Give the reference the same font as the app so only layout differences show up.
const fontCss = [400, 500, 700]
  .map((w) => `@font-face{font-family:"Shantell Sans";font-weight:${w};src:url("${font(w)}")}`)
  .concat(`@font-face{font-family:"Shantell Sans";font-style:italic;font-weight:400;src:url("${font(400, "italic")}")}`)
  .concat(`:root{--hand:"Shantell Sans",cursive;--notes-hand:"Shantell Sans",cursive}`)
  .join("\n");

mkdirSync(out, { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width, height } });

await page.goto(appUrl);
await page.evaluate(() => document.fonts.ready);
await page.screenshot({ path: resolve(out, "app.png") });

await page.goto(reference);
await page.addStyleTag({ content: fontCss });
await page.evaluate(() => document.fonts.ready);
await page.waitForTimeout(200);
await page.screenshot({ path: resolve(out, "reference.png") });
await browser.close();

const a = PNG.sync.read(readFileSync(resolve(out, "app.png")));
const b = PNG.sync.read(readFileSync(resolve(out, "reference.png")));
const overlay = new PNG({ width: a.width, height: a.height });
const diff = new PNG({ width: a.width, height: a.height });
let changed = 0;
for (let i = 0; i < a.data.length; i += 4) {
  let delta = 0;
  for (let c = 0; c < 3; c++) {
    overlay.data[i + c] = (a.data[i + c] + b.data[i + c]) >> 1;
    delta = Math.max(delta, Math.abs(a.data[i + c] - b.data[i + c]));
  }
  if (delta > 24) changed++;
  const v = delta > 24 ? 0 : 255;
  diff.data[i] = 255;
  diff.data[i + 1] = v;
  diff.data[i + 2] = v;
  overlay.data[i + 3] = diff.data[i + 3] = 255;
}
writeFileSync(resolve(out, "overlay.png"), PNG.sync.write(overlay));
writeFileSync(resolve(out, "diff.png"), PNG.sync.write(diff));
console.log(`${width}x${height}: ${((changed / (a.width * a.height)) * 100).toFixed(2)}% of pixels differ`);
