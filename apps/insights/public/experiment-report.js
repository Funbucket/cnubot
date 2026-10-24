/* Read-only interpretation of existing results; never changes experiment decisions. */
(() => {
  "use strict";
  const finite = value => typeof value === "number" && Number.isFinite(value);
  const choices = { adopt: "B 확대 적용 기록", keep: "현행 유지 결정", inconclusive: "결론 유보 기록", followup: "후속 실험 결정" };
  function build(data) {
    const d = data.experiment, button = data.type === "button", r = data.run?.result, a = button ? d.analysis : null;
    const terminal = ["completed", "decided", "stopped"].includes(d.status);
    const exploratory = d.protocol?.purpose === "exploratory" || d.analysis_plan?.mode === "exploratory_timebox";
    const available = Boolean(button ? a : data.run);
    const groups = button ? (d.variants || []).map(v => {
      const row = a?.variants?.find(item => item.variant_key === v.variant_key);
      return { key: v.variant_key === "control" ? "A" : "B", label: v.label, users: row?.exposed_users, clicks: row?.clicked_users };
    }) : ["A", "B"].map(key => ({ key, label: key === "A" ? "대조군" : "비교군", users: r?.mature?.[key], clicks: r?.clicks?.[key] }));
    const effect = button ? a?.variants?.find(v => v.variant_key === "treatment")?.comparison : r?.effect;
    const validGroups = groups.length === 2 && groups.every(g => finite(g.users) && g.users > 0 && finite(g.clicks) && g.clicks >= 0 && g.clicks <= g.users);
    const interval = validGroups && effect && [effect.delta, effect.ci_low, effect.ci_high].every(finite) && effect.ci_low <= effect.ci_high ? effect : null;
    const direction = !interval ? "unavailable" : interval.ci_high < 0 ? "A" : interval.ci_low > 0 ? "B" : "uncertain";
    const observed = { A: "A 방향의 차이 관측", B: "B 방향의 차이 관측", uncertain: "차이의 방향 불확실", unavailable: "효과 추정 불가" }[direction];
    const srm = button ? a?.srm : r?.srm;
    const partial = data.quality_review?.details?.scope === "basic_instrumentation";
    const recovered = Boolean(r?.operational_recoveries?.length || data.history?.some(h => h.action === "recover"));
    const decision = data.history?.find(h => h.action === "decision");
    const checks = [];
    const check = (name, status, label, detail) => checks.push({ name, status, label, detail });
    check("배정 균형 (SRM)", srm?.status === "pass" ? "pass" : srm?.status === "fail" ? "fail" : terminal ? "limited" : "pending", srm?.status === "pass" ? "이상 미검출" : srm?.status === "fail" ? "불균형 감지" : "검증 자료 부족", finite(srm?.p_value) ? `SRM p값 ${srm.p_value.toPrecision(4)}. 균형 확인이 클릭 수집 완전성을 보장하지는 않습니다.` : "배정 균형을 확인할 계산값이 없습니다.");
    if (button) {
      check("클릭 출처·수집 완전성", "limited", "운영 확인 미기록", "선행 노출 이후 같은 문구·목적지로 확인된 클릭만 포함합니다. 출처 미확인 클릭은 제외하며 누락 규모·실기기 전달 완전성은 이 결과만으로 확인할 수 없습니다.");
      check("분석 범위", "info", "버튼 진입률", "문구와 연결 기획전을 함께 비교했습니다. 구매 전환이나 순수 문구 효과로 해석하지 않습니다.");
      if (exploratory) {
        check("설계·종료 규칙", "info", "고정 기간 탐색", "시작 후 계획을 개정한 탐색 실험입니다. 예상 모집 인원은 확증 표본 목표가 아니며, 원래 표본 계산은 폐기된 계획입니다. 자동 승자 판정 대상이 아닙니다.");
      } else check("계획 표본", a?.quality?.sample_size_ok ? "pass" : terminal ? "limited" : "pending", a?.quality?.sample_size_ok ? "충족" : terminal ? "종료 시 미충족" : "모집 중", "저장된 계획 표본 충족 여부입니다. 미충족을 차이가 없다는 결론으로 해석하지 않습니다.");
    } else {
      check("관찰 기간", r?.final ? "pass" : terminal ? "limited" : "pending", r?.final ? "기간 완료" : terminal ? "완료 조건 미충족" : "관찰 중", `배정 후 ${d.protocol?.observation_hours ?? "계획된"}시간의 관찰 조건과 수집 여유를 적용한 분석입니다.`);
      check("수집 완전성", r?.data_complete ? "pass" : terminal ? "limited" : "pending", r?.data_complete ? "운영 확인 기록" : "운영 확인 미기록", "수집 완전성은 분석 계산이나 실험 종료와 별도로 운영 확인 기록을 확인합니다.");
      check("응답·제공 품질", r?.operational_passed === true ? "pass" : r?.operational_passed === false ? "fail" : terminal ? "limited" : "pending", r?.operational_passed === true ? "기준 충족" : r?.operational_passed === false ? "기준 미충족" : "확인 자료 부족", "오류·미완료·지연의 기존 품질 판정을 사용합니다. 상세 집계와 감사 이력을 함께 확인하세요.");
      if (recovered) check("중단·복구 이력", "limited", "해석 제한", "중단 구간과 오류 기록을 보존한 결과입니다. 중단 없는 정상 실험으로 해석하지 않습니다.");
      if (partial) check("A/A 승인 범위", "limited", "기본 계측 부분 승인", "확인된 기본 계측 항목만 승인한 기록입니다. 정식 A/A 전체 통과나 효과 검증이 아닙니다.");
    }
    const failed = checks.some(c => c.status === "fail") || !button && r?.quality_status === "fail";
    const limited = checks.some(c => c.status === "limited");
    const quality = { label: failed ? "품질 문제 있음" : partial ? "기본 계측 부분 승인" : !available ? "분석 자료 없음" : limited ? "계측 확인 제한" : !button && r?.quality_status === "pending" ? "관찰·수집 중" : "품질 기준 확인", tone: failed ? "danger" : !available ? "pending" : limited || partial ? "warning" : r?.quality_status === "pending" ? "pending" : "success" };
    const outcomeLabels = { quality_inconclusive: "품질 한계로 결론 제한", inconclusive: "표본 부족으로 결론 유보", aa_complete: "A/A 계측 검증 완료", adoption_supported: "계획상 채택 근거 충족", safety_unconfirmed: "학식 안전성 미확인", keep_or_followup: "현행 유지·후속 검토", operational_stop: "운영상 중단", exploratory_complete: "탐색 관찰 완료" };
    const decisionLabel = decision ? choices[decision.details?.choice] || "결정 기록 있음" : partial ? "기본 계측 부분 승인" : d.kind === "aa" ? r?.outcome === "aa_complete" ? "A/A 계측 검증 완료" : "정식 A/A 전체 통과 미확인" : exploratory ? "자동 승자 판정 대상 아님" : terminal ? "채택 결정 미기록" : "최종 결정 전";
    const headline = partial ? "중단된 A/A · 기본 계측 부분 승인" : failed ? "품질 한계를 포함한 종료 결과" : !available ? "종료됐지만 분석 자료가 없습니다" : !interval ? "종료 결과 · 효과 추정 자료 부족" : exploratory ? `탐색 결과 · ${observed}` : outcomeLabels[r?.outcome] || observed;
    const limitation = !available ? "종료 기록만으로 통계 결과를 만들지 않습니다. 분석 자료와 운영 이력을 확인하세요." : partial ? "확인된 기본 계측과 미확인 항목을 구분해 검토하세요. 정식 A/A 전체 통과가 아닙니다." : failed ? "관측 수치는 확인할 수 있지만 품질 문제로 인과적 결론과 확대 적용 판단이 제한됩니다." : exploratory ? "관측 차이와 불확실성을 보고하는 탐색 결과입니다. 통계 구간의 방향과 제품 채택 결정은 별도로 검토합니다." : direction === "uncertain" ? "현재 구간에는 0이 포함됩니다. 차이가 없다는 증명이나 동등성 판정은 아닙니다." : "효과 크기·불확실성·품질·사전에 고정한 판단 조건을 함께 검토하세요.";
    return { terminal, exploratory, available, button, groups, effect: interval, direction, observed, quality, checks, decision, decisionLabel, headline, limitation, partial, recovered, start: d.started_at, end: button ? d.ended_at : decision?.created_at || (d.status === "stopped" ? d.stopped_at : null), enrollmentEnd: d.enrollment_closed_at, analysisAt: data.run?.created_at, watermark: data.run?.watermark, runId: data.run?.id };
  }
  globalThis.CnuExperimentReport = Object.freeze({ build });
})();
