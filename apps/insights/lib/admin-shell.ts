import { adminSections } from "./admin-navigation";

// These pages keep their existing, tested forms and event handlers. They are
// served on the Next.js origin with the same workspace navigation and tokens.
const theme = `
body.admin-workspace{--green:#194b7e;--ink:#202833;--muted:#646b76;--line:#e1e5eb;margin:0;background:#f5f6f8;color:#202833;font:14px/1.6 "Inter","Noto Sans KR",sans-serif;font-variant-numeric:tabular-nums}
.admin-workspace *{box-sizing:border-box}
.admin-workspace fieldset{min-inline-size:0;min-width:0;max-width:100%}.admin-workspace .grid>*{min-width:0}
body.admin-workspace main#main,body.admin-workspace main.shell#main{max-width:none;min-width:0;width:auto;margin:0 0 0 220px;padding:30px 32px 140px}
.admin-workspace .cnu-sidebar{position:fixed;inset:0 auto 0 0;z-index:25;width:220px;background:#fff;border-right:1px solid #e1e5eb;padding:24px 16px;overflow-y:auto}
.admin-workspace .cnu-brand{display:flex;align-items:center;gap:10px;margin:0 6px 28px;text-decoration:none;font-size:18px;font-weight:750;color:#194b7e}
.cnu-brand-mark{display:grid;place-items:center;width:30px;height:32px;background:#194b7e;color:white;clip-path:polygon(25% 0,75% 0,100% 50%,75% 100%,25% 100%,0 50%);font-size:14px}
.cnu-project{display:flex;gap:10px;align-items:center;padding:12px;background:#f0f2f5;border:1px solid #e1e5eb;border-radius:4px;margin-bottom:24px;font-weight:600;font-size:13px}
.cnu-project small{display:block;color:#646b76;font-weight:400;font-size:11px}.cnu-project>span{display:grid;place-items:center;flex-shrink:0;width:26px;height:26px;border-radius:4px;background:#e2e6ed;color:#646b76}
.cnu-nav-label{font-size:10px;color:#646b76;letter-spacing:.04em;margin:20px 10px 8px}
.admin-workspace .cnu-navigation{display:flex;flex-direction:column;gap:4px;line-height:normal}
.admin-workspace .cnu-navigation a{display:flex;gap:12px;align-items:center;min-height:40px;padding:10px 12px;border-radius:4px;font-size:13px;font-weight:550;text-decoration:none;color:#46505d;white-space:nowrap}
.admin-workspace .cnu-navigation a:hover{background:#f0f3f7}.admin-workspace .cnu-navigation a[aria-current=page]{background:#194b7e;color:#fff}
.cnu-navigation svg{width:17px;height:17px;flex-shrink:0}.cnu-sidebar-foot{margin:32px 10px 0;border-top:1px solid #e1e5eb;padding-top:16px;color:#646b76;font-size:11px}
.admin-workspace .cnu-topbar{display:flex;align-items:center;justify-content:space-between;gap:16px;height:60px;margin-left:220px;padding:0 32px;background:#f5f6f8;color:#646b76;font-size:12px}.cnu-topbar b{padding:0 12px;font-weight:400;color:#9aa3af}.cnu-topbar .cnu-private{white-space:nowrap;font-size:11px}.cnu-private:before{content:"";display:inline-block;width:5px;height:5px;background:#194b7e;border-radius:50%;margin-right:7px}
.admin-workspace .page-heading,.admin-workspace .admin-page-heading{margin:0 0 24px;display:block}.admin-workspace h1,.admin-workspace #title{font-size:24px;line-height:1.4;letter-spacing:-.04em;margin:0 0 8px}.admin-workspace h2{font-size:17px;line-height:1.5}.admin-workspace h3{font-size:14px}.admin-workspace .eyebrow{color:#646b76;letter-spacing:.04em;font-size:10px}.admin-workspace .page-heading p,.admin-workspace .admin-page-heading p{color:#646b76;font-size:13px}
.admin-workspace .card,.admin-workspace .panel,.admin-workspace .metric,.admin-workspace .experiment-card,.admin-workspace form#new-experiment,.admin-workspace.admin-events main>section{border:1px solid #e1e5eb;border-radius:6px;background:#fff;box-shadow:none}.admin-workspace .metric strong{color:#194b7e}.admin-workspace .notice:not(.warning):not(.error),.admin-workspace .note,.admin-workspace .step,.admin-workspace .inline-note{background:#edf3f9;color:#38516a;border-color:#cedbea;border-radius:4px}.admin-workspace .notice{border-left-color:#194b7e}.admin-workspace .step b,.admin-workspace .links a{color:#194b7e}
.admin-workspace button{min-height:38px;border:1px solid #194b7e;background:#194b7e;color:#fff;border-radius:4px;padding:8px 12px;font-family:inherit;font-size:13px;font-weight:550;line-height:1.5;cursor:pointer}.admin-workspace button.secondary{background:#fff;border-color:#bdc8d6;color:#194b7e}.admin-workspace button.danger{color:#b03232;border-color:#dfb6b6;background:#fff}.admin-workspace button:disabled{opacity:.5;cursor:default}.admin-workspace .tabs button{background:transparent;border-color:transparent;color:#646b76;border-radius:0}.admin-workspace .tabs button[aria-selected=true]{color:#194b7e;border-bottom-color:#194b7e;background:#edf3f9}
.admin-workspace input,.admin-workspace textarea,.admin-workspace select{border-color:#bdc8d6;border-radius:4px;color:#202833;font-family:inherit;accent-color:#194b7e}.admin-workspace input[type=checkbox],.admin-workspace input[type=radio]{accent-color:#194b7e}.admin-workspace a{color:#194b7e}.admin-workspace :focus-visible{outline:2px solid #194b7e;outline-offset:3px}
.admin-workspace button.collection-option{background:#fff;border-color:#bdc8d6;color:#202833;border-radius:6px}.admin-workspace button.collection-option[aria-pressed=true],.admin-workspace .mode-options label:has(input:checked){background:#edf3f9;border-color:#194b7e}.admin-workspace .collection-option .state{color:#194b7e}.admin-workspace .collection-option span{color:#646b76}.admin-workspace .badge{background:#edf3f9;color:#194b7e;border-radius:4px}.admin-workspace .mode-options label,.admin-workspace .product,.admin-workspace .add-details{border-radius:6px}.admin-workspace .empty{border-radius:4px;background:#f5f6f8;color:#646b76}.admin-workspace .savebar{left:220px;right:0;border-color:#e1e5eb;background:#fff}.admin-workspace .save-info strong{color:#202833}.admin-workspace .batch-metrics>div{border-radius:4px;background:#f5f6f8}
.admin-workspace td,.admin-workspace th{border-bottom-color:#e1e5eb}.admin-workspace th{font-size:11px;color:#646b76;background:#f7f8fa}.admin-workspace pre{max-width:100%;border-radius:4px}.admin-workspace pre,.admin-workspace code{font-family:ui-monospace,SFMono-Regular,"Noto Sans KR",monospace}.admin-workspace .table-wrap{max-width:100%;overflow-x:auto}.admin-workspace .skip-link{position:fixed;top:-100px;left:16px;z-index:100;background:#194b7e;color:#fff;padding:10px}.admin-workspace .skip-link:focus{top:8px}
@media(max-width:1050px){body.admin-workspace main#main,body.admin-workspace main.shell#main{padding:24px 20px 140px}.admin-workspace .workspace{grid-template-columns:minmax(0,1fr)}.admin-workspace .preview-panel{position:static;max-height:none}}
@media(max-width:800px){.admin-workspace .cnu-sidebar{position:static;width:100%;padding:14px 16px 10px;border-right:0;border-bottom:1px solid #e1e5eb;overflow:hidden}.admin-workspace .cnu-brand{margin:0 0 12px;font-size:16px}.admin-workspace .cnu-project,.admin-workspace .cnu-nav-label,.admin-workspace .cnu-sidebar-foot{display:none}.admin-workspace .cnu-navigation{flex-direction:row;overflow-x:auto;max-width:100%;gap:4px;scrollbar-width:thin;padding-bottom:4px}.admin-workspace .cnu-navigation a{flex-shrink:0;min-height:38px;padding:9px 10px;font-size:12px;gap:7px}.admin-workspace .cnu-topbar{height:44px;margin:0;padding:0 16px;font-size:11px}.cnu-topbar b{padding:0 8px}.admin-workspace .cnu-private{font-size:10px}body.admin-workspace main#main,body.admin-workspace main.shell#main{margin:0;padding:18px 16px 160px}.admin-workspace .savebar{left:0}.admin-workspace h1,.admin-workspace #title{font-size:22px}.admin-workspace .collection-picker{gap:8px}.admin-workspace .collection-option strong{font-size:14px}.admin-workspace .collection-option span{font-size:11px}.admin-workspace .card,.admin-workspace.admin-events main>section{border-radius:6px;padding:16px}.admin-workspace .grid{min-width:0}.admin-workspace .flow{grid-template-columns:1fr}}
@media(max-width:380px){body.admin-workspace main#main,body.admin-workspace main.shell#main{padding-left:12px;padding-right:12px}.cnu-topbar .cnu-private{display:none}.admin-workspace .collection-picker{grid-template-columns:1fr}.admin-workspace .fields{grid-template-columns:1fr}.admin-workspace .section-top{flex-wrap:wrap}.admin-workspace .batch-metrics{grid-template-columns:1fr}}
`;

