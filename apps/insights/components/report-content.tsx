"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useMemo, useState, type CSSProperties } from "react";
import {
  number,
  ratio,
  type Report,
  type ReportData,
  type ReportResponse,
  type Row,
} from "@/lib/reports";
import { fetchReport } from "@/lib/client";
import { productCSV } from "@/lib/csv";
import { chartColors } from "@/lib/design";
import { Icon } from "./icon";
import {
  Activity,
  Bars,
  Breakdown,
  DataTable,
  Empty,
  Metric,
  Note,
  Panel,
  Source,
} from "./ui";

const Trend = dynamic(() => import("./trend"), {
  loading: () => (
    <div className="chart-placeholder" role="status">
      차트를 불러오는 중…
    </div>
  ),
  ssr: false,
});
const serviceKeys = [
  {
    key: "menu_users",
    label: "학식",
    korean: "학식",
    report: "quality",
    color: chartColors.primary,
  },
  {
    key: "fortune_users",
    label: "운세",
    korean: "운세",
    report: "fortune",
    color: chartColors.purple,
  },
  {
    key: "restaurant_users",
    label: "맛집",
    korean: "맛집",
    report: "restaurants",
    color: chartColors.teal,
  },
  {
    key: "shuttle_users",
    label: "셔틀",
    korean: "셔틀",
    report: "shuttle",
    color: chartColors.cyan,
  },
  {
    key: "clicked_users",
    label: "상품 클릭",
    korean: "상품 클릭",
    report: "products",
    color: chartColors.coral,
  },
];

function Overview({
  data,
  query,
  revenue,
  revenueError,
}: {
  data: ReportData;
  query: string;
  revenue?: ReportData;
  revenueError?: boolean;
}) {
  const current = data.current ?? {},
    previous = data.previous ?? {};
  return (
    <>
      <div className="metrics-grid overview-metrics">
        {serviceKeys.map((service) => (
          <Metric
            key={service.key}
            label={`${service.korean} 이용 사용자`.replace("클릭 이용", "클릭")}
            value={number(current[service.key])}
            unit="명"
            note="선택 기간의 중복 제거 사용자"
            current={current[service.key]}
            previous={data.comparison ? previous[service.key] : null}
            tone={
              service.report === "fortune"
                ? "purple"
                : service.report === "shuttle"
                  ? "blue"
                  : "green"
            }
          />
        ))}
        <Metric
          label="구매확정 수익"
          value={
            revenue?.status === "ok"
              ? number(revenue.summary?.confirmedCommissionAmount)
              : "—"
          }
          unit="원"
          note={
            revenueError
              ? "수익 조회 실패 · 다시 조회해 주세요"
              : revenue?.status === "ok"
                ? "거래처 전체 · 세전 · 결제일 기준"
                : revenue
                  ? "수익 보고서에서 상태를 확인하세요"
                  : "토스 실적을 확인하고 있습니다"
          }
          tone="amber"
        />
      </div>
      <Note>
        {data.comparison
          ? data.partial
            ? "이전 동일 일수의 같은 경과시간과 비교합니다. 오늘 수치는 집계 중입니다."
            : "이전 동일 일수와 비교합니다."
          : "비교 가능한 이전 기간이 없어 증감률을 표시하지 않습니다."}{" "}
        서비스 간 사용자는 중복될 수 있습니다.
      </Note>
      <div className="report-grid wide-left">
        <Panel
          title="서비스 이용 추이"
          note="기록이 있는 최근 최대 30일 · 일별 사용자 합은 기간 순사용자 수와 다릅니다."
        >
          <Trend
            rows={data.daily ?? []}
            choices={serviceKeys.map((service) => ({
              key: service.key,
              label: `${service.korean} 이용`.replace("클릭 이용", "클릭"),
              unit: "명",
              color: service.color,
            }))}
          />
        </Panel>
        <Panel
          title="눈여겨볼 변화"
          note="숫자에서 출발해, 맥락까지 살펴보세요."
        >
          <div className="findings">
            {serviceKeys.map((service) => {
              const now = current[service.key],
                before = previous[service.key];
              const delta =
                data.comparison &&
                typeof now === "number" &&
                typeof before === "number" &&
                before > 0
                  ? ((now - before) / before) * 100
                  : null;
              return (
                <Link
                  key={service.key}
                  href={`/insights/${service.report}?${query}`}
                  className="finding"
                >
                  <span
                    className="finding-icon"
                    style={{ color: service.color }}
                  >
                    <Icon name={service.report as Report} />
                  </span>
                  <div>
                    <strong>
                      {service.korean}{" "}
                      {delta === null
                        ? `${number(now)}명`
                        : `${Math.abs(delta).toFixed(1)}% ${delta < 0 ? "감소" : "증가"}`}
                    </strong>
                    <p>
                      {delta === null
                        ? "선택 기간의 관측값을 확인하세요."
                        : `이번 ${number(now)}명 · 이전 ${number(before)}명`}
                    </p>
                  </div>
                  <span aria-hidden="true">↗</span>
                </Link>
              );
            })}
          </div>
          <Note>관측된 변화이며 원인이나 인과 효과를 의미하지 않습니다.</Note>
        </Panel>
      </div>
      <Panel
        title="학식은 언제 가장 많이 이용하나요?"
        note="요일·시간대별 학식 조회 횟수 · 선택 기간 전체 · KST"
      >
        <Activity rows={data.activity ?? []} />
      </Panel>
    </>
  );
}

