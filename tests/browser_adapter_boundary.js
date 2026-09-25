const { spawn } = require('child_process');
const net = require('net');
const { chromium } = require('@playwright/test');

const children = [];
const injectedClient = {
  id: 'peer-test-injected',
  name: 'Injected Test Peer',
  status: 'ONLINE',
  lastHandshakeAt: '2026-09-22T10:00:00Z',
  lastSeenAt: '2026-09-22T10:01:00Z',
  createdAt: '2026-09-01T10:00:00Z',
  expiration: '',
  rxBytes: 10,
  txBytes: 20,
  notes: 'synthetic test adapter',
  tags: ['test'],
  warning: ''
};

async function freePort() {
  return new Promise((resolve, reject) => {
    const probe = net.createServer();
    probe.once('error', reject);
    probe.listen(0, '127.0.0.1', () => {
      const address = probe.address();
      const port = typeof address === 'object' && address ? address.port : null;
      probe.close((error) => error ? reject(error) : resolve(port));
    });
  });
}

async function startFixture(mode) {
  const port = await freePort();
  const url = `http://127.0.0.1:${port}/`;
  const child = spawn(process.env.AWG_TEST_PYTHON || 'python3', ['tests/fixture_server.py'], {
    cwd: process.cwd(),
    stdio: 'ignore',
    env: {
      ...process.env,
      AWG_FIXTURE_MODE: mode,
      AWG_FIXTURE_PORT: String(port),
      PYTHONPATH: process.cwd()
    }
  });
  children.push(child);
  for (let attempt = 0; attempt < 50; attempt += 1) {
    if (child.exitCode !== null) throw new Error(`${mode} fixture exited early with ${child.exitCode}`);
    try {
      const response = await fetch(`${url}api/status`);
      if (response.status === 200 || response.status === 503) return url;
    } catch (_) {
      // The owned fixture is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`${mode} fixture did not become ready within 5 seconds`);
}

async function waitReady(page) {
  await page.locator('#app').waitFor({ state: 'attached' });
  await page.waitForFunction(() => document.querySelector('#app')?.getAttribute('aria-busy') === 'false');
}

async function assertInjectedAdapter(url, expectedMode) {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const diagnostics = { consoleErrors: [], pageErrors: [], failedRequests: [], lifecycleRequests: [] };
  page.on('console', (message) => {
    if (message.type() === 'error') diagnostics.consoleErrors.push(message.text());
  });
  page.on('pageerror', (error) => diagnostics.pageErrors.push(String(error)));
  page.on('requestfailed', (request) => diagnostics.failedRequests.push(`${request.method()} ${request.url()}`));
  page.on('request', (request) => {
    const pathname = new URL(request.url()).pathname;
    if (pathname.startsWith('/api/lifecycle/')) diagnostics.lifecycleRequests.push(`${request.method()} ${pathname}`);
  });
  await page.addInitScript((client) => {
    window.__AWG_CITA_ADAPTER__ = { listClients: async () => [client] };
  }, injectedClient);
  try {
    await page.goto(url, { waitUntil: 'networkidle' });
    await waitReady(page);
    const runtime = await page.locator('.shell').evaluate((node) => ({
      mode: node.dataset.runtime,
      testMode: node.dataset.testMode
    }));
    const names = await page.locator('#client-rows .client-row .client-cell strong').allTextContents();
    const adapterState = await page.evaluate(() => ({
      hooksExposed: Boolean(window.__AWG_CITA_TEST_HOOKS__),
      injectedAdapterSelected: window.__AWG_CITA_TEST_HOOKS__
        ? window.__AWG_CITA_TEST_HOOKS__.adapter === window.__AWG_CITA_ADAPTER__
        : false
    }));

    if (expectedMode === 'test') {
      if (runtime.mode !== 'mock_lifecycle' || runtime.testMode !== 'true') {
        throw new Error(`test fixture did not expose explicit test mode: ${JSON.stringify(runtime)}`);
      }
      if (!adapterState.hooksExposed || !adapterState.injectedAdapterSelected) {
        throw new Error('explicit test mode did not select the injected adapter');
      }
      if (names.length !== 1 || names[0].trim() !== injectedClient.name) {
        throw new Error(`test adapter result was not rendered: ${JSON.stringify(names)}`);
      }
      await page.getByRole('button', { name: 'Клиенты' }).click();
      await page.waitForURL(/#clients$/);
      await page.locator('#client-rows .client-row').click();
      const createdAtLabel = (await page.locator('#dossier-created').textContent()).trim();
      if (!createdAtLabel || createdAtLabel === '—' || !createdAtLabel.includes('2026')) {
        throw new Error(`ISO createdAt timestamp did not render correctly: ${JSON.stringify(createdAtLabel)}`);
      }
    } else {
      if (runtime.mode !== 'mock_lifecycle' || runtime.testMode !== undefined) {
        throw new Error(`normal fixture did not remain in mock runtime: ${JSON.stringify(runtime)}`);
      }
      if (adapterState.hooksExposed || names.length !== 10 || names.some((name) => name.trim() === injectedClient.name)) {
        throw new Error(`normal runtime honored or exposed the injected adapter: ${JSON.stringify({ adapterState, names })}`);
      }
    }
    if (diagnostics.consoleErrors.length || diagnostics.pageErrors.length || diagnostics.failedRequests.length || diagnostics.lifecycleRequests.length) {
      throw new Error(`${expectedMode} runtime diagnostics were not clean: ${JSON.stringify(diagnostics)}`);
    }
    return { runtime, adapterState, renderedClientCount: names.length, diagnostics };
  } finally {
    await page.close();
    await browser.close();
  }
}

(async () => {
  try {
    const testUrl = await startFixture('test');
    const testMode = await assertInjectedAdapter(testUrl, 'test');
    const normalUrl = await startFixture('normal');
    const normalMode = await assertInjectedAdapter(normalUrl, 'normal');
    console.log(JSON.stringify({ browser_adapter_boundary: 'PASS', testMode, normalMode }));
  } finally {
    for (const child of children) {
      if (child.exitCode === null) child.kill();
    }
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
