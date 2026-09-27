const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('@playwright/test');

const root = path.resolve(__dirname, '..', 'awg_cita', 'static');
const content = {
  '/login': ['login.html', 'text/html; charset=utf-8'],
  '/auth/login.css': ['login.css', 'text/css; charset=utf-8'],
  '/auth/login.js': ['login.js', 'text/javascript; charset=utf-8'],
};

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const width of [1280, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 800 } });
      const errors = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await page.route('http://panel.test/**', async (route) => {
        const pathname = new URL(route.request().url()).pathname;
        if (pathname === '/auth/login') {
          const submitted = route.request().postDataJSON();
          return route.fulfill({ status: submitted.password === 'correct' ? 200 : 401,
            contentType: 'application/json', body: JSON.stringify({ ok: submitted.password === 'correct' }) });
        }
        if (pathname === '/') return route.fulfill({ status: 200, contentType: 'text/plain', body: 'signed in' });
        if (!content[pathname]) return route.fulfill({ status: 404 });
        const [file, contentType] = content[pathname];
        return route.fulfill({ status: 200, contentType, body: fs.readFileSync(path.join(root, file)) });
      });
      await page.goto('http://panel.test/login');
      if (process.env.AWG_LOGIN_SCREENSHOT_DIR) {
        fs.mkdirSync(process.env.AWG_LOGIN_SCREENSHOT_DIR, { recursive: true });
        await page.screenshot({ path: path.join(process.env.AWG_LOGIN_SCREENSHOT_DIR, `login-${width}.png`), fullPage: true });
      }
      assert.equal(await page.locator('#login-title').innerText(), 'Вход в панель');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await page.locator('#username').fill('awg-admin');
      await page.locator('#password').fill('wrong');
      await page.locator('#password-toggle').click();
      assert.equal(await page.locator('#password').getAttribute('type'), 'text');
      await page.locator('#login-submit').click();
      await page.locator('#login-error').waitFor({ state: 'visible' });
      assert.match(await page.locator('#login-error').innerText(), /Проверьте логин и пароль/);
      await page.locator('#password').fill('correct');
      await page.locator('#login-submit').click();
      await page.waitForURL('http://panel.test/');
      assert.deepEqual(errors, []);
      await page.close();
    }
    console.log('login page: desktop and mobile pass');
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
