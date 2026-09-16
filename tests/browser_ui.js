const { spawn } = require('child_process');
const { chromium } = require('@playwright/test');

const server = spawn('python3', ['tests/fixture_server.py'], {
  stdio: 'ignore',
  env: { ...process.env, PYTHONPATH: process.cwd() },
});
const die = async (error) => { server.kill(); if (error) { console.error(error); process.exitCode = 1; } };
const waitForFixture = async () => {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    try {
      if ((await fetch('http://127.0.0.1:8791/api/status')).ok) return;
    } catch (_) {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error('fixture server did not become ready within 5 seconds');
};
(async () => {
  await waitForFixture();
  const browser = await chromium.launch();
  try {
    for (const [width, mobile] of [[1440, false], [390, true]]) {
      const page = await browser.newPage({ viewport: { width, height: 844 }, isMobile: mobile });
      await page.goto('http://127.0.0.1:8791/', { waitUntil: 'networkidle' });
      await page.waitForFunction(() => document.querySelector('#dashboard')?.getAttribute('aria-busy') === 'false');
      if ((await page.locator('#state').textContent()).trim() !== 'OK') throw new Error('status did not render');
      if (await page.locator('#peers .row').count() !== 1) throw new Error('peer registry did not render');
      if ((await page.locator('#inspect-total').textContent()).trim() !== '3.0 KB') throw new Error('dossier total did not render');
      if (mobile) {
        const railDisplay = await page.locator('.rail').evaluate(n => getComputedStyle(n).display);
        if (railDisplay !== 'none') {
          const viewport = await page.evaluate(() => ({ innerWidth, dpr: devicePixelRatio, media: matchMedia('(max-width:780px)').matches, css: Array.from(document.styleSheets[0].cssRules).map(rule => rule.cssText).filter(rule => rule.includes('@media')).join('\n') }));
          throw new Error(`rail visible on mobile: ${JSON.stringify(viewport)}`);
        }
        if (!await page.locator('table').evaluate(t => t.scrollWidth <= t.clientWidth)) throw new Error('mobile table overflows');
      } else {
        await page.locator('#language-toggle').click();
        await page.getByRole('button', { name: 'English' }).click();
        if ((await page.locator('#refresh').textContent()).trim() !== 'Refresh') throw new Error('English locale did not render');
      }
    }
    console.log('playwright_sector_console=PASS');
  } finally { await browser.close(); await die(); }
})().catch(die);
