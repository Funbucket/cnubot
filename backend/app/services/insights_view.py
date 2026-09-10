"""Server-rendered promotion dashboard. Ratios retain their own denominators."""
import html
from datetime import date, datetime, timedelta
from pathlib import Path
from string import Template
from zoneinfo import ZoneInfo


def esc(value):
    return html.escape(str(value or ""), quote=True)


def rate(clicks, reach):
    return f"{clicks / reach * 100:.1f}%" if reach else "—"


def table(headers, rows, empty="선택한 기간에 수집된 데이터가 없습니다.", attributes=""):
    body = "".join(rows) or f'<tr><td colspan="{len(headers)}" class="empty">{empty}</td></tr>'
    return f'<div class="table-wrap"><table {attributes}><thead><tr>' + "".join(f'<th scope="col">{h}</th>' for h in headers) + f'</tr></thead><tbody>{body}</tbody></table></div>'


def row(*cells):
    return '<tr>' + ''.join(f'<td>{cell}</td>' for cell in cells) + '</tr>'


def render_insights(data):
    paths = {p['path']: p for p in data.get('paths', [])}
    entry, inline = paths.get('entry', {}), paths.get('inline', {})
    today = datetime.now(ZoneInfo('Asia/Seoul')).date()
    start, end = data.get('start_date'), data.get('end_date')
    period = f"{start or '수집 시작'} → {end or '현재'}"
    presets = ''.join(f'<a class="preset{" selected" if start == today - timedelta(days=days-1) and end == today else ""}" href="?start_date={today-timedelta(days=days-1)}&amp;end_date={today}">{label}</a>' for days, label in [(1, '오늘'), (7, '7일'), (30, '30일')])
    presets += f'<a class="preset{" selected" if not start and not end else ""}" href="?all_time=true">전체</a>'
    cards = []
    for label, p, metric, note in [
        ('버튼 경유 · 상품 클릭', entry, 'clicked_users', '버튼에서 상품 목록으로 이동한 경로'),
        ('바로 노출 · 상품 클릭', inline, 'clicked_users', '학식 응답 안에 상품이 바로 보이는 경로'),
    ]:
        reach, clicked = p.get('reach_users', 0), p.get(metric, 0)
        cards.append(f'<article class="metric"><span>{label}</span><strong>{clicked:,}<small>명</small></strong><p>접점 노출 {reach:,}명 <span class="pill">클릭률 {rate(clicked, reach)}</span></p><small>{note}</small></article>')
    products = data.get('products', [])
    active = sum(1 for p in products if p.get('clicked_users', 0))
    cards.append(f'<article class="metric"><span>클릭이 발생한 상품</span><strong>{active:,}<small>개</small></strong><p>관측된 상품 {len(products):,}개 중</p><small>상품별 성과에서 클릭이 집중된 상품을 확인하세요.</small></article>')
    observations = []
    if not any(p.get('reach_users') or p.get('clicked_users') for p in paths.values()):
        observations.append(('데이터를 기다리고 있어요', '기간을 넓혀 보세요. 데이터가 수집되면 경로별 성과와 상품 순위가 표시됩니다.'))
    else:
        if entry.get('reach_users'):
            observations.append(('버튼에서 얼마나 이동했나요?', f"버튼을 본 {entry['reach_users']:,}명 중 {entry.get('action_users', 0):,}명이 반응했습니다. 버튼 반응률은 {rate(entry.get('action_users', 0), entry['reach_users'])}입니다."))
        if products:
            best = max(products, key=lambda p: p.get('clicked_users', 0))
            if best.get('clicked_users'):
                observations.append(('가장 많은 사람이 클릭한 상품', f"{best.get('product_name') or best['product_key']} · {best['clicked_users']:,}명. 아래에서 노출 규모와 함께 비교하세요."))
        if any(p.get('clicked_users', 0) > p.get('reach_users', 0) for p in paths.values()):
            observations.append(('노출과 클릭의 집계 범위를 확인하세요', '노출보다 클릭한 사용자가 많은 경로가 있습니다. 기간 밖 노출이나 누락된 노출 기록이 있는지 확인하세요.'))
    observation_html = ''.join(f'<div class="observation"><b>{esc(title)}</b><p>{esc(note)}</p></div>' for title, note in observations)
    totals = data.get('totals') or {}
    flows = []
    for key, title, note in [('entry', '버튼을 거쳐 상품 보기', '버튼 노출 → 버튼 클릭 → 상품 노출 → 상품 클릭'), ('inline', '학식에서 상품 바로 보기', '상품 노출 → 상품 클릭')]:
        p = paths.get(key, {})
        # Path aggregates are independent unique-user counts. A funnel needs the
        # attributed cohort in totals, or a later step can exceed an earlier one.
        steps = [('버튼 노출', totals.get('entry_exposed_users', 0)), ('버튼 클릭', totals.get('entry_users', 0)), ('상품 노출', totals.get('exposed_users', 0)), ('상품 클릭', totals.get('clicked_users', 0))] if key == 'entry' else [('상품 노출', p.get('reach_users', 0)), ('상품 클릭', p.get('clicked_users', 0))]
        peak = max([v for _, v in steps] + [1])
        bars = ''.join(f'<div class="flow-step"><div><span><em>{i:02}</em>{label}</span><b>{value:,}<small> 명</small></b></div><div class="track"><div style="width:{value / peak * 100:.2f}%"></div></div></div>' for i, (label, value) in enumerate(steps, 1))
        # 하단 요약도 퍼널과 같은 코호트를 써야 두 숫자가 어긋나지 않는다.
        first, last = steps[0][1], steps[-1][1]
        flows.append(f'<article class="panel flow"><span class="tag">{"버튼 경유" if key == "entry" else "바로 노출"}</span><h3>{title}</h3><p class="muted">{note}</p>{bars}<footer>접점 대비 상품 클릭률 <b>{rate(last, first)}</b></footer></article>')
    product_rows = []
    for index, p in enumerate(sorted(products, key=lambda p: p.get('clicked_users', 0), reverse=True), 1):
        name = p.get('product_name') or p['product_key']
        exposed, clicked = p.get('exposed_users', 0), p.get('clicked_users', 0)
        product_rows.append(f'<tr data-product data-name="{esc(name)} {esc(p.get("category_name"))} {esc(p["product_key"])}" data-clicks="{clicked}" data-reach="{exposed}" data-rate="{clicked/exposed if exposed else -1}"><td><span class="rank">{index:02}</span><div><b>{esc(name)}</b><small>{esc(p.get("category_name") or "카테고리 미상")}</small><details class="product-id"><summary>상품 ID</summary><code>{esc(p["product_key"])}</code></details></div></td><td>{exposed:,}</td><td><b>{clicked:,}</b></td><td>{rate(clicked, exposed)}</td><td>{p.get("click_events", 0):,}</td></tr>')
    product_table = table(['상품', '노출 사용자', '클릭 사용자 ↓', '클릭률', '클릭 횟수'], product_rows, attributes='id="products-table"')
    daily = sorted(data.get('daily', []), key=lambda r: str(r['day']))
    peak = max([r['clicked_users'] for r in daily] + [1])
    chart = ''.join(f'<div class="chart-day" tabindex="0" aria-label="{esc(r["day"])}: 클릭 {r["clicked_users"]:,}명"><div class="chart-tip">{esc(r["day"])}<br>클릭 {r["clicked_users"]:,}명</div><div class="chart-bar" style="height:{max(2, r["clicked_users"]/peak*100):.1f}%;opacity:{1 if r["clicked_users"] else .2}"></div><small>{str(r["day"])[5:]}</small></div>' for r in daily)
    if not daily:
        chart = '<p class="empty">아직 일별 클릭 데이터가 없습니다.</p>'
    daily_table = table(['날짜 (KST)', '노출 사용자', '클릭 사용자', '클릭 횟수'], [row(esc(r['day']), f'{r["exposed_users"]:,}', f'{r["clicked_users"]:,}', f'{r["click_events"]:,}') for r in reversed(daily)])
    messages = table(['버튼 문구 / 위치', '버튼 노출 사용자', '버튼 클릭 사용자', '버튼 클릭률', '상품 클릭 사용자'], [row(f'<b>{esc(r["label"])}</b><small>{esc(r.get("source"))}</small>', f'{r["exposed_users"]:,}', f'{r["entry_users"]:,}', rate(r['entry_users'], r['exposed_users']), f'{r["card_clicked_users"]:,}') for r in data.get('entry_labels', [])])
    positions = table(['카드 위치', '노출 사용자', '클릭 사용자', '클릭률'], [row(f'{r["row"]}행 {r["column"]}열', f'{r["exposed_users"]:,}', f'{r["clicked_users"]:,}', rate(r['clicked_users'], r['exposed_users'])) for r in data.get('positions', [])])
    fatigue = table(['경로', '기간 내 노출 순서', '노출 횟수', '반응 횟수', '반응률'], [row('바로 노출' if r['path'] == 'inline' else '버튼 경유', f'{r["nth"]}회차' + (' 이상' if r['nth'] >= 6 else ''), f'{r["impressions"]:,}', f'{r["actions"]:,}', rate(r['actions'], r['impressions'])) for r in data.get('fatigue', [])])
    guardrail_rows = []
    for g in data.get('guardrails', []):
        if g.get('return_rate_pending'):
            retention = '<small>집계 중</small>'
        elif not g.get('return_rate_measurable'):
            retention = '<small>측정 불가</small>'
        else:
            retention = f'<b>{g["return_rate"]:.1f}%</b><small>{g["returned_users"]:,}명 복귀</small>'
        views = f'{g["views_per_user"]:.2f}회<small>{g["menu_views"]:,}회 / {g["menu_view_users"]:,}명</small>' if g.get('menu_view_users') else '<small>계측 전</small>'
        guardrail_rows.append(row(esc(g['day']), f'{g["active_users"]:,}', views, retention))
    guardrails = table(['날짜 (KST)', '활성 사용자', '1인당 학식 조회', '다음날 재방문'], guardrail_rows)
    surfaces = table(['클릭 위치', '클릭 사용자', '클릭 횟수'], [row(esc({'commerce_card': '상품 카드', 'menu_button': '학식 메뉴 버튼', 'quick_reply': '퀵리플라이', 'promotion_block': '기타 프로모션'}.get(r['surface'], r['surface'])), f'{r["users"]:,}', f'{r["events"]:,}') for r in data.get('surfaces', [])])
    template = Template((Path(__file__).parent.parent / 'static' / 'insights.html').read_text())
    return template.substitute(period=esc(period), start=esc(start), end=esc(end), today=today.isoformat(), presets=presets, cards=''.join(cards), observations=observation_html, flows=''.join(flows), products=product_table, chart=chart, daily=daily_table, messages=messages, positions=positions, fatigue=fatigue, guardrails=guardrails, surfaces=surfaces)
