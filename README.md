# cnubot

충남대학교 학생을 위한 카카오톡 챗봇 서버입니다.

학식, 셔틀, 기숙사 식당 혼잡도, 쇼핑 특가 정보를 제공합니다.

## Getting started

```bash
docker compose up -d
```

## Test

```bash
docker compose exec -T backend sh -lc \
  "PYTHONPATH=/code/app python -m unittest discover -s /code/tests"
```

## Menu data

```bash
docker compose exec -T backend python -m app.jobs.scrape_menus all
```

수집된 메뉴는 `data/menus/`에 저장됩니다.

## Stack

FastAPI · Uvicorn · PostgreSQL · Docker Compose
