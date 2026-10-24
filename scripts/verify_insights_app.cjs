// Read-only browser checks for the React dashboard. All addresses and credentials
// are supplied privately; screenshots are optional and never stored in the repo.
const { chromium } = require('playwright-core');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const base = process.env.INSIGHTS_BASE_URL || 'http://localhost:3100';
const username = process.env.INSIGHTS_ADMIN_USERNAME;
const password = process.env.INSIGHTS_ADMIN_PASSWORD;
const names = { overview: '전체 현황', fortune: '오늘의 운세', restaurants: '맛집', shuttle: '셔틀', products: '상품·탐색', revenue: '수익', quality: '참여·품질' };
let stage = 'setup';
(async () => {
  assert(username && password, 'Administrator credentials are required through private environment variables');
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'], ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}) });
  try {
    const anonymous = await browser.newContext();
    for (const route of ['/insights/overview', '/api/reports/overview', '/api/reports/fortune-users']) {
      const response = await anonymous.request.get(new URL(route, base).href);
      assert.equal(response.status(), 401, 'Anonymous access must be denied');
      assert.match(response.headers()['cache-control'], /no-store/);
    }
    await anonymous.close();
    const context = await browser.newContext({ httpCredentials: { username, password, origin: new URL(base).origin }, acceptDownloads: true });
    const page = await context.newPage(), errors = [];
    page.on('pageerror', () => errors.push(true));
    const seenRequests = [];
    page.on('request', request => { if (request.url().includes('/api/reports/')) seenRequests.push(new URL(request.url()).pathname); });
    const waitReport = (report) => page.waitForResponse(response => new URL(response.url()).pathname === '/api/reports/' + report && response.ok(), { timeout: 90000 });
    for (const width of [1440, 390, 320]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const report of Object.keys(names)) {
        stage = `${width}: ${report}`;
        const pending = waitReport(report);
        await page.goto(new URL('/insights/' + report, base).href);
        const response = await pending;
        const payload = await response.json();
        assert.equal(payload.report, report);
        assert.match(response.headers()['cache-control'], /no-store/);
        await page.locator('.skeleton-report').waitFor({ state: 'detached' });
        assert.equal(await page.locator('h1').count(), 1);
        assert.equal(await page.locator('.error-state').count(), 0);
        await page.waitForFunction(() => !document.querySelector('.chart-placeholder'));
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Page overflows viewport');
        if (report === 'overview') {
          const cards = await page.locator('.metric-value').allTextContents();
          for (const [i, key] of ['menu_users', 'fortune_users', 'restaurant_users', 'shuttle_users', 'clicked_users'].entries()) assert.equal(cards[i].replace(/[^0-9]/g, ''), String(payload.data.current[key]));
          const options = page.locator('.chart-options button');
          if (await options.count() > 1) { await options.nth(1).click(); assert.equal(await options.nth(1).getAttribute('aria-pressed'), 'true'); }
          await page.getByRole('button', { name: '표 보기', exact: true }).first().click();
          await page.locator('.trend-table').first().waitFor();
          assert.equal(await page.getByRole('button', { name: '표 보기', exact: true }).first().getAttribute('aria-pressed'), 'true');
          await page.getByRole('button', { name: '차트 보기', exact: true }).first().click();
          await page.locator('.trend-table').waitFor({ state: 'detached' });
          await page.locator('.source summary').first().click();
          if (payload.data.daily.length) await page.locator('.source table').first().waitFor();
          if (width === 1440) {
            const refreshed = page.waitForResponse(response => new URL(response.url()).pathname === '/api/reports/overview' && new URL(response.url()).searchParams.get('refresh') === 'true');
            await page.getByRole('button', { name: '새로고침', exact: true }).click();
            assert((await refreshed).ok());
            await page.getByRole('button', { name: '새로고침', exact: true }).waitFor();
          }
        }
        if (report === 'fortune') {
          assert(!seenRequests.includes('/api/reports/fortune-users'), 'Personal data loaded before explicit request');
          if (width === 1440) {
            const personalResponse = waitReport('fortune-users');
            await page.locator('.personal-toggle').click();
            const personal = await (await personalResponse).json();
            assert(Array.isArray(personal.data));
            for (const row of personal.data) assert.deepEqual(Object.keys(row).sort(), ['birth_year', 'birthplace', 'last_view_at', 'sex']);
            await page.locator('.personal-toggle').click();
            seenRequests.splice(0, seenRequests.length);
          }
        }
        if (report === 'products') {
          stage = `${width}: product search`;
          await page.getByRole('textbox', { name: '상품 검색' }).fill('synthetic-no-product-match');
          await page.getByRole('status').filter({ hasText: '상품 0개' }).waitFor();
          assert(await page.getByRole('button', { name: '↓ CSV' }).isDisabled());
          await page.getByRole('textbox', { name: '상품 검색' }).fill('');
          stage = `${width}: product sorting and exposure filter`;
          await page.getByLabel('상품 정렬').selectOption('rate');
          await page.getByLabel('최소 노출 사용자').fill('1');
          if (width === 1440 && !await page.getByRole('button', { name: '↓ CSV' }).isDisabled()) {
            stage = `${width}: product CSV download`;
            const downloadEvent = page.waitForEvent('download');
            await page.getByRole('button', { name: '↓ CSV' }).click();
            const download = await downloadEvent;
            assert.equal(download.suggestedFilename(), 'cnu-insights-products.csv');
            // Read the browser-owned blob directly: sandboxed Chromium may keep
            // its temporary download files in a separate filesystem namespace.
            const content = await page.evaluate(async url => (await fetch(url)).text(), download.url());
            assert(content.includes('상품 ID'));
          }
        }
        if (process.env.INSIGHTS_SCREENSHOT_DIR && (report === 'overview' || report === 'products' || report === 'fortune')) {
          await fs.mkdir(process.env.INSIGHTS_SCREENSHOT_DIR, { recursive: true });
          await page.evaluate(() => { document.activeElement?.blur(); window.scrollTo(0, 0); });
          await page.screenshot({ path: path.join(process.env.INSIGHTS_SCREENSHOT_DIR, `insights-${report}-${width}.png`), fullPage: true });
        }
      }
      console.log(`PASS: all reports and controls at ${width}px`);
    }
    stage = 'initial overview before period change';
    await page.setViewportSize({ width: 1440, height: 1000 });
    const initialOverview = waitReport('overview');
    await page.goto(new URL('/insights/overview', base).href);
    await initialOverview;
    stage = '30-day preset';
    const periodResponse = waitReport('overview');
    await page.getByRole('link', { name: '최근 30일', exact: true }).click();
    const period = await (await periodResponse).json();
    assert.equal((Date.parse(period.end_date) - Date.parse(period.start_date)) / 86400000, 29);
    const selected = new URL(page.url()).search;
    stage = 'navigation preserves period';
    await page.getByRole('navigation', { name: '보고서 탐색' }).getByRole('link', { name: '셔틀', exact: true }).click();
    await page.waitForURL(url => url.pathname === '/insights/shuttle');
    assert.equal(new URL(page.url()).search, selected);
    stage = 'direct detail reload';
    const direct = waitReport('shuttle'); await page.reload(); await direct;
    stage = 'custom period validation and correction';
    await page.getByLabel('시작일', { exact: true }).fill(period.end_date);
    await page.getByLabel('종료일', { exact: true }).fill(period.start_date);
    await page.getByRole('button', { name: '조회', exact: true }).click();
    assert.equal(await page.getByLabel('종료일', { exact: true }).evaluate(input => input.checkValidity()), false);
    const corrected = new Date(period.start_date); corrected.setUTCDate(corrected.getUTCDate() - 1);
    await page.getByLabel('시작일', { exact: true }).fill(corrected.toISOString().slice(0, 10));
    const custom = waitReport('shuttle');
    await page.getByRole('button', { name: '조회', exact: true }).click();
    const customData = await (await custom).json();
    assert.equal((Date.parse(customData.end_date) - Date.parse(customData.start_date)) / 86400000, 1);
    const todayRequest = waitReport('shuttle');
    await page.getByRole('link', { name: '오늘', exact: true }).click();
    const todayData = await (await todayRequest).json(); assert.equal(todayData.start_date, todayData.end_date);
    const allRequest = waitReport('shuttle');
    await page.getByRole('link', { name: '전체 기간', exact: true }).click();
    const allData = await (await allRequest).json(); assert.equal(allData.start_date, null); assert.equal(allData.end_date, null);
    stage = 'error and retry';
    await page.route('**/api/reports/restaurants?*', route => route.fulfill({ status: 503, contentType: 'application/json', body: '{"error":"synthetic"}' }));
    await page.goto(new URL('/insights/restaurants?all_time=true', base).href);
    await page.locator('.error-state').waitFor();
    await page.unroute('**/api/reports/restaurants?*');
    const retried = waitReport('restaurants'); await page.getByRole('button', { name: '다시 불러오기' }).click(); await retried;
    await page.locator('.error-state').waitFor({ state: 'detached' });
    assert.equal(errors.length, 0, 'Browser runtime errors detected');
    console.log('PASS: all 7 reports at 1440/390/320px; live counts, authorization, chart controls, lazy personal data, product filters/CSV, refresh, period navigation, direct reload, and error retry.');
  } finally { await browser.close(); }
})().catch(error => { console.error('Insights browser verification failed at ' + stage + ': ' + String(error.message).split('\n')[0].replace(/https?:\/\/\S+/g, '<private-url>')); process.exitCode = 1; });
