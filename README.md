# cnubot

충남대학교 학생을 위한 카카오톡 챗봇입니다. 학식, 셔틀, 학교혜택, 기숙사 식당 혼잡도, 쇼핑 특가를 제공합니다.

## 실행

```bash
docker compose up -d
```

## 식단 갱신

```bash
docker compose exec -T backend python -m app.jobs.scrape_menus all
```

식단은 `data/`에 저장됩니다. 기숙사 식단은 일요일 19시~월요일 9시(KST)에 15분 간격으로 검증하고, 누락되거나 오래됐으면 다시 수집합니다.

## 테스트

```bash
docker compose exec -T backend python -m unittest discover -s tests
```

## 문서

- [코드 구조](docs/code-structure.md)
- [카카오 메시지 등록](docs/kakao-message-routing.md)
- [상품 배치 수집](docs/product-collection.md)
- [학교 주변 맛집 등록·운영](docs/restaurants.md)

## 기술

FastAPI · Uvicorn · PostgreSQL · Docker Compose
