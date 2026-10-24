import assert from "node:assert/strict";
import { test, mock } from "node:test";
import { createCipheriv, randomBytes } from "node:crypto";
import { allowedAdmin, validAdminOrigin } from "../lib/admin-navigation";
import { openAdmin, sealAdmin } from "../lib/admin-bridge";
import { renderAdminHTML } from "../lib/admin-shell";
import { GET, PUT } from "../app/admin/[[...path]]/route";

const authorization = "Basic " + Buffer.from("synthetic:synthetic-password").toString("base64");
function setup() {
  process.env.INSIGHTS_ADMIN_USERNAME = "synthetic";
  process.env.INSIGHTS_ADMIN_PASSWORD = "synthetic-password";
}

test("admin pages require auth; redirects stay within the Vercel application", async () => {
  setup();
  assert.equal((await GET(new Request("https://example.com/admin/experiments"))).status, 401);
  const response = await GET(new Request("https://example.com/admin", { headers: { authorization } }));
  assert.equal(response.status, 303);
  assert.equal(response.headers.get("location"), "/admin/recommendations");
  assert.match(response.headers.get("cache-control")!, /no-store/);
});

test("cross-origin, missing-origin, non-JSON and oversized mutations never reach the backend", async () => {
  setup();
  const base = { authorization, "content-type": "application/json", "x-promotion-editor": "1" };
  for (const headers of [base, { ...base, origin: "https://other.example.com" }, { ...base, origin: "https://example.com", "sec-fetch-site": "cross-site" }]) {
    const response = await PUT(new Request("https://example.com/admin/promotion-settings", { method: "PUT", headers, body: "{}" }));
    assert.equal(response.status, 403);
  }
  const response = await PUT(new Request("https://example.com/admin/promotion-settings", { method: "PUT", headers: { authorization, origin: "https://example.com", "content-type": "text/plain" }, body: "{}" }));
  assert.equal(response.status, 415);
  const oversized = await PUT(new Request("https://example.com/admin/promotion-settings", { method: "PUT", headers: { ...base, origin: "https://example.com" }, body: "x".repeat(350_001) }));
  assert.equal(oversized.status, 413);
});

test("origin guard uses the public Host behind a TLS proxy without trusting forwarded Host", () => {
  const headers = { host: "example.com", origin: "https://example.com", "x-forwarded-proto": "https" };
  assert(validAdminOrigin(new Request("http://localhost:3100/admin/promotion-settings", { headers })));
  assert(!validAdminOrigin(new Request("http://localhost:3100/admin/promotion-settings", { headers: { ...headers, origin: "https://other.example.com", "x-forwarded-host": "other.example.com" } })));
});

test("management relay seals credentials and binds purpose, direction and request ID", () => {
  setup();
  const key = randomBytes(32);
  process.env.INSIGHTS_RELAY_KEY = key.toString("base64url") + "=";
  const request = sealAdmin({ method: "GET", path: "/admin/experiments", query: "", body: "", headers: {} });
  assert(!JSON.stringify(request).includes("synthetic-password"));
  const iv = randomBytes(12), cipher = createCipheriv("aes-256-gcm", key, iv);
  cipher.setAAD(Buffer.from(`admin-bridge:v1:response:${request.id}`));
  const value = { status: 409, content_type: "application/json", body: '{"detail":"revision conflict"}' };
  const data = Buffer.concat([cipher.update(JSON.stringify(value)), cipher.final(), cipher.getAuthTag()]);
  const envelope = { version: 1, id: request.id, iv: iv.toString("base64url"), data: data.toString("base64url") };
  assert.deepEqual(openAdmin(envelope, request.id), value);
  assert.throws(() => openAdmin(request, request.id));
  assert.throws(() => openAdmin(envelope, "other-request"));
  data[0] ^= 1;
  assert.throws(() => openAdmin({ ...envelope, data: data.toString("base64url") }, request.id));
});

test("route allowlist preserves experiment namespaces and denies arbitrary proxying", () => {
  assert(allowedAdmin("POST", "/admin/api/button-experiments/3/running"));
  assert(allowedAdmin("POST", "/admin/api/experiments/3/enrollment"));
  assert(!allowedAdmin("POST", "/admin/api/experiments/3/running"));
  assert(!allowedAdmin("POST", "/admin/api/button-experiments/3/enrollment"));
  for (const page of ["/admin/experiments", "/admin/events", "/admin/recommendations", "/admin/restaurants", "/admin/assets/admin_nav.css"]) assert(!allowedAdmin("GET", page));
  for (const path of ["https://example.com/admin/events", "/admin/workspace/relay", "/admin/%65vents", "/admin/events/", "/admin/api/experiments/0/results"]) assert(!allowedAdmin("GET", path));
});

test("admin documents and shared CSS are local and never fetch the FastAPI HTML", async () => {
  setup();
  const fetch = mock.method(globalThis, "fetch", async () => { throw Error("Unexpected backend request"); });
  try {
    for (const route of ["/admin/recommendations", "/admin/experiments", "/admin/experiments/new", "/admin/events", "/admin/restaurants", "/admin/assets/admin_nav.css"]) {
      assert.equal((await GET(new Request("https://example.com" + route))).status, 401);
      const response = await GET(new Request("https://example.com" + route, { headers: { authorization } }));
      assert.equal(response.status, 200);
      assert.match(response.headers.get("cache-control")!, /no-store/);
      assert((await response.text()).length > 500);
    }
    assert.equal(fetch.mock.callCount(), 0);
  } finally { fetch.mock.restore(); }
});

test("administrator shell keeps the complete existing form and same-origin navigation", () => {
  const html = renderAdminHTML('<html><head></head><body class="admin-unified"><header class="admin-topbar">old nav</header><main><form id="editor"></form><a href="/admin/insights#fortune">운세</a></main><script>existingEditor()</script></body></html>', "/admin/recommendations");
  assert(html.includes('<form id="editor"></form>'));
  assert(html.includes('<script>existingEditor()</script>'));
  assert(html.includes('href="/insights/fortune"'));
  assert(html.includes('href="/admin/experiments"'));
  assert(html.includes('href="/admin/events"'));
  assert(html.includes('href="/admin/restaurants"'));
  assert(!html.includes('old nav'));
  assert(html.includes('id="main"'));
  assert(html.includes('cnu-workspace-theme'));
});
