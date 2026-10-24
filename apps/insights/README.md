# 관리자 웹 앱

Next.js App Router · React · TypeScript로 만든 관리자 전용 인사이트다. 화면은 Vercel, 기존 집계·DB 연결은 FastAPI에서 처리한다. 운영 주소와 인증정보는 이 문서에 기록하지 않는다.

상품·버튼 관리, 실험실, 이벤트 수집 안내, 맛집 관리도 같은 Vercel origin에서 제공한다. 이 네 화면의 HTML·JavaScript와 공통 CSS는 이 앱의 `templates/admin`에서 직접 제공한다. 검증된 기존 폼·이벤트 처리를 보존했고, FastAPI에서 HTML을 가져오지 않는다. 인사이트 보고서는 React 컴포넌트다. 기존 관리 기능을 React로 전부 다시 작성한 것은 아니다.

화면은 [Statsig 공식 콘솔](https://docs.statsig.com/metrics/console)의 탐색·표시 방식을 참고한다. 흰 패널·회색 배경·파란색 선택/동작을 공통 토큰으로 사용하고, KPI 값의 색은 통일한다. 증감은 초록/빨강, 차트 계열은 공통 팔레트로 구분한다. 모든 추이 패널은 같은 지표 선택·차트/표 전환을 제공하며 표에도 단위와 미측정 값을 유지한다. 로고와 서비스 명칭은 CNU Insights를 사용한다.

## 구성

- `/insights/overview`: 서비스별 순사용자·이전 동기간 비교·추이·시간대·별도 수익 조회
- `/insights/fortune`: 등록·응답 품질·D1 및 7일 내 재이용·코호트·선택 조회 원자료
- `/insights/restaurants`, `/insights/shuttle`: 이용 추이·행동 및 상태·시간대
- `/insights/products`: 클릭 추이·카테고리·탐색 경로·검색/필터/정렬·CSV
- `/insights/revenue`: 토스 거래처 전체의 결제일 기준 실적
- `/insights/quality`: 학식 이용 건강성·문구·카드 위치·반복 노출·기획전
- `/admin/recommendations`: 상품 선택 방식·버튼 문구·상품 편집·배치 현황·미리보기·저장
- `/admin/experiments`: 카드·버튼 실험 공통 목록·상세·결과·품질·경험·설계·기존 운영 기능
- `/admin/events`: 이벤트 수집 흐름·정의·JSON 예시·해석 제한
- `/admin/restaurants`: 맛집 목록·장소 확인·가격·별점·추천 미리보기·저장

공통 관리자 메뉴로 화면을 왕복할 수 있다. `/admin`은 상품·버튼 관리로 연결되며 실험의 기존 유형별 상세 주소와 새로고침도 유지한다.

기간은 URL에 보관하고 보고서 간 이동·새로고침·직접 주소 진입 시 유지한다. 기본 최근 7일, 오늘·최근 30일·전체·직접 기간을 지원한다. 집계 정의와 제한은 [인사이트 문서](../../docs/insights-dashboard.md)를 따른다. 수익과 개인 원자료는 별도 요청이며 개인 원자료는 펼칠 때만 읽고 접으면 화면 상태를 해제한다. 데이터가 없거나 측정 불가·관찰 미완료일 때 가짜 수치로 대체하지 않는다.

## 비공개 설정

| 변수 | 용도 |
|---|---|
| `INSIGHTS_ADMIN_USERNAME` | 기존 관리자 사용자명 |
| `INSIGHTS_ADMIN_PASSWORD` | 기존 관리자 비밀번호 |
| `INSIGHTS_BACKEND_ORIGIN` | 기존 백엔드의 origin, 예: `https://example.com` |
| `INSIGHTS_RELAY_KEY` | 별도로 생성한 32바이트 padded base64url 키 |

브라우저의 Basic 인증은 HTTPS의 Next.js 서버에서 확인한다. 페이지·Proxy·API에서 인증을 확인하며 미설정은 503, 미인증은 401이다. 위 변수에는 `NEXT_PUBLIC_` 접두사를 붙이지 않는다. 운영 값은 저장소 밖 비공개 설정에서 주입한다. Vercel에서는 Production·Preview의 Secret으로 등록한다. CLI로 등록할 때 비밀 파일을 표준입력으로 사용하고 값을 명령 인자나 로그에 넣지 않는다.

백엔드는 같은 `INSIGHTS_RELAY_KEY`를 환경변수로 받는다. 기존 컨테이너의 다른 런타임 설정을 보존해야 하는 경우, 비공개 영속 데이터 마운트(`MENU_DATA_DIR`)의 `.insights-relay-key` 파일도 지원한다. 파일 권한은 0600으로 제한한다. 환경변수가 우선이며 잘못된 키를 다른 키로 대체하지 않는다. 운세·DB 암호화 키와 재사용하지 않는다.

`POST /admin/insights/relay`는 전용 키로 인증한 읽기 전용 요청만 실행한다. AES-256-GCM은 요청·응답과 요청 ID·방향을 결합하고, 요청 시각을 과거 90초·미래 30초로 제한한다. 이 시간 안의 같은 읽기 요청 재전송은 허용되며 1회용 쓰기 토큰이 아니다. 원본 관리자 비밀번호는 백엔드에 전송하지 않는다. HTTP origin에서도 보고서 본문은 암호화되지만 Vercel 함수에서는 복호화된 보고서를 처리한다. 원자료·키·인증 헤더·응답 본문을 로그에 남기지 않는다.

브라우저 응답과 백엔드 JSON·relay 응답에는 `no-store`를 적용한다. 서버의 기존 2분 집계 캐시는 재사용하고 상품·품질은 같은 집계를 공유한다. 개인 원자료는 집계 캐시에 넣지 않는다. 토스 캐시는 최대 5분이다.

### 기존 관리자 기능 연결

`POST /admin/workspace/relay`는 허용된 JSON 관리 API만 연결한다. 화면·스타일 경로는 relay 허용 목록에서 제외하며 Next.js가 응답 형식도 검사한다. 인사이트 읽기 전용 relay와 암호문 용도·방향을 구분한다. 요청에는 기존 관리자 인증을 암호문 안에 함께 넣고, 백엔드가 자격증명과 기존 편집 헤더를 다시 검증한다. 보고서 키만으로 관리 권한을 얻을 수 없다. 임의 URL·다른 라우터·재귀 relay·외부 리디렉션은 허용하지 않는다.

Next.js는 쓰기 요청의 동일 origin, JSON 형식, 크기를 검사한다. 백엔드는 비 GET 요청의 UUID를 비공개 영속 SQLite 파일에 원자적으로 기록해 복수 워커·재시작 후 재전송을 막는다. 응답이 불확실한 쓰기는 자동 재시도하지 않고 현황을 다시 읽는다. 관리 API의 기존 충돌 검사·실험 시작 게이트·감사 이력·유형별 ID 검사는 그대로 실행한다. 자격증명·원문 요청·응답·인증 쿠키는 저장소나 로그에 기록하지 않는다.

## 개발·검증

Node.js 24를 사용한다.

```bash
npm ci
npm test
npm run typecheck
npm run build
npm run dev
```

로컬 실행 전에 위 4개 설정을 비공개 환경에서 주입한다. `.env.example`은 키 이름만 제공하며 자격증명이나 동작하는 예시 값을 포함하지 않는다. 로컬에서 `.env.local`을 사용한다면 Git 제외 상태를 유지한다. 운영 비밀값을 개발용 `.env.local`에 내려받지 않는다.

백엔드 회귀 검증:

```bash
docker compose exec -T backend python -m unittest discover -s tests -p 'test_insights_api.py'
docker compose exec -T backend python -m unittest discover -s tests -p 'test_insights_cache.py'
docker compose exec -T backend python -m unittest discover -s tests -p 'test_admin_bridge.py'
docker compose exec -T backend python -m unittest discover -s tests -p 'test_admin_pages.py'
```

브라우저 검증은 저장소 루트에서 Playwright Core를 사용할 수 있는 런타임으로 실행한다. `INSIGHTS_BASE_URL`, 관리자 변수, 필요 시 `PLAYWRIGHT_CHROMIUM_EXECUTABLE`·`NODE_PATH`를 비공개로 주입한다. 선택적 `INSIGHTS_SCREENSHOT_DIR`는 저장소 밖의 비공개 경로를 사용한다.

```bash
node scripts/verify_insights_app.cjs
node scripts/verify_experiment_admin.cjs --expect-running-name "유지할 실험 이름"
node scripts/verify_admin_workspace.cjs
node scripts/verify_experiment_detail_ux.cjs
```

첫 명령은 1440·390·320px에서 7개 보고서, 실제 API 수치, 미인증 차단, 차트·기간 이동·직접 새로고침·원자료 지연 조회·검색/정렬/CSV·오류 재시도를 검증한다. 실험 검증에는 기존 `ADMIN_BASE_URL`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`를 별도로 사용하며 운영 실험 상태를 변경하지 않는다. 배포 전후 `python -m app.jobs.check_experiment_integrity`를 실행하고 유지할 실험 ID·키를 명시한다.

실험 상세 UX 검증은 같은 관리자 설정으로 실제 결과표와 API 수치를 비교하고 모바일·키보드·선택 탭 공유·새로고침·뒤로 가기를 확인한다. 상세 화면의 공통 표시 자산은 기존 관리 함수를 재사용하며 통계 계산이나 운영 게이트를 변경하지 않는다. 표시 원칙은 [실험 상세 문서](../../docs/experiment-lab-implementation.md#실험-상세-화면-ux)를 따른다.

완료·결정·중단 상태에는 [종료 결과 리포트](../../docs/experiment-results-ux.md)를 제공한다. 운영 종료·관측 차이·품질 제한·실제 채택 결정을 구분하고, 공통 목록도 같은 품질 요약을 사용한다. 기본 계측 부분 승인과 탐색 결과를 정식 실험 통과로 승격하지 않는다.

## Vercel 배포

프로젝트의 Root Directory는 `apps/insights`, 프레임워크는 Next.js, Node.js는 24다. 기본 `npm ci`·`npm run build`를 사용한다. `vercel.json`의 리전은 `icn1`이다. 이 앱은 백엔드 Python 소스를 업로드하지 않는다.

1. FastAPI에 새 JSON·relay 라우터를 적용하고 전용 relay 키를 설정한다.
2. 의도한 Vercel 계정·프로젝트를 확인하고 위 4개 서버 전용 설정을 등록한다.
3. Preview를 배포하고 Vercel 보호를 유지한 상태로 인증·실제 데이터·브라우저 전체 흐름을 검증한다.
4. 프로덕션은 `vercel deploy --prod --skip-domain`으로 준비한 뒤 같은 검증을 수행하고 `vercel promote`한다. Preview를 프로덕션으로 승격하면 환경변수로 재빌드될 수 있으므로 테스트한 프로덕션 빌드를 사용한다.

기존 서버는 관리자 HTML을 렌더링하지 않는다. 예전 관리자 주소는 인증 후 새 웹으로 303 연결한다. 백엔드의 `ADMIN_WEB_ORIGIN`에 `https://example.com` 형태의 origin을 지정하며, 기존 컨테이너 설정을 보존해야 하면 비공개 `MENU_DATA_DIR/.admin-web-origin` 파일도 지원한다. 환경변수가 우선이며 사용자 입력·Host·next 쿼리로 목적지를 바꾸지 않는다. 인사이트의 예전 해시 북마크는 Next.js에서 알려진 보고서 이름만 해석한다. 신규 배포에서는 이 앱을 먼저 검증하고 승격한 뒤 백엔드의 중복 HTML을 제거한다.

새 UI는 `https://example.com/insights/overview`로 진입한다. 카카오 발화·버튼·POST 스킬 변경이나 신규 카카오 등록은 없다. 관리자 버튼으로 기존 실험 운영 기능을 이용할 수 있으므로 실험 설계·시작·기준 변경은 저장소의 사전 검토 절차를 따른다. 화면 이전 검증에서는 운영 실험 상태나 상품 설정을 변경하지 않는다.
