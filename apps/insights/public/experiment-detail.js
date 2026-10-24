/* Presentation only. Existing APIs, analysis, and operational handlers remain authoritative. */
(() => {
  "use strict";
  const root = document.querySelector("#detail");
  if (!root || typeof window.openDetail !== "function") return;
  const $ = (selector) => root.querySelector(selector);
  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const number = (value) => value == null || !Number.isFinite(Number(value)) ? "—" : Number(value).toLocaleString("ko-KR");
  const points = (value) => Number.isFinite(value) ? (100 * value).toFixed(2) + "%p" : "계산 대기";
  const percentage = (clicks, users) => users > 0 ? (100 * clicks / users).toFixed(2) + "%" : "계산 대기";
  const state = () => typeof current === "undefined" ? null : current;
  const views = new Set(["results", "overview", "quality", "preview", "plan", "manage"]);
  const original = { open: window.openDetail, back: window.back, tab: window.tab, list: window.renderList, comparison: window.clickComparison, chart: window.effectChart, preview: window.showPreview };
  let navigatingHistory = false, renderingOpen = 0, selectedView = "overview", lastRendered = null;

  function element(tag, className, html) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (html) node.innerHTML = html;
    return node;
  }
  function matchDetail(url = new URL(location.href)) {
    const match = url.hash.match(/^#experiment\/(?:(button)\/)?(\d+)$/);
    return match ? { id: Number(match[2]), type: match[1] ? "button" : "card" } : null;
  }
  function writeView(view) {
    const url = new URL(location.href);
    if (!matchDetail(url)) return;
    url.searchParams.set("view", view);
    history.replaceState(history.state, "", url);
  }
  function defaultView(data) {
    return data.type === "button" ? data.experiment.analysis ? "results" : "overview" : data.run ? "results" : "overview";
  }
  function annotateList() {
    const entries = [...(typeof designs === "undefined" ? [] : designs).map(d => ({ type: "card", experiment: d, run: d.result ? { result: d.result } : null, quality_review: d.quality_review })), ...(typeof buttonExperiments === "undefined" ? [] : buttonExperiments).map(d => ({ type: "button", experiment: d }))];
    document.querySelectorAll("#rows tr").forEach(row => {
      const match = row.querySelector("button[onclick]")?.getAttribute("onclick").match(/openDetail\((\d+),'(card|button)'\)/);
      const data = match && entries.find(d => d.type === match[2] && d.experiment.id === Number(match[1]));
      if (!data) return;
      const report = globalThis.CnuExperimentReport.build(data);
      if (!report.terminal) return;
      const cells = row.querySelectorAll("td");
      cells[6].textContent = report.quality.label;
      cells[6].title = "배정 균형·수집 완전성·운영 품질을 상세에서 따로 확인하세요.";
      cells[7].textContent = data.experiment.status === "stopped" ? "중단 근거와 해석 제한 검토" : report.exploratory ? "종료된 탐색 결과 검토" : "종료 결과와 결정 기록 검토";
    });
  }
  window.renderList = (...args) => { original.list(...args); annotateList(); };
  annotateList();

  // Reuse all original IDs so the existing renderer and mutation guards continue to run.
  const heading = $(".detail-heading"), toolbar = $(".detail-toolbar"), summary = $(".detail-summary");
  const counts = $("#counts"), hypothesis = $("#hypothesis"), resultNote = $("#result-note");
  const anchors = { counts: document.createComment("counts"), summary: document.createComment("summary"), hypothesis: document.createComment("hypothesis"), note: document.createComment("note") };
  counts.before(anchors.counts); summary.before(anchors.summary); hypothesis.before(anchors.hypothesis); resultNote.before(anchors.note);
  toolbar.classList.add("experiment-breadcrumb");
  const refresh = $("#refresh");
  const headerActions = element("div", "experiment-header-actions", '<button type="button" class="secondary" data-detail-action="copy">링크 복사</button><button type="button" class="secondary" data-detail-tab="manage">운영 관리</button><details class="experiment-more"><summary aria-label="추가 동작">⋯</summary><div class="experiment-more-content"></div></details>');
  headerActions.querySelector('[data-detail-action="copy"]').textContent = "링크 복사";
  headerActions.prepend(refresh);
  const download = $("#results > button");
  if (download) headerActions.querySelector(".experiment-more-content").append(download);
  heading.append(headerActions);
  const timestamp = $("#timestamp");
  heading.append(timestamp);
  summary.append(element("span", "experiment-summary-icon", '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v6m0 3v1"/></svg>'));
  const summaryCTA = element("button", "secondary experiment-summary-action");
  summaryCTA.type = "button";
  summary.append(summaryCTA);
  const scope = element("details", "experiment-scope");
  scope.innerHTML = '<summary>사용자 경험과 해석 범위</summary>';
  scope.append($("#experience-scope"));
  $("#overview").prepend(scope);
  const description = element("details", "experiment-description", '<summary>실험 설명</summary>');
  scope.after(description);
  const secondary = element("details", "experiment-statistics", '<summary>보조 지표</summary>');
  secondary.id = "secondary-metrics";
  $("#safety").before(secondary);
  secondary.append($("#safety"));
  const interpretation = element("div", "experiment-interpretation");
  interpretation.id = "experiment-interpretation";
  summary.after(interpretation);
  const completedReport = element("section", "experiment-completed-report");
  completedReport.id = "experiment-completed-report";
  completedReport.hidden = true;
  $("#results").prepend(completedReport);
  const qualityEvidence = element("section", "experiment-quality-evidence");
  qualityEvidence.id = "experiment-quality-evidence";
  $("#diagnostics").before(qualityEvidence);

  const tabbar = $(".tabs");
  const manageButton = element("button", "", "운영 관리");
  manageButton.type = "button";
  manageButton.id = "tab-manage";
  manageButton.setAttribute("role", "tab");
  manageButton.setAttribute("aria-controls", "manage");
  manageButton.setAttribute("aria-selected", "false");
  manageButton.tabIndex = -1;
  manageButton.addEventListener("click", () => window.tab("manage", manageButton));
  tabbar.append(manageButton);
  const managePanel = element("div", "tabcontent hidden", '<div class="experiment-panel-heading"><div><p class="experiment-kicker">OPERATIONS</p><h2>운영 관리</h2><p>모집·분석·결정을 관리합니다. 현재 상태에서 가능한 작업만 표시됩니다.</p></div></div><div id="operations-empty" class="experiment-empty" hidden><strong>현재 상태에서 실행할 운영 작업이 없습니다</strong><p>저장된 결과와 설계·이력에서 진행 내용을 확인할 수 있습니다.</p><button type="button" class="secondary" data-detail-tab="plan">설계·이력 보기</button></div>');
  managePanel.id = "manage";
  managePanel.setAttribute("role", "tabpanel");
  managePanel.setAttribute("aria-labelledby", "tab-manage");
  managePanel.append($("#operations"));
  $(".detail-body").append(managePanel);
  for (const view of ["results", "overview", "quality", "preview", "plan", "manage"]) tabbar.append($("#tab-" + view));

  const allocation = element("section", "experiment-allocation");
  allocation.id = "experiment-allocation";
  scope.before(allocation);
  const statisticalDetails = element("details", "experiment-statistics", '<summary><span>지표·통계 설정</span><small>기준율 · 목표 효과 · 표본 설계</small></summary>');
  statisticalDetails.id = "statistical-details";
  const sampleDesign = $("#sample-design-results");
  sampleDesign.before(statisticalDetails);
  statisticalDetails.append(sampleDesign);
  const qualityHeader = element("div", "experiment-panel-heading", '<div><p class="experiment-kicker">DIAGNOSTICS</p><h2>분석 전에 확인할 데이터 품질</h2><p>배정 균형, 응답 오류, 수집 완전성을 함께 확인합니다.</p></div><span id="quality-summary" class="experiment-chip"></span>');
  $("#quality").prepend(qualityHeader);
  const indicator = element("span", "experiment-tab-indicator");
  indicator.id = "quality-tab-indicator";
  indicator.setAttribute("aria-hidden", "true");
  $("#tab-quality").append(indicator);
  const toast = element("p", "experiment-toast");
  toast.id = "experiment-toast";
  toast.setAttribute("role", "status");
  toast.setAttribute("aria-live", "polite");
  toast.hidden = true;
  root.append(toast);

  function renderComparison(options) {
    const { title, population, groups, effect, note, thresholds = [] } = options;
    if (!groups || groups.length !== 2) return original.comparison(options);
    const e = effect && [effect.delta, effect.ci_low, effect.ci_high].every(Number.isFinite) && effect.ci_low <= effect.ci_high && groups.every(g => Number.isFinite(g.users) && g.users > 0 && Number.isFinite(g.clicked) && g.clicked >= 0 && g.clicked <= g.users) ? effect : null;
    const a = groups[0], b = groups[1], direction = !e ? "pending" : e.ci_low > 0 ? "positive" : e.ci_high < 0 ? "negative" : "neutral";
    const directionLabel = !e ? "데이터 부족" : e.ci_low > 0 ? "B가 높음" : e.ci_high < 0 ? "A가 높음" : "차이 불확실";
    const metric = title.replace(/\s*사용자$/, "률");
    const table = `<div class="experiment-scorecard-scroll"><table class="experiment-scorecard"><caption class="sr-only">${escape(title)}의 A/B 클릭률, 절대 차이, 95% 신뢰구간</caption><thead><tr><th>지표</th><th>A · 대조군</th><th>B · 비교군</th><th>차이 (B−A)</th><th>95% 신뢰구간</th></tr></thead><tbody><tr><td data-label="지표"><strong>${escape(metric)}</strong></td><td data-label="A · 대조군"><strong>${percentage(a.clicked, a.users)}</strong><small>${number(a.clicked)} / ${number(a.users)}명</small></td><td data-label="B · 비교군"><strong>${percentage(b.clicked, b.users)}</strong><small>${number(b.clicked)} / ${number(b.users)}명</small></td><td data-label="차이 (B−A)" class="experiment-delta ${direction}"><strong>${e ? points(e.delta) : "계산 대기"}</strong></td><td data-label="95% 신뢰구간"><strong>${e ? `[${points(e.ci_low)}, ${points(e.ci_high)}]` : "계산 대기"}</strong><span class="experiment-chip ${direction}">${directionLabel}</span></td></tr></tbody></table></div>`;
    const relative = Number.isFinite(e?.relative_change) ? `<div><dt>상대 변화 (B−A)/A</dt><dd>${(100 * e.relative_change).toFixed(2)}%</dd></div>` : "";
    const stats = e ? `<dl class="experiment-stat-facts"><div><dt>p값</dt><dd>${Number.isFinite(e.p_value) ? e.p_value.toPrecision(4) : "계산 대기"}</dd></div>${relative}<div><dt>1,000명당 차이</dt><dd>${(e.delta * 1000).toFixed(1)}명</dd></div></dl><p class="experiment-stat-method">${escape(e.test)} · ${escape(e.ci_method)}</p>` : "";
    const raw = `<details class="experiment-raw-values"><summary>분모·통계 상세</summary><p class="comparison-population">분모: ${escape(population)} · ${escape(note)}</p><div class="scroll"><table class="comparison-table"><thead><tr><th>군</th><th>클릭 사용자</th><th>${escape(population)} (분모)</th><th>클릭률</th></tr></thead><tbody>${groups.map(g => `<tr><td>${escape(g.label)}</td><td>${number(g.clicked)}명</td><td>${number(g.users)}명</td><td>${percentage(g.clicked, g.users)}</td></tr>`).join("")}</tbody></table></div>${stats}<p class="experiment-stat-method">%p는 절대 차이, %는 상대 변화입니다. p값은 승리 확률이 아닙니다.</p></details>`;
    const interval = e ? `<div class="experiment-compact-chart ${direction}">${original.chart(e, thresholds)}</div>` : '<div class="experiment-empty">비교할 데이터가 아직 부족합니다.</div>';
    const labels = `<div class="experiment-variant-labels">${groups.map((g, i) => `<span><b>${i ? "B" : "A"}</b>${escape(g.label.replace(/^[AB]\s*·\s*/, ""))}</span>`).join("")}</div>`;
    return `<section class="click-comparison experiment-scorecard-panel"><div class="experiment-panel-heading"><h2>지표 비교</h2></div>${labels}${table}${interval}${raw}</section>`;
  }
  window.clickComparison = renderComparison;

  function renderAllocation(data) {
    const d = data.experiment, button = data.type === "button", r = data.run?.result;
    const values = button ? (d.variants || []).map(v => ({ label: v.variant_key === "control" ? "A · 대조군" : "B · 비교군", value: d.analysis?.srm?.observed?.[v.variant_key] })) : Object.entries(data.live_assigned || r?.assigned || {}).map(([key, value]) => ({ label: `${key} · ${key === "A" ? "대조군" : "비교군"}`, value }));
    const known = values.length === 2 && values.every(v => Number.isFinite(v.value));
    const total = known ? values.reduce((sum, v) => sum + v.value, 0) : 0;
    allocation.innerHTML = `<div class="experiment-panel-heading"><div><p class="experiment-kicker">ALLOCATION</p><h2>사용자 배정</h2><p>사용자별 배정 수입니다. 분석 분모인 ${button ? "버튼 노출" : "관찰 완료"} 사용자와 구분합니다.</p></div><span class="experiment-chip">사용자 단위 고정 배정</span></div>${known ? `<div class="experiment-allocation-bar" role="img" aria-label="${values.map(v => `${escape(v.label)} ${number(v.value)}명`).join(" / ")}">${values.map((v, i) => `<span class="variant-${i}" style="width:${total ? 100 * v.value / total : 0}%"></span>`).join("")}</div><div class="experiment-allocation-legend">${values.map((v, i) => `<div><span class="variant-dot variant-${i}"></span><span>${escape(v.label)}</span><strong>${number(v.value)}명</strong><small>${total ? (100 * v.value / total).toFixed(1) + "%" : "배정 대기"}</small></div>`).join("")}</div>` : '<p class="experiment-muted">군별 배정 수는 현재 응답에서 확인되지 않습니다. 전체 참여자는 상단 요약에서 확인하세요.</p>'}`;
  }

  function renderPreview() {
    const panel = $("#preview");
    if (!panel.querySelector(".experiment-preview-heading")) panel.prepend(element("div", "experiment-panel-heading experiment-preview-heading", '<div><p class="experiment-kicker">EXPERIENCE</p><h2>사용자가 보게 될 경험</h2><p>A/B 구성을 확인하고, 실기기 예약은 필요한 경우에만 펼쳐 사용하세요.</p></div>'));
    const reservations = [...panel.querySelectorAll("button[onclick]")].filter(button => button.getAttribute("onclick").includes("preview-override"));
    if (reservations.length && !panel.querySelector(".experiment-developer-qa")) {
      const details = element("details", "experiment-developer-qa", '<summary>개발자 계정 실기기 QA 예약</summary><p>기존 예약 규칙에 따라 개발자 계정의 다음 적격 조회에만 적용됩니다. 공식 분석에서 제외됩니다.</p><div class="actions"></div>');
      reservations.forEach(button => details.querySelector(".actions").append(button));
      panel.append(details);
    }
  }

  const fullDate = value => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString("ko-KR", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }) + " KST" : "기록 없음";
  function renderReport(data, report) {
    const d = data.experiment;
    const statuses = { pass: "확인", fail: "문제", limited: "제한", pending: "진행 중", info: "해석 범위" };
    qualityEvidence.innerHTML = `<div class="experiment-evidence-heading"><h3>확인된 사실과 해석 제한</h3><span class="experiment-chip" data-tone="${report.quality.tone}">${escape(report.quality.label)}</span></div><div class="experiment-evidence-grid">${report.checks.map(c => `<article class="experiment-evidence-item" data-check="${escape(c.name)}" data-state="${c.status}"><div><h4>${escape(c.name)}</h4><span class="experiment-chip ${c.status}">${statuses[c.status]}</span></div><strong>${escape(c.label)}</strong><p>${escape(c.detail)}</p></article>`).join("")}</div>`;
    if (report.button) $("#diagnostics").innerHTML = "";
    const metric = $("#counts .metric:last-child");
    metric.querySelector("b").textContent = report.quality.label;
    metric.querySelector("small").textContent = report.button ? "SRM과 클릭 수집 완전성은 별도 항목입니다. 데이터 품질 탭에서 근거를 확인하세요." : "관찰 기간·수집 확인·응답 품질을 구분합니다. 데이터 품질 탭에서 근거를 확인하세요.";
    completedReport.hidden = !report.terminal;
    root.dataset.terminal = String(report.terminal);
    description.hidden = !report.terminal;
    if (report.terminal) {
      $("#overview").prepend(summary, counts);
      description.append(hypothesis);
      scope.append(resultNote);
    } else {
      anchors.summary.after(summary); anchors.counts.after(counts);
      anchors.hypothesis.after(hypothesis); anchors.note.after(resultNote);
    }
    if (!report.terminal) return;
    const lifecycle = d.status === "stopped" ? "중단 기록" : d.status === "decided" ? "결정 기록 완료" : "실험 종료";
    $("#next").innerHTML = `<strong>${lifecycle} · ${escape(report.partial ? "기본 계측 부분 승인" : report.decisionLabel)}</strong>${escape(report.limitation)}`;
    $("#counts .metric:first-child .metric-label").textContent = "최종 배정 사용자";
    $("#counts .metric:nth-child(2) .metric-label").textContent = report.button ? "분석 노출 · 진입 사용자" : "분석 관찰 완료 사용자";
    $("#gates-heading").textContent = "종료 결과 검토";
    $("#gates").innerHTML = report.checks.map(c => `<article class="check"><span class="status ${c.status === "pass" ? "pass" : c.status === "fail" ? "fail" : "review"}">${escape(c.label)}</span><strong>${escape(c.name)}</strong><p>${escape(c.detail)}</p></article>`).join("");
    $("#result-note").textContent = report.limitation + " 종료 후 표본·기간을 유의성에 맞춰 바꾸거나 원래의 미확인 기록을 통과로 처리하지 않습니다.";
    const decision = report.decision;
    const successor = decision?.details?.successor_id;
    const successorLink = Number.isSafeInteger(successor) && successor > 0 ? `<a class="experiment-successor" href="/admin/experiments?view=results#experiment/${successor}">기록된 후속 실험 #${successor} 열기 →</a>` : "";
    const decisionText = decision ? `<p>${escape(decision.reason)}</p><small>기록 ${fullDate(decision.created_at)}${decision.details?.run_id ? ` · 검토 분석 #${escape(decision.details.run_id)}` : ""}</small>${successorLink}` : `<p>${d.kind === "aa" ? report.partial ? "기본 계측 항목만 부분 승인했습니다. 승인 범위와 미확인 항목은 품질 탭에서 확인하세요." : "A/A는 효과의 승자를 고르는 실험이 아닙니다. 양군 동일 경험과 계측 검증 기록을 확인하세요." : report.exploratory ? "자동 승자 판정을 하지 않는 설계입니다. 종료됐다는 사실과 어느 경험을 채택할지는 별개입니다." : "저장된 채택 결정이 없습니다. 종료·중단을 확대 적용 승인으로 해석하지 않습니다."}</p>`;
    const endLabel = d.status === "stopped" ? "중단 시각" : d.status === "decided" ? "결정 기록" : "분석 종료";
    const headline = report.partial ? "기본 계측만 확인했습니다" : report.quality.tone === "danger" ? "품질 문제로 결론을 내리기 어렵습니다" : data.run?.result?.outcome === "safety_unconfirmed" ? "학식 이용 안전성을 확인하지 못했습니다" : report.direction === "unavailable" ? "비교할 데이터가 부족합니다" : report.direction === "uncertain" ? "뚜렷한 차이를 확인하지 못했습니다" : `${report.direction}의 ${report.button ? "진입률" : "클릭률"}이 더 높게 나타났습니다`;
    completedReport.innerHTML = `<div class="experiment-compact-outcome"><span class="experiment-kicker">결과</span><h2>${escape(headline)}</h2></div><details id="experiment-review-details" class="experiment-review-details"><summary>기간·결정 기록</summary><div class="experiment-record"><h3>${escape(report.decisionLabel)}</h3>${decisionText}</div><dl class="experiment-analysis-period"><div><dt>시작</dt><dd>${fullDate(report.start)}</dd></div><div><dt>${endLabel}</dt><dd>${fullDate(report.end)}</dd></div><div><dt>${report.button ? "집계 범위" : "분석·데이터 기준"}</dt><dd>${report.button ? "시작~종료 누적 · 선행 노출 후 클릭" : `분석 #${escape(report.runId ?? "미기록")} · ${fullDate(report.watermark)}`}</dd></div></dl><p class="experiment-report-limitation">${escape(report.limitation)}</p></details>`;
    const shortDate = value => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleDateString("ko-KR", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit" }) : "기록 없음";
    $("#timestamp").textContent = `${shortDate(report.start)} ~ ${shortDate(report.end)} · KST`;
    $("#detail-meta").textContent = `${report.button ? "버튼 실험" : d.kind === "aa" ? "A/A 실험" : "A/B 실험"} #${d.id}`;
    if (report.button) {
      $("#schedule-note").textContent = `${report.exploratory && d.analysis_plan?.duration_days ? d.analysis_plan.duration_days + "일 고정 기간의 " : ""}모집과 분석 구간이 종료된 누적 결과입니다. 군별 관측값·수집 한계·고정 설계를 함께 검토하세요. 현황 새로고침은 실험을 재개하지 않습니다.`;
      const events = [["실험 시작", report.start], ...(d.analysis_plan?.amended_at ? [["계획 개정 기록", d.analysis_plan.amended_at]] : []), ["실험 종료", report.end]];
      $("#timeline").innerHTML = events.map(([label, date]) => `<div class="timeline-item ${date ? "done" : ""}"><strong>${label}</strong><small>${fullDate(date)}</small></div>`).join("");
    }
  }

  function render(data) {
    lastRendered = data;
    const d = data.experiment, r = data.run?.result, button = data.type === "button";
    const report = globalThis.CnuExperimentReport.build(data);
    renderReport(data, report);
    root.dataset.ux = "ready";
    root.dataset.experimentType = data.type;
    $("#status").dataset.status = d.status;
    const quality = $("#counts .metric:last-child b")?.textContent || "집계 대기";
    $("#counts").querySelectorAll(".metric").forEach(metric => {
      const note = metric.querySelector(":scope > small");
      if (!note) return;
      const definition = element("details", "experiment-metric-definition", "<summary>집계 기준</summary>");
      definition.append(note);
      metric.append(definition);
    });
    $("#quality-summary").textContent = quality;
    const failed = report.quality.tone === "danger";
    $("#quality-summary").dataset.tone = report.quality.tone;
    indicator.dataset.tone = report.quality.tone;
    $("#tab-quality").title = `데이터 품질: ${quality}`;
    summary.dataset.tone = failed || d.status === "stopped" ? "warning" : "neutral";
    const issues = [];
    if (report.exploratory) issues.push("탐색 결과");
    if (report.partial) issues.push("기본 계측만 부분 승인");
    if (failed) issues.push("품질 문제 확인 필요");
    else if (report.quality.tone === "warning") issues.push("수집 확인 필요");
    if (report.recovered) issues.push("중단·복구 이력");
    interpretation.textContent = issues.join(" · ");
    interpretation.hidden = !issues.length;
    if (issues.length) {
      const more = element("button", "experiment-notice-link", "자세히");
      more.type = "button"; more.dataset.detailTab = "quality";
      interpretation.append(more);
    }
    secondary.hidden = !$("#safety").textContent.trim();
    const target = failed || data.quality_review || report.terminal && report.quality.tone === "warning" ? "quality" : !button && d.status === "draft" ? "plan" : "results";
    summaryCTA.dataset.detailTab = target;
    summaryCTA.textContent = target === "quality" ? "품질 점검 보기" : target === "plan" ? "설계 확인" : "결과 확인";
    const sections = ["enrollment-section", "draft-section", "analysis-section", "decision-section"].map(id => $("#" + id));
    $("#operations-empty").hidden = sections.some(section => !section.hidden);
    $("#operations").hidden = !sections.some(section => !section.hidden);
    renderAllocation(data);
    renderPreview();
    document.title = `${d.name} · 실험실 · CNU Insights`;
  }

  function selectView(view, persist = true) {
    if (!views.has(view)) view = "overview";
    original.tab(view, $("#tab-" + view));
    selectedView = view;
    root.dataset.activeView = view;
    if (view === "manage") $("#operations").open = true;
    const active = $("#tab-" + view);
    if (tabbar.scrollWidth > tabbar.clientWidth) tabbar.scrollLeft = Math.max(0, active.offsetLeft - tabbar.offsetLeft - tabbar.clientWidth / 2 + active.offsetWidth / 2);
    if (persist) writeView(view);
  }
  window.tab = (view) => selectView(view);
  window.openDetail = async (id, type = "card", options = {}) => {
    const request = ++renderingOpen, before = new URL(location.href), previousHistoryState = history.state, old = state(), fromList = root.classList.contains("hidden");
    const same = old?.experiment.id === Number(id) && old?.type === type;
    const desired = options.view || (same ? selectedView : matchDetail(before)?.id === Number(id) && matchDetail(before)?.type === type ? before.searchParams.get("view") || window.__cnubotExperimentEntryView : null);
    const openFromHistory = navigatingHistory || options.history === "replace";
    await original.open(id, type);
    const data = state();
    if (request !== renderingOpen || !data || data.experiment.id !== Number(id) || data.type !== type) return;
    render(data);
    selectView(views.has(desired) ? desired : defaultView(data), false);
    const final = new URL(location.href);
    final.searchParams.set("view", selectedView);
    const alreadyAtDetail = matchDetail(before)?.id === Number(id) && matchDetail(before)?.type === type;
    if (!same && !alreadyAtDetail && !openFromHistory) {
      history.replaceState(previousHistoryState, "", before);
      history.pushState({ experimentDetail: true }, "", final);
    } else history.replaceState(previousHistoryState, "", final);
    if (fromList && !openFromHistory) window.scrollTo(0, 0);
    window.__cnubotExperimentEntryView = null;
  };
  window.back = () => {
    if (history.state?.experimentDetail && !root.classList.contains("hidden")) history.back();
    else original.back();
  };
  window.addEventListener("popstate", async () => {
    navigatingHistory = true;
    try {
      const detail = matchDetail();
      if (detail) await window.openDetail(detail.id, detail.type, { history: "replace", view: new URL(location.href).searchParams.get("view") });
      else original.back();
    } finally { navigatingHistory = false; }
  });

  // Capture prevents the old five-tab key handler from skipping the new operations tab.
  tabbar.addEventListener("keydown", event => {
    const button = event.target.closest('[role="tab"]');
    if (!button || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    const tabs = [...tabbar.querySelectorAll('[role="tab"]')], index = tabs.indexOf(button);
    const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + (event.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length;
    selectView(tabs[next].getAttribute("aria-controls"));
    tabs[next].focus({ preventScroll: true });
  }, true);

  let toastTimer;
  root.addEventListener("click", async event => {
    const scroll = event.target.closest("[data-detail-scroll]");
    if (scroll) { $("#" + scroll.dataset.detailScroll)?.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" }); return; }
    const tab = event.target.closest("[data-detail-tab]");
    if (tab) { selectView(tab.dataset.detailTab); return; }
    if (!event.target.closest('[data-detail-action="copy"]')) return;
    try {
      await navigator.clipboard.writeText(location.href);
      toast.textContent = "현재 탭의 상세 주소를 복사했습니다.";
    } catch {
      const input = element("input", "experiment-copy-fallback");
      input.value = location.href;
      root.append(input); input.select();
      const copied = document.execCommand("copy");
      input.remove();
      toast.textContent = copied ? "상세 주소를 복사했습니다." : "주소창에서 상세 주소를 복사해 주세요.";
    }
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.hidden = true; }, 4000);
  });
  window.showPreview = async (...args) => {
    const cards = $("#preview-cards");
    cards?.setAttribute("aria-busy", "true");
    try { return await original.preview(...args); }
    finally { cards?.setAttribute("aria-busy", "false"); }
  };

  const existing = state();
  if (existing && !root.classList.contains("hidden")) {
    if (existing.type === "button") window.renderButtonDetail(); else window.renderDetail();
    render(existing);
    selectView(views.has(window.__cnubotExperimentEntryView) ? window.__cnubotExperimentEntryView : defaultView(existing));
  }
  // An initial API response can finish before or during the deferred asset load.
  // Observe that one render as well; object identity avoids observing our own UI updates.
  new MutationObserver(() => {
    const data = state();
    if (!data || data === lastRendered || root.classList.contains("hidden")) return;
    const same = lastRendered?.type === data.type && lastRendered?.experiment.id === data.experiment.id;
    const requested = new URL(location.href).searchParams.get("view") || window.__cnubotExperimentEntryView;
    render(data);
    selectView(views.has(requested) ? requested : same ? selectedView : defaultView(data));
    window.__cnubotExperimentEntryView = null;
  }).observe(root, { childList: true, subtree: true, attributes: true, attributeFilter: ["class"] });
  root.dataset.ux = "ready";
})();
