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

## 학교혜택·정보

장학금·교육·국제교류 모집·인턴창업·교내채용·학사정보·행사를 6시간 주기로 수집합니다. 최신/마감임박과 분야별 목록에서 5개씩 탐색하며, 확인된 신청 마감만 표시합니다. 상세 조건은 공식 공고 링크로 연결합니다. 새 collector 적용과 추가 카카오 발화는 [학교혜택 운영 안내](docs/school-benefits.md)를 참고하세요.

## 문서

- [코드 구조](docs/code-structure.md)
- [카카오 메시지 등록](docs/kakao-message-routing.md)
- [상품 배치 수집](docs/product-collection.md)
- [학교혜택 수집·등록](docs/school-benefits.md)
- [학교 주변 맛집 등록·운영](docs/restaurants.md)

## 기술

FastAPI · Uvicorn · PostgreSQL · Docker Compose
