"use client";

import { useId, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { number, type Row } from "@/lib/reports";
import { DataTable, Empty, Source } from "./ui";
import { chartColors } from "@/lib/design";
import { Icon } from "./icon";

export type Choice = {
  key: string;
  label: string;
  unit: string;
  color?: string;
};
export default function Trend({
  rows,
  choices,
  x = "day",
}: {
  rows: Row[];
  choices: Choice[];
  x?: string;
}) {
  const [selected, setSelected] = useState(choices[0].key);
  const [view, setView] = useState<"chart" | "table">("chart");
  const gradientId = useId().replace(/:/g, "");
  const columns = [
    { key: x, label: x === "day" ? "날짜 (KST)" : "노출 회차" },
    ...choices.map((item) => ({
      key: item.key,
      label: `${item.label} (${item.unit})`,
    })),
  ];
  const choice = choices.find((item) => item.key === selected) ?? choices[0];
  const plotted: Row[] = [];
  // A missing calendar day breaks the line instead of implying continuous data.
  rows.forEach((row, i) => {
    if (x === "day" && i > 0 && String(row.day).match(/^\d{4}-\d{2}-\d{2}$/)) {
      const prior = new Date(`${rows[i - 1].day}T00:00:00Z`);
      prior.setUTCDate(prior.getUTCDate() + 1);
      if (prior.getTime() < new Date(`${row.day}T00:00:00Z`).getTime())
        plotted.push({
          day: prior.toISOString().slice(0, 10),
          [choice.key]: null,
        });
    }
    plotted.push(row);
  });
  const hasData = rows.some((row) => typeof row[choice.key] === "number");
  return (
    <>
      <div className="chart-toolbar">
        <div className="chart-options" role="group" aria-label="차트 지표">
          {choices.map((item) => (
            <button
              type="button"
              aria-pressed={choice.key === item.key}
              key={item.key}
              onClick={() => setSelected(item.key)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <div className="view-switch" role="group" aria-label="표시 방식">
          <button
            type="button"
            aria-label="차트 보기"
            aria-pressed={view === "chart"}
            onClick={() => setView("chart")}
            title="차트 보기"
          >
            <Icon name="chart" />
            <span>차트</span>
          </button>
          <button
            type="button"
            aria-label="표 보기"
            aria-pressed={view === "table"}
            onClick={() => setView("table")}
            title="표 보기"
          >
            <Icon name="table" />
            <span>표</span>
          </button>
        </div>
      </div>
      <div className="chart-unit">
        {choice.label} · {choice.unit}
      </div>
      {view === "table" ? (
        <div className="trend-table">
          <DataTable rows={rows} columns={columns} />
        </div>
      ) : hasData ? (
        <div
          className="trend-chart"
          role="img"
          aria-label={`${choice.label} 추이, 단위 ${choice.unit}. 아래 집계 데이터 표에서 정확한 값을 확인할 수 있습니다.`}
        >
          <ResponsiveContainer width="100%" height={264} minWidth={0}>
            <AreaChart
              data={plotted}
              margin={{ top: 12, right: 12, bottom: 0, left: -12 }}
              accessibilityLayer
            >
              <defs>
                <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                  <stop
                    offset="0%"
                    stopColor={choice.color ?? chartColors.primary}
                    stopOpacity={0.18}
                  />
                  <stop
                    offset="100%"
                    stopColor={choice.color ?? chartColors.primary}
                    stopOpacity={0.01}
                  />
                </linearGradient>
              </defs>
              <CartesianGrid
                stroke="#e5e7eb"
                strokeDasharray="3 3"
                vertical={false}
              />
              <XAxis
                dataKey={x}
                tickFormatter={(label) =>
                  x === "day"
                    ? String(label).slice(5).replace("-", ".")
                    : String(label)
                }
                axisLine={false}
                tickLine={false}
                minTickGap={30}
                tick={{ fontSize: 11, fill: "#6b7280" }}
              />
              <YAxis
                axisLine={false}
                tickLine={false}
                allowDecimals={choice.unit !== "명" && choice.unit !== "회"}
                tickFormatter={(value) => number(value)}
                tick={{ fontSize: 11, fill: "#6b7280" }}
              />
              <Tooltip
                formatter={(value) => [
                  `${number(value)}${choice.unit}`,
                  choice.label,
                ]}
                labelFormatter={(label) => String(label)}
                contentStyle={{
                  border: "1px solid #d7dbe0",
                  borderRadius: 6,
                  fontSize: 12,
                }}
              />
              <Area
                type="linear"
                dataKey={choice.key}
                stroke={choice.color ?? chartColors.primary}
                strokeWidth={2}
                fill={`url(#${gradientId})`}
                connectNulls={false}
                dot={{ r: 3, fill: "white", strokeWidth: 2 }}
                activeDot={{ r: 5 }}
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <Empty>선택한 지표의 측정 가능한 기록이 없습니다.</Empty>
      )}
      {view === "chart" ? <Source rows={rows} columns={columns} /> : null}
    </>
  );
}
