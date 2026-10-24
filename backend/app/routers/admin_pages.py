"""Authenticated redirects for bookmarks of the retired FastAPI UI."""
import os
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.routers.admin import require_admin

router = APIRouter(dependencies=[Depends(require_admin)])
PAGES = {
    '': '/admin/recommendations',
    '/': '/admin/recommendations',
    '/recommendations': '/admin/recommendations',
    '/events': '/admin/events',
    '/restaurants': '/admin/restaurants',
    '/experiments': '/admin/experiments',
    '/experiments/new': '/admin/experiments/new',
    '/experiments/legacy': '/admin/experiments',
    '/experiments/legacy/new': '/admin/experiments',
    '/insight': '/admin/insights',
    '/insights': '/admin/insights',
    '/insights/fortune/users': '/insights/fortune',
    **{f'/insights/{report}': f'/insights/{report}' for report in
       ('overview', 'fortune', 'restaurants', 'shuttle', 'products', 'quality', 'revenue')},
}


def web_origin():
    value = os.getenv('ADMIN_WEB_ORIGIN', '').strip()
    if not value:
        try:
            value = (Path(os.getenv('MENU_DATA_DIR', 'data')) / '.admin-web-origin').read_text().strip()
        except OSError:
            pass
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ('https', 'http') or not parsed.hostname or
                parsed.username or parsed.password or parsed.path not in ('', '/') or
                parsed.query or parsed.fragment or any(c.isspace() for c in value)):
            raise ValueError('Invalid origin')
        _ = parsed.port
    except ValueError:
        raise HTTPException(503, '관리자 웹 주소 설정을 확인해 주세요.')
    return value.rstrip('/')


def redirect_to(destination):
    async def redirect(request: Request):
        # Only report filters survive. Host, next and redirect query parameters
        # never control the destination; credentials are never forwarded.
        query = urlencode({key: value for key, value in request.query_params.items()
                           if key in {'start_date', 'end_date', 'all_time', 'refresh'}})
        return RedirectResponse(web_origin() + destination + ('?' + query if query else ''),
                                status_code=303, headers={'Cache-Control': 'private, no-store'})
    return redirect


for source, destination in PAGES.items():
    router.add_api_route(source, redirect_to(destination), methods=['GET'], include_in_schema=False)
