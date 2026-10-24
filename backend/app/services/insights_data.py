"""Read-only JSON reports shared by the Next.js dashboard and its encrypted relay."""
from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from app.database import get_pool
from app.services import campus_insights, fortune_insights, insights_overview, promotion_insights, toss_revenue
from app.services.insights_cache import cached

ReportName = Literal['overview', 'fortune', 'restaurants', 'shuttle', 'products', 'quality', 'revenue', 'fortune-users']


class ReportQuery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    report: ReportName
    start_date: date | None = None
    end_date: date | None = None
    all_time: bool = False
    refresh: bool = False

    @model_validator(mode='after')
    def valid_period(self):
        if self.all_time and (self.start_date or self.end_date):
            raise ValueError('전체 기간과 날짜 조건을 함께 사용할 수 없습니다.')
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError('시작일은 종료일보다 늦을 수 없습니다.')
        return self

    def dates(self):
        if not self.all_time and self.start_date is None and self.end_date is None:
            end = datetime.now(insights_overview.KST).date()
            return end - timedelta(days=6), end
        return self.start_date, self.end_date


async def load_report(query: ReportQuery):
    start, end = query.dates()
    report = query.report
    if report == 'fortune-users':
        # Never decrypt or cache personal source data during aggregate requests.
        async with get_pool().acquire() as conn:
            data = await fortune_insights.recent_users(conn, start, end, insights_overview.excluded_users())
    elif report == 'revenue':
        data = await toss_revenue.get_revenue(start, end)
    else:
        if report == 'overview':
            key, loader = 'overview', lambda: insights_overview.summary(start, end)
        elif report == 'fortune':
            key, loader = 'fortune', lambda: fortune_insights.summary(start, end, include_recent=False)
        elif report in ('restaurants', 'shuttle'):
            key, loader = report, lambda: campus_insights.summary(report, start, end)
        else:
            key, loader = 'promotion', lambda: promotion_insights.get_promotion_insights(get_pool(), start, end)
        data = await cached((key, start, end), loader, refresh=query.refresh)
        if report == 'products':
            data = {k: data[k] for k in ('totals', 'daily', 'paths', 'products') if k in data}
        elif report == 'quality':
            data = {k: data[k] for k in ('guardrails', 'entry_labels', 'positions', 'fatigue', 'surfaces', 'collections') if k in data}
    return {'report': report, 'start_date': start, 'end_date': end,
            'timezone': 'Asia/Seoul', 'requested_at': datetime.now(insights_overview.KST), 'data': data}
