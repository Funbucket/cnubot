export const adminSections = [
  { key: "insights", label: "인사이트", href: "/insights/overview", icon: "chart" },
  { key: "recommendations", label: "상품·버튼 관리", href: "/admin/recommendations", icon: "products" },
  { key: "experiments", label: "실험실", href: "/admin/experiments", icon: "quality" },
  { key: "events", label: "이벤트 수집", href: "/admin/events", icon: "table" },
  { key: "restaurants", label: "맛집 관리", href: "/admin/restaurants", icon: "restaurants" },
] as const;

const destinations: Record<string, RegExp[]> = {
  GET: [
    /^\/admin\/promotion-settings(\/collection-status|\/diagnostic)?$/,
    /^\/admin\/restaurants\/catalog$/,
    /^\/admin\/api\/(experiments|button-experiments)$/,
    /^\/admin\/api\/button-experiments\/[1-9][0-9]*$/,
    /^\/admin\/api\/experiments\/[1-9][0-9]*\/(results|diagnostics)$/,
  ],
  POST: [
    /^\/admin\/promotion-settings\/(parse|preview)$/,
    /^\/admin\/restaurants\/(search|preview)$/,
    /^\/admin\/api\/experiments$/,
    /^\/admin\/api\/experiments\/[1-9][0-9]*\/(enrollment|stop|analysis-runs|simulation|preview|preview-override|decision)$/,
    /^\/admin\/api\/button-experiments\/[1-9][0-9]*\/(running|paused|completed)$/,
  ],
  PUT: [
    /^\/admin\/promotion-settings$/,
    /^\/admin\/restaurants\/catalog$/,
    /^\/admin\/api\/experiments\/[1-9][0-9]*$/,
  ],
  DELETE: [/^\/admin\/api\/experiments\/[1-9][0-9]*\/preview-override$/],
};

export function allowedAdmin(method: string, path: string) {
  return destinations[method]?.some((pattern) => pattern.test(path)) ?? false;
}

export function validAdminOrigin(request: Request) {
  const origin = request.headers.get("origin");
  const url = new URL(request.url);
  // Next.js may use its internal hostname in Request.url. Host identifies the
  // browser-facing origin; Vercel supplies the protocol after TLS termination.
  const host = request.headers.get("host") || url.host;
  const forwardedProtocol = request.headers.get("x-forwarded-proto");
  const protocol = forwardedProtocol === "http" || forwardedProtocol === "https" ? forwardedProtocol + ":" : url.protocol;
  return origin === `${protocol}//${host}` &&
    request.headers.get("sec-fetch-site") !== "cross-site";
}
