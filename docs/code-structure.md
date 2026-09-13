# 코드 구조와 유지보수 기준

## 역할별 위치

| 영역 | 위치 | 책임 |
| --- | --- | --- |
| HTTP | `backend/app/routers/` | 요청 인증·검증, 서비스 호출, HTTP 응답 |
| 요청 모델 | `backend/app/schemas/` | 외부 입력 구조와 검증 조건 |
| 도메인 서비스 | `backend/app/services/` | 학식·셔틀·상품 선택과 업무 규칙 |
| 관리자 화면 | `services/admin_views.py`, `services/insights_view.py` | 데이터로 HTML 생성 |
| 상품 카드 | `services/promotion_cards.py` | 상품 데이터로 Kakao 응답 생성 |
| 인사이트 집계 | `services/promotion_insights.py` | 기간 필터, SQL, 경로·재방문 집계 |
| 셔틀 일정 | `services/shuttle_calendar.py` | 휴일·방학·다음 운행일 판단 |
| 수집 | `backend/app/scrapers/` | 원본 페이지에서 데이터 추출 |
| 작업 실행 | `backend/app/jobs/` | 수집·검증·저장 작업 조합 |
| JSON 저장 | `utils/json_files.py` | 기존 권한을 유지하는 원자적 파일 교체 |

## 변경 시 기준

- 라우터에는 화면 템플릿이나 데이터 수집 구현을 추가하지 않는다.
- 카드 출력 변경은 `promotion_cards.py`에서 처리한다. 상품 선택·회전·추적은 `promotions.py`에서 처리한다.
- `experiments.get_promotion_insights()`는 기존 호출을 유지하는 진입점이며, 데이터베이스 풀을 집계 모듈에 전달한다. SQL 수정은 집계 모듈에서 한다.
- 기존 모듈에서 가져오던 렌더러와 헬퍼는 재노출해 기존 호출부를 유지한다. 신규 호출은 역할에 맞는 모듈을 사용한다.
- 원자적 JSON 저장은 메뉴 데이터 저장에 사용한다. 다른 파일 저장 방식으로 확대할 때는 파일 생성·권한·오류 처리 요구를 별도로 확인한다.
- API 경로·요청 모델·Kakao 응답 내용·집계 SQL 변경은 리팩토링과 구분해서 검증한다.

## 검증

기본 회귀 검증: `docker compose exec -T backend python -m unittest discover -s tests`

PostgreSQL 통합 테스트는 별도 실행 옵션이 필요하다. 기본 실행에서 건너뛴 테스트를 통과한 것으로 간주하지 않는다.
