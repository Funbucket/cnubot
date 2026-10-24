"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import useSWR from "swr";
import {
  daysBefore,
  reports,
  type Report,
  type ReportResponse,
} from "@/lib/reports";
import ReportContent from "./report-content";
import { fetchReport } from "@/lib/client";
import { Icon } from "./icon";
import { AdminNavigation } from "./admin-navigation";

export default function Dashboard({
  report,
  today,
}: {
  report: Report;
  today: string;
}) {
  const params = useSearchParams(),
    router = useRouter();
  const navigation = useRef<HTMLElement>(null);
  useEffect(() => {
    const nav = navigation.current;
    const active = nav?.querySelector<HTMLElement>('a[aria-current="page"]');
    if (nav && active && nav.scrollWidth > nav.clientWidth) {
      nav.scrollTo({
        left: Math.max(
          0,
          active.offsetLeft - nav.clientWidth / 2 + active.offsetWidth / 2,
        ),
      });
    }
  }, [report]);
  const [refreshing, setRefreshing] = useState(false),
    [refreshError, setRefreshError] = useState("");
  const all = params.get("all_time") === "true";
  const start = all
    ? ""
    : (params.get("start_date") ??
      (params.has("end_date") ? "" : daysBefore(today, 6)));
  const end = all
    ? ""
    : (params.get("end_date") ?? (params.has("start_date") ? "" : today));
  const query = all
    ? "all_time=true"
    : new URLSearchParams({
        ...(start ? { start_date: start } : {}),
        ...(end ? { end_date: end } : {}),
      }).toString();
  const endpoint = `/api/reports/${report}?${query}`;
  const swrOptions = {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
    dedupingInterval: 30_000,
  };
  const { data, error, isLoading, mutate } = useSWR<ReportResponse>(
    endpoint,
    fetchReport,
    swrOptions,
  );
  const revenueURL = `/api/reports/revenue?${query}`;
  const revenue = useSWR<ReportResponse>(
    report === "overview" ? revenueURL : null,
    fetchReport,
    swrOptions,
  );
  const meta = reports[report];
  const presets = [
    { label: "오늘", days: 1 },
    { label: "최근 7일", days: 7 },
    { label: "최근 30일", days: 30 },
    { label: "전체 기간", days: 0 },
  ];
  function selectPeriod(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget,
      first = form.elements.namedItem("start_date") as HTMLInputElement,
      last = form.elements.namedItem("end_date") as HTMLInputElement;
    last.setCustomValidity(
      first.value && last.value && first.value > last.value
        ? "종료일은 시작일 이후로 선택해 주세요."
        : "",
    );
    if (!form.reportValidity()) return;
    const search = new URLSearchParams();
    if (first.value) search.set("start_date", first.value);
    if (last.value) search.set("end_date", last.value);
    if (!first.value && !last.value) search.set("all_time", "true");
    router.push(`/insights/${report}?${search}`);
  }
  async function refresh() {
    setRefreshing(true);
    setRefreshError("");
    try {
      await Promise.all([
        mutate(() => fetchReport(endpoint + "&refresh=true"), {
          revalidate: false,
        }),
        ...(report === "overview"
          ? [
              revenue.mutate(() => fetchReport(revenueURL + "&refresh=true"), {
                revalidate: false,
              }),
            ]
          : []),
      ]);
    } catch {
      setRefreshError(
        "새로고침에 실패했습니다. 표시된 데이터의 조회 시각을 확인하고 다시 시도해 주세요.",
      );
    } finally {
      setRefreshing(false);
    }
  }
  return (
    <div className="workspace">
      <a className="skip-link" href="#main">
        본문으로 이동
      </a>
      <aside className="sidebar">
        <Link
          href={`/insights/overview?${query}`}
          className="brand"
          aria-label="CNU Insights 전체 현황"
        >
          <span className="brand-mark">
            <Icon name="quality" />
          </span>
          <div>
            CNU<span>Insights</span>
          </div>
        </Link>
        <div className="workspace-label">
          <span className="project-avatar">C</span>
          <span>
            CNU 챗봇<small>관리자 워크스페이스</small>
          </span>
        </div>
        <p className="nav-label">워크스페이스</p>
        <AdminNavigation current="insights" />
        <p className="nav-label">인사이트 보고서</p>
        <nav ref={navigation} aria-label="보고서 탐색">
          {(Object.keys(reports) as Report[]).map((key) => (
            <Link
              key={key}
              href={`/insights/${key}?${query}`}
              aria-current={report === key ? "page" : undefined}
              className={report === key ? "active" : ""}
            >
              <Icon name={key} className="nav-icon" />
              {reports[key].label}
            </Link>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <span className="status-dot" />
          <div>
            관리자 워크스페이스<small>한국 표준시 · KST</small>
          </div>
          <span aria-hidden="true">↗</span>
        </div>
      </aside>
      <div className="workspace-main">
        <header className="topbar">
          <div>
            <span>CNU 챗봇</span>
            <b>/</b>
            <span>인사이트</span>
            <b>/</b>
            {meta.label}
          </div>
          <span className="private-badge">
            <i />
            관리자 전용
          </span>
        </header>
        <main id="main">
          <div className="page-heading">
            <div>
              <h1>{meta.label}</h1>
              <p className="page-description">{meta.description}</p>
            </div>
            <button
              className={`refresh-button ${refreshing ? "refreshing" : ""}`}
              disabled={refreshing || isLoading}
              onClick={refresh}
            >
              <Icon name="refresh" />
              {refreshing ? "갱신 중" : "새로고침"}
            </button>
          </div>
          <section className="period-bar" aria-label="분석 기간">
            <div className="period-presets">
              {presets.map((preset) => {
                const selected =
                  preset.days === 0
                    ? all
                    : !all &&
                      end === today &&
                      start === daysBefore(today, preset.days - 1);
                const period = preset.days
                  ? `start_date=${daysBefore(today, preset.days - 1)}&end_date=${today}`
                  : "all_time=true";
                return (
                  <Link
                    key={preset.days}
                    aria-current={selected ? "true" : undefined}
                    href={`/insights/${report}?${period}`}
                  >
                    {preset.label}
                  </Link>
                );
              })}
            </div>
            <form
              key={query}
              onSubmit={selectPeriod}
              onChange={(event) =>
                (
                  event.currentTarget.elements.namedItem(
                    "end_date",
                  ) as HTMLInputElement
                ).setCustomValidity("")
              }
            >
              <Icon name="calendar" className="date-symbol" />
              <label>
                <span className="sr-only">시작일</span>
                <input
                  type="date"
                  name="start_date"
                  defaultValue={start}
                  max={today}
                />
              </label>
              <span className="date-separator">—</span>
              <label>
                <span className="sr-only">종료일</span>
                <input
                  type="date"
                  name="end_date"
                  defaultValue={end}
                  max={today}
                />
              </label>
              <button type="submit">조회</button>
            </form>
          </section>
          <div className="period-caption">
            <span>
              {all ? "전체 기간" : `${start || "전체 시작"} — ${end || "오늘"}`}
              <span className="caption-divider">·</span>KST 기준
            </span>
            <span>
              {data
                ? new Intl.DateTimeFormat("ko-KR", {
                    timeZone: "Asia/Seoul",
                    hour: "2-digit",
                    minute: "2-digit",
                    hour12: false,
                  }).format(new Date(data.requested_at)) + " 조회"
                : "보고서 조회 중"}
            </span>
          </div>
          {refreshError ? (
            <div className="error-banner" role="alert">
              {refreshError}
            </div>
          ) : null}
          {error ? (
            <div className="error-state" role="alert">
              <span aria-hidden="true">◌</span>
              <h2>보고서를 불러오지 못했어요</h2>
              <p>{error.message}</p>
              <button className="primary-button" onClick={() => mutate()}>
                다시 불러오기
              </button>
            </div>
          ) : isLoading || !data ? (
            <div
              className="skeleton-report"
              role="status"
              aria-label="보고서를 불러오는 중"
            >
              <div className="skeleton-metrics">
                {Array.from({ length: 4 }, (_, i) => (
                  <div key={i} />
                ))}
              </div>
              <div className="skeleton-chart" />
              <span className="sr-only">보고서를 불러오는 중입니다.</span>
            </div>
          ) : (
            <ReportContent
              key={`${report}-${query}`}
              report={report}
              data={data.data}
              query={query}
              revenue={revenue.data?.data}
              revenueError={Boolean(revenue.error)}
            />
          )}
          <footer className="page-footer">
            <span>CNU Insights</span>
            <p>개발자·QA 제외 · 서비스 간 순사용자는 중복될 수 있습니다.</p>
            <details>
              <summary>집계 기준</summary>
              <p>
                날짜는 한국 시간이며 종료일을 포함합니다. 집계 캐시는 최대 2분,
                토스 수익 캐시는 최대 5분입니다. 측정 불가 값은 —, 관찰이 끝나지
                않은 코호트는 대기로 표시합니다. 관측 지표만으로 인과 효과를
                판단할 수 없습니다.
              </p>
            </details>
          </footer>
        </main>
      </div>
    </div>
  );
}
