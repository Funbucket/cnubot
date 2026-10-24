"use client";

import { useState, type ReactNode, type CSSProperties } from "react";
import { number, type Row } from "@/lib/reports";

export function Panel({
  title,
  note,
  children,
  className = "",
}: {
  title: string;
  note?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      <header className="panel-heading">
        <h2>{title}</h2>
        {note ? <p>{note}</p> : null}
      </header>
      {children}
    </section>
  );
}
export function Empty({
  children = "선택한 기간에 수집된 데이터가 없습니다.",
}: {
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <span aria-hidden="true">◌</span>
      <p>{children}</p>
    </div>
  );
}
export function Note({ children }: { children: ReactNode }) {
  return <p className="scope-note">{children}</p>;
}
export function Metric({
  label,
  value,
  unit,
  note,
  previous,
  current,
  tone = "green",
}: {
  label: string;
  value: string;
  unit?: string;
  note: string;
  previous?: number | null;
  current?: number | null;
  tone?: string;
}) {
  const delta =
    typeof previous === "number" && previous > 0 && typeof current === "number"
      ? ((current - previous) / previous) * 100
      : null;
  return (
    <article className={`metric ${tone}`}>
      <div className="metric-label">{label}</div>
      <p className="metric-value">
        {value}
        <span>{unit}</span>
      </p>
      {delta !== null ? (
        <p className={`delta ${delta < 0 ? "negative" : ""}`}>
          {delta >= 0 ? "↗" : "↘"} {Math.abs(delta).toFixed(1)}%{" "}
          <span>이전 동기간 대비</span>
        </p>
      ) : null}
      <p className="metric-note">{note}</p>
    </article>
  );
}

export type Column = {
  key: string;
  label: string;
  render?: (row: Row) => ReactNode;
};
export function DataTable({
  rows,
  columns,
  pageSize = 15,
}: {
  rows: Row[];
  columns: Column[];
  pageSize?: number;
}) {
  const [page, setPage] = useState(0);
  const last = Math.max(0, Math.ceil(rows.length / pageSize) - 1),
    current = Math.min(page, last);
  if (!rows.length) return <Empty />;
  return (
    <>
      <div
        className="table-scroll"
        tabIndex={0}
        role="region"
        aria-label="보고서 데이터 표"
      >
        <table>
          <thead>
            <tr>
              {columns.map((col) => (
                <th scope="col" key={col.key}>
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows
              .slice(current * pageSize, (current + 1) * pageSize)
              .map((row, i) => (
                <tr
                  key={String(row.product_key ?? row.place_id ?? row.day ?? i)}
                >
                  {columns.map((col) => (
                    <td key={col.key}>
                      {col.render
                        ? col.render(row)
                        : typeof row[col.key] === "number"
                          ? number(row[col.key])
                          : String(row[col.key] ?? "—")}
                    </td>
                  ))}
                </tr>
              ))}
          </tbody>
        </table>
      </div>
      {rows.length > pageSize ? (
        <div className="pagination">
          <span>
            전체 {number(rows.length)}개 · {current + 1} / {last + 1}페이지
          </span>
          <div>
            <button
              disabled={current === 0}
              onClick={() => setPage(current - 1)}
              aria-label="이전 페이지"
            >
              ←
            </button>
            <button
              disabled={current === last}
              onClick={() => setPage(current + 1)}
              aria-label="다음 페이지"
            >
              →
            </button>
          </div>
        </div>
      ) : null}
    </>
  );
}
export function Source({
  rows,
  columns,
  title = "집계 데이터 보기",
}: {
  rows: Row[];
  columns: Column[];
  title?: string;
}) {
  return (
    <details className="source">
      <summary>
        {title}
        <span>{number(rows.length)}개</span>
      </summary>
      <DataTable rows={rows} columns={columns} />
    </details>
  );
}
export function Bars({
  rows,
  label = "label",
  value = "events",
  unit = "회",
  labels = {},
}: {
  rows: Row[];
  label?: string;
  value?: string;
  unit?: string;
  labels?: Record<string, string>;
}) {
  if (!rows.length) return <Empty />;
  const peak = Math.max(
    1,
    ...rows.map((row) =>
      typeof row[value] === "number" ? (row[value] as number) : 0,
    ),
  );
  return (
    <div className="bars">
      {rows.slice(0, 12).map((row, i) => (
        <div className="bar-row" key={`${String(row[label])}-${i}`}>
          <div>
            <span>
              {labels[String(row[label])] ?? String(row[label] ?? "미기록")}
            </span>
            <strong>
              {number(row[value])}
              <small>{unit}</small>
            </strong>
          </div>
          <div className="bar-track">
            <i
              style={{
                width: `${Math.max(0, Math.min(100, (Number(row[value]) / peak) * 100))}%`,
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
export function Breakdown({
  title,
  note,
  rows,
  labels = {},
}: {
  title: string;
  note: string;
  rows: Row[];
  labels?: Record<string, string>;
}) {
  return (
    <Panel title={title} note={note}>
      <Bars rows={rows} labels={labels} />
      <Source
        rows={rows}
        columns={[
          {
            key: "label",
            label: "항목",
            render: (row) =>
              labels[String(row.label)] ?? String(row.label ?? "—"),
          },
          { key: "users", label: "순사용자 (명)" },
          { key: "events", label: "횟수 (회)" },
        ]}
      />
    </Panel>
  );
}

export function Activity({ rows }: { rows: Row[] }) {
  if (!rows.length) return <Empty>활동 시간대 기록이 아직 없습니다.</Empty>;
  const values = new Map(
    rows.map((row) => [`${row.weekday}-${row.hour}`, Number(row.events)]),
  );
  const peak = Math.max(1, ...values.values());
  return (
    <>
      <div
        className="heat-scroll"
        role="region"
        aria-label="요일·시간대별 이용 횟수"
        tabIndex={0}
      >
        <div className="activity-grid">
          <span />
          {Array.from({ length: 24 }, (_, hour) => (
            <small key={hour}>{hour % 3 === 0 ? `${hour}시` : ""}</small>
          ))}
          {["월", "화", "수", "목", "금", "토", "일"].map((day, i) => (
            <div className="heat-row" key={day}>
              <small>{day}</small>
              {Array.from({ length: 24 }, (_, hour) => {
                const count = values.get(`${i + 1}-${hour}`) ?? 0;
                return (
                  <span
                    className="heat-cell"
                    key={hour}
                    style={
                      {
                        "--intensity": count ? 0.15 + (0.85 * count) / peak : 0,
                      } as CSSProperties
                    }
                    title={`${day}요일 ${hour}시 · ${number(count)}회`}
                    role="img"
                    aria-label={`${day}요일 ${hour}시 ${count}회`}
                  />
                );
              })}
            </div>
          ))}
        </div>
      </div>
      <div className="heat-legend">
        <span>적음</span>
        {[0, 0.2, 0.5, 0.8, 1].map((value) => (
          <i
            className="heat-cell"
            key={value}
            style={{ "--intensity": value } as CSSProperties}
          />
        ))}
        <span>많음 · 조회 횟수</span>
      </div>
    </>
  );
}
