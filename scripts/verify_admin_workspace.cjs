// Read-only UI checks. Do not save settings or change operational experiments.
const { chromium } = require('playwright-core');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const base = process.env.ADMIN_BASE_URL || process.env.INSIGHTS_BASE_URL || 'http://localhost:3100';
const origin = new URL(base).origin;
let stage = 'setup';
(async () => {
  assert(process.env.INSIGHTS_ADMIN_USERNAME && process.env.INSIGHTS_ADMIN_PASSWORD);
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'], ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}) });
  try {
    const anonymous = await browser.newContext();
    for (const route of ['/admin/recommendations', '/admin/experiments', '/admin/events', '/admin/restaurants', '/admin/promotion-settings']) {
      const response = await anonymous.request.get(new URL(route, base).href);
      assert.equal(response.status(), 401, 'Management page exposed without administrator authentication');
    }
    await anonymous.close();
    const context = await browser.newContext({ httpCredentials: { username: process.env.INSIGHTS_ADMIN_USERNAME, password: process.env.INSIGHTS_ADMIN_PASSWORD, origin } });
    const page = await context.newPage(), errors = [];
    page.setDefaultTimeout(45_000);
    page.on('pageerror', () => errors.push(true));
    const settingsURL = new URL('/admin/promotion-settings', base).href;
    const before = await context.request.get(settingsURL);
    assert.equal(before.status(), 200);
    const settings = await before.json();
    stage = 'cross-origin write guard';
    let denied = await context.request.put(settingsURL, { headers: { origin: 'https://other.example.com', 'x-promotion-editor': '1' }, data: {} });
    assert.equal(denied.status(), 403);
    stage = 'backend editor write guard';
    // The empty body cannot validate as settings even if an editor guard regresses.
    denied = await context.request.put(settingsURL, { headers: { origin }, data: {} });
    assert.equal(denied.status(), 403);
    for (const width of [1440, 390, 320]) {
      await page.setViewportSize({ width, height: 1000 });
      stage = `${width}: report workspace navigation`;
      await page.goto(new URL('/insights/overview', base).href);
      await page.getByRole('navigation', { name: '관리자 메뉴' }).getByRole('link', { name: '상품·버튼 관리', exact: true }).click();
      await page.waitForURL(url => url.pathname === '/admin/recommendations');
      stage = `${width}: product settings and preview`;
      await page.waitForFunction(() => !document.querySelector('#fields').disabled);
      await page.waitForFunction(() => document.querySelector('#preview').childElementCount > 0);
      assert.equal(await page.locator('#save').isDisabled(), true);
      await page.locator('#pickLiving').click();
      assert.equal(await page.locator('#pickLiving').getAttribute('aria-pressed'), 'true');
      await page.locator('#pickFood').click();
      if (width === 1440) {
        await page.locator('#buttonSettings summary').click();
        const input = page.getByLabel('보이는 버튼명', { exact: true }), original = await input.inputValue();
        await input.fill('임시 확인');
        assert.equal(await page.locator('#save').isDisabled(), false);
        await input.fill(original);
        assert.equal(await page.locator('#save').isDisabled(), true);
      }
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Product editor viewport overflow');
      stage = `${width}: experiment menu and list`;
      await page.getByRole('navigation', { name: '관리자 메뉴' }).getByRole('link', { name: '실험실', exact: true }).click();
      await page.locator('#rows button').first().waitFor();
      assert.equal(new URL(page.url()).origin, origin);
      stage = `${width}: event collection examples`;
      await page.getByRole('navigation', { name: '관리자 메뉴' }).getByRole('link', { name: '이벤트 수집', exact: true }).click();
      await page.locator('#event-select option').first().waitFor({ state: 'attached' });
      assert((await page.locator('#json').innerText()).length > 30);
      const values = await page.locator('#event-select option').evaluateAll(options => options.map(option => option.value));
      if (values.length > 1) await page.locator('#event-select').selectOption(values[1]);
      JSON.parse(await page.locator('#json').innerText());
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Event documentation viewport overflow');
      stage = `${width}: restaurant catalog and preview`;
      await page.getByRole('navigation', { name: '관리자 메뉴' }).getByRole('link', { name: '맛집 관리', exact: true }).click();
      await page.waitForFunction(() => !document.querySelector('#save').disabled);
      const preview = page.waitForResponse(response => new URL(response.url()).pathname === '/admin/restaurants/preview' && response.ok());
      await page.locator('#inspect').click();
      await preview;
      await page.locator('#preview > *').first().waitFor();
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Restaurant editor viewport overflow');
      await page.reload();
      await page.waitForFunction(() => !document.querySelector('#save').disabled);
      await page.evaluate(() => document.fonts.ready);
      assert.equal(new URL(page.url()).origin, origin);
      const active = page.getByRole('navigation', { name: '관리자 메뉴' }).locator('[aria-current="page"]');
      assert.equal(await active.innerText(), '맛집 관리');
      const bounds = await active.boundingBox();
      assert(bounds && bounds.x >= 0 && bounds.x + bounds.width <= width + 1, 'Current management section is outside navigation viewport');
      if (process.env.ADMIN_SCREENSHOT_DIR) {
        await fs.mkdir(process.env.ADMIN_SCREENSHOT_DIR, { recursive: true });
        await page.screenshot({ path: path.join(process.env.ADMIN_SCREENSHOT_DIR, `restaurants-${width}.png`), fullPage: false });
      }
      stage = `${width}: return to React insights`;
      await page.getByRole('navigation', { name: '관리자 메뉴' }).getByRole('link', { name: '인사이트', exact: true }).click();
      await page.waitForURL(url => url.pathname === '/insights/overview');
      await page.getByRole('heading', { name: '전체 현황', exact: true }).waitFor();
      console.log(`PASS: workspace menus, settings draft, previews, events, and reload at ${width}px`);
    }
    stage = 'legacy insights bookmarks';
    await page.goto(new URL('/admin/insights?start_date=2026-10-01&end_date=2026-10-07#fortune', base).href);
    await page.waitForURL(url => url.pathname === '/insights/fortune');
    assert.equal(new URL(page.url()).searchParams.get('start_date'), '2026-10-01');
    await page.goto(new URL('/admin/insights#https://other.example.com', base).href);
    await page.waitForURL(url => url.pathname === '/insights/overview');
    assert.equal(new URL(page.url()).origin, origin);
    const after = await context.request.get(settingsURL);
    assert.deepEqual(await after.json(), settings, 'Operational settings changed during read-only verification');
    assert.equal(errors.length, 0, 'Browser runtime errors detected');
    console.log('PASS: full administrator navigation; operational settings unchanged; no browser runtime errors.');
  } finally { await browser.close(); }
})().catch(error => { console.error('Admin workspace verification failed at ' + stage + ': ' + String(error.message).split('\n')[0].replace(/https?:\/\/\S+/g, '<private-url>')); process.exitCode = 1; });
