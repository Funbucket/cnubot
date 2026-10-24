import { readFile } from "node:fs/promises";
import path from "node:path";
import { renderAdminHTML } from "./admin-shell";

const pages: Record<string, string> = {
  "/admin/recommendations": "promotion_editor.html",
  "/admin/experiments": "experiment_lab.html",
  "/admin/experiments/new": "experiment_lab.html",
  "/admin/events": "events.html",
  "/admin/restaurants": "restaurant_editor.html",
};

// Fixed names only: incoming paths never become filesystem paths.
export async function localAdminPage(route: string) {
  const file = pages[route] || (route === "/admin/assets/admin_nav.css" ? "admin_nav.css" : undefined);
  if (!file) return null;
  const source = await readFile(path.join(process.cwd(), "templates", "admin", file), "utf8");
  return file.endsWith(".css")
    ? { body: source, contentType: "text/css; charset=utf-8" }
    : { body: renderAdminHTML(source, route), contentType: "text/html; charset=utf-8" };
}

export function legacyInsightsRedirect() {
  // Old bookmarks used fragments, which servers cannot read. Resolve only the
  // known report names on the authenticated Next.js origin.
  return `<!doctype html><html lang="ko"><meta charset="utf-8"><title>인사이트</title><script>const names=['overview','fortune','restaurants','shuttle','products','revenue','quality'];const report=location.hash.slice(1);location.replace('/insights/'+(names.includes(report)?report:'overview')+location.search);</script><a href="/insights/overview">인사이트 열기</a></html>`;
}
