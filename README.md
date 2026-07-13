# cnubot

충남대학교 학생을 위한 카카오톡 챗봇 기반 캠퍼스 정보 서비스입니다.  
학식, 셔틀버스, 도서관 좌석, 고객센터 연결 기능을 제공하며, FastAPI 백엔드와 Postgres 기반 투표 저장소로 구성되어 있습니다.

## Features

- 카카오톡 챗봇 응답 포맷에 맞춘 학식 조회 API
- 학식 운영 시간표 및 요일별 메뉴 조회
- 실시간 기준 셔틀 운행 상태 조회
- 도서관 좌석 현황 조회
- 카카오 상담원 연결용 고객센터 응답 제공
- backend job을 통한 교내 식단 데이터 수집 및 JSON 저장
- 식단 반응 투표 및 결과 집계

## Architecture

```text
KakaoTalk Chatbot
        |
        v
  FastAPI backend
   - cafeteria
   - shuttle
   - library
   - help
        |
        +--> static JSON / image assets
        |
        +--> /data/menus/*.json
        |
        +--> backend Postgres
             - meal snapshots
             - meal reactions

Host scheduler
        |
        +--> docker compose exec backend python -m app.jobs.scrape_menus ...
```

## Project Structure

```text
cnubot/
├── backend/
│   ├── app/
│   │   ├── routers/      FastAPI route definitions
│   │   ├── jobs/         scheduled command entrypoints
│   │   ├── scrapers/     menu scraping/parsing logic
│   │   ├── services/     Kakao response builders and domain logic
│   │   ├── utils/        common helpers and Kakao JSON formatter
│   │   └── static/       static data and image assets
│   ├── Dockerfile
│   └── pyproject.toml
├── data/                generated menu JSON files
└── docker-compose.yml
```

## Services

### Backend

- `POST /cafeteria/schedule`
  - 식당 운영 시간표와 운영 기간 조회
- `POST /cafeteria/menu/today`
  - 오늘의 메뉴 조회
- `POST /cafeteria/menu/day`
  - 특정 요일 메뉴 조회
- `POST /cafeteria/menu/reaction`
  - 식단 반응 저장 및 투표 결과 반환
- `POST /cafeteria/favorites`
  - 사용자의 즐겨찾기 식당 목록 조회
- `POST /cafeteria/favorites/toggle`
  - 식당 즐겨찾기 추가/해제
- `POST /shuttle/nearby`
  - 현재 시각 기준 셔틀 운행/대기 정보 조회
- `POST /library/seats`
  - 도서관 좌석 현황 조회
- `POST /help/contact`
  - 카카오 상담원 연결 응답 반환
- `GET /cafeteria/images/{image_name}`
- `GET /shuttle/images/{image_name}`

### Menu Scraping

backend job이 교내 식당 페이지를 스크래핑해 `/data/menus/*.json` 파일을 생성합니다.

```bash
docker compose exec -T backend python -m app.jobs.scrape_menus dorm
docker compose exec -T backend python -m app.jobs.scrape_menus hall_2 hall_3 sangrok life_science
docker compose exec -T backend python -m app.jobs.scrape_menus all
```

운영 서버에서는 host cron 또는 systemd timer에서 위 명령을 실행합니다.

기숙사 메뉴는 별도 HTML 구조를 파싱하고, 나머지 식당은 공통 스크래핑 로직을 사용합니다.

## Tech Stack

- Python 3.10
- FastAPI
- Uvicorn
- PostgreSQL
- BeautifulSoup4
- Docker Compose

## Kakao Chatbot Integration

이 프로젝트는 카카오 챗봇 스킬 서버 형태로 동작합니다.  
백엔드는 카카오 스킬 응답 포맷에 맞는 JSON을 생성하며, 카드·캐러셀·퀵리플라이·상담원 연결 버튼을 반환합니다.

주요 구현 위치:

- `backend/app/utils/kakao_json_response.py`
- `backend/app/services/`

식단 반응 버튼을 카카오 블록 연결로 고정하려면 운영 환경에 반응 블록 ID를 설정합니다.

```env
KAKAO_REACTION_BLOCK_ID=<카카오 반응 블록 ID>
```

값이 없으면 반응 버튼은 `message` action으로 동작합니다.

즐겨찾기는 message action 기반으로 동작합니다. 카카오 관리자에서 다음 발화를 즐겨찾기 블록에 연결합니다.

```text
즐겨찾기
기숙사 즐겨찾기
기숙사 즐겨찾기 해제
```

## Tests

```bash
cd backend
PYTHONPATH=app python -m unittest discover -s tests
```

운영 컨테이너에서는 다음처럼 실행합니다.

```bash
docker compose exec -T backend sh -lc "PYTHONPATH=/code/app python -m unittest discover -s /code/tests"
```

## Notes

- 시간대는 `Asia/Seoul` 기준입니다.
- 셔틀 정보는 정적 시간표 JSON을 기반으로 현재 시각에 맞춰 운행 상태를 계산합니다.
- 학식 정보는 정적 운영 시간표와 backend job이 수집한 동적 메뉴 JSON을 함께 사용합니다.
- 일부 백엔드 환경 변수는 현재 코드상 직접 사용되지 않더라도 `docker-compose.yml`에서 주입됩니다.

## License

개인 프로젝트 용도로 작성된 저장소입니다. 필요 시 별도 라이선스를 추가하세요.
