import assert from "node:assert/strict";
import { test } from "node:test";
import "../public/experiment-report.js";

const build = (globalThis as typeof globalThis & { CnuExperimentReport: { build: (data: any) => any } }).CnuExperimentReport.build;
function button(overrides: Record<string, unknown> = {}) {
  return { type: "button", experiment: { status: "completed", started_at: "2026-01-01T00:00:00Z", ended_at: "2026-01-08T00:00:00Z", analysis_plan: { mode: "exploratory_timebox" }, variants: [{ variant_key: "control", label: "A" }, { variant_key: "treatment", label: "B" }], analysis: { variants: [{ variant_key: "control", exposed_users: 100, clicked_users: 10 }, { variant_key: "treatment", exposed_users: 100, clicked_users: 2, comparison: { delta: -.08, ci_low: -.15, ci_high: -.01, p_value: .02 } }], srm: { status: "pass", p_value: 1 }, quality: { sample_size_ok: false, decision_ready: false } }, ...overrides } };
}

test("completed exploratory results separate observed direction, quality and decision", () => {
  const result = build(button());
  assert.equal(result.terminal, true);
  assert.equal(result.direction, "A");
  assert.equal(result.observed, "A 방향의 차이 관측");
  assert.equal(result.quality.label, "계측 확인 제한");
  assert.equal(result.decisionLabel, "자동 승자 판정 대상 아님");
  assert(!result.checks.some((c: any) => c.name === "계획 표본" || c.status === "pending"));
  assert.equal(result.checks[0].status, "pass");
  assert.equal(result.checks.find((c: any) => c.name === "클릭 출처·수집 완전성").status, "limited");
});

test("SRM failure overrides a favorable observed interval", () => {
  const data = button();
  data.experiment.analysis.srm.status = "fail";
  const result = build(data);
  assert.equal(result.quality.tone, "danger");
  assert.match(result.headline, /품질 한계/);
  assert.equal(result.decisionLabel, "자동 승자 판정 대상 아님");
});

test("missing, zero-denominator and malformed intervals never imply a winner", () => {
  for (const comparison of [undefined, { delta: 0, ci_low: NaN, ci_high: .1 }, { delta: 0, ci_low: .1, ci_high: -.1 }]) {
    const data: any = button();
    data.experiment.analysis.variants[1].comparison = comparison;
    const result = build(data);
    assert.equal(result.direction, "unavailable");
    assert.equal(result.effect, null);
  }
  const data: any = button({ analysis: null });
  assert.equal(build(data).available, false);
  assert.equal(build(data).direction, "unavailable");
  const empty: any = button();
  empty.experiment.analysis.variants[0].exposed_users = 0;
  assert.equal(build(empty).effect, null);
});

test("interval including zero is uncertainty rather than proof of no effect", () => {
  const data: any = button({ analysis_plan: {} });
  data.experiment.analysis.variants[1].comparison = { delta: -.01, ci_low: -.1, ci_high: .1 };
  const result = build(data);
  assert.equal(result.direction, "uncertain");
  assert.match(result.limitation, /동등성 판정은 아닙니다/);
  assert.equal(result.checks.find((c: any) => c.name === "계획 표본").label, "종료 시 미충족");
});

test("recorded followup, quality failure and old recovery remain independently visible", () => {
  const data = { type: "card", experiment: { status: "decided", protocol: { purpose: "exploratory" } }, run: { id: 9, result: { final: true, data_complete: false, quality_status: "fail", operational_passed: false, operational_recoveries: [{ created_at: "2026-01-02T00:00:00Z" }], srm: { status: "pass" } } }, history: [{ action: "decision", reason: "Keep evidence", created_at: "2026-01-09T00:00:00Z", details: { choice: "followup", run_id: 9, successor_id: 10 } }] };
  const result = build(data);
  assert.equal(result.recovered, true);
  assert.equal(result.quality.label, "품질 문제 있음");
  assert.equal(result.decisionLabel, "후속 실험 결정");
  assert.equal(result.end, data.history[0].created_at);
  assert.equal(result.decision.details.successor_id, 10);
});

test("stopped A/A partial approval preserves the stop and does not become full approval", () => {
  const result = build({ type: "card", experiment: { status: "stopped", kind: "aa", stopped_at: "2026-01-02T00:00:00Z", protocol: {} }, quality_review: { details: { scope: "basic_instrumentation" } }, run: { result: { quality_status: "fail", operational_passed: false } } });
  assert.equal(result.terminal, true);
  assert.equal(result.partial, true);
  assert.match(result.headline, /중단된 A\/A/);
  assert.equal(result.end, "2026-01-02T00:00:00Z");
  assert.match(result.limitation, /정식 A\/A 전체 통과가 아닙니다/);
});
