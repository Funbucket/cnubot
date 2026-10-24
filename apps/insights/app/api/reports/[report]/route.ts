import { authFailure, privateHeaders } from "@/lib/auth";
import { requestReport, type RelayQuery } from "@/lib/relay";
import { isReport } from "@/lib/reports";

export const dynamic = "force-dynamic";
export const maxDuration = 90;

export async function GET(
  request: Request,
  context: { params: Promise<{ report: string }> },
) {
  const denied = authFailure(request.headers.get("authorization"));
  if (denied) return denied;
  const { report } = await context.params;
  if (!isReport(report) && report !== "fortune-users") {
    return Response.json(
      { error: "지원하지 않는 보고서입니다." },
      { status: 404, headers: privateHeaders },
    );
  }
  const params = new URL(request.url).searchParams;
  const query: RelayQuery = { report };
  for (const key of params.keys()) {
    if (
      !["start_date", "end_date", "all_time", "refresh"].includes(key) ||
      params.getAll(key).length !== 1
    ) {
      return Response.json(
        { error: "조회 조건을 확인해 주세요." },
        { status: 400, headers: privateHeaders },
      );
    }
  }
  for (const field of ["start_date", "end_date"] as const) {
    const value = params.get(field);
    if (value !== null) {
      const stamp = new Date(`${value}T00:00:00Z`);
      if (
        !/^\d{4}-\d{2}-\d{2}$/.test(value) ||
        !Number.isFinite(stamp.getTime()) ||
        stamp.toISOString().slice(0, 10) !== value
      ) {
        return Response.json(
          { error: "유효한 날짜를 선택해 주세요." },
          { status: 400, headers: privateHeaders },
        );
      }
      query[field] = value;
    }
  }
  for (const field of ["all_time", "refresh"] as const) {
    if (params.has(field)) {
      if (!["true", "false"].includes(params.get(field)!))
        return Response.json(
          { error: "조회 조건을 확인해 주세요." },
          { status: 400, headers: privateHeaders },
        );
      query[field] = params.get(field) === "true";
    }
  }
  if (
    (query.start_date && query.end_date && query.start_date > query.end_date) ||
    (query.all_time && (query.start_date || query.end_date))
  ) {
    return Response.json(
      { error: "조회 기간을 확인해 주세요." },
      { status: 400, headers: privateHeaders },
    );
  }
  try {
    const { body, status } = await requestReport(query);
    return Response.json(body, { status, headers: privateHeaders });
  } catch {
    return Response.json(
      { error: "보고서를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요." },
      { status: 503, headers: privateHeaders },
    );
  }
}
