import type { ReportResponse } from "./reports";

export async function fetchReport<T = ReportResponse>(
  url: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(url, {
    cache: "no-store",
    credentials: "same-origin",
    signal: signal ?? AbortSignal.timeout(75_000),
  });
  if (!response.ok)
    throw Error(
      response.status === 401
        ? "인증이 만료되었습니다. 페이지를 새로고침해 로그인해 주세요."
        : "보고서를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.",
    );
  return response.json();
}
