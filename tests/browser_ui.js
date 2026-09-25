const { spawn } = require('child_process');
const net = require('net');
const fs = require('fs');
const { chromium } = require('@playwright/test');

const configuredUrl = process.env.AWG_TEST_URL || '';
let baseUrl = configuredUrl.replace(/#.*$/, '');
const artifacts = '.ops-tmp/awg-cita-browser-artifacts';
fs.mkdirSync(artifacts, { recursive: true });
let fixtureProcess = null;

const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function canReachFixture() {
  if (!baseUrl) return false;
  try {
    const response = await fetch(`${baseUrl}api/status`);
    return response.status === 200 || response.status === 503;
  } catch (_) {
    return false;
  }
}

async function getFreePort() {
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

async function ensureFixture() {
  if (configuredUrl) {
    if (!(await canReachFixture())) throw new Error(`configured AWG_TEST_URL is not reachable: ${baseUrl}`);
    return;
  }
  const port = await getFreePort();
  baseUrl = `http://127.0.0.1:${port}/`;
  fixtureProcess = spawn(process.env.AWG_TEST_PYTHON || 'python3', ['tests/fixture_server.py'], {
    cwd: process.cwd(),
    stdio: 'ignore',
    env: { ...process.env, AWG_FIXTURE_MODE: 'test', AWG_FIXTURE_PORT: String(port), PYTHONPATH: process.cwd() }
  });
  for (let attempt = 0; attempt < 50; attempt += 1) {
    if (await canReachFixture()) return;
    await sleep(100);
  }
  throw new Error('fixture server did not become ready within 5 seconds');
}

async function waitReady(page) {
  await page.locator('#app').waitFor({ state: 'attached' });
  await page.waitForFunction(() => document.querySelector('#app')?.getAttribute('aria-busy') === 'false');
}

async function rowNames(page) {
  return page.locator('#client-rows .client-row').evaluateAll((rows) => rows.map((row) => row.querySelector('.client-cell strong')?.textContent.trim()));
}

async function assertDesktopClientLayout(page) {
  const geometry = await page.evaluate(() => {
    const rect = (element) => {
      const box = element.getBoundingClientRect();
      return { left: box.left, right: box.right, width: box.width };
    };
    const layout = document.querySelector('.client-layout');
    const tablePanel = document.querySelector('.table-panel');
    const tableScroller = document.querySelector('.table-scroll');
    const table = tableScroller?.querySelector('table');
    const dossier = document.querySelector('#client-dossier');
    if (!layout || !tablePanel || !tableScroller || !table || !dossier) return null;
    return {
      viewportWidth: window.innerWidth,
      documentScrollWidth: document.documentElement.scrollWidth,
      layout: rect(layout),
      tablePanel: rect(tablePanel),
      tableScroller: { ...rect(tableScroller), clientWidth: tableScroller.clientWidth, scrollWidth: tableScroller.scrollWidth, overflowX: getComputedStyle(tableScroller).overflowX },
      table: rect(table),
      dossier: rect(dossier)
    };
  });
  if (!geometry || geometry.viewportWidth !== 1280) throw new Error(`desktop layout probe did not run at 1280px: ${JSON.stringify(geometry)}`);
  if (geometry.table.left < geometry.tableScroller.left - 0.5 || geometry.table.right > geometry.tableScroller.right + 0.5) throw new Error(`registry table exceeds its 1280px pane: ${JSON.stringify(geometry)}`);
  if (geometry.tableScroller.right > geometry.tablePanel.right + 0.5 || geometry.dossier.left < geometry.tablePanel.right - 0.5) throw new Error(`registry pane and dossier overlap at 1280px: ${JSON.stringify(geometry)}`);
  if (geometry.documentScrollWidth > geometry.viewportWidth + 0.5) throw new Error(`desktop page has uncontrolled horizontal overflow at 1280px: ${JSON.stringify(geometry)}`);
  if (geometry.tableScroller.scrollWidth > geometry.tableScroller.clientWidth + 1) throw new Error(`registry table requires horizontal scrolling at 1280px: ${JSON.stringify(geometry)}`);
  return geometry;
}

async function openActions(page, clientId) {
  const row = page.locator(`#client-rows .client-row[data-client-id="${clientId}"]`);
  await row.locator('[data-action-menu-toggle]').click();
  if (await page.locator('#client-actions-menu').getAttribute('hidden') !== null) throw new Error(`actions menu did not open for ${clientId}`);
}

async function rejectConfigurationPreview(page, mutation) {
  await page.evaluate((mutationName) => {
    const adapter = window.__AWG_CITA_TEST_HOOKS__.adapter;
    if (!window.__AWG_CITA_ORIGINAL_CONFIG_PREVIEW__) {
      window.__AWG_CITA_ORIGINAL_CONFIG_PREVIEW__ = adapter.generateConfigurationPreview.bind(adapter);
    }
    const original = window.__AWG_CITA_ORIGINAL_CONFIG_PREVIEW__;
    adapter.generateConfigurationPreview = async (id) => {
      const preview = await original(id);
      if (mutationName === 'client-mismatch') return { ...preview, clientId: 'peer-boreal' };
      return { ...preview, configText: '# MOCK CONFIGURATION\nArbitrary non-canonical fixture text' };
    };
  }, mutation);
  await openActions(page, 'peer-atlas');
  await page.locator('#client-actions-menu [data-client-action="config"]').click();
  await page.waitForFunction(() => window.__AWG_CITA_TEST_HOOKS__.state.configPreview.loading === false);
  const rejected = await page.evaluate(() => ({
    error: window.__AWG_CITA_TEST_HOOKS__.state.configPreview.error,
    result: window.__AWG_CITA_TEST_HOOKS__.state.configPreview.result,
    copyDisabled: document.querySelector('#config-preview-copy').disabled,
    downloadDisabled: document.querySelector('#config-preview-download').disabled
  }));
  if (rejected.error !== 'configAdapterError' || rejected.result !== null || !rejected.copyDisabled || !rejected.downloadDisabled) {
    throw new Error(`unsafe configuration preview was accepted or exportable (${mutation}): ${JSON.stringify(rejected)}`);
  }
  await page.locator('#config-preview-close').click();
  if (await page.locator('#config-preview-modal').getAttribute('hidden') !== '') throw new Error('rejected configuration preview did not close');
}

async function save(page, name) {
  await page.screenshot({ path: `${artifacts}/${name}.png` });
}

function attachDiagnostics(page, diagnostics) {
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/lifecycle/')) diagnostics.lifecycleRequests.push(`${request.method()} ${url.pathname}`);
  });
  page.on('console', (message) => {
    if (message.type() === 'error') diagnostics.consoleErrors.push(message.text());
  });
  page.on('pageerror', (error) => diagnostics.pageErrors.push(String(error)));
  page.on('requestfailed', (request) => diagnostics.failedRequests.push(`${request.method()} ${request.url()} :: ${request.failure()?.errorText || 'failed'}`));
  page.on('response', (response) => {
    if (response.status() >= 400) diagnostics.httpFailures.push(`${response.status()} ${response.url()}`);
  });
}

