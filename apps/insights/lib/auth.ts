import { createHash, timingSafeEqual } from "node:crypto";

export const privateHeaders = {
  "Cache-Control": "private, no-store",
  Vary: "Authorization",
};

function equal(left: string, right: string) {
  return timingSafeEqual(
    createHash("sha256").update(left).digest(),
    createHash("sha256").update(right).digest(),
  );
}

export function authFailure(authorization: string | null): Response | null {
  const username = process.env.INSIGHTS_ADMIN_USERNAME;
  const password = process.env.INSIGHTS_ADMIN_PASSWORD;
  if (!username || !password) {
    return Response.json(
      { error: "관리자 인증 설정이 필요합니다." },
      { status: 503, headers: privateHeaders },
    );
  }
  if (authorization?.startsWith("Basic ") && authorization.length < 8192) {
    const decoded = Buffer.from(authorization.slice(6), "base64").toString(
      "utf8",
    );
    const colon = decoded.indexOf(":");
    // Evaluate both comparisons even when one credential is incorrect.
    const userMatches = equal(decoded.slice(0, colon), username);
    const passwordMatches = equal(decoded.slice(colon + 1), password);
    if (colon > 0 && userMatches && passwordMatches) return null;
  }
  return Response.json(
    { error: "관리자 인증이 필요합니다." },
    {
      status: 401,
      headers: {
        ...privateHeaders,
        "WWW-Authenticate": 'Basic realm="CNU Insights", charset="UTF-8"',
      },
    },
  );
}
