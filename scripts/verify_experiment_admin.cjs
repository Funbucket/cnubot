// Read-only check of the shared experiment list and detail UI.
const {chromium} = require('playwright-core');
const base = process.env.ADMIN_BASE_URL || 'http://localhost';
const expected = [];
for (let i = 2; i < process.argv.length; i++) {
  if (process.argv[i] !== '--expect-running-name' || !process.argv[i + 1]) {
    throw Error('Use --expect-running-name <experiment name>');
  }
  expected.push(process.argv[++i]);
}
let stage = 'setup';
(async () => {
  if (!process.env.ADMIN_USERNAME || !process.env.ADMIN_PASSWORD) {
    throw Error('Administrator credentials must be provided through environment variables');
  }
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox'],
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? {executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE} : {})});
  try {
    const context = await browser.newContext({httpCredentials: {
      username: process.env.ADMIN_USERNAME, password: process.env.ADMIN_PASSWORD}});
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', () => errors.push(true));
    for (const width of [1440, 390]) {
      stage = `${width}: shared list`;
      await page.setViewportSize({width, height: 950});
      await page.goto(new URL('/admin/experiments', base).href);
      await page.locator('#rows button').first().waitFor();
      await page.waitForFunction(() => !document.querySelector('#message').textContent.includes('불러오지 못'));
      for (const name of expected) {
        const row = page.locator('#rows tr').filter({hasText: name});
        await row.waitFor();
        const text = await row.innerText();
        if ((await row.locator('td').nth(1).innerText()).trim() !== '모집 중') throw Error('Expected experiment is not running');
      }
      const headers = await page.locator('#list th').allTextContents();
      if (headers.join('|') !== '이름|상태|현재 참여자|모집 계획|관찰 완료|모집 마감|품질|다음 행동') throw Error('List column semantics mismatch');
      for (const row of await page.locator('#rows tr').all()) {
        const cells = row.locator('td');
        if (await cells.count() !== 8) throw Error('Wrong list cell count');
        if ((await cells.nth(2).innerText()).includes('/')) throw Error('Participant count mixed with plan');
        if ((await cells.nth(4).innerText()).includes('KST')) throw Error('Deadline in observation column');
      }
      await page.locator('#filter').selectOption('running');
      for (const row of await page.locator('#rows tr').all()) {
        if ((await row.locator('td').nth(1).innerText()).trim() !== '모집 중') throw Error('Running filter and labels disagree');
      }
      for (const name of expected) {
        if (await page.locator('#rows tr').filter({hasText:name}).count() !== 1) throw Error('Running experiment missing from filter');
      }
      await page.locator('#filter').selectOption('');
      const entries = await page.locator('#rows button').evaluateAll(buttons => buttons.map(button => {
        const match = button.getAttribute('onclick').match(/openDetail\((\d+),'(card|button)'\)/);
        if (!match) throw Error('List entry does not use the shared detail');
        return {id: match[1], type: match[2], name: button.textContent, status: button.closest('tr').children[1].textContent.trim()};
      }));
      for (const entry of entries) {
        stage = `${width}: ${entry.type} shared detail`;
        await page.locator('#rows button').filter({hasText: entry.name}).click();
        await page.waitForFunction(name => document.querySelector('#title').textContent === name, entry.name);
        if ((await page.locator('#counts .metric-label').first().textContent()).trim() !== '현재 참여자') throw Error('Detail participant metric inconsistent');
        if ((await page.locator('#status').textContent()).trim() !== entry.status) throw Error('List and detail status mismatch');
        const hash = await page.evaluate(() => location.hash);
        const expectedHash = '#experiment/' + (entry.type === 'button' ? 'button/' : '') + entry.id;
        if (hash !== expectedHash) throw Error('Detail namespace mismatch');
        for (const [label, selector] of [['진행 현황', '#overview'], ['분석 결과', '#results'],
          ['데이터 품질', '#quality'], ['경험 미리보기', '#preview'], ['설계·이력', '#plan']]) {
          await page.getByRole('tab', {name: label, exact: true}).click();
          await page.locator(selector).waitFor();
        }
        const path = entry.type === 'button' ? `/admin/api/button-experiments/${entry.id}` : `/admin/api/experiments/${entry.id}/results`;
        const [response] = await Promise.all([page.waitForResponse(r => new URL(r.url()).pathname === path),
          page.getByRole('button', {name: '현황 새로고침', exact: true}).click()]);
        if (!response.ok()) throw Error('Detail refresh failed');
        if (entry.type === 'card') {
          const detail = await response.json();
          if (detail.quality_review?.details?.scope === 'basic_instrumentation') {
            if (detail.quality_review.details.formal_pass !== false || detail.run?.result?.quality_passed || detail.run?.result?.decision_ready) throw Error('Partial approval promoted to formal pass');
            if (!(await page.locator('#next').textContent()).includes('부분 승인')) throw Error('Partial approval missing from summary');
            const diagnostics = await page.locator('#diagnostics').textContent();
            if (!diagnostics.includes('기본 계측 부분 승인') || !diagnostics.includes('보류:')) throw Error('Approval scope missing from quality tab');
            if (!(await page.locator('#audit-list').textContent()).includes('기본 계측 부분 승인')) throw Error('Approval missing from history');
            const analysis = await page.locator('#quality-analysis').textContent();
            if (!analysis.includes('A/A 기본 계측 분석 결과') || !analysis.includes('부분 승인') || !analysis.includes('보류')) throw Error('Quality review missing from analysis results');
            if (await page.locator('#quality-analysis tbody tr').count() !== 7) throw Error('Incomplete analysis review table');
            const evidence = detail.quality_review.details.evidence;
            if (!analysis.replaceAll(',','').includes(String(evidence.delivered_bundles))) throw Error('Exposure evidence missing from analysis');
            await page.getByRole('tab', {name:'분석 결과',exact:true}).click();
            await page.locator('#quality-analysis').waitFor();
            await page.getByRole('tab', {name:'설계·이력',exact:true}).click();

          }
        }
        if (entry.type === 'button') {
          if ((await page.locator('#quality-analysis').textContent()).trim()) throw Error('A/A review leaked into button results');
          const detail = await response.json();
          if (detail.analysis_plan?.mode === 'exploratory_timebox') {
            const counts = await page.locator('#counts').textContent();
            const note = await page.locator('#schedule-note').textContent();
            if (!counts.replaceAll(',','').includes(String(detail.analysis_plan.planned_total_users)) || !counts.includes('예상')) throw Error('Exploration budget missing');
            if (!note.includes('7일') || !note.includes('종료')) throw Error('Timebox missing');
            if (detail.analysis?.quality?.decision_ready) throw Error('Exploratory automatic winner');
            if (!(await page.locator('#plan-facts').textContent()).includes('사후 개정')) throw Error('Amendment disclosure missing');
          }
        }

        if (await page.locator('#tab-plan').getAttribute('aria-selected') !== 'true') throw Error('Refresh lost selected tab');
        stage = `${width}: ${entry.type} direct detail reload`;
        await page.reload();
        await page.waitForFunction(name => document.querySelector('#title').textContent === name, entry.name);
        if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw Error('Page overflow');
        await page.getByRole('button', {name: '← 실험 목록', exact: true}).click();
        await page.locator('#rows button').first().waitFor();
      }
      if (errors.length) throw Error('Browser JavaScript errors');
      console.log(`Admin experiment UI ${width}px: passed (${entries.length} entries)`);
    }
  } finally {
    await browser.close();
  }
})().catch(() => { console.error(`Admin experiment UI verification failed at ${stage}`); process.exitCode = 1; });
