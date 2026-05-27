// build-cta.js — render cta.html frame-by-frame via Playwright + headless chromium.
// Each frame is captured as a transparent PNG (omitBackground). The driver below
// steps the page's window.setT(t) deterministically so timing is exact.
const { chromium } = require('playwright');
const path = require('path');

(async () => {
  const outDir = process.argv[2];
  const fps = parseFloat(process.argv[3] || '30');
  const duration = parseFloat(process.argv[4] || '3.0');
  if (!outDir) {
    console.error('usage: node build-cta.js <out-frames-dir> [fps=30] [duration=3.0]');
    process.exit(2);
  }
  const total = Math.ceil(fps * duration) + 1;

  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    viewport: { width: 1080, height: 320 },
    deviceScaleFactor: 1,
  });
  const page = await ctx.newPage();
  await page.goto('file://' + path.resolve(__dirname, 'cta.html'));
  await page.waitForFunction(() => window.__ready === true);

  for (let i = 0; i < total; i++) {
    const t = i / fps;
    await page.evaluate((tt) => window.setT(tt), t);
    const name = String(i).padStart(4, '0');
    await page.screenshot({
      path: `${outDir}/frame_${name}.png`,
      omitBackground: true,
      clip: { x: 0, y: 0, width: 1080, height: 320 },
    });
  }

  await browser.close();
  console.error(`build-cta: rendered ${total} frames at ${fps}fps to ${outDir}`);
})();