function menuIcon(icon: string) {
  const paths: Record<string, string> = {
    chart: '<path d="M3 3v18h18M6 15l4-5 4 2 6-8"/>',
    products: '<path d="m3 7 9-4 9 4-9 4-9-4Zm0 0v10l9 4 9-4V7M12 11v10"/>',
    quality: '<path d="M3 19h18M5 15l4-5 4 3 6-8M16 5h3v3"/>',
    table: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M3 14h18M9 4v16"/>',
    restaurants: '<path d="M7 3v6m-3-6v6a3 3 0 0 0 6 0V3M7 12v9m10-18c-3 3-3 8 0 9h3M20 3v18"/>',
  };
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[icon]}</svg>`;
}

export function renderAdminHTML(html: string, path: string) {
  const selected = adminSections.find((item) => path === item.href || path.startsWith(item.href + "/"));
  const navigation = `<a class="skip-link" href="#main">본문으로 이동</a><aside class="cnu-sidebar"><a href="/insights/overview" class="cnu-brand"><span class="cnu-brand-mark">C</span>CNU <small>Insights</small></a><div class="cnu-project"><span>C</span><div>CNU 챗봇<small>관리자 워크스페이스</small></div></div><p class="cnu-nav-label">워크스페이스</p><nav class="cnu-navigation" aria-label="관리자 메뉴">${adminSections.map((item) => `<a href="${item.href}"${item.key === selected?.key ? ' aria-current="page"' : ""}>${menuIcon(item.icon)}${item.label}</a>`).join("")}</nav><div class="cnu-sidebar-foot">관리자 워크스페이스<br>한국 표준시 · KST</div></aside><header class="cnu-topbar"><span>CNU 챗봇<b>/</b>${selected?.label ?? "관리자"}</span><span class="cnu-private">관리자 전용</span></header>`;
  html = html.replace(/<header\s+class="admin-topbar"[^>]*>[\s\S]*?<\/header>/i, "");
  html = html.replace(/<body([^>]*)>/i, (_, attributes: string) => {
    const attrs = /class="/.test(attributes) ? attributes.replace('class="', 'class="admin-workspace ') : attributes + ' class="admin-workspace"';
    return `<body${attrs}>${navigation}`;
  });
  html = html.replace(/<main([^>]*)>/i, (_, attributes: string) => `<main${/\bid=/.test(attributes) ? attributes : attributes + ' id="main"'}>`);
  html = html.replace(/href="\/admin\/insights#(fortune|restaurants|shuttle|products|revenue|quality)"/g, 'href="/insights/$1"');
  html = html.replaceAll('href="/admin/insights"', 'href="/insights/overview"');
  if (path === "/admin/experiments" || path === "/admin/experiments/new") {
    html = html.replace(/<\/head>/i, `<script>window.__cnubotExperimentEntryView=new URL(location.href).searchParams.get('view');</script><link rel="stylesheet" href="/experiment-detail.css"><script src="/experiment-report.js" defer></script><script src="/experiment-detail.js" defer></script></head>`);
  }
  html = html.replace(/<\/body>/i, `<script>const alignMenu=()=>{const nav=document.querySelector('.cnu-navigation'),active=nav?.querySelector('[aria-current="page"]');if(nav&&active&&nav.scrollWidth>nav.clientWidth)nav.scrollLeft=Math.max(0,active.offsetLeft-nav.offsetLeft-nav.clientWidth/2+active.offsetWidth/2)};window.addEventListener('load',alignMenu);document.fonts.ready.then(alignMenu);</script></body>`);
  return html.replace(/<\/head>/i, `<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&amp;family=Noto+Sans+KR:wght@400;500;600;700&amp;display=swap"><style id="cnu-workspace-theme">${theme}</style></head>`);
}
