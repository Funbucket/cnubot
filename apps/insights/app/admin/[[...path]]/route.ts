import { authFailure, privateHeaders } from "@/lib/auth";
import { allowedAdmin, validAdminOrigin } from "@/lib/admin-navigation";
import { requestAdmin } from "@/lib/admin-bridge";
import { legacyInsightsRedirect, localAdminPage } from "@/lib/admin-pages";

export const dynamic = "force-dynamic";
export const maxDuration = 90;
const MAX_BODY = 350_000;
const editorHeaders = ["x-promotion-editor", "x-experiment-admin", "x-restaurants-editor"];

function error(status: number, detail: string) {
  return Response.json({ detail }, { status, headers: privateHeaders });
}

async function handler(request: Request) {
  const denied = authFailure(request.headers.get("authorization"));
  if (denied) return denied;
  const url = new URL(request.url), path = url.pathname;
  if (request.method === "GET" && ["/admin", "/admin/"].includes(path)) return new Response(null, { status: 303, headers: { ...privateHeaders, Location: "/admin/recommendations" } });
  if (request.method === "GET" && ["/admin/insight", "/admin/insights"].includes(path)) return new Response(legacyInsightsRedirect(), { headers: { ...privateHeaders, "Content-Type": "text/html; charset=utf-8" } });
  if (request.method === "GET") {
    const page = await localAdminPage(path);
    if (page) return new Response(page.body, { headers: { ...privateHeaders, "Content-Type": page.contentType, "Content-Security-Policy": "frame-ancestors 'none'; base-uri 'self'; form-action 'self'" } });
  }
  if (!allowedAdmin(request.method, path)) return error(404, "지원하지 않는 관리 경로입니다.");
  if (url.search.length > 4097 || /[\r\n]/.test(url.search)) return error(400, "조회 조건을 확인해 주세요.");
  if (request.method !== "GET") {
    if (!validAdminOrigin(request)) return error(403, "관리자 화면에서 다시 요청해 주세요.");
    if (!/^application\/json(?:;|$)/i.test(request.headers.get("content-type") ?? "")) return error(415, "JSON 요청이 필요합니다.");
  }
  let body = "";
  if (request.method !== "GET" && request.body) {
    const reader = request.body.getReader(), chunks: Uint8Array[] = [];
    let size = 0;
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        size += value.length;
        if (size > MAX_BODY) { await reader.cancel(); return error(413, "요청이 너무 큽니다."); }
        chunks.push(value);
      }
      body = Buffer.concat(chunks).toString("utf8");
      if (body) JSON.parse(body);
    } catch { return error(400, "요청 내용을 확인해 주세요."); }
  }
  const headers: Record<string, string> = {};
  for (const name of editorHeaders) if (request.headers.get(name) === "1") headers[name] = "1";
  try {
    const result = await requestAdmin({ method: request.method, path, query: url.search.slice(1), body, headers });
    if (!result.content_type.startsWith("application/json")) return error(502, "관리 API 응답을 확인해 주세요.");
    return new Response(result.status === 204 ? null : result.body, {
      status: result.status,
      headers: { ...privateHeaders, "Content-Type": result.content_type, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "Content-Security-Policy": "frame-ancestors 'none'; base-uri 'self'; form-action 'self'" },
    });
  } catch { return error(503, "관리 기능을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요."); }
}

export { handler as GET, handler as POST, handler as PUT, handler as DELETE };
