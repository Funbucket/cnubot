export const reports = {
  overview: {
    label: "전체 현황",
    kicker: "WORKSPACE OVERVIEW",
    title: "서비스의 흐름을 한눈에",
    description: "이용부터 관심, 수익까지. 우리 서비스의 현재를 살펴보세요.",
    icon: "◫",
  },
  fortune: {
    label: "오늘의 운세",
    kicker: "ACTIVATION & RETENTION",
    title: "다시 찾아오는 경험을 만들고 있나요?",
    description: "첫 등록부터 반복 이용까지, 운세 이용자의 여정을 확인하세요.",
    icon: "✳",
  },
  restaurants: {
    label: "맛집",
    kicker: "RESTAURANT EXPLORATION",
    title: "어떤 맛집을 찾고 있나요?",
    description: "지역과 예산 선택부터 추천, 지도 열기까지 살펴보세요.",
    icon: "⌖",
  },
  shuttle: {
    label: "셔틀",
    kicker: "SHUTTLE USAGE",
    title: "셔틀은 언제 확인하나요?",
    description: "조회 시간대와 응답 당시의 운행 상태를 확인하세요.",
    icon: "⇄",
  },
  products: {
    label: "상품·탐색",
    kicker: "DISCOVERY & ENGAGEMENT",
    title: "관심이 클릭으로 이어지는 순간",
    description: "탐색 경로와 상품별 반응을 살피고 다음 기회를 발견하세요.",
    icon: "▧",
  },
  revenue: {
    label: "수익",
    kicker: "REVENUE",
    title: "실제 수익은 어떻게 쌓이고 있나요?",
    description: "토스 거래처 전체의 결제일 기준 실적을 확인하세요.",
    icon: "₩",
  },
  quality: {
    label: "참여·품질",
    kicker: "EXPERIENCE & DIAGNOSTICS",
    title: "더 나은 이용 경험을 위한 단서",
    description:
      "학식 이용의 건강성과 문구, 배치, 반복 노출 반응을 살펴보세요.",
    icon: "≋",
  },
} as const;
export type Report = keyof typeof reports;
export const isReport = (value: string): value is Report =>
  value in reports && Object.hasOwn(reports, value);
export type Row = Record<string, string | number | boolean | null>;
export type Metrics = Record<string, number | null>;
export type ReportData = {
  current?: Metrics;
  previous?: Metrics | null;
  comparison?: boolean;
  partial?: boolean;
  daily?: Row[];
  activity?: Row[];
  totals?: Metrics;
  products?: Row[];
  paths?: Row[];
  cohorts?: Row[];
  areas?: Row[];
  budgets?: Row[];
  actions?: Row[];
  modes?: Row[];
  places?: Row[];
  statuses?: Row[];
  reasons?: Row[];
  guardrails?: Row[];
  entry_labels?: Row[];
  positions?: Row[];
  fatigue?: Row[];
  surfaces?: Row[];
  collections?: Row[];
  status?: string;
  summary?: Metrics;
  last_updated_at?: string | null;
  fetched_at?: string;
  generated_at?: string;
  entered_users?: number;
  result_users?: number;
  registration_started_users?: number;
  registration_completed_users?: number;
  d1_eligible?: number;
  d1_returned?: number;
  d7_eligible?: number;
  d7_returned?: number;
  result_requests?: number;
  result_responses?: number;
  errors?: number;
};
export type ReportResponse<T = ReportData> = {
  report: string;
  start_date: string | null;
  end_date: string | null;
  timezone: string;
  requested_at: string;
  data: T;
};
export const number = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value)
    ? new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 1 }).format(value)
    : "—";
export const ratio = (value: unknown, total: unknown) =>
  typeof value === "number" && typeof total === "number" && total > 0
    ? `${((value / total) * 100).toFixed(1)}%`
    : "—";
export function kstDate(now = new Date()) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}
export function daysBefore(day: string, count: number) {
  const date = new Date(`${day}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() - count);
  return date.toISOString().slice(0, 10);
}
