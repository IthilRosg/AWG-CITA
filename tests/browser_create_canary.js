// Synthetic, intercepted real-canary create contract; never contacts a live peer.
const { spawn } = require('child_process');
const net = require('net');
const { chromium } = require('@playwright/test');
const fs = require('node:fs');
const artifacts = '.ops-tmp/awg-cita-browser-create';
fs.mkdirSync(artifacts, { recursive: true });
const assert = require('node:assert/strict');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const peerId = 'peer-abcdef0123456789';
const config = '[Interface]\nPrivateKey = SYNTHETIC-TEST-ONLY\nAddress = 127.0.0.2/32\n';
// Valid 1x1 PNG, entirely synthetic; do not capture the result in screenshots.
const qr = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC';
const client = { id: peerId, name: 'Synthetic Canary', status: 'NEVER', lastHandshakeAt: null, lastSeenAt: null, createdAt: null, expiration: '', rxBytes: 0, txBytes: 0, notes: '', tags: ['field'], warning: '' };
async function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer(); server.once('error', reject);
    server.listen(0, '127.0.0.1', () => { const port = server.address().port; server.close(() => resolve(port)); });
  });
}
async function main() {
  const port = await freePort();
  const url = `http://127.0.0.1:${port}/`;
  const child = spawn(process.env.AWG_TEST_PYTHON || 'python3', ['tests/real_fixture_server.py'], { cwd: process.cwd(), stdio: 'ignore', env: { ...process.env, AWG_FIXTURE_PORT: String(port), PYTHONPATH: process.cwd() } });
  let browser;
  try {
    let ready = false;
    for (let i = 0; i < 50; i++) {
      if (child.exitCode !== null) throw new Error('fixture exited');
      try { if ((await fetch(`${url}api/status`)).status === 200) { ready = true; break; } } catch (_) {}
      await pause(100);
    }
    assert(ready, 'fixture did not start');
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, acceptDownloads: true });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    let created = false, posts = 0, gets = 0, loseResponse = false, orphanPresent = false;
    let lostNonce = null, releaseLostResponse = null;
    await page.route('**/api/clients', async route => {
      const request = route.request();
      if (request.method() === 'POST') {
        posts++;
        const body = request.postDataJSON();
        assert.deepEqual(Object.keys(body).sort(), ['acknowledged', 'idempotencyKey', 'name', 'tags'].sort());
        assert.equal(body.name, loseResponse ? 'Lost Response' : client.name);
        assert.deepEqual(body.tags, client.tags);
        assert.equal(body.acknowledged, true);
        assert.match(body.idempotencyKey, /^[0-9a-f-]{36}$/i);
        assert(request.headers()['x-csrf-token'], 'CSRF header missing');
        if (loseResponse) {
          lostNonce = body.idempotencyKey;
          orphanPresent = true; // Server committed; browser never receives its one-time secret.
          await new Promise(resolve => { releaseLostResponse = resolve; });
          await route.abort('failed');
        } else {
          created = true;
          await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ schema_version: 1, client, configText: config, qrDataUri: qr, oneTime: false }) });
        }
      } else {
        gets++;
        const orphan = { ...client, id: 'peer-orphan123', name: 'Server Normalized Name' };
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ schema_version: 1, clients: [...(created ? [client] : []), ...(orphanPresent ? [orphan] : [])] }) });
      }
    });
    await page.route(`**/api/clients/${peerId}/config`, async route => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        schema_version: 1, client, configText: config, qrDataUri: qr
      }) });
    });
    await page.goto(`${url}#clients`);
    await page.waitForFunction(() => document.querySelector('#app')?.getAttribute('aria-busy') === 'false');
    await page.locator('#add-client-button').click();
    assert.match(await page.locator('#preview-dialog-title').textContent(), /создан|creat/i);
    assert.match(await page.locator('#preview-dialog-copy').textContent(), /AmneziaWG 3\.1/i);
    await page.locator('#preview-name').fill(client.name);
    await page.locator('#preview-tags').fill('field');
    assert.equal(await page.locator('#preview-ack, #preview-step-confirm').count(), 0);
    await page.screenshot({ path: `${artifacts}/before-submit-no-secrets.png` });
    await page.locator('#preview-submit').click();
    await page.waitForFunction(() => document.querySelector('#preview-step-result')?.getAttribute('hidden') === null);
    assert.equal(posts, 1);
    assert.equal(await page.locator('#preview-result-id').textContent(), peerId);
    assert.equal(await page.locator('#preview-result-name').textContent(), client.name);
    assert.equal(await page.locator('#create-config-text').inputValue(), config);
    await page.waitForFunction(() => document.querySelector('#create-qr')?.dataset.rendered === 'true', null, { timeout: 4000 }).catch(async () => { throw new Error(`QR not rendered: ${await page.locator('#preview-form-error').textContent()}; console_count=${errors.length}`); });
    assert.equal(await page.locator('#create-qr').getAttribute('role'), 'img');
    assert.equal(await page.locator('#create-qr-caption').count(), 1, 'QR compatibility caption missing');
    assert.match(await page.locator('#create-qr-caption').textContent(), /совместим|compatible/i);
    assert.match(await page.locator('#create-one-time-warning').textContent(), /меню клиента|client menu/i);
    const downloadPromise = page.waitForEvent('download');
    await page.locator('#create-config-download').click();
    const download = await downloadPromise;
    assert.match(download.suggestedFilename(), /\.conf$/);
    assert.equal(await (await require('node:fs/promises').readFile(await download.path(), 'utf8')), config);
    await page.locator('#preview-done').click();
    assert.equal(await page.locator('#create-config-text').inputValue(), '');
    assert.equal(await page.locator('#create-qr').getAttribute('data-rendered'), null);
    assert.equal(await page.locator('#create-qr').evaluate(c => c.getContext('2d').getImageData(0, 0, 1, 1).data[3]), 0, 'QR pixels retained after close');
    assert.equal(await page.locator('#create-preview-modal').getAttribute('hidden'), '');
    assert.equal(await page.locator('#client-rows [data-client-id="' + peerId + '"]').count(), 1);
    await page.locator(`[data-action-menu-toggle="${peerId}"]`).click();
    await page.locator('#client-action-config').click();
    await page.waitForFunction(() => document.querySelector('#config-preview-text')?.textContent.includes('SYNTHETIC-TEST-ONLY'));
    assert.equal(await page.locator('#config-preview-download').isDisabled(), false);
    assert.equal(await page.locator('#config-preview-qr img').count(), 1);
    const repeatedDownload = page.waitForEvent('download');
    await page.locator('#config-preview-download').click();
    assert.equal(await (await require('node:fs/promises').readFile(await (await repeatedDownload).path(), 'utf8')), config);
    await page.locator('#config-preview-close').click();
    assert(gets >= 2, 'no list read-back after create');
    const leakage = await page.evaluate(() => [document.documentElement.outerHTML, JSON.stringify(localStorage), JSON.stringify(sessionStorage)].join('\n'));
    assert(!leakage.includes('SYNTHETIC-TEST-ONLY') && !leakage.includes(qr), 'secret retained in DOM or storage');
    await page.screenshot({ path: `${artifacts}/after-close-no-secrets.png` });
    assert(!errors.some(e => e.includes('SYNTHETIC-TEST-ONLY') || e.includes(qr)), `secret logged: ${errors.map(e => e.replaceAll(config, '[CONFIG]').replaceAll(qr, '[QR]'))}`);
    assert.deepEqual(errors, []);

    // A lost response may leave a peer behind, but Create must stay available.
    loseResponse = true;
    await page.locator('#add-client-button').click();
    await page.locator('#preview-name').fill('Lost Response');
    await page.locator('#preview-tags').fill('field');
    await page.locator('#preview-submit').evaluate(button => button.click());
    await page.waitForFunction(() => document.querySelector('#preview-submit')?.disabled === true);
    releaseLostResponse();
    await page.waitForFunction(() => document.querySelector('#preview-submit')?.disabled === false);
    assert.equal(await page.locator('#create-reconcile').count(), 0);
    await page.screenshot({ path: `${artifacts}/lost-response-no-secrets.png` });
    assert.equal(posts, 2);
    assert.equal(await page.locator('#create-config-text').inputValue(), '');
    await page.locator('#preview-close').click();
    await page.locator('#add-client-button').click();
    assert.equal(await page.locator('#preview-submit').isDisabled(), false);
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#app')?.getAttribute('aria-busy') === 'false');
    await page.locator('#add-client-button').click();
    assert.equal(await page.locator('#preview-submit').isDisabled(), false);
    const secondTab = await context.newPage();
    await secondTab.goto(`${url}#clients`);
    await secondTab.waitForFunction(() => document.querySelector('#app')?.getAttribute('aria-busy') === 'false');
    await secondTab.locator('#add-client-button').click();
    assert.equal(await secondTab.locator('#preview-submit').isDisabled(), false);
    await secondTab.close();
    assert.equal(posts, 2);
    const afterLoss = await page.evaluate(() => [document.documentElement.outerHTML, JSON.stringify(localStorage), JSON.stringify(sessionStorage)].join('\n'));
    assert(!afterLoss.includes('SYNTHETIC-TEST-ONLY') && !afterLoss.includes(qr), 'secret leaked on ambiguity');
    assert(!errors.some(e => e.includes('SYNTHETIC-TEST-ONLY') || e.includes(qr)), 'secret logged on ambiguity');
    assert(errors.every(e => /net::ERR_FAILED/.test(e)), `unexpected console/page errors: ${errors}`);
    console.log('CANARY_CREATE=PASS request=1 readback=PASS secret_cleanup=PASS lost_response=UNBLOCKED');
  } finally { if (browser) await browser.close(); child.kill(); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
