// Read-only end-to-end checks of the experiment detail navigation and scorecard.
const { chromium } = require('playwright-core');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const base = process.env.ADMIN_BASE_URL || 'http://localhost:3100';
let stage = 'setup';
(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'], ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}) });
  try {
    const context = await browser.newContext({ httpCredentials: { username: process.env.ADMIN_USERNAME, password: process.env.ADMIN_PASSWORD, origin: new URL(base).origin } });
    const page = await context.newPage(), errors = [];
    page.setDefaultTimeout(35_000);
    page.on('pageerror', () => errors.push(true));
    for (const width of [1440, 390, 320]) {
      stage = `${width}: common experiment list`;
      await page.setViewportSize({ width, height: 1000 });
      await page.goto(new URL('/admin/experiments', base).href);
      await page.locator('#rows button').first().waitFor();
      const entries = await page.locator('#rows button').evaluateAll(buttons => buttons.map(button => {
        const match = button.getAttribute('onclick').match(/openDetail\((\d+),'(card|button)'\)/);
        return { id: Number(match[1]), type: match[2], name: button.textContent };
      }));
      for (const entry of entries) {
        stage = `${width}: ${entry.type} default result and scorecard`;
        const endpoint = entry.type === 'button' ? `/admin/api/button-experiments/${entry.id}` : `/admin/api/experiments/${entry.id}/results`;
        const request = page.waitForResponse(response => new URL(response.url()).pathname === endpoint && response.ok());
        await page.locator('#rows button').filter({ hasText: entry.name }).click();
        const payload = await (await request).json();
        await page.waitForFunction(name => document.querySelector('#title').textContent === name && document.querySelector('#detail').dataset.ux === 'ready', entry.name);
        await page.evaluate(() => document.fonts.ready);
        const data = entry.type === 'button' ? payload : payload.experiment;
        const hasAnalysis = entry.type === 'button' ? Boolean(payload.analysis) : Boolean(payload.run);
        await page.waitForFunction(view => document.querySelector('#detail').dataset.activeView === view, hasAnalysis ? 'results' : 'overview');
        assert.equal(new URL(page.url()).searchParams.get('view'), hasAnalysis ? 'results' : 'overview');
        assert.equal(await page.locator('#detail [role=tab]').count(), 6);
        assert.equal(await page.locator('#overview #operations').count(), 0);
        assert.equal(await page.locator('#manage #operations').count(), 1);
        const terminal = ['completed', 'decided', 'stopped'].includes(data.status);
        assert.equal(await page.locator('#detail').getAttribute('data-terminal'), String(terminal));
        if (terminal) {
          await page.locator('#experiment-completed-report').waitFor();
          assert.equal(await page.locator('#experiment-review-details').getAttribute('open'), null, 'Detailed notes should be collapsed initially');
          assert.equal(await page.locator('#counts').isVisible(), false, 'Overview counts must not duplicate the result table');
          assert(!(await page.locator('#counts .metric:last-child b').innerText()).includes('판단 대기'));
          assert(!(await page.locator('#gates').textContent()).includes('수집 중'));
          if (entry.type === 'button') {
            assert((await page.locator('#results').innerText()).length < 550, 'Default results contain too much explanatory prose');
            await page.locator('#experiment-review-details > summary').click();
            if (data.analysis_plan?.mode === 'exploratory_timebox') assert((await page.locator('#experiment-completed-report').innerText()).includes('자동 승자 판정 대상 아님'));
            await page.locator('#experiment-review-details > summary').click();
            await page.getByRole('tab', { name: '데이터 품질', exact: true }).click();
            assert.equal(await page.locator('[data-check="배정 균형 (SRM)"]').getAttribute('data-state'), payload.analysis.srm.status === 'pass' ? 'pass' : payload.analysis.srm.status === 'fail' ? 'fail' : 'limited');
            assert.equal(await page.locator('[data-check="클릭 출처·수집 완전성"]').getAttribute('data-state'), 'limited');
            await page.getByRole('tab', { name: '분석 결과', exact: true }).click();
          }
          if (entry.type === 'card' && payload.history.some(h => h.action === 'decision')) {
            const decision = payload.history.find(h => h.action === 'decision');
            await page.locator('#experiment-review-details > summary').click();
            assert((await page.locator('#experiment-completed-report').innerText()).includes(decision.reason));
            if (decision.details.successor_id) {
              await page.locator('.experiment-successor').click();
              await page.waitForFunction(id => document.querySelector('#detail').dataset.ux === 'ready' && document.querySelector('#title').textContent && typeof current !== 'undefined' && current.experiment.id === id, decision.details.successor_id);
              await page.goBack();
              await page.waitForFunction(id => typeof current !== 'undefined' && current.experiment.id === id && document.querySelector('#detail').dataset.terminal === 'true', entry.id);
            } else await page.locator('#experiment-review-details > summary').click();
          }
        } else assert.equal(await page.locator('#experiment-completed-report').isVisible(), false);
        if (hasAnalysis) {
          const rows = entry.type === 'button' ? payload.variants.map(v => payload.analysis.variants.find(row => row.variant_key === v.variant_key)) : [{ clicked_users: payload.run.result.clicks.A, exposed_users: payload.run.result.mature.A }, { clicked_users: payload.run.result.clicks.B, exposed_users: payload.run.result.mature.B }];
          const cells = page.locator('.experiment-scorecard tbody td');
          for (let i = 0; i < 2; i++) {
            const expected = rows[i].exposed_users ? (100 * rows[i].clicked_users / rows[i].exposed_users).toFixed(2) + '%' : '계산 대기';
            assert.equal(await cells.nth(i + 1).locator('strong').innerText(), expected);
          }
          const effect = entry.type === 'button' ? rows.find(row => row.variant_key === 'treatment')?.comparison : payload.run.result.effect;
          assert.equal(await cells.nth(3).locator('strong').innerText(), effect ? (100 * effect.delta).toFixed(2) + '%p' : '계산 대기');
          if (!effect) assert.equal(await page.locator('#effect svg.chart').count(), 0, 'Missing analysis must not fabricate an interval');
          if (data.protocol?.purpose === 'exploratory' || data.analysis_plan?.mode === 'exploratory_timebox') await page.locator('#experiment-interpretation').filter({ hasText: '탐색' }).waitFor();
        }
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Detail viewport overflow');
        if (process.env.ADMIN_SCREENSHOT_DIR && (entry.id === 3 && entry.type === 'card' || entry.type === 'button')) {
          await fs.mkdir(process.env.ADMIN_SCREENSHOT_DIR, { recursive: true });
          await page.evaluate(() => window.scrollTo(0, 0));
          await page.screenshot({ path: path.join(process.env.ADMIN_SCREENSHOT_DIR, `detail-${entry.type}-${width}.png`), fullPage: true });
        }
        stage = `${width}: ${entry.type} keyboard, operations and deep-link persistence`;
        await page.locator('#tab-results').focus();
        await page.keyboard.press('End');
        assert.equal(await page.locator('#tab-manage').getAttribute('aria-selected'), 'true');
        assert.equal(await page.locator('#operations').getAttribute('open') !== null, true);
        await page.getByRole('tab', { name: '데이터 품질', exact: true }).click();
        const shared = page.url();
        await page.reload();
        await page.waitForFunction(() => document.querySelector('#detail').dataset.activeView === 'quality');
        assert.equal(page.url(), shared, 'Direct refresh lost the selected tab');
        await page.getByRole('tab', { name: '설계·이력', exact: true }).click();
        const refresh = page.waitForResponse(response => new URL(response.url()).pathname === endpoint && response.ok());
        await page.getByRole('button', { name: '현황 새로고침', exact: true }).click();
        await refresh;
        await page.waitForFunction(() => document.querySelector('#tab-plan').getAttribute('aria-selected') === 'true');
        assert.equal(new URL(page.url()).searchParams.get('view'), 'plan');
        // All operator buttons remain untouched; go back using browser history.
        stage = `${width}: ${entry.type} browser history`;
        await page.goBack();
        await page.locator('#rows button').first().waitFor();
        assert.equal(new URL(page.url()).hash, '');
        if (terminal) assert(!(await page.locator('#rows tr').filter({ hasText: entry.name }).locator('td').nth(6).innerText()).includes('판단 대기'));
      }
      console.log(`PASS: detail scorecard, empty states, six tabs, keyboard, refresh and browser back at ${width}px`);
    }
    assert.equal(errors.length, 0, 'Browser runtime errors detected');
    console.log('PASS: experiment detail UX; no operational experiment actions were invoked.');
  } finally { await browser.close(); }
})().catch(error => { console.error(`Experiment detail UX failed at ${stage}: ${String(error.message).split('\n')[0].replace(/https?:\/\/\S+/g, '<private-url>')}`); process.exitCode = 1; });
