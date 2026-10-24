"""Fortune metrics and a limited birth-information table for authenticated admins."""
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet, InvalidToken

from app.database import get_pool
# Reporting only needs the stored profile format, not the fortune calculation engine.
KST = ZoneInfo("Asia/Seoul")
BIRTHPLACE_LABELS = dict(zip(
    ("seoul", "busan", "daegu", "incheon", "gwangju", "daejeon", "ulsan", "sejong",
     "suwon", "chuncheon", "gangneung", "cheongju", "cheonan", "jeonju", "mokpo",
     "pohang", "changwon", "jeju"),
    ("서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "수원", "춘천",
     "강릉", "청주", "천안", "전주", "목포", "포항", "창원", "제주"),
))


def unseal(value):
    key = os.environ.get("FORTUNE_ENCRYPTION_KEY", "").encode()
    return json.loads(Fernet(key).decrypt(bytes(value)))

RECENT_USER_LIMIT = 100


async def recent_users(conn, start_date, end_date, excluded):
    rows = await conn.fetch("""WITH latest AS (
        SELECT DISTINCT ON (user_id) user_id,created_at,id,properties
        FROM user_events
        WHERE event_name='fortune_response_created' AND properties->>'feature'='fortune'
          AND user_id IS NOT NULL AND NOT(user_id=ANY($3::text[]))
          AND ($1::date IS NULL OR created_at>=($1::date::timestamp AT TIME ZONE 'Asia/Seoul'))
          AND ($2::date IS NULL OR created_at<(($2::date+1)::timestamp AT TIME ZONE 'Asia/Seoul'))
        ORDER BY user_id,created_at DESC,id DESC
    ), recent AS (
        SELECT * FROM latest ORDER BY created_at DESC,id DESC LIMIT $4
    ) SELECT recent.created_at,v.payload FROM recent
      LEFT JOIN fortune_profile_versions v
        ON v.user_id=recent.user_id AND v.id::text=(recent.properties->>'profile_id')
      ORDER BY recent.created_at DESC,recent.id DESC""",
      start_date, end_date, excluded, RECENT_USER_LIMIT)
    users = []
    for row in rows:
        user = {"last_view_at": row["created_at"].astimezone(KST).strftime("%m/%d %H:%M:%S"),
                "birth_year": "—", "sex": "—", "birthplace": "—"}
        if row["payload"] is not None:
            try:
                birth = unseal(row["payload"])["input"]
                year = birth.get("birth_year")
                if type(year) is int and 1900 <= year <= 2050:
                    user["birth_year"] = f"{year}년생"
                user["sex"] = {"male": "남성", "female": "여성"}.get(birth.get("sex"), "—")
                user["birthplace"] = BIRTHPLACE_LABELS.get(birth.get("birthplace"), "—")
            except (InvalidToken, ValueError, KeyError, TypeError, AttributeError):
                # Keep metrics usable when the key or an old profile is unavailable.
                # Never include decrypted data or exception details in logs/HTML.
                pass
        users.append(user)
    return users


