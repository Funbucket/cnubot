import assert from "node:assert/strict";
import { test } from "node:test";
import { createCipheriv, randomBytes } from "node:crypto";
import { authFailure } from "../lib/auth";
import { open, seal } from "../lib/relay";
import { csvCell } from "../lib/csv";
import { daysBefore, isReport, kstDate, ratio } from "../lib/reports";
import { GET } from "../app/api/reports/[report]/route";

test("authorization fails closed, and authenticates both credentials", () => {
  delete process.env.INSIGHTS_ADMIN_USERNAME;
  delete process.env.INSIGHTS_ADMIN_PASSWORD;
  assert.equal(authFailure(null)?.status, 503);
  process.env.INSIGHTS_ADMIN_USERNAME = "synthetic";
  process.env.INSIGHTS_ADMIN_PASSWORD = "synthetic-password";
  assert.equal(authFailure(null)?.status, 401);
  assert.equal(
    authFailure("Basic " + Buffer.from("synthetic:wrong").toString("base64"))
      ?.status,
    401,
  );
  assert.equal(
    authFailure(
      "Basic " + Buffer.from("wrong:synthetic-password").toString("base64"),
    )?.status,
    401,
  );
  assert.equal(
    authFailure(
      "Basic " + Buffer.from("synthetic:synthetic-password").toString("base64"),
    ),
    null,
  );
});

test("relay rejects tampering, response substitution, and reflected requests", () => {
  const key = randomBytes(32);
  process.env.INSIGHTS_RELAY_KEY = key.toString("base64url") + "=";
  const request = seal({ report: "overview" });
  const iv = randomBytes(12),
    cipher = createCipheriv("aes-256-gcm", key, iv);
  cipher.setAAD(Buffer.from(`insights-relay:v1:response:${request.id}`));
  const data = Buffer.concat([
    cipher.update(JSON.stringify({ status: 200, body: { missing: null } })),
    cipher.final(),
    cipher.getAuthTag(),
  ]);
  const response = {
    version: 1,
    id: request.id,
    iv: iv.toString("base64url"),
    data: data.toString("base64url"),
  };
  assert.deepEqual(open(response, request.id), {
    status: 200,
    body: { missing: null },
  });
  assert.throws(() => open(response, "different-id"));
  assert.throws(() => open(request, request.id));
  data[0] ^= 1;
  assert.throws(() =>
    open({ ...response, data: data.toString("base64url") }, request.id),
  );
});

test("KST periods and missing denominators preserve metric definitions", () => {
  assert.equal(kstDate(new Date("2026-10-22T15:01:00Z")), "2026-10-23");
  assert.equal(daysBefore("2026-03-01", 1), "2026-02-28");
  assert.equal(ratio(0, 0), "—");
  assert.equal(ratio(null, 10), "—");
  assert.equal(ratio(0, 10), "0.0%");
  assert.equal(isReport("__proto__"), false);
  assert.equal(isReport("overview"), true);
});

test("CSV neutralizes spreadsheet formulas and escapes quoted names", () => {
  for (const value of ["=1+1", "+1", "-1", "@SUM(A1)", "  =1"])
    assert.ok(csvCell(value).startsWith("\"'"));
  assert.equal(csvCell('a"b,c'), '"a""b,c"');
});

test("report route checks auth and validates input before reaching origin", async () => {
  process.env.INSIGHTS_ADMIN_USERNAME = "synthetic";
  process.env.INSIGHTS_ADMIN_PASSWORD = "synthetic-password";
  const headers = {
    authorization:
      "Basic " + Buffer.from("synthetic:synthetic-password").toString("base64"),
  };
  const context = (report = "overview") => ({
    params: Promise.resolve({ report }),
  });
  const denied = await GET(
    new Request("https://example.com/api/reports/overview"),
    context(),
  );
  assert.equal(denied.status, 401);
  const unknown = await GET(
    new Request("https://example.com/api/reports/unknown", { headers }),
    context("unknown"),
  );
  assert.equal(unknown.status, 404);
  for (const query of [
    "start_date=2026-02-30",
    "start_date=2026-10-23&end_date=2026-10-01",
    "all_time=true&start_date=2026-10-01",
    "refresh=1",
    "arbitrary=true",
    "all_time=true&all_time=false",
  ]) {
    const response = await GET(
      new Request("https://example.com/api/reports/overview?" + query, {
        headers,
      }),
      context(),
    );
    assert.equal(response.status, 400, query);
    assert.match(response.headers.get("cache-control")!, /no-store/);
  }
});
