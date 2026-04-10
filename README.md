# cnubot

충남대학교 학생을 위한 카카오톡 챗봇 기반 캠퍼스 정보 서비스입니다.  
학식, 셔틀버스, 도서관 좌석, 고객센터 연결 기능을 제공하며, FastAPI 백엔드와 Airflow 기반 ETL 파이프라인으로 구성되어 있습니다.

## Features

- 카카오톡 챗봇 응답 포맷에 맞춘 학식 조회 API
- 학식 운영 시간표 및 요일별 메뉴 조회
- 실시간 기준 셔틀 운행 상태 조회
- 도서관 좌석 현황 조회
- 카카오 상담원 연결용 고객센터 응답 제공
- Airflow DAG를 통한 교내 식단 데이터 수집 및 JSON 저장

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
        +--> /opt/airflow/data/*.json
                ^
                |
        Apache Airflow ETL
   - dorm menu
   - hall 2 menu
   - hall 3 menu
   - sangrok menu
   - life science menu
```

## Project Structure

```text
cnubot/
├── backend/
│   ├── app/
│   │   ├── routers/      FastAPI route definitions
│   │   ├── services/     Kakao response builders and domain logic
│   │   ├── utils/        common helpers and Kakao JSON formatter
│   │   └── static/       static data and image assets
│   ├── Dockerfile
│   └── pyproject.toml
├── etl/
│   ├── dags/            Airflow menu scraping pipelines
│   └── Dockerfile
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
- `POST /shuttle/nearby`
  - 현재 시각 기준 셔틀 운행/대기 정보 조회
- `POST /library/seats`
  - 도서관 좌석 현황 조회
- `POST /help/contact`
  - 카카오 상담원 연결 응답 반환
- `GET /cafeteria/images/{image_name}`
- `GET /shuttle/images/{image_name}`

### ETL

Airflow DAG가 교내 식당 페이지를 스크래핑해 `/opt/airflow/data/*.json` 파일을 생성합니다.

- `ETL_dorm_menu`
- `ETL_second_student_hall_menu`
- `ETL_third_student_hall_menu`
- `ETL_sangrok_hall_menu`
- `ETL_life_science_hall_menu`

기숙사 메뉴는 별도 HTML 구조를 파싱하고, 나머지 식당은 공통 스크래핑 로직을 사용합니다.

## Tech Stack

- Python 3.10
- FastAPI
- Uvicorn
- Apache Airflow 2.9
- Celery
- Redis
- PostgreSQL
- BeautifulSoup4
- Docker Compose

## Kakao Chatbot Integration

이 프로젝트는 카카오 챗봇 스킬 서버 형태로 동작합니다.  
백엔드는 카카오 스킬 응답 포맷에 맞는 JSON을 생성하며, 카드·캐러셀·퀵리플라이·상담원 연결 버튼을 반환합니다.

주요 구현 위치:

- `backend/app/utils/kakao_json_response.py`
- `backend/app/services/`

## Notes

- 시간대는 `Asia/Seoul` 기준입니다.
- 셔틀 정보는 정적 시간표 JSON을 기반으로 현재 시각에 맞춰 운행 상태를 계산합니다.
- 학식 정보는 정적 운영 시간표와 Airflow가 수집한 동적 메뉴 JSON을 함께 사용합니다.
- 일부 백엔드 환경 변수는 현재 코드상 직접 사용되지 않더라도 `docker-compose.yml`에서 주입됩니다.

## License

개인 프로젝트 용도로 작성된 저장소입니다. 필요 시 별도 라이선스를 추가하세요.
