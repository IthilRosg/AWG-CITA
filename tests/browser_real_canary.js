// Local browser flow over the real same-origin HTTP contract (synthetic peer).
const { spawn } = require('child_process');
const net = require('net');
const fs = require('fs');
const { chromium } = require('@playwright/test');

const id = 'peer-0123456789abcdef';
const artifacts = '.ops-tmp/awg-cita-browser-real';
fs.mkdirSync(artifacts, { recursive: true });
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const port = server.address().port;
      server.close(() => resolve(port));
    });
  });
}
async function openAction(page, operation) {
  await page.locator(`#client-rows [data-client-id="${id}"] [data-action-menu-toggle]`).click();
  await page.locator(`#client-actions-menu [data-client-action="${operation}"]`).click();
}
async function main() {
  const port = await freePort();
  const url = `http://127.0.0.1:${port}/`;
  const child = spawn(process.env.AWG_TEST_PYTHON || 'python3', ['tests/real_fixture_server.py'], {
    cwd: process.cwd(), stdio: 'ignore',
    env: { ...process.env, AWG_FIXTURE_PORT: String(port), PYTHONPATH: process.cwd() }
  });
  let browser;
  try {
    let ready = false;
    for (let i = 0; i < 50; i += 1) {
      if (child.exitCode !== null) throw new Error(`fixture exited: ${child.exitCode}`);
      try { if ((await fetch(`${url}api/status`)).status === 200) { ready = true; break; } } catch (_) {}
      await pause(100);
    }
    if (!ready) throw new Error('fixture not ready');
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    const page = await context.newPage();
    const consoleErrors = [];
    const networkErrors = [];
    page.on('console', (message) => { if (message.type() === 'error') consoleErrors.push(message.text()); });
    page.on('pageerror', (error) => consoleErrors.push(error.stack || error.message));
    page.on('response', (response) => { if (response.status() >= 400) networkErrors.push(`${response.status()} ${response.url()}`); });
    await page.goto(`${url}#clients`);
    await page.waitForFunction(() => document.querySelector('#app')?.getAttribute('aria-busy') === 'false');
    if ((await page.locator('[data-i18n="adapterMock"]').textContent()).trim() !== 'REAL CANARY') throw new Error('real runtime still displays the mock adapter label');
    if ((await page.locator('[data-i18n="footerMode"]').textContent()).includes('MOCK')) throw new Error('real runtime still displays the mock footer');
    if ((await page.locator('[data-i18n="stateDescription"]').textContent()).includes('frontend state')) throw new Error('real runtime still displays the fixture state description');
    if ((await page.locator(`#client-rows [data-client-id="${id}"]`).count()) !== 1) throw new Error('initial peer missing');
    await openAction(page, 'disable');
    const token = await page.locator('meta[name="csrf-token"]').getAttribute('content');
    await page.locator('meta[name="csrf-token"]').evaluate((node) => { node.content = 'invalid-csrf'; });
    await page.locator('#status-confirm').click();
    await page.waitForFunction(() => document.querySelector('#status-confirm')?.disabled === false);
    if ((await page.locator('.toast').allTextContents()).length === 0) throw new Error('mutation error was not visible');
    if (!(await page.locator(`#client-rows [data-client-id="${id}"]`).textContent()).includes('NEVER')) throw new Error('failed request changed UI');
    if (!networkErrors.some((value) => value.includes('403'))) throw new Error('CSRF rejection not observed');
    await page.locator('meta[name="csrf-token"]').evaluate((node, value) => { node.content = value; }, token);
    consoleErrors.length = 0;
    networkErrors.length = 0;
    await page.locator('#status-confirm').click();
    await page.waitForFunction(() => document.querySelector('#status-client-modal')?.getAttribute('hidden') === '');
    if (!(await page.locator(`#client-rows [data-client-id="${id}"]`).textContent()).includes('DISABLED')) throw new Error('disable failed');
    await page.screenshot({ path: `${artifacts}/disabled.png` });
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#app')?.getAttribute('aria-busy') === 'false');
    if (!(await page.locator(`#client-rows [data-client-id="${id}"]`).textContent()).includes('DISABLED')) throw new Error('disable readback failed');
    await openAction(page, 'enable');
    await page.locator('#status-confirm').click();
    await page.waitForFunction(() => document.querySelector('#status-client-modal')?.getAttribute('hidden') === '');
    if ((await page.locator(`#client-rows [data-client-id="${id}"]`).textContent()).includes('DISABLED')) throw new Error('enable failed');
    await page.screenshot({ path: `${artifacts}/enabled.png` });
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#app')?.getAttribute('aria-busy') === 'false');
    if ((await page.locator(`#client-rows [data-client-id="${id}"]`).textContent()).includes('DISABLED')) throw new Error('enable readback failed');
    await openAction(page, 'delete');
    await page.locator('#delete-confirm').click();
    await page.waitForFunction(() => document.querySelector('#delete-client-modal')?.getAttribute('hidden') === '', undefined, { timeout: 5000 }).catch(async (error) => {
      console.error('delete_debug', JSON.stringify({
        toast: await page.locator('#toast-region').textContent(),
        requests: networkErrors,
        console: consoleErrors,
        disabled: await page.locator('#delete-confirm').isDisabled()
      }));
      throw error;
    });
    if (await page.locator(`#client-rows [data-client-id="${id}"]`).count()) throw new Error('delete failed');
    await page.screenshot({ path: `${artifacts}/deleted.png` });
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#app')?.getAttribute('aria-busy') === 'false');
    if (await page.locator(`#client-rows [data-client-id="${id}"]`).count()) throw new Error('delete readback failed');
    if (consoleErrors.length || networkErrors.length) throw new Error(`browser errors: ${JSON.stringify({ consoleErrors, networkErrors })}`);
    console.log('UI_DISABLE=PASS UI_ENABLE=PASS UI_DELETE=PASS errors_visible=PASS refresh_readback=PASS console_errors=0 network_errors=0');
  } finally {
    if (browser) await browser.close();
    child.kill();
  }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
