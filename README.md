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

상품 자동 추천은 `product-collector` 서비스가 하루 4회 수집한 저장 데이터를 사용합니다. 새로고침은 사용자별 노출 이력으로 상품을 순환합니다. 수집 일정·장애 시 동작·수동 실행은 [상품 배치 수집](docs/product-collection.md)을 참고하세요.

## Stack

FastAPI · Uvicorn · PostgreSQL · Docker Compose
