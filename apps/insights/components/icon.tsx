import type { Report } from "@/lib/reports";

type IconName =
  | Report
  | "refresh"
  | "calendar"
  | "chevron"
  | "chart"
  | "table"
  | "search";
const paths: Record<IconName, React.ReactNode> = {
  overview: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </>
  ),
  fortune: (
    <>
      <path d="m12 3 2.4 6.6L21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4L12 3Z" />
    </>
  ),
  restaurants: (
    <>
      <path d="M7 3v6m-3-6v6a3 3 0 0 0 6 0V3M7 12v9m10-18c-3 3-3 8 0 9h3M20 3v18" />
    </>
  ),
  shuttle: (
    <>
      <rect x="4" y="3" width="16" height="15" rx="3" />
      <path d="M4 10h16M8 18v3m8-3v3M8 14h.01M16 14h.01" />
    </>
  ),
  products: (
    <>
      <path d="m3 7 9-4 9 4-9 4-9-4Zm0 0v10l9 4 9-4V7M12 11v10M7 5l10 4" />
    </>
  ),
  revenue: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M3 10h18m-4 5h1M7 15h2" />
    </>
  ),
  quality: (
    <>
      <path d="M3 19h18M5 15l4-5 4 3 6-8M16 5h3v3" />
    </>
  ),
  refresh: (
    <>
      <path d="M20 7v5h-5M4 17v-5h5" />
      <path d="M6 7a7 7 0 0 1 11-2l3 3M4 16l3 3a7 7 0 0 0 11-2" />
    </>
  ),
  calendar: (
    <>
      <rect x="3" y="5" width="18" height="16" rx="2" />
      <path d="M7 3v4m10-4v4M3 11h18m-13 4h2m4 0h2" />
    </>
  ),
  chevron: <path d="m9 5 7 7-7 7" />,
  chart: (
    <>
      <path d="M3 3v18h18M6 15l4-5 4 2 6-8" />
    </>
  ),
  table: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M3 9h18M3 14h18M9 4v16" />
    </>
  ),
  search: (
    <>
      <circle cx="10" cy="10" r="6" />
      <path d="m15 15 6 6" />
    </>
  ),
};

export function Icon({
  name,
  className = "",
}: {
  name: IconName;
  className?: string;
}) {
  return (
    <svg
      className={`icon ${className}`}
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  );
}
