const { spawn } = require('child_process');
const net = require('net');
const { chromium } = require('@playwright/test');

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
      try { if ((await fetch(`${url}api/status`)).status === 200) { ready = true; break; } } catch (_) {}
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    if (!ready) throw new Error('fixture not ready');
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    const template = { dns_server: '127.0.0.1', allowed_ips: '0.0.0.0/0', mtu: 1420, keepalive: 25 };
    const calls = [];
    await page.route('**/api/profiles/*/clients', async (route) => {
      calls.push(route.request().url());
      await route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ schema_version: 1, clients: [] }) });
    });
    await page.route('**/api/profiles/*/template', async (route) => {
      const profile = route.request().url().split('/').at(-2);
      if (route.request().method() === 'POST') {
        const payload = route.request().postDataJSON();
        if (profile !== 'wg' || payload.allowed_ips !== '127.0.0.0/8' || !payload.idempotencyKey) throw new Error('invalid template request');
        template.allowed_ips = payload.allowed_ips;
      }
      await route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ schema_version: 1, profile, template }) });
    });
    await page.goto(`${url}#clients`);
    await page.waitForFunction(() => document.querySelector('#app')?.getAttribute('aria-busy') === 'false');
    await page.locator('[data-client-profile="awg2"]').click();
    await page.waitForFunction(() => document.querySelector('[data-client-profile="awg2"]')?.getAttribute('aria-pressed') === 'true');
    await page.waitForFunction(() => document.querySelector('#app')?.getAttribute('aria-busy') === 'false');
    await page.locator('#add-client-button').click();
    if (!(await page.locator('#preview-dialog-copy').textContent()).includes('AmneziaWG 2.0')) throw new Error('AWG 2.0 create copy missing');
    await page.locator('#preview-close').click();
    await page.locator('[data-client-profile="wg"]').click();
    await page.waitForFunction(() => document.querySelector('[data-client-profile="wg"]')?.getAttribute('aria-pressed') === 'true');
    await page.waitForFunction(() => document.querySelector('#app')?.getAttribute('aria-busy') === 'false');
    await page.locator('#add-client-button').click();
    if (!(await page.locator('#preview-dialog-copy').textContent()).includes('WireGuard')) throw new Error('WG create copy missing');
    await page.locator('#preview-close').click();
    if (!calls.some((value) => value.endsWith('/awg2/clients')) || !calls.some((value) => value.endsWith('/wg/clients'))) throw new Error('profile list routes missing');
    await page.locator('[data-view="settings"]').click();
    const form = page.locator('[data-template-profile="wg"]');
    await page.waitForFunction(() => document.querySelector('[data-template-profile="wg"]')?.dataset.loaded === 'true');
    await form.locator('[name="allowed_ips"]').fill('127.0.0.0/8');
    await form.locator('button[type="submit"]').click();
    await page.waitForFunction(() => document.querySelector('[data-template-status="wg"]')?.textContent.includes('Сохранено'));
    if (await form.locator('[name="allowed_ips"]').inputValue() !== '127.0.0.0/8') throw new Error('template readback missing');
    await page.screenshot({ path: '.ops-tmp/awg-cita-browser-artifacts/multi-profile-settings.png' });
    console.log('PROFILE_SWITCH=PASS TEMPLATE_SETTINGS=PASS');
  } finally {
    if (browser) await browser.close();
    child.kill();
  }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
