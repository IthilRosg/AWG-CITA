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
    const endpoints = { awg3: '127.0.0.1', awg2: '127.0.0.1', wg: '127.0.0.1' };
    const ports = { awg3: 47193, awg2: 47193, wg: 47193 };
    await page.route('**/api/profiles/*/server/port', async (route) => {
      const profile = route.request().url().split('/').at(-3);
      const payload = route.request().postDataJSON();
      if (profile !== 'awg2' || payload.listenPort !== 48193 || payload.expectedRevision !== 'a'.repeat(64) || !payload.idempotencyKey) throw new Error('invalid port request');
      ports.awg2 = payload.listenPort;
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        schema_version: 1, profile, interface: 'awg-cita2', endpoint: endpoints[profile],
        address: '127.0.0.2/24', listenPort: ports[profile], state: 'ACTIVE', clientCount: 2,
        revision: 'b'.repeat(64)
      }) });
    });
    await page.route('**/api/profiles/*/server', async (route) => {
      const profile = route.request().url().split('/').at(-2);
      const interfaces = { awg3: 'awg-canary0', awg2: 'awg-cita2', wg: 'awg-cita-wg' };
      if (route.request().method() === 'POST') {
        const payload = route.request().postDataJSON();
        if (profile !== 'wg' || payload.endpoint !== 'vpn.example.org' || payload.expectedRevision !== 'a'.repeat(64) || !payload.idempotencyKey) throw new Error('invalid endpoint request');
        endpoints.wg = payload.endpoint;
      }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        schema_version: 1, profile, interface: interfaces[profile], endpoint: endpoints[profile],
        address: '127.0.0.2/24', listenPort: ports[profile], state: 'ACTIVE', clientCount: 2,
        revision: endpoints[profile] === '127.0.0.1' && ports[profile] === 47193 ? 'a'.repeat(64) : 'b'.repeat(64)
      }) });
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
    await page.waitForFunction(() => document.querySelector('[data-server-profile="awg2"] .server-settings-content')?.textContent.includes('awg-cita2'));
    const endpointForm = page.locator('[data-endpoint-profile="wg"]');
    await endpointForm.locator('[name="endpoint"]').fill('vpn.example.org');
    await endpointForm.locator('button').click();
    await page.waitForFunction(() => document.querySelector('[data-server-profile="wg"] .server-settings-content')?.textContent.includes('vpn.example.org'));
    const portForm = page.locator('[data-port-profile="awg2"]');
    await portForm.locator('[name="listenPort"]').fill('48193');
    await portForm.locator('button').click();
    await page.waitForFunction(() => document.querySelector('[data-server-profile="awg2"] .server-settings-content')?.textContent.includes('48193'));
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
