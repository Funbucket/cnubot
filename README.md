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

수집된 메뉴는 Compose의 공유 볼륨인 `data/`에 저장됩니다.

`dorm-menu-monitor`는 한국 시간 기준 **일요일 19:00부터 월요일 09:00까지** 15분 간격으로 기숙사 식단이 이번 주 월~일 날짜에 맞고, 7개 요일과 메뉴 항목이 정상인지 확인합니다. 그 외 시간에는 자동 검증·수집을 하지 않습니다. 파일이 없거나 손상·누락·지난주 데이터이면 공식 식단 1페이지부터 확인하고, 필요하면 2페이지를 확인해 이번 주 식단만 원자적으로 저장합니다. 연말에는 원본의 연도를 포함한 날짜로 주간 범위를 확인합니다. 이번 주 파일이 정상이면 원본 페이지를 다시 요청하지 않습니다.

수집 실패 시 기존 파일을 보존하고 위 점검 시간대 안에서 15분 뒤 재시도합니다. 월요일 09:00까지 복구되지 않으면 다음 일요일 점검 또는 수동 수집이 필요합니다. 카카오 메뉴 응답은 점검 시간대와 관계없이 지난주나 불완전한 기숙사 식단을 표시하지 않고 갱신 대기 안내와 기존 요일 버튼을 반환합니다. 기존 일요일 수집과 함께 실행할 수 있으며, 새 서비스를 적용하려면 `docker compose up -d --build dorm-menu-monitor`를 실행합니다. 공식 페이지 장애나 이번 주 식단 미게시 시 복구가 지연될 수 있습니다.

상품 자동 추천은 `product-collector` 서비스가 하루 4회 수집한 저장 데이터를 사용합니다. 새로고침은 사용자별 노출 이력으로 상품을 순환합니다. 수집 일정·장애 시 동작·수동 실행은 [상품 배치 수집](docs/product-collection.md)을 참고하세요.

## Stack

FastAPI · Uvicorn · PostgreSQL · Docker Compose
