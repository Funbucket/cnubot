// Read-only check of the shared experiment list and detail UI.
const {chromium} = require('playwright-core');
const base = process.env.ADMIN_BASE_URL || 'http://localhost';
const expected = [],expectedStates=[];
for(let i=2;i<process.argv.length;i++){
 const flag=process.argv[i],value=process.argv[++i];
 if(!value||!['--expect-running-name','--expect-status'].includes(flag))throw Error('Use --expect-running-name <name> or --expect-status <name>=<label>');
 if(flag==='--expect-running-name')expected.push(value);
 else {const split=value.lastIndexOf('=');if(split<1)throw Error('Expected name=status');expectedStates.push([value.slice(0,split),value.slice(split+1)]);}
}
let stage = 'setup';
async function verifySampleDesign(page, detail, type){
 const root=page.locator('#sample-design-results');
 const text=(await root.textContent()).replaceAll(',','');
 for(const label of ['Baseline','목표 효과','유의수준','검정력'])if(!text.includes(label))throw Error('Sample design input missing');
 if((await page.locator('#sample-design-plan').innerHTML())!==(await root.innerHTML()))throw Error('Results and plan sample design mismatch');
 if(type==='card'){
  const p=detail.experiment.protocol,sim=detail.sample_simulation?.details;
  if(p.baseline_rate!=null&&!text.includes((100*p.baseline_rate).toFixed(4)+'%'))throw Error('Baseline differs from protocol');
  if(!text.includes((100*p.alpha).toFixed(2)+'%')||!text.includes(String(p.total_users)))throw Error('Alpha or sample count differs from protocol');
  if(sim){
   if(sim.config_hash!==detail.experiment.config_hash)throw Error('Simulation is from another plan');
   for(const row of sim.scenarios)if(!text.includes((100*row.significance_probability).toFixed(2)+'%'))throw Error('Stored power missing');
  }
  if(p.purpose==='exploratory'&&!text.includes('역산한 수가 아님'))throw Error('Exploratory sample misrepresented');
 }else{
  const p=detail.analysis_plan;
  if(p?.mode==='exploratory_timebox'){
   if(!text.includes('폐기된 계획')||!text.includes('참고율')||!text.includes('필요 표본이 아님'))throw Error('Planning assumptions presented as current formal design');
   if(!text.includes(String(2*p.original_plan.min_sample_size))||!text.includes((100*p.original_plan.power).toFixed(2)+'%'))throw Error('Original sample inputs missing');
   for(const power of p.power_at_1200_proxy)if(!text.includes((100*power).toFixed(2)+'%'))throw Error('Current power scenarios missing');
  }
 }
 await page.getByRole('tab',{name:'분석 결과',exact:true}).click();
 const statistics=page.locator('#statistical-details');
 if(await statistics.count()&&await statistics.getAttribute('open')===null)await statistics.locator('summary').first().click();
 await root.waitFor();
 if(type==='button'){
  const original=root.locator('.original-sample-plan');
  if(await original.count()){
   await original.locator('summary').click();
   await original.locator('.plan-facts').waitFor();
  }
 }
 await page.getByRole('tab',{name:'설계·이력',exact:true}).click();
}
async function verifyComparison(page, groups, effect, population){
 const table=page.locator('#effect .comparison-table');
 if(await table.locator('tbody tr').count()!==groups.length)throw Error('Shared comparison rows missing');
 if(!(await table.locator('th').nth(2).textContent()).includes(population))throw Error('Comparison denominator mislabeled');
 for(let i=0;i<groups.length;i++){
  const cells=await table.locator('tbody tr').nth(i).locator('td').allTextContents(),g=groups[i];
  if(cells[1].replaceAll(',','')!==g.clicked+'명'||cells[2].replaceAll(',','')!==g.users+'명')throw Error('Comparison counts differ from API');
  if(cells[3]!== (g.users?(100*g.clicked/g.users).toFixed(2)+'%':'계산 대기'))throw Error('Comparison rate differs from API');
 }
 const graph=page.locator('#effect svg.chart');
 if(await graph.count()!==(effect?1:0))throw Error('Comparison chart missing or fabricated');
 if(effect){
  const aria=await graph.getAttribute('aria-label');
  for(const value of [effect.delta,effect.ci_low,effect.ci_high])if(!aria.includes((100*value).toFixed(2)+'%p'))throw Error('CI chart differs from API');
  const bounds=await graph.locator('.ci-interval').evaluate(el=>[Number(el.getAttribute('x1')),Number(el.getAttribute('x2'))]);
  const point=Number(await graph.locator('.ci-estimate').getAttribute('cx'));
  const zero=Number(await graph.locator('.ci-zero').first().getAttribute('x1'));
  if(![...bounds,point,zero].every(Number.isFinite)||bounds[0]<35||bounds[1]>665||point<bounds[0]||point>bounds[1])throw Error('CI chart clipped or invalid');
  if(effect.delta<0&&point>=zero||effect.delta>0&&point<=zero)throw Error('Effect direction reversed');
 }
}
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
      for(const [name,status] of expectedStates){
        const row=page.locator('#rows tr').filter({hasText:name});await row.waitFor();
        if((await row.locator('td').nth(1).innerText()).trim()!==status)throw Error('Expected lifecycle status mismatch');
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
      const runningRows = page.locator('#rows tr:has(button)');
      if (await runningRows.count() === 0) {
        const empty = page.locator('#rows td.empty');
        if (await empty.count() !== 1 || (await empty.innerText()).trim() !== '검색 조건에 맞는 실험이 없습니다.') throw Error('Running filter empty state missing');
      }
      for (const row of await runningRows.all()) {
        if (await row.locator('td').count() !== 8) throw Error('Wrong running list cell count');
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
        const participantLabel = await page.locator('#detail').getAttribute('data-terminal') === 'true' ? '최종 배정 사용자' : '현재 참여자';
        if ((await page.locator('#counts .metric-label').first().textContent()).trim() !== participantLabel) throw Error('Detail participant metric inconsistent');
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
          await verifySampleDesign(page,detail,'card');
          if(detail.followup_schedule&&detail.experiment.status==='draft'){if(detail.experiment.started_at||!(await page.locator('#next').textContent()).includes('전환 대기'))throw Error('Followup started early or waiting state missing');if(await page.locator('#lifecycle button').isVisible().catch(()=>false))throw Error('Early start action exposed');}
          if(detail.run){const r=detail.run.result;await verifyComparison(page,[{users:r.mature.A,clicked:r.clicks.A},{users:r.mature.B,clicked:r.clicks.B}],r.effect,detail.experiment.protocol.observation_hours+'시간 관찰 완료 사용자');}
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
          await verifySampleDesign(page,detail,'button');
          if(detail.analysis){const rows=detail.variants.map(v=>detail.analysis.variants.find(r=>r.variant_key===v.variant_key));await verifyComparison(page,rows.map(r=>({users:r.exposed_users,clicked:r.clicked_users})),rows.find(r=>r.variant_key==='treatment')?.comparison,'버튼 노출 사용자');}
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