async function assertDesktop(page, diagnostics) {
  await page.goto(baseUrl, { waitUntil: 'networkidle' });
  await waitReady(page);
  const runtime = await page.locator('.shell').evaluate((node) => ({ mode: node.dataset.runtime, testMode: node.dataset.testMode }));
  if (runtime.mode !== 'mock_lifecycle' || runtime.testMode !== 'true') throw new Error(`browser fixture did not select the mock-only test runtime: ${JSON.stringify(runtime)}`);
  if ((await page.locator('#metric-state').textContent()).trim() !== 'READY') throw new Error('overview did not reach READY state');
  if ((await page.locator('#health-total').textContent()).trim() !== '10') throw new Error('fixture dataset did not render ten clients');
  const clientProjection = await page.evaluate(() => {
    const hooks = window.__AWG_CITA_TEST_HOOKS__;
    const source = hooks.state.clients[0];
    const safe = hooks.normalizeClients([{ ...source, privateKey: 'synthetic-secret', extraField: 'untrusted' }])[0];
    let invalidId = 'accepted';
    try {
      hooks.normalizeClients([{ ...source, id: '../path' }]);
    } catch (error) {
      invalidId = String(error?.message || error);
    }
    let oversized = 'accepted';
    try {
      hooks.normalizeClients(Array.from({ length: 65 }, (_, index) => ({ ...source, id: `peer-test-${index}` })));
    } catch (error) {
      oversized = String(error?.message || error);
    }
    return { privateKey: safe.privateKey, extraField: safe.extraField, invalidId, oversized };
  });
  if (clientProjection.privateKey || clientProjection.extraField || clientProjection.invalidId !== 'malformed_adapter_result' || clientProjection.oversized !== 'malformed_adapter_result') throw new Error(`client normalization did not enforce the bounded projection: ${JSON.stringify(clientProjection)}`);
  const malformedClientResults = await page.evaluate(() => {
    const hooks = window.__AWG_CITA_TEST_HOOKS__;
    const source = hooks.state.clients[0];
    const longTimestamp = `2026-09-22T10:00:00.${'1'.repeat(20)}Z`;
    const candidates = [
      { ...source, name: 'N'.repeat(49) },
      { ...source, tags: Array.from({ length: 6 }, () => 'test') },
      { ...source, notes: 'N'.repeat(241) },
      { ...source, id: `peer-${'x'.repeat(65)}` },
      { ...source, lastHandshakeAt: longTimestamp },
      { ...source, createdAt: longTimestamp },
      { ...source, rxBytes: Number.MAX_SAFE_INTEGER + 1 },
      { ...source, txBytes: -1 },
      { ...source, status: 'UNKNOWN' }
    ];
    return candidates.map((candidate) => {
      try {
        hooks.normalizeClients([candidate]);
        return 'accepted';
      } catch (error) {
        return String(error?.message || error);
      }
    });
  });
  if (malformedClientResults.some((result) => result !== 'malformed_adapter_result')) throw new Error(`malformed or oversized client data was accepted: ${JSON.stringify(malformedClientResults)}`);
  await save(page, 'sprint1-overview');

  await page.getByRole('button', { name: 'Клиенты' }).click();
  await page.waitForURL(/#clients$/);
  if (await page.locator('#clients-view').getAttribute('hidden') !== null) throw new Error('Clients view remained hidden after navigation');
  if (await page.locator('#client-rows .client-row').count() !== 10) throw new Error('default client registry did not render ten rows');
  await save(page, 'sprint1-clients');
  const layout1280 = await assertDesktopClientLayout(page);
  console.log(JSON.stringify({ desktop_layout_1280: layout1280 }));

  await page.locator('#client-search').fill('priority');
  if (await page.locator('#client-rows .client-row').count() !== 2) throw new Error('tag search did not filter two priority clients');
  if ((await page.locator('#visible-count').textContent()).trim() !== '2 / 10') throw new Error('search result count is wrong');

  await page.locator('#clear-search').click();
  await page.locator('[data-status-filter="STALE"]').click();
  if ((await page.locator('[data-status-filter="STALE"]').getAttribute('aria-pressed')) !== 'true') throw new Error('STALE filter did not activate');
  if (await page.locator('#client-rows .client-row').count() !== 2) throw new Error('STALE filter did not render two rows');
  await save(page, 'sprint1-filtered');

  await page.locator('#clear-filters').click();
  const initialNames = await rowNames(page);
  await page.locator('[data-sort-key="name"]').click();
  const descendingNames = await rowNames(page);
  if (initialNames[0] === descendingNames[0]) throw new Error('name sorting did not change order');
  if ((await page.locator('[data-sort-col="name"]').getAttribute('aria-sort')) !== 'descending') throw new Error('descending sort state is not exposed');

  await page.locator('#client-rows .client-row').first().click();
  if (await page.locator('#dossier-content').getAttribute('hidden') !== null) throw new Error('selected client dossier did not open');
  if (!(await page.locator('#dossier-client-name').textContent()).trim()) throw new Error('selected client name is empty');
  if (await page.locator('.client-row.is-selected').count() !== 1) throw new Error('selected row highlight is missing');
  await save(page, 'sprint1-selected-dossier');

  await page.locator('#client-search').fill('archive');
  if (await page.locator('#client-rows .client-row').count() !== 1) throw new Error('notes/tags search did not isolate archive fixture');
  if (await page.locator('.client-row.is-selected').count() !== 0) throw new Error('selection remained on a client removed by filtering');
  if ((await page.locator('#client-dossier').getAttribute('aria-hidden')) !== 'true') throw new Error('dossier remained open after the selected client was filtered out');
  await page.locator('#client-search').fill('no-such-client');
  if (await page.locator('#clients-empty').getAttribute('hidden') !== null) throw new Error('empty result state is not visible');
  await save(page, 'sprint1-empty-result');
  await page.locator('#reset-empty').click();
  if (await page.locator('#client-rows .client-row').count() !== 10) throw new Error('empty result reset did not restore rows');
  if (await page.locator('#client-search').inputValue() !== '') throw new Error('empty result reset did not clear the search input');

  const initialClientRows = await page.locator('#client-rows .client-row').count();
  await page.locator('#add-client-button').click();
  if (await page.locator('#create-preview-modal').getAttribute('hidden') !== null) throw new Error('Create Client preview modal did not open');
  await page.locator('#preview-next').click();
  if (await page.locator('#preview-form-error').getAttribute('hidden') !== null) throw new Error('empty preview form did not expose a validation error');
  await page.locator('#preview-name').fill('Kestrel Preview');
  await page.locator('#preview-tags').fill('demo, bad tag');
  await page.locator('#preview-next').click();
  if (await page.locator('#preview-form-error').getAttribute('hidden') !== null) throw new Error('unsafe preview tag did not expose a validation error');
  await page.locator('#preview-tags').fill('demo, ops');
  await page.locator('#preview-next').click();
  if (await page.locator('#preview-step-confirm').getAttribute('hidden') !== null) throw new Error('valid preview metadata did not advance to confirmation');
  await page.locator('#preview-submit').click();
  if (await page.locator('#preview-form-error').getAttribute('hidden') !== null) throw new Error('preview acknowledgement was not required');
  await page.locator('#preview-ack').check();
  await page.locator('#preview-submit').click();
  await page.waitForFunction(() => document.querySelector('#preview-step-result')?.getAttribute('hidden') === null);
  if ((await page.locator('#preview-result-status').textContent()).trim() !== 'DRY_RUN') throw new Error('preview result did not expose DRY_RUN status');
  if (!(await page.locator('#preview-result-boundary').textContent()).includes('NO PEER CREATED')) throw new Error('preview result did not expose the no-peer-created boundary');
  if (await page.locator('#client-rows .client-row').count() !== initialClientRows) throw new Error('create preview mutated the client registry');
  const malformedPreviewResults = await page.evaluate(() => {
    const normalize = window.__AWG_CITA_TEST_HOOKS__.normalizePreviewResult;
    const base = { schemaVersion: 1, previewId: 'preview-12345', created: false, status: 'DRY_RUN', name: 'Safe Preview', tags: ['demo'], acknowledged: true, boundary: 'NO PEER CREATED' };
    return [
      { ...base, previewId: 'preview-' },
      { ...base, name: 'unsafe/name' },
      { ...base, tags: ['unsafe tag'] }
    ].map((candidate) => {
      try {
        normalize(candidate);
        return 'accepted';
      } catch (error) {
        return String(error?.message || error);
      }
    });
  });
  if (malformedPreviewResults.some((result) => result !== 'malformed_preview_result')) throw new Error(`malformed preview result was accepted: ${JSON.stringify(malformedPreviewResults)}`);
  await save(page, 'sprint3-create-preview-result');
  await page.locator('#preview-done').click();
  if (await page.locator('#create-preview-modal').getAttribute('hidden') !== '') throw new Error('preview Done did not close the modal');
  await page.locator('#add-client-button').click();
  await page.keyboard.press('Escape');
  if (await page.locator('#create-preview-modal').getAttribute('hidden') !== '') throw new Error('Escape did not close the preview modal');

  await openActions(page, 'peer-atlas');
  await save(page, 'sprint4-actions-menu');
  const menuFocus = await page.evaluate(() => ({ action: document.activeElement?.dataset?.clientAction || '', outline: getComputedStyle(document.activeElement).outlineStyle }));
  if (menuFocus.action !== 'open' || menuFocus.outline === 'none') throw new Error(`action menu focus is not visibly exposed: ${JSON.stringify(menuFocus)}`);
  if (await page.locator('#client-actions-menu [role="menuitem"]').count() !== 5) throw new Error('client actions menu did not expose five actions');
  await page.keyboard.press('Escape');
  if (await page.locator('#client-actions-menu').getAttribute('hidden') !== '') throw new Error('Escape did not close the client actions menu');

  await openActions(page, 'peer-atlas');
  await page.locator('#client-actions-menu [data-client-action="edit"]').click();
  if (await page.locator('#edit-client-modal').getAttribute('hidden') !== null) throw new Error('edit metadata modal did not open');
  await save(page, 'sprint4-edit-modal');
  await page.locator('#edit-name').fill('Atlas Relay Edited');
  await page.locator('#edit-notes').fill('Updated synthetic metadata for Sprint 4.');
  await page.locator('#edit-tags').fill('priority, office, sprint4');
  await page.locator('#edit-expiration').fill('2027-01-31');
  await page.locator('#edit-save').click();
  await page.waitForFunction(() => document.querySelector('#edit-client-modal')?.getAttribute('hidden') === '');
  if (!(await page.locator('#client-rows .client-row[data-client-id="peer-atlas"]').textContent()).includes('Atlas Relay Edited')) throw new Error('edited client name did not update the table');
  await page.locator('#client-search').fill('Atlas Relay Edited');
  if (await page.locator('#client-rows .client-row').count() !== 1) throw new Error('search did not react to the backend-updated client name');
  await page.locator('#clear-search').click();
  await page.locator('[data-sort-key="name"]').click();
  if ((await rowNames(page))[0] !== 'Atlas Relay Edited') throw new Error('name sorting did not include the backend-updated client name');
  if (await page.locator('[data-sort-col="name"]').getAttribute('aria-sort') !== 'ascending') throw new Error('backend-updated name did not preserve sortable state');
  await page.locator('#client-rows .client-row[data-client-id="peer-atlas"]').click();
  if ((await page.locator('#dossier-client-name').textContent()).trim() !== 'Atlas Relay Edited') throw new Error('edited client name did not update the dossier');
  await save(page, 'sprint4-edit');

  await openActions(page, 'peer-atlas');
  await page.locator('#client-actions-menu [data-client-action="disable"]').click();
  if (await page.locator('#status-client-modal').getAttribute('hidden') !== null) throw new Error('disable confirmation did not open');
  await page.evaluate(() => {
    const adapter = window.__AWG_CITA_TEST_HOOKS__.adapter;
    window.__testOriginalDisableClient = adapter.disableClient.bind(adapter);
    window.__testReleaseLifecycleFailure = null;
    adapter.disableClient = () => new Promise((_resolve, reject) => {
      window.__testReleaseLifecycleFailure = () => reject(new Error('awg_timeout'));
    });
  });
  await page.locator('#status-confirm').click();
  await page.waitForFunction(() => typeof window.__testReleaseLifecycleFailure === 'function');
  if (!(await page.locator('#status-confirm').isDisabled())) throw new Error('mock lifecycle operation did not expose its loading state');
  await page.evaluate(() => window.__testReleaseLifecycleFailure());
  await page.waitForFunction(() => document.querySelector('#status-confirm')?.disabled === false);
  if (await page.locator('#status-client-modal').getAttribute('hidden') !== null) throw new Error('mock lifecycle error closed the confirmation modal unexpectedly');
  if (!(await page.locator('.toast').last().textContent()).includes('Состояние клиента не было изменено.')) throw new Error('mock lifecycle error did not render safe translated feedback');
  if (!(await page.locator('#client-rows .client-row[data-client-id="peer-atlas"] .status-pill').textContent()).includes('ONLINE')) throw new Error('mock lifecycle error changed the visible client state');
  await page.evaluate(() => {
    const adapter = window.__AWG_CITA_TEST_HOOKS__.adapter;
    adapter.disableClient = window.__testOriginalDisableClient;
    delete window.__testOriginalDisableClient;
    delete window.__testReleaseLifecycleFailure;
  });
  await page.locator('#status-confirm').click();
  await page.waitForFunction(() => document.querySelector('#status-client-modal')?.getAttribute('hidden') === '');
  if (!(await page.locator('#client-rows .client-row[data-client-id="peer-atlas"] .status-pill').textContent()).includes('DISABLED')) throw new Error('disable flow did not update status');
  await page.locator('[data-status-filter="DISABLED"]').click();
  if (await page.locator('#client-rows .client-row').count() !== 2) throw new Error('status filter did not react to the backend disable');
  await page.locator('#clear-filters').click();

  await openActions(page, 'peer-atlas');
  if (await page.locator('#client-actions-menu [data-client-action="enable"]').getAttribute('hidden') !== null) throw new Error('enable action was not exposed for disabled client');
  await page.locator('#client-actions-menu [data-client-action="enable"]').click();
  if (await page.locator('#status-client-modal').getAttribute('hidden') !== null) throw new Error('enable confirmation did not open');
  await page.locator('#status-confirm').click();
  await page.waitForFunction(() => document.querySelector('#status-client-modal')?.getAttribute('hidden') === '');
  if (!(await page.locator('#client-rows .client-row[data-client-id="peer-atlas"] .status-pill').textContent()).includes('ONLINE')) throw new Error('enable flow did not restore status');

  const previousPreviewState = await page.evaluate(() => {
    const hooks = window.__AWG_CITA_TEST_HOOKS__;
    const record = hooks.adapter.records.find((client) => client.id === 'peer-atlas');
    const client = hooks.state.clients.find((item) => item.id === 'peer-atlas');
    const previous = {
      name: record.name,
      activity: hooks.state.activity.slice(),
      auditEvents: hooks.state.auditEvents.slice()
    };
    record.name = 'Production Endpoint';
    client.name = record.name;
    hooks.selectClient('peer-atlas');
    return previous;
  });
  await openActions(page, 'peer-atlas');
  await page.locator('#client-actions-menu [data-client-action="config"]').click();
  await page.waitForFunction(() => window.__AWG_CITA_TEST_HOOKS__.state.configPreview.loading === false);
  const metadataWordPreview = await page.evaluate(() => ({
    error: window.__AWG_CITA_TEST_HOOKS__.state.configPreview.error,
    clientName: window.__AWG_CITA_TEST_HOOKS__.state.configPreview.result?.clientName || ''
  }));
  if (metadataWordPreview.error || metadataWordPreview.clientName !== 'Production Endpoint') {
    throw new Error(`valid client metadata was rejected by configuration safety validation: ${JSON.stringify(metadataWordPreview)}`);
  }
  await page.locator('#config-preview-close').click();
  await page.evaluate((previous) => {
    const hooks = window.__AWG_CITA_TEST_HOOKS__;
    hooks.adapter.records.find((client) => client.id === 'peer-atlas').name = previous.name;
    hooks.state.clients.find((client) => client.id === 'peer-atlas').name = previous.name;
    hooks.state.activity = previous.activity;
    hooks.state.auditEvents = previous.auditEvents;
    hooks.selectClient('peer-atlas');
  }, previousPreviewState);

  await rejectConfigurationPreview(page, 'client-mismatch');
  await rejectConfigurationPreview(page, 'noncanonical-config');
  await page.evaluate(() => {
    const adapter = window.__AWG_CITA_TEST_HOOKS__.adapter;
    adapter.generateConfigurationPreview = window.__AWG_CITA_ORIGINAL_CONFIG_PREVIEW__;
    delete window.__AWG_CITA_ORIGINAL_CONFIG_PREVIEW__;
  });

  const previewRaceBaseline = await page.evaluate(() => ({
    activity: window.__AWG_CITA_TEST_HOOKS__.state.activity.slice(),
    auditEvents: window.__AWG_CITA_TEST_HOOKS__.state.auditEvents.slice()
  }));
  await page.evaluate(() => {
    const adapter = window.__AWG_CITA_TEST_HOOKS__.adapter;
    window.__AWG_CITA_ORIGINAL_CONFIG_PREVIEW__ = adapter.generateConfigurationPreview.bind(adapter);
    window.__testConfigPreviewPending = Object.create(null);
    window.__testConfigPreviewCompleted = Object.create(null);
    adapter.generateConfigurationPreview = (id) => new Promise((resolve, reject) => {
      window.__testConfigPreviewPending[id] = {
        resolve: async () => {
          try {
            resolve(await window.__AWG_CITA_ORIGINAL_CONFIG_PREVIEW__(id));
          } catch (error) {
            reject(error);
          }
          await new Promise((done) => window.setTimeout(done, 0));
          window.__testConfigPreviewCompleted[id] = 'resolved';
        },
        reject: async () => {
          reject(new Error('controlled preview failure'));
          await new Promise((done) => window.setTimeout(done, 0));
          window.__testConfigPreviewCompleted[id] = 'rejected';
        }
      };
    });
  });
  await openActions(page, 'peer-atlas');
  await page.locator('#client-actions-menu [data-client-action="config"]').click();
  await page.waitForFunction(() => Boolean(window.__testConfigPreviewPending['peer-atlas']));
  await page.locator('#config-preview-close').click();
  await openActions(page, 'peer-boreal');
  await page.locator('#client-actions-menu [data-client-action="config"]').click();
  await page.waitForFunction(() => Boolean(window.__testConfigPreviewPending['peer-boreal']));
  const pendingPreviewDisplay = await page.evaluate(() => ({
    name: document.querySelector('#config-preview-name').textContent.trim(),
    status: document.querySelector('#config-preview-status').textContent.trim(),
    qrLabel: document.querySelector('#config-preview-qr').getAttribute('aria-label'),
    qrPayload: document.querySelector('#config-preview-qr-payload').textContent.trim(),
    configText: document.querySelector('#config-preview-text').textContent.trim()
  }));
  if (pendingPreviewDisplay.name !== '—' || pendingPreviewDisplay.status !== '—' || pendingPreviewDisplay.qrLabel !== 'QR' ||
      pendingPreviewDisplay.qrPayload !== '—' || pendingPreviewDisplay.configText !== '# MOCK CONFIGURATION') {
    throw new Error(`opening a new configuration preview left prior client content visible: ${JSON.stringify(pendingPreviewDisplay)}`);
  }
  await page.evaluate(async () => window.__testConfigPreviewPending['peer-atlas'].resolve());
  await page.waitForFunction(() => window.__testConfigPreviewCompleted['peer-atlas'] === 'resolved');
  const staleResponseState = await page.evaluate(() => ({
    clientId: window.__AWG_CITA_TEST_HOOKS__.state.configPreview.clientId,
    loading: window.__AWG_CITA_TEST_HOOKS__.state.configPreview.loading,
    resultClientId: window.__AWG_CITA_TEST_HOOKS__.state.configPreview.result?.clientId || null,
    error: window.__AWG_CITA_TEST_HOOKS__.state.configPreview.error
  }));
  if (staleResponseState.clientId !== 'peer-boreal' || !staleResponseState.loading || staleResponseState.resultClientId !== null || staleResponseState.error) {
    throw new Error(`stale configuration response changed the active preview: ${JSON.stringify(staleResponseState)}`);
  }
  await page.evaluate(async () => window.__testConfigPreviewPending['peer-boreal'].reject());
  await page.waitForFunction(() => window.__testConfigPreviewCompleted['peer-boreal'] === 'rejected');
  const failedCurrentPreview = await page.evaluate(() => ({
    clientId: window.__AWG_CITA_TEST_HOOKS__.state.configPreview.clientId,
    loading: window.__AWG_CITA_TEST_HOOKS__.state.configPreview.loading,
    error: window.__AWG_CITA_TEST_HOOKS__.state.configPreview.error,
    resultClientId: window.__AWG_CITA_TEST_HOOKS__.state.configPreview.result?.clientId || null,
    copyDisabled: document.querySelector('#config-preview-copy').disabled,
    downloadDisabled: document.querySelector('#config-preview-download').disabled,
    name: document.querySelector('#config-preview-name').textContent.trim(),
    qrPayload: document.querySelector('#config-preview-qr-payload').textContent.trim(),
    configText: document.querySelector('#config-preview-text').textContent.trim()
  }));
  if (failedCurrentPreview.clientId !== 'peer-boreal' || failedCurrentPreview.loading || failedCurrentPreview.error !== 'configAdapterError' ||
      failedCurrentPreview.resultClientId !== null || !failedCurrentPreview.copyDisabled || !failedCurrentPreview.downloadDisabled ||
      failedCurrentPreview.name !== '—' || failedCurrentPreview.qrPayload !== '—' || failedCurrentPreview.configText !== '# MOCK CONFIGURATION') {
    throw new Error(`failed current preview retained stale configuration data: ${JSON.stringify(failedCurrentPreview)}`);
  }
  await page.locator('#config-preview-close').click();
  await page.evaluate((baseline) => {
    const hooks = window.__AWG_CITA_TEST_HOOKS__;
    hooks.adapter.generateConfigurationPreview = window.__AWG_CITA_ORIGINAL_CONFIG_PREVIEW__;
    hooks.state.activity = baseline.activity;
    hooks.state.auditEvents = baseline.auditEvents;
    delete window.__AWG_CITA_ORIGINAL_CONFIG_PREVIEW__;
    delete window.__testConfigPreviewPending;
    delete window.__testConfigPreviewCompleted;
    hooks.selectClient('peer-atlas');
  }, previewRaceBaseline);
  await page.waitForFunction(() => document.querySelectorAll('#toast-region .toast').length === 0, null, { timeout: 5000 });

  await openActions(page, 'peer-atlas');
  await page.locator('#client-actions-menu [data-client-action="config"]').click();
  if (await page.locator('#config-preview-modal').getAttribute('hidden') !== null) throw new Error('configuration preview did not open');
  await page.waitForFunction(() => Boolean(window.__AWG_CITA_TEST_HOOKS__.state.configPreview.result));
  if (await page.locator('#config-preview-tab-qr').getAttribute('aria-selected') !== 'true') throw new Error('QR tab was not selected by default');
  const configPreview = await page.evaluate(() => window.__AWG_CITA_TEST_HOOKS__.state.configPreview.result);
  if (!configPreview || configPreview.status !== 'MOCK_PREVIEW' || !String(configPreview.qrPayload).startsWith('AWG-CITA-MOCK-QR|')) throw new Error('configuration preview did not expose approved mock QR data');
  if (/private[_ -]?key|public[_ -]?key|secret|endpoint|production|BEGIN [A-Z ]+ KEY/i.test(JSON.stringify(configPreview))) throw new Error('configuration preview contains forbidden secret-bearing data');
  await page.waitForFunction(() => document.querySelectorAll('.toast').length === 0, null, { timeout: 5000 });
  await page.screenshot({ path: `${artifacts}/sprint4-configuration-qr.png` });
  await page.locator('#config-preview-tab-config').click();
  if (await page.locator('#config-preview-config-panel').getAttribute('hidden') !== null) throw new Error('configuration text tab did not open');
  if (!(await page.locator('#config-preview-text').textContent()).includes('MOCK CONFIGURATION')) throw new Error('mock configuration text is missing its boundary');
  await page.screenshot({ path: `${artifacts}/sprint4-configuration-text.png` });
  await page.evaluate(() => {
    window.__testCopiedConfiguration = '';
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: async (text) => { window.__testCopiedConfiguration = text; } }
    });
  });
  await page.locator('#config-preview-copy').click();
  await page.waitForFunction(() => window.__testCopiedConfiguration === window.__AWG_CITA_TEST_HOOKS__.state.configPreview.result.configText);
  await page.waitForFunction(() => document.querySelector('#toast-region .toast')?.textContent.includes('Mock configuration скопирован'));
  await page.evaluate(() => {
    delete navigator.clipboard;
    delete window.__testCopiedConfiguration;
  });
  const [configDownload] = await Promise.all([
    page.waitForEvent('download'),
    page.locator('#config-preview-download').click()
  ]);
  const configPath = await configDownload.path();
  if (!configPath) throw new Error('mock configuration download did not expose a path');
  const configText = fs.readFileSync(configPath, 'utf8');
  if (!configText.includes('MOCK CONFIGURATION') || /private[_ -]?key|public[_ -]?key|secret|endpoint|production|BEGIN [A-Z ]+ KEY/i.test(configText)) throw new Error('downloaded mock configuration is not safe');
  await page.locator('#config-preview-close').click();
  if (await page.locator('#config-preview-modal').getAttribute('hidden') !== '') throw new Error('configuration preview did not close');

  await page.locator('#client-rows .client-row[data-client-id="peer-boreal"]').click();
  await openActions(page, 'peer-boreal');
  await page.locator('#client-actions-menu [data-client-action="delete"]').click();
  if (await page.locator('#delete-client-modal').getAttribute('hidden') !== null) throw new Error('delete confirmation did not open');
  await page.keyboard.press('Escape');
  if (await page.locator('#delete-client-modal').getAttribute('hidden') !== '') throw new Error('Escape did not cancel delete confirmation');
  await openActions(page, 'peer-boreal');
  await page.locator('#client-actions-menu [data-client-action="delete"]').click();
  if (!(await page.locator('#delete-client-name').textContent()).includes('Boreal Lab')) throw new Error('delete confirmation did not show the client name');
  await save(page, 'sprint4-delete');
  await page.locator('#delete-confirm').click();
  await page.waitForFunction(() => document.querySelector('#delete-client-modal')?.getAttribute('hidden') === '');
  if (await page.locator('#client-rows .client-row[data-client-id="peer-boreal"]').count() !== 0) throw new Error('delete flow did not remove the client row');
  if (await page.locator('#dossier-content').getAttribute('hidden') !== '') throw new Error('deleting the selected client did not close the dossier');
  const deleteFocus = await page.evaluate(() => ({ id: document.activeElement?.id || '', tag: document.activeElement?.tagName || '' }));
  if (deleteFocus.id !== 'client-search') throw new Error(`delete focus recovery did not move to the stable clients control: ${JSON.stringify(deleteFocus)}`);

  const actionEvents = await page.evaluate(() => window.__AWG_CITA_TEST_HOOKS__.state.auditEvents.map((event) => event.action));
  for (const expected of ['CLIENT_PREVIEWED', 'CLIENT_UPDATED', 'CLIENT_DISABLED', 'CLIENT_ENABLED', 'CONFIG_PREVIEWED', 'CLIENT_DELETED']) {
    if (!actionEvents.includes(expected)) throw new Error(`Journal is missing ${expected}`);
  }
  if (diagnostics.lifecycleRequests.length) throw new Error(`mock-only UI issued lifecycle HTTP requests: ${JSON.stringify(diagnostics.lifecycleRequests)}`);

  const activityBeforeRefresh = Number((await page.locator('#activity-count').textContent()).trim());
  await page.locator('#refresh-button').click();
  if (!(await page.locator('#refresh-button').isDisabled())) throw new Error('refresh button allowed a parallel request');
  await page.waitForFunction(() => document.querySelector('#refresh-button')?.disabled === false);
  const activityAfterRefresh = Number((await page.locator('#activity-count').textContent()).trim());
  if (activityAfterRefresh !== activityBeforeRefresh + 1) throw new Error('refresh did not add exactly one activity event');
  if (await page.locator('.toast').count() < 1) throw new Error('refresh success toast did not render');

  await page.getByRole('button', { name: 'Журнал' }).click();
  await page.waitForURL(/#journal$/);
  if (await page.locator('#journal-view').getAttribute('hidden') !== null) throw new Error('Journal view remained hidden after navigation');
  if (await page.locator('#journal-history .history-row').count() < 6) throw new Error('status history did not render the bounded snapshots');
  if (await page.locator('#journal-events .audit-row').count() < 6) throw new Error('audit event stream did not render safe fixture events');
  if (await page.locator('#journal-events .audit-row').filter({ hasText: 'CLIENT_PREVIEWED' }).count() !== 1) throw new Error('client preview audit event was not rendered');
  if (await page.locator('#journal-alerts .alert-card').count() !== 3) throw new Error('health alert cards did not render three fixture signals');
  const unsupportedSchemaResult = await page.evaluate(() => {
    try {
      window.__AWG_CITA_TEST_HOOKS__.normalizeObservability({ schemaVersion: 2, statusHistory: [], auditEvents: [], alerts: [] });
      return 'accepted';
    } catch (error) {
      return String(error?.message || error);
    }
  });
  if (unsupportedSchemaResult !== 'unsupported_observability_schema') throw new Error(`unsupported observability schema was accepted: ${unsupportedSchemaResult}`);
  await save(page, 'sprint2-journal');

  await page.locator('#journal-result-filter').selectOption('ERROR');
  if (await page.locator('#journal-events .audit-row').count() !== 1) throw new Error('ERROR audit filter did not isolate one event');
  await page.locator('#journal-search').fill('snapshot');
  if (await page.locator('#journal-events .audit-row').count() !== 1) throw new Error('journal search did not preserve the matching event');
  await save(page, 'sprint2-journal-filtered');
  await page.locator('#journal-search').fill('');
  await page.locator('#journal-result-filter').selectOption('ALL');

  const [jsonDownload] = await Promise.all([
    page.waitForEvent('download'),
    page.locator('#export-json').click()
  ]);
  const jsonPath = await jsonDownload.path();
  if (!jsonPath) throw new Error('JSON evidence download did not expose a path');
  const jsonEvidence = JSON.parse(fs.readFileSync(jsonPath, 'utf8'));
  if (jsonEvidence.schema_version !== 1 || jsonEvidence.runtime !== 'mock_observability') throw new Error('JSON evidence schema marker is wrong');
  if (!Array.isArray(jsonEvidence.audit_events) || jsonEvidence.audit_events.length < 6) throw new Error('JSON evidence is missing audit events');
  if (/private[_-]?key|public[_-]?key|raw[_-]?config|secret|endpoint/i.test(JSON.stringify(jsonEvidence))) throw new Error('JSON evidence contains a forbidden secret-bearing field');

  const [csvDownload] = await Promise.all([
    page.waitForEvent('download'),
    page.locator('#export-csv').click()
  ]);
  const csvPath = await csvDownload.path();
  if (!csvPath) throw new Error('CSV evidence download did not expose a path');
  const csvEvidence = fs.readFileSync(csvPath, 'utf8');
  if (!csvEvidence.startsWith('"schema_version","generated_at","record_type"')) throw new Error('CSV evidence header is wrong');
  if (csvEvidence.split(/\r?\n/).length < 7) throw new Error('CSV evidence is missing audit rows');

  await page.locator('#language-toggle').click();
  await page.getByRole('menuitem', { name: 'English' }).click();
  if ((await page.locator('#journal-heading').textContent()).trim() !== 'Observability and audit') throw new Error('English translation did not update the Journal view');
  await page.locator('#language-toggle').click();
  await page.getByRole('menuitem', { name: 'Русский' }).click();
  await page.getByRole('button', { name: 'Клиенты' }).click();
  await page.waitForURL(/#clients$/);

  await page.locator('#language-toggle').click();
  await page.getByRole('menuitem', { name: 'English' }).click();
  if ((await page.locator('#clients-heading').textContent()).trim() !== 'Client registry') throw new Error('English translation did not update the Clients view');
  await page.locator('#language-toggle').click();
  await page.getByRole('menuitem', { name: 'Русский' }).click();

  await page.getByRole('button', { name: 'Обзор' }).click();
  await page.waitForURL(/#overview$/);
  await page.goBack();
  await page.waitForURL(/#clients$/);
  if (await page.locator('#clients-view').getAttribute('hidden') !== null) throw new Error('browser Back did not restore Clients');
  await page.goForward();
  await page.waitForURL(/#overview$/);
  if (await page.locator('#overview-view').getAttribute('hidden') !== null) throw new Error('browser Forward did not restore Overview');

  await page.evaluate(() => { window.__AWG_CITA_TEST_HOOKS__.adapter.failNextRefresh = true; });
  await page.locator('#refresh-button').click();
  await page.waitForFunction(() => document.querySelector('#refresh-button')?.disabled === false);
  await page.getByRole('button', { name: 'Журнал' }).click();
  await page.waitForURL(/#journal$/);
  if (await page.locator('#journal-alerts code').filter({ hasText: 'REFRESH_FAILURE' }).count() !== 0) throw new Error('refresh failure alert opened before repeated failures');
  await page.getByRole('button', { name: 'Обзор' }).click();
  await page.waitForURL(/#overview$/);
  await page.evaluate(() => { window.__AWG_CITA_TEST_HOOKS__.adapter.failNextRefresh = true; });
  await page.locator('#refresh-button').click();
  await page.waitForFunction(() => document.querySelector('#refresh-button')?.disabled === false);
  await page.getByRole('button', { name: 'Журнал' }).click();
  await page.waitForURL(/#journal$/);
  if (await page.locator('#journal-alerts code').filter({ hasText: 'REFRESH_FAILURE' }).count() !== 1) throw new Error('repeated refresh failure alert did not render');

  if (diagnostics.consoleErrors.length || diagnostics.pageErrors.length || diagnostics.failedRequests.length || diagnostics.httpFailures.length) {
    throw new Error(`desktop diagnostics failed: ${JSON.stringify(diagnostics)}`);
  }
}

async function assertMobile(browser, diagnostics) {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true });
  attachDiagnostics(page, diagnostics);
  try {
    await page.goto(`${baseUrl}#clients`, { waitUntil: 'networkidle' });
    await waitReady(page);
    if (await page.locator('#client-rows .client-row').count() !== 10) throw new Error('mobile mock registry did not load the synthetic fixture records');
    const horizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    if (horizontalOverflow) throw new Error('mobile page has horizontal overflow');
    await page.locator('#client-rows .client-row').first().click();
    if (await page.locator('#client-dossier').evaluate((node) => !node.classList.contains('is-open'))) throw new Error('mobile dossier drawer did not open');
    await page.waitForFunction(() => {
      const node = document.querySelector('#client-dossier');
      if (!node?.classList.contains('is-open')) return false;
      const rect = node.getBoundingClientRect();
      return rect.x >= 0 && rect.right <= window.innerWidth + 0.5;
    });
    const drawerBox = await page.locator('#client-dossier').boundingBox();
    const viewportWidth = page.viewportSize()?.width || 390;
    if (!drawerBox || drawerBox.width > 360 || drawerBox.x < 0 || drawerBox.x + drawerBox.width > viewportWidth + 0.5) throw new Error(`mobile drawer geometry is unexpected: ${JSON.stringify(drawerBox)}`);
    await save(page, 'sprint1-mobile-drawer');
    await page.keyboard.press('Escape');
    if (await page.locator('#client-dossier').evaluate((node) => node.classList.contains('is-open'))) throw new Error('Escape did not close mobile dossier');
    await page.goto(`${baseUrl}#journal`, { waitUntil: 'networkidle' });
    await waitReady(page);
    if (await page.locator('#journal-view').getAttribute('hidden') !== null) throw new Error('mobile Journal view remained hidden');
    const journalOverflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    if (journalOverflow) throw new Error('mobile Journal view has horizontal overflow');
    await save(page, 'sprint2-mobile-journal');
    await page.locator('#add-client-button').click();
    const previewBox = await page.locator('#create-preview-modal .modal-dialog').boundingBox();
    const previewViewportWidth = page.viewportSize()?.width || 390;
    if (!previewBox || previewBox.x < 0 || previewBox.width > previewViewportWidth + 0.5 || previewBox.x + previewBox.width > previewViewportWidth + 0.5) throw new Error(`mobile preview modal geometry is unexpected: ${JSON.stringify(previewBox)}`);
    if (await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)) throw new Error('mobile preview modal introduced horizontal overflow');
    await save(page, 'sprint3-mobile-preview');
    await page.keyboard.press('Escape');
    if (await page.locator('#create-preview-modal').getAttribute('hidden') !== '') throw new Error('mobile Escape did not close the preview modal');
    await page.getByRole('button', { name: 'Клиенты' }).click();
    await page.waitForURL(/#clients$/);
    await waitReady(page);
    await openActions(page, 'peer-atlas');
    const menuBox = await page.locator('#client-actions-menu').boundingBox();
    if (!menuBox || menuBox.x < 0 || menuBox.x + menuBox.width > (page.viewportSize()?.width || 390) + 0.5) throw new Error(`mobile action menu geometry is unexpected: ${JSON.stringify(menuBox)}`);
    await page.keyboard.press('Escape');
    await openActions(page, 'peer-atlas');
    await page.locator('#client-actions-menu [data-client-action="edit"]').click();
    const editBox = await page.locator('#edit-client-modal .modal-dialog').boundingBox();
    if (!editBox || editBox.x < 0 || editBox.x + editBox.width > (page.viewportSize()?.width || 390) + 0.5) throw new Error(`mobile edit modal geometry is unexpected: ${JSON.stringify(editBox)}`);
    await save(page, 'sprint4-mobile-edit');
    await page.keyboard.press('Escape');
    if (await page.locator('#edit-client-modal').getAttribute('hidden') !== '') throw new Error('mobile Escape did not close edit modal');
    if (diagnostics.consoleErrors.length || diagnostics.pageErrors.length || diagnostics.failedRequests.length || diagnostics.httpFailures.length) {
      throw new Error(`mobile diagnostics failed: ${JSON.stringify(diagnostics)}`);
    }
  } finally {
    await page.close();
  }
}

(async () => {
  await ensureFixture();
  const browser = await chromium.launch();
  const desktopDiagnostics = { consoleErrors: [], pageErrors: [], failedRequests: [], httpFailures: [], lifecycleRequests: [] };
  const mobileDiagnostics = { consoleErrors: [], pageErrors: [], failedRequests: [], httpFailures: [], lifecycleRequests: [] };
  const desktop = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
  attachDiagnostics(desktop, desktopDiagnostics);
  try {
    await assertDesktop(desktop, desktopDiagnostics);
    await assertMobile(browser, mobileDiagnostics);
    console.log(JSON.stringify({
      playwright_sprint4: 'PASS',
      url: baseUrl,
      desktop: desktopDiagnostics,
      mobile: mobileDiagnostics,
      screenshots: [
        'artifacts/sprint1-overview.png',
        'artifacts/sprint1-clients.png',
        'artifacts/sprint1-filtered.png',
        'artifacts/sprint1-selected-dossier.png',
        'artifacts/sprint1-empty-result.png',
        'artifacts/sprint1-mobile-drawer.png',
        'artifacts/sprint3-create-preview-result.png',
        'artifacts/sprint2-journal.png',
        'artifacts/sprint2-journal-filtered.png',
        'artifacts/sprint2-mobile-journal.png',
        'artifacts/sprint3-mobile-preview.png',
        'artifacts/sprint4-edit.png',
        'artifacts/sprint4-edit-modal.png',
        'artifacts/sprint4-actions-menu.png',
        'artifacts/sprint4-delete.png',
        'artifacts/sprint4-mobile-edit.png',
        'artifacts/sprint4-configuration-qr.png',
        'artifacts/sprint4-configuration-text.png'
      ].map((path) => path.replace(/^artifacts\//, `${artifacts}/`))
    }));
  } finally {
    await desktop.close();
    await browser.close();
    if (fixtureProcess) fixtureProcess.kill();
  }
})().catch((error) => {
  console.error(error);
  if (fixtureProcess) fixtureProcess.kill();
  process.exitCode = 1;
});