async def summary(start_date=None, end_date=None, *, include_recent=True):
    excluded = {value.strip() for value in os.getenv("EXPERIMENT_QA_IDS", "").split(",") if value.strip()}
    if os.getenv("DEVELOPER_ID", "").strip():
        excluded.add(os.environ["DEVELOPER_ID"].strip())
    today = datetime.now(KST).date()
    async with get_pool().acquire() as conn:
        totals = await conn.fetchrow("""WITH scoped AS (
            SELECT * FROM user_events WHERE properties->>'feature'='fortune'
              AND (user_id IS NULL OR NOT(user_id=ANY($3::text[])))
              AND ($1::date IS NULL OR created_at>=($1::date::timestamp AT TIME ZONE 'Asia/Seoul'))
              AND ($2::date IS NULL OR created_at<(($2::date+1)::timestamp AT TIME ZONE 'Asia/Seoul'))
        ), initial_open AS (
            SELECT user_id,MIN(created_at) AS opened_at FROM scoped
            WHERE event_name='fortune_profile_form_opened' AND properties->>'is_edit'='false' AND user_id IS NOT NULL
            GROUP BY user_id
        ) SELECT
            (SELECT COUNT(DISTINCT user_id) FROM scoped WHERE event_name='fortune_entered')::int AS entered_users,
            (SELECT COUNT(*) FROM initial_open)::int AS registration_started_users,
            (SELECT COUNT(*) FROM initial_open o WHERE EXISTS(SELECT 1 FROM scoped s WHERE s.user_id=o.user_id
                AND s.event_name='fortune_profile_saved' AND s.created_at>=o.opened_at))::int AS registration_completed_users,
            COUNT(DISTINCT request_id) FILTER(WHERE event_name='fortune_requested' OR
                (event_name='fortune_failed' AND properties->>'route' IN ('home','today')))::int AS result_requests,
            COUNT(DISTINCT request_id) FILTER(WHERE event_name='fortune_response_created')::int AS result_responses,
            COUNT(DISTINCT user_id) FILTER(WHERE event_name='fortune_response_created')::int AS result_users,
            COUNT(*) FILTER(WHERE event_name='fortune_failed')::int AS errors
        FROM scoped""", start_date, end_date, list(excluded))
        retention = await conn.fetchrow("""WITH successes AS (
            SELECT user_id,created_at,(created_at AT TIME ZONE 'Asia/Seoul')::date AS day
            FROM user_events WHERE event_name='fortune_response_created' AND properties->>'feature'='fortune'
              AND user_id IS NOT NULL AND NOT(user_id=ANY($3::text[]))
        ), first_success AS (
            SELECT user_id,MIN(day) AS day FROM successes GROUP BY user_id
        ), cohort AS (
            SELECT * FROM first_success WHERE ($1::date IS NULL OR day>=$1) AND ($2::date IS NULL OR day<=$2)
        ) SELECT
            COUNT(*) FILTER(WHERE c.day+1<$4::date)::int AS d1_eligible,
            COUNT(*) FILTER(WHERE c.day+1<$4::date AND EXISTS(SELECT 1 FROM successes s WHERE s.user_id=c.user_id AND s.day=c.day+1))::int AS d1_returned,
            COUNT(*) FILTER(WHERE c.day+7<$4::date)::int AS d7_eligible,
            COUNT(*) FILTER(WHERE c.day+7<$4::date AND EXISTS(SELECT 1 FROM successes s WHERE s.user_id=c.user_id AND s.day>c.day AND s.day<=c.day+7))::int AS d7_returned
        FROM cohort c""", start_date, end_date, list(excluded), today)
        lifecycle = await conn.fetch("""WITH days AS MATERIALIZED (
            SELECT user_id,(created_at AT TIME ZONE 'Asia/Seoul')::date AS day
            FROM user_events WHERE event_name='fortune_response_created' AND properties->>'feature'='fortune'
              AND user_id IS NOT NULL AND NOT(user_id=ANY($3::text[])) GROUP BY 1,2
        ), firsts AS (SELECT user_id,MIN(day) AS first_day FROM days GROUP BY 1)
        SELECT d.day,COUNT(*)::int AS users,
            COUNT(*) FILTER(WHERE d.day=f.first_day)::int AS new_users,
            COUNT(*) FILTER(WHERE d.day>f.first_day)::int AS returning_users
        FROM days d JOIN firsts f USING(user_id)
        WHERE ($1::date IS NULL OR d.day>=$1) AND ($2::date IS NULL OR d.day<=$2)
        GROUP BY d.day ORDER BY d.day DESC LIMIT 30""",start_date,end_date,list(excluded))
        cohorts = await conn.fetch("""WITH days AS MATERIALIZED (
            SELECT user_id,(created_at AT TIME ZONE 'Asia/Seoul')::date AS day
            FROM user_events WHERE event_name='fortune_response_created' AND properties->>'feature'='fortune'
              AND user_id IS NOT NULL AND NOT(user_id=ANY($3::text[])) GROUP BY 1,2
        ), firsts AS (SELECT user_id,MIN(day) AS day FROM days GROUP BY 1), cohort AS (
            SELECT * FROM firsts WHERE ($1::date IS NULL OR day>=$1) AND ($2::date IS NULL OR day<=$2)
        ) SELECT c.day,offsets.n AS offset,COUNT(*)::int AS users,
            CASE WHEN c.day+offsets.n<$4::date THEN COUNT(*)::int ELSE 0 END AS eligible,
            CASE WHEN c.day+offsets.n<$4::date THEN COUNT(d.user_id)::int ELSE 0 END AS returned
        FROM cohort c CROSS JOIN generate_series(1,7) offsets(n)
        LEFT JOIN days d ON d.user_id=c.user_id AND d.day=c.day+offsets.n
        GROUP BY c.day,offsets.n ORDER BY c.day DESC,offsets.n LIMIT 210""",start_date,end_date,list(excluded),today)
        recent = await recent_users(conn, start_date, end_date, list(excluded)) if include_recent else None
    result = {**dict(totals), **dict(retention), "daily": [dict(r) for r in reversed(lifecycle)],
              "cohorts": [dict(r) for r in cohorts]}
    if recent is not None:
        result["recent_users"] = recent
    return result