function RecentUsers({ query }: { query: string }) {
  const [rows, setRows] = useState<Row[] | null>(null),
    [error, setError] = useState(""),
    [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setRows(null);
    setError("");
    fetchReport<ReportResponse<Row[]>>(
      `/api/reports/fortune-users?${query}`,
      controller.signal,
    )
      .then((response) => setRows(response.data))
      .catch((error) => {
        if (!controller.signal.aborted) setError(error.message);
      });
    return () => controller.abort();
  }, [query, attempt]);
  return (
    <div className="personal-data">
      {error ? (
        <div role="alert">
          <p>{error}</p>
          <button onClick={() => setAttempt((value) => value + 1)}>
            다시 조회
          </button>
        </div>
      ) : rows === null ? (
        <p role="status">원자료를 불러오는 중입니다…</p>
      ) : (
        <DataTable
          rows={rows}
          columns={[
            { key: "last_view_at", label: "최근 조회 (KST)" },
            { key: "birth_year", label: "출생연도" },
            { key: "sex", label: "성별" },
            { key: "birthplace", label: "출생지" },
          ]}
        />
      )}
      <Note>
        선택 기간의 사용자별 마지막 조회 · 최신 100명 · 조회 당시 사용한 출생
        정보이며 확인할 수 없는 값은 —로 표시합니다.
      </Note>
    </div>
  );
}
function Fortune({ data, query }: { data: ReportData; query: string }) {
  const [personal, setPersonal] = useState(false);
  const cohorts = new Map<string, Row[]>();
  for (const row of data.cohorts ?? [])
    cohorts.set(String(row.day), [
      ...(cohorts.get(String(row.day)) ?? []),
      row,
    ]);
  return (
    <>
      <div className="metrics-grid">
        <Metric
          label="운세 이용 사용자"
          value={number(data.result_users)}
          unit="명"
          note="운세 응답이 생성된 순사용자"
          tone="purple"
        />
        <Metric
          label="최초 등록 완료율"
          value={ratio(
            data.registration_completed_users,
            data.registration_started_users,
          )}
          note={`첫 입력창 ${number(data.registration_started_users)}명 → 저장 ${number(data.registration_completed_users)}명`}
          tone="purple"
        />
        <Metric
          label="다음 날 재이용률"
          value={ratio(data.d1_returned, data.d1_eligible)}
          note={`재이용 ${number(data.d1_returned)} / 관찰 완료 ${number(data.d1_eligible)}명`}
          tone="purple"
        />
        <Metric
          label="7일 내 재이용률"
          value={ratio(data.d7_returned, data.d7_eligible)}
          note={`재이용 ${number(data.d7_returned)} / 관찰 완료 ${number(data.d7_eligible)}명`}
          tone="purple"
        />
      </div>
      <Note>
        D1은 첫 이용 다음 날, 7일 내 재이용은 이후 7일 중 한 번 이상입니다.
        관찰이 끝난 사용자만 분모에 포함합니다.
      </Note>
      <Panel
        title="새로운 사용자와 다시 찾는 사용자"
        note="첫 이용일은 전체 기록 기준 · 기록이 있는 최근 최대 30일"
      >
        <Trend
          rows={data.daily ?? []}
          choices={[
            {
              key: "new_users",
              label: "첫 이용 사용자",
              unit: "명",
              color: chartColors.purple,
            },
            {
              key: "returning_users",
              label: "재이용 사용자",
              unit: "명",
              color: chartColors.teal,
            },
            {
              key: "users",
              label: "전체 이용 사용자",
              unit: "명",
              color: chartColors.purple,
            },
          ]}
        />
      </Panel>
      <div className="report-grid">
        <Panel
          title="등록 경험에서 막히는 곳은 없나요?"
          note="선택 기간에 첫 입력창을 연 뒤 저장한 사용자"
        >
          <Bars
            rows={[
              {
                label: "첫 입력창 열기",
                events: data.registration_started_users ?? 0,
              },
              {
                label: "등록 저장 완료",
                events: data.registration_completed_users ?? 0,
              },
            ]}
            unit="명"
          />
          <div className="panel-total">
            <span>등록 완료율</span>
            <strong>
              {ratio(
                data.registration_completed_users,
                data.registration_started_users,
              )}
            </strong>
          </div>
          <Note>
            운세 진입 사용자 {number(data.entered_users)}명은 별도 집계입니다.
          </Note>
        </Panel>
        <Panel
          title="운세는 정상적으로 제공되고 있나요?"
          note="요청 ID 기준 · 응답 생성은 실제 읽음을 뜻하지 않습니다."
        >
          <div className="quality-value">
            {ratio(data.result_responses, data.result_requests)}
            <span>응답 생성률</span>
          </div>
          <div className="inline-facts">
            <span>
              결과 요청 <b>{number(data.result_requests)}건</b>
            </span>
            <span>
              응답 생성 <b>{number(data.result_responses)}건</b>
            </span>
            <span>
              입력·조회 오류 <b>{number(data.errors)}건</b>
            </span>
          </div>
          <Note>
            오류 기록은 입력·조회 전반의 기록이며 요청 실패 건수와 다릅니다.
          </Note>
        </Panel>
      </div>
      <Panel
        title="첫 이용 이후, 언제 다시 찾아오나요?"
        note="첫 이용일 코호트별 해당 날짜 재이용률 · 최근 최대 30개 코호트"
      >
        {cohorts.size ? (
          <div className="table-scroll">
            <table className="cohort-table">
              <thead>
                <tr>
                  <th>첫 이용일</th>
                  <th>사용자</th>
                  {Array.from({ length: 7 }, (_, i) => (
                    <th key={i}>D{i + 1}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...cohorts]
                  .sort(([a], [b]) => b.localeCompare(a))
                  .map(([day, rows]) => (
                    <tr key={day}>
                      <td>{day}</td>
                      <td>{number(rows[0].users)}명</td>
                      {Array.from({ length: 7 }, (_, i) => {
                        const row = rows.find(
                            (row) => Number(row.offset) === i + 1,
                          ),
                          eligible = Number(row?.eligible ?? 0),
                          returned = Number(row?.returned ?? 0);
                        return (
                          <td key={i}>
                            {eligible ? (
                              <span
                                className="cohort-cell"
                                style={
                                  {
                                    "--intensity": Math.max(
                                      0,
                                      Math.min(1, returned / eligible),
                                    ),
                                  } as CSSProperties
                                }
                                title={`재이용 ${returned} / 관찰 완료 ${eligible}명`}
                              >
                                {ratio(returned, eligible)}
                              </span>
                            ) : (
                              <span className="pending-cell">대기</span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>
            첫 운세 이용이 기록되면 코호트별 재이용을 확인할 수 있습니다.
          </Empty>
        )}
        <Note>
          D7 열은 정확히 7일 뒤 재이용이며, 위의 7일 내 재이용률과 다릅니다.
          오늘까지 진행 중인 관찰은 대기로 표시합니다.
        </Note>
      </Panel>
      <section className="panel personal-panel">
        <button
          className="personal-toggle"
          aria-expanded={personal}
          onClick={() => setPersonal((value) => !value)}
        >
          <span>
            최근 이용자 원자료 <small>최신 100명 · 열 때 조회</small>
          </span>
          <span>{personal ? "−" : "+"}</span>
        </button>
        {personal ? <RecentUsers query={query} /> : null}
      </section>
    </>
  );
}

function Campus({ data, shuttle }: { data: ReportData; shuttle: boolean }) {
  const totals = data.totals ?? {};
  const metrics = shuttle
    ? [
        ["users", "셔틀 이용 사용자", "명", "응답이 생성된 순사용자"],
        ["views", "셔틀 조회", "회", "동일 사용자의 반복 조회 포함"],
        ["operating", "운행 중 조회", "회", "노선 중 하나 이상이 운행 중인 때"],
        ["closed", "휴무일 조회", "회", "휴무 안내 응답이 생성된 횟수"],
      ]
    : [
        ["users", "맛집 이용 사용자", "명", "진입·탐색·추천 순사용자"],
        ["recommendations", "추천 응답", "회", "빈 결과를 포함한 추천 요청"],
        [
          "map_users",
          "지도 클릭 사용자",
          "명",
          "유효한 지도 링크를 연 순사용자",
        ],
        ["map_clicks", "지도 클릭", "회", "같은 링크 재접근은 한 번만 기록"],
      ];
  return (
    <>
      <div className="metrics-grid">
        {metrics.map(([key, label, unit, note]) => (
          <Metric
            key={key}
            label={label}
            value={number(totals[key])}
            unit={unit}
            note={note}
            tone={shuttle ? "blue" : "green"}
          />
        ))}
      </div>
      <Note>
        {shuttle
          ? "새 계측 이후 생성된 응답만 집계합니다. 조회는 실제 탑승을 뜻하지 않습니다. 식별자가 없는 조회는 횟수에만 포함하며 외부 링크 클릭은 계측하지 않습니다."
          : "기존 진입·추천·지도 클릭 기록도 포함합니다. 탐색 행동과 시간대는 새 계측 이후부터 수집합니다. 지도 열기는 실제 방문을 뜻하지 않습니다."}
      </Note>
      <Panel
        title={shuttle ? "셔틀 이용 추이" : "맛집 이용 추이"}
        note="기록이 있는 최근 최대 30일 · 일별 사용자 합은 기간 순사용자 수와 다릅니다."
      >
        <Trend
          rows={data.daily ?? []}
          choices={
            shuttle
              ? [
                  {
                    key: "users",
                    label: "이용 사용자",
                    unit: "명",
                    color: chartColors.primary,
                  },
                  { key: "views", label: "조회 횟수", unit: "회" },
                ]
              : [
                  { key: "users", label: "이용 사용자", unit: "명" },
                  {
                    key: "recommendations",
                    label: "추천 응답",
                    unit: "회",
                    color: chartColors.primary,
                  },
                  {
                    key: "map_clicks",
                    label: "지도 클릭",
                    unit: "회",
                    color: chartColors.purple,
                  },
                ]
          }
        />
      </Panel>
      {shuttle ? (
        <div className="report-grid">
          <Breakdown
            title="어떤 상태에서 조회하나요?"
            note="여러 노선이 표시돼도 조회 한 번으로 집계합니다."
            rows={data.statuses ?? []}
            labels={{
              operating: "운행 중",
              before_first: "첫차 전",
              ended: "운행 종료",
              closed: "휴무",
              unknown: "확인 불가",
            }}
          />
          <Breakdown
            title="휴무일에도 확인하나요?"
            note="응답에 실제 사용한 휴무 사유별 조회 횟수"
            rows={data.reasons ?? []}
          />
        </div>
      ) : (
        <>
          <div className="report-grid">
            <Breakdown
              title="어떤 지역을 찾나요?"
              note="추천 응답의 지역별 횟수 · 랜덤은 추천된 식당의 지역"
              rows={data.areas ?? []}
            />
            <Breakdown
              title="어느 예산대를 찾나요?"
              note="추천 응답에 적용된 예산 · 랜덤은 2만원 미만"
              rows={data.budgets ?? []}
            />
          </div>
          <div className="report-grid">
            <Breakdown
              title="어떤 탐색을 하나요?"
              note="새 계측 이후의 유효한 발화 처리 횟수"
              rows={data.actions ?? []}
              labels={{
                home: "맛집 진입",
                random: "랜덤 추천",
                area: "지역 선택",
                budget: "예산 선택",
                rating: "별점 조건",
                more: "다른 곳 추천",
              }}
            />
            <Breakdown
              title="추천 결과는 충분한가요?"
              note={`빈 결과 ${number(totals.empty_results)}회 · 다시 추천 ${number(totals.refreshes)}회`}
              rows={data.modes ?? []}
              labels={{ random: "랜덤 추천", conditions: "조건 추천" }}
            />
          </div>
          <Panel
            title="어느 식당의 지도를 여나요?"
            note="지도 클릭·카드 노출 순 상위 30곳 · 식당명은 현재 목록 기준"
          >
            <DataTable
              rows={data.places ?? []}
              columns={[
                { key: "name", label: "식당" },
                { key: "users", label: "노출 사용자 (명)" },
                { key: "exposures", label: "카드 노출 (회)" },
                { key: "clicks", label: "지도 클릭 (회)" },
              ]}
            />
          </Panel>
        </>
      )}
      <Panel
        title={shuttle ? "언제 가장 많이 조회하나요?" : "맛집은 언제 찾나요?"}
        note={`요일·시간대별 ${shuttle ? "셔틀 응답" : "탐색 행동"} 횟수 · 선택 기간 전체 · KST`}
      >
        <Activity rows={data.activity ?? []} />
      </Panel>
    </>
  );
}

function ProductExplorer({ products }: { products: Row[] }) {
  const [search, setSearch] = useState(""),
    [category, setCategory] = useState(""),
    [minimum, setMinimum] = useState("0"),
    [sort, setSort] = useState("clicked_users");
  const categories = [
    ...new Set(
      products.map((row) => String(row.category_name || "카테고리 미상")),
    ),
  ];
  const filtered = useMemo(
    () =>
      products
        .filter(
          (row) =>
            (!category ||
              String(row.category_name || "카테고리 미상") === category) &&
            Number(row.exposed_users) >= Number(minimum) &&
            `${row.product_name ?? ""} ${row.product_key} ${row.category_name ?? ""}`
              .toLocaleLowerCase("ko")
              .includes(search.toLocaleLowerCase("ko")),
        )
        .sort((a, b) => {
          const score = (row: Row) =>
            sort === "rate"
              ? Number(row.exposed_users)
                ? Number(row.clicked_users) / Number(row.exposed_users)
                : -1
              : Number(row[sort] ?? 0);
          return (
            score(b) - score(a) ||
            String(a.product_key).localeCompare(String(b.product_key))
          );
        }),
    [products, category, minimum, search, sort],
  );
  function download() {
    const url = URL.createObjectURL(
      new Blob([productCSV(filtered)], { type: "text/csv;charset=utf-8" }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "cnu-insights-products.csv";
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <Panel
      title="상품 성과 탐색"
      note="최소 노출 필터로 표본 규모를 확인하고 클릭률을 함께 읽어 주세요."
    >
      <div className="product-filters">
        <label className="search-field">
          <span aria-hidden="true">⌕</span>
          <input
            aria-label="상품 검색"
            placeholder="상품명, 카테고리, ID 검색"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <label>
          <span className="sr-only">카테고리</span>
          <select
            value={category}
            onChange={(event) => setCategory(event.target.value)}
          >
            <option value="">전체 카테고리</option>
            {categories.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label className="minimum-filter">
          최소 노출
          <input
            type="number"
            aria-label="최소 노출 사용자"
            min="0"
            step="1"
            value={minimum}
            onChange={(event) => setMinimum(event.target.value)}
          />
          <span>명</span>
        </label>
        <label>
          <span className="sr-only">상품 정렬</span>
          <select
            value={sort}
            onChange={(event) => setSort(event.target.value)}
          >
            <option value="clicked_users">클릭 사용자순</option>
            <option value="exposed_users">노출 사용자순</option>
            <option value="rate">클릭률순</option>
            <option value="click_events">클릭 횟수순</option>
          </select>
        </label>
        <button
          className="export-button"
          onClick={download}
          disabled={!filtered.length}
        >
          ↓ CSV
        </button>
      </div>
      <p className="results-count" role="status">
        상품 {number(filtered.length)}개
      </p>
      <DataTable
        rows={filtered}
        columns={[
          {
            key: "product_name",
            label: "상품",
            render: (row) => (
              <div className="product-name">
                <strong>{String(row.product_name || row.product_key)}</strong>
                <small>{String(row.category_name || "카테고리 미상")}</small>
                <details>
                  <summary>상품 ID</summary>
                  <code>{String(row.product_key)}</code>
                </details>
              </div>
            ),
          },
          { key: "exposed_users", label: "노출 사용자 (명)" },
          { key: "clicked_users", label: "클릭 사용자 (명)" },
          {
            key: "rate",
            label: "클릭률",
            render: (row) => ratio(row.clicked_users, row.exposed_users),
          },
          { key: "click_events", label: "클릭 횟수 (회)" },
        ]}
      />
    </Panel>
  );
}
function Products({ data }: { data: ReportData }) {
  const totals = data.totals ?? {},
    products = data.products ?? [],
    categories = new Map<string, number>();
  products.forEach((row) =>
    categories.set(
      String(row.category_name || "카테고리 미상"),
      (categories.get(String(row.category_name || "카테고리 미상")) ?? 0) +
        Number(row.click_events ?? 0),
    ),
  );
  return (
    <>
      <div className="metrics-grid">
        <Metric
          label="상품 노출 사용자"
          value={number(totals.product_exposed_users)}
          unit="명"
          note="상품 카드가 응답에 포함된 순사용자"
        />
        <Metric
          label="상품 클릭 사용자"
          value={number(totals.product_clicked_users)}
          unit="명"
          note="반복 클릭은 한 명으로 중복 제거"
        />
        <Metric
          label="상품 클릭률"
          value={ratio(
            totals.product_clicked_users,
            totals.product_exposed_users,
          )}
          note="클릭 사용자 ÷ 노출 사용자"
          tone="blue"
        />
        <Metric
          label="상품 클릭 횟수"
          value={number(
            products.reduce(
              (sum, row) => sum + Number(row.click_events ?? 0),
              0,
            ),
          )}
          unit="회"
          note="같은 사용자의 반복 행동 포함"
          tone="blue"
        />
      </div>
      <Note>
        클릭률은 기록상 노출 대비 비율입니다. 노출 누락·기간 밖 노출이 있으면
        100%를 넘을 수 있습니다.
      </Note>
      <div className="report-grid wide-left">
        <Panel title="상품 반응 추이" note="기록이 있는 최근 최대 30일">
          <Trend
            rows={[...(data.daily ?? [])].sort((a, b) =>
              String(a.day).localeCompare(String(b.day)),
            )}
            choices={[
              {
                key: "clicked_users",
                label: "클릭 사용자",
                unit: "명",
                color: chartColors.primary,
              },
              { key: "exposed_users", label: "노출 사용자", unit: "명" },
              {
                key: "click_events",
                label: "클릭 횟수",
                unit: "회",
                color: chartColors.primary,
              },
            ]}
          />
        </Panel>
        <Panel
          title="어떤 카테고리를 클릭하나요?"
          note="카테고리별 클릭 횟수 · 반복 클릭 포함"
        >
          <Bars
            rows={[...categories]
              .map(([label, events]) => ({ label, events }))
              .sort((a, b) => b.events - a.events)}
          />
        </Panel>
      </div>
      <div className="section-title">
        <span>01 — DISCOVERY PATHS</span>
        <h2>탐색 경로</h2>
      </div>
      <div className="report-grid">
        {["entry", "inline"].map((path) => {
          const row = data.paths?.find((row) => row.path === path);
          const steps =
            path === "entry"
              ? [
                  {
                    label: "버튼 노출",
                    value: totals.entry_exposed_users ?? 0,
                  },
                  { label: "목록 진입", value: totals.entry_users ?? 0 },
                  { label: "상품 노출", value: totals.exposed_users ?? 0 },
                  { label: "상품 클릭", value: totals.clicked_users ?? 0 },
                ]
              : [
                  { label: "상품 노출", value: Number(row?.reach_users ?? 0) },
                  {
                    label: "상품 클릭",
                    value: Number(row?.clicked_users ?? 0),
                  },
                ];
          return (
            <Panel
              key={path}
              title={
                path === "entry"
                  ? "버튼을 거쳐 상품 탐색"
                  : "학식에서 상품 바로 보기"
              }
              note="선택 기간의 단계별 사용자 집계"
            >
              <Bars rows={steps} value="value" unit="명" />
              <div className="panel-total">
                <span>접점 대비 상품 클릭률</span>
                <strong>{ratio(steps.at(-1)?.value, steps[0].value)}</strong>
              </div>
            </Panel>
          );
        })}
      </div>
      <Note>
        각 단계는 기간 내 개별 집계이며 동일 사용자의 순차 전환·이탈률이
        아닙니다. 경로 간 사용자는 합산하지 않습니다.
      </Note>
      <ProductExplorer products={products} />
    </>
  );
}

function Revenue({ data }: { data: ReportData }) {
  const messages: Record<string, string> = {
    not_configured: "토스 실적 조회 설정이 필요합니다.",
    no_start_date: "조회 시작일을 확인할 수 없습니다. 날짜를 지정해 주세요.",
    no_period: "선택한 기간에는 조회 가능한 실적이 없습니다.",
    too_long: "조회 기간이 너무 깁니다. 기간을 줄여 다시 조회해 주세요.",
    unavailable: "토스 실적을 불러오지 못했습니다. 잠시 후 새로고침해 주세요.",
  };
  if (data.status !== "ok")
    return (
      <Panel title="수익 조회 상태">
        <Empty>
          {messages[data.status ?? ""] ?? "수익을 확인할 수 없습니다."}
        </Empty>
      </Panel>
    );
  const summary = data.summary ?? {};
  return (
    <>
      <div className="metrics-grid">
        <Metric
          label="구매확정 수익"
          value={number(summary.confirmedCommissionAmount)}
          unit="원"
          note="구매가 확정된 세전 수익"
          tone="amber"
        />
        <Metric
          label="예상 수익"
          value={number(summary.expectedCommissionAmount)}
          unit="원"
          note="구매확정 전 변동될 수 있는 금액"
          tone="amber"
        />
        <Metric
          label="실 결제금액"
          value={number(summary.netPaymentAmount)}
          unit="원"
          note="토스 거래처 전체의 결제 실적"
        />
        <Metric
          label="판매 수량"
          value={number(summary.soldQuantity)}
          unit="개"
          note="순사용자·주문 수와 다른 지표"
        />
      </div>
      <Note>
        거래처 전체 · 결제일 기준 · 세전 금액입니다. 챗봇 클릭과 직접 연결된
        구매 전환율이나 클릭당 수익으로 해석할 수 없습니다.
      </Note>
      <Panel
        title="토스 실적 상세"
        note="토스 API의 전체 기간 요약 합계 · 취소·환불·구매확정에 따라 변경될 수 있습니다."
      >
        <DataTable
          rows={[
            {
              label: "토스 클릭 수",
              value: summary.clickCount ?? null,
              unit: "회",
            },
            {
              label: "판매 수량",
              value: summary.soldQuantity ?? null,
              unit: "개",
            },
            {
              label: "환불 수량",
              value: summary.refundedQuantity ?? null,
              unit: "개",
            },
            {
              label: "판매금액",
              value: summary.salesAmount ?? null,
              unit: "원",
            },
            {
              label: "할인금액",
              value: summary.discountAmount ?? null,
              unit: "원",
            },
            {
              label: "실 결제금액",
              value: summary.netPaymentAmount ?? null,
              unit: "원",
            },
            {
              label: "예상 수익",
              value: summary.expectedCommissionAmount ?? null,
              unit: "원",
            },
            {
              label: "구매확정 수익",
              value: summary.confirmedCommissionAmount ?? null,
              unit: "원",
            },
          ]}
          columns={[
            { key: "label", label: "지표" },
            { key: "value", label: "실적" },
            { key: "unit", label: "단위" },
          ]}
        />
        <Note>
          토스 반영 시각:{" "}
          {data.last_updated_at
            ? new Date(data.last_updated_at).toLocaleString("ko-KR", {
                timeZone: "Asia/Seoul",
              }) + " KST"
            : "제공되지 않음"}{" "}
          · 캐시 최대 5분이며 새로고침은 토스 반영 완료를 보장하지 않습니다.
        </Note>
      </Panel>
    </>
  );
}

function Quality({ data }: { data: ReportData }) {
  const guards = [...(data.guardrails ?? [])]
    .sort((a, b) => String(a.day).localeCompare(String(b.day)))
    .map((row) => ({
      ...row,
      views: row.menu_view_users ? row.views_per_user : null,
      retention:
        row.return_rate_measurable && !row.return_rate_pending
          ? row.return_rate
          : null,
    }));
  return (
    <>
      <Panel
        title="학식 이용의 건강성"
        note="최근 최대 14일 · 집계 중·측정 불가 값은 0으로 그리지 않습니다."
      >
        <Trend
          rows={guards}
          choices={[
            { key: "active_users", label: "활성 사용자", unit: "명" },
            { key: "views", label: "1인당 학식 조회", unit: "회" },
            {
              key: "retention",
              label: "다음 날 재방문",
              unit: "%",
              color: chartColors.primary,
            },
          ]}
        />
      </Panel>
      <div className="report-grid">
        <Panel
          title="어떤 문구가 탐색으로 이어지나요?"
          note="막대는 목록 진입 사용자 수 · 문구의 인과 효과가 아닙니다."
        >
          <Bars rows={data.entry_labels ?? []} value="entry_users" unit="명" />
          <Source
            rows={data.entry_labels ?? []}
            columns={[
              { key: "label", label: "문구" },
              { key: "source", label: "위치" },
              { key: "exposed_users", label: "노출 사용자" },
              { key: "entry_users", label: "진입 사용자" },
              {
                key: "rate",
                label: "진입률",
                render: (row) => ratio(row.entry_users, row.exposed_users),
              },
              { key: "card_clicked_users", label: "상품 클릭 사용자" },
            ]}
          />
        </Panel>
        <Panel
          title="어느 카드 위치에서 반응하나요?"
          note="카드 위치별 클릭률 · 사용자 기준"
        >
          {data.positions?.length ? (
            <div className="positions">
              {data.positions.map((row, i) => (
                <div key={i} className="position-card">
                  <small>
                    {String(row.row ?? "?")}행 {String(row.column ?? "?")}열
                  </small>
                  <strong>{ratio(row.clicked_users, row.exposed_users)}</strong>
                  <span>
                    클릭 {number(row.clicked_users)} / 노출{" "}
                    {number(row.exposed_users)}명
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <Empty>위치가 기록된 카드가 없습니다.</Empty>
          )}
          <Note>상품 구성과 노출량이 달라 위치 효과로 단정할 수 없습니다.</Note>
        </Panel>
      </div>
      <Panel
        title="반복 노출에도 반응이 유지되나요?"
        note="다음 노출 전까지 반응한 노출 비율 · 6+는 6회 이상"
      >
        <div className="report-grid compact">
          {["entry", "inline"].map((path) => (
            <div key={path}>
              <h3>
                {path === "entry"
                  ? "버튼 경유 · 목록 진입률"
                  : "바로 노출 · 상품 클릭률"}
              </h3>
              <Trend
                x="nth"
                rows={(data.fatigue ?? [])
                  .filter((row) => row.path === path)
                  .sort((a, b) => Number(a.nth) - Number(b.nth))
                  .map((row) => ({
                    ...row,
                    nth: Number(row.nth) >= 6 ? "6+" : String(row.nth),
                    rate: Number(row.impressions)
                      ? (Number(row.actions) / Number(row.impressions)) * 100
                      : null,
                  }))}
                choices={[{ key: "rate", label: "반응률", unit: "%" }]}
              />
            </div>
          ))}
        </div>
        <Source
          rows={data.fatigue ?? []}
          title="반복 노출의 분모·반응 보기"
          columns={[
            { key: "path", label: "경로" },
            { key: "nth", label: "노출 회차" },
            { key: "impressions", label: "노출 횟수" },
            { key: "actions", label: "반응 횟수" },
          ]}
        />
        <Note>
          사용자별 기간 내 노출 순서이며 마지막 노출은 선택 기간 종료까지
          관찰합니다. 두 경로의 반응 정의가 다릅니다.
        </Note>
      </Panel>
      <div className="report-grid">
        <Panel
          title="어디에서 클릭이 기록됐나요?"
          note="위치별 클릭 횟수 · 이벤트 기준"
        >
          <Bars
            rows={(data.surfaces ?? []).map((row) => ({
              ...row,
              label:
                (
                  {
                    menu_inline_card: "학식 상품 카드",
                    menu_inline_more: "먹거리 더 보기",
                    commerce_card: "상품 카드",
                    menu_button: "학식 메뉴 버튼",
                    quick_reply: "퀵리플라이",
                    promotion_block: "기타 프로모션",
                  } as Record<string, string>
                )[String(row.surface)] ?? String(row.surface),
            }))}
          />
        </Panel>
        <Panel
          title="집계 범위와 해석"
          note="관측 데이터로 확인할 수 있는 범위"
        >
          <ul className="reading-notes">
            <li>활성 사용자는 학식 조회 또는 프로모션 노출 사용자입니다.</li>
            <li>재방문율 하락만으로 광고가 원인이라고 판단할 수 없습니다.</li>
            <li>
              문구·배치별 상품과 사용자가 달라 단순 순위는 실험 결과가 아닙니다.
            </li>
            <li>표본이 작으면 비율 변동이 큽니다. 분모를 함께 확인하세요.</li>
          </ul>
        </Panel>
      </div>
      <Panel
        title="기획전별 집계"
        note="기획전·선택 모드·노출 위치별 개별 집계"
      >
        <DataTable
          rows={data.collections ?? []}
          columns={[
            {
              key: "collection_id",
              label: "기획전",
              render: (row) =>
                (
                  ({ food: "먹거리", living: "꿀템" }) as Record<string, string>
                )[String(row.collection_id)] ?? String(row.collection_id),
            },
            { key: "selection_mode", label: "선택 모드" },
            { key: "placement", label: "노출 위치" },
            { key: "exposed_users", label: "노출 사용자" },
            { key: "clicked_users", label: "클릭 사용자" },
            { key: "click_events", label: "클릭 횟수" },
            { key: "entry_events", label: "목록 진입 횟수" },
          ]}
        />
      </Panel>
    </>
  );
}

export default function ReportContent({
  report,
  data,
  query,
  revenue,
  revenueError,
}: {
  report: Report;
  data: ReportData;
  query: string;
  revenue?: ReportData;
  revenueError?: boolean;
}) {
  if (report === "overview")
    return (
      <Overview
        data={data}
        query={query}
        revenue={revenue}
        revenueError={revenueError}
      />
    );
  if (report === "fortune") return <Fortune data={data} query={query} />;
  if (report === "restaurants" || report === "shuttle")
    return <Campus data={data} shuttle={report === "shuttle"} />;
  if (report === "products") return <Products data={data} />;
  if (report === "revenue") return <Revenue data={data} />;
  return <Quality data={data} />;
}
