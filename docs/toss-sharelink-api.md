# Toss Sharelink Open API

공식 문서: https://sharelink-docs.toss.im/guide/open-api/readme

이 문서는 cnubot에서 Toss Sharelink Open API를 연동할 때 필요한 규칙을 요약한다. 운영 API만 제공되며 별도 테스트 환경은 없다. 공식 문서가 원본이므로 변경 시 공식 문서를 우선한다.

## 프로젝트 연결 지점

- 상품/프로모션 데이터: `backend/app/services/promotions.py`
- 카카오 응답 연결: `backend/app/routers/promotions.py`, `backend/app/routers/cafeteria.py`
- 추후 API client를 추가할 때 토큰·상품·sharelink 캐시는 API client 또는 저장소 계층에 둔다.

## 전체 흐름

```text
Access Key + Secret Key
        ↓
POST oauth2.cert.toss.im/token
        ↓ access_token 재사용
GET  /openapi/health
        ↓
GET  /openapi/products/best-selling
        ↓ tacaItemId
POST /openapi/links (tacaItemId + publisherId)
        ↓ shortUrl
카카오 게시물에 상품 정보 + shortUrl 사용
```

시작 전에 다음을 Toss 어드민에서 준비한다.

- Access Key / Secret Key
- API를 호출하는 서버의 출발지 IP 등록
- 링크 발급에 사용할 `publisherId`

실제 인증값과 서버 IP는 이 문서, 코드, Git 이력에 기록하지 않는다.

## 1. 액세스 토큰

엔드포인트:

```text
POST https://oauth2.cert.toss.im/token
Content-Type: application/x-www-form-urlencoded
```

본문:

```text
grant_type=client_credentials
client_id=<TOSS_ACCESS_KEY>
client_secret=<TOSS_SECRET_KEY>
scope=sharelink:read sharelink:write
```

토큰은 `expires_in` 동안 재사용한다. API 호출마다 토큰을 새로 발급하지 않는다. 만료가 확인될 때만 다시 발급한다.

권장 환경변수 이름:

```env
TOSS_ACCESS_KEY=
TOSS_SECRET_KEY=
TOSS_PUBLISHER_ID=
```

값은 서버의 `.env`에만 저장하며 `.env.example`에는 이름과 placeholder만 둔다.

## 2. 연결 확인

```text
GET https://sharelink.toss.im/openapi/health
Authorization: Bearer <access_token>
```

성공 예:

```json
{"resultType":"SUCCESS","success":{"status":"ok"}}
```

403이면 인증 정보 또는 등록된 출발지 IP를 확인한다. 401이면 토큰 만료·무효 여부를 확인한다.

## 3. 상품 목록 조회

```text
GET https://sharelink.toss.im/openapi/products/best-selling?size=5
Authorization: Bearer <access_token>
```

응답에서 다음 값을 사용한다.

- `tacaItemId`: 상품 옵션 ID. 상세 조회와 링크 발급에 사용
- `displayName`: 상품명
- `thumbnailUrl`: 썸네일
- `displayPrice`: 배송비가 포함된 판매가
- `originalPrice`, `discountRate`: 가격 표시용
- `isSoldOut`: 품절 여부
- `reviewScore`, `reviewCount`: 리뷰 정보
- `categoryIds`: 상위→하위 카테고리 ID 경로
- `nextCursor`, `hasNext`: 다음 페이지 정보

`productUrl`은 추적되지 않는 일반 상품 링크다. 게시글에 넣으면 수익이 집계되지 않으므로 사용하지 않는다.

`categoryIds`는 빈 배열일 수 있다. 첫 번째/마지막 요소를 읽기 전에 비어 있는지 확인한다.

## 4. Sharelink 발급

```text
POST https://sharelink.toss.im/openapi/links
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "tacaItemId": 1234567890,
  "publisherId": "<TOSS_PUBLISHER_ID>"
}
```

응답의 `shortUrl` 또는 `originUrl`을 게시글 링크로 사용한다.

- `shortUrl`: 게시글에 넣기 좋은 추적 링크
- `originUrl`: 추적 파라미터가 포함된 원본 링크
- 같은 `tacaItemId`와 `publisherId`를 다시 요청하면 기존 링크가 반환될 수 있다.
- 발급한 링크는 저장하고 재사용한다.
- `tacaId`가 아니라 반드시 `tacaItemId`를 사용한다.

## 5. 게시

상품 목록/상세 응답의 상품명·이미지·가격과 링크 발급 응답의 `shortUrl`을 조합한다.

```json
{
  "title": "<displayName>",
  "imageUrl": "<thumbnailUrl>",
  "price": 19900,
  "link": "<shortUrl>"
}
```

상세 이미지가 필요하면 상품 상세 조회의 `detailImageUrls`를 사용한다. 가격과 품절 상태는 변할 수 있으므로 오래된 목록을 그대로 게시하지 말고 필요하면 상세 조회로 최신 상태를 확인한다.

## 공통 응답 형식

성공/실패는 HTTP 상태만으로 판별하지 않는다. 반드시 `resultType`을 확인한다.

성공:

```json
{
  "resultType": "SUCCESS",
  "success": {}
}
```

실패:

```json
{
  "resultType": "FAIL",
  "error": {
    "errorType": 400,
    "errorCode": "INVALID_ARGUMENT",
    "reason": "오류 내용"
  }
}
```

`success`와 `error`에 필드가 추가될 수 있으므로 모르는 필드는 무시한다. `errorCode`가 없거나 새로운 값이어도 서비스가 중단되지 않게 처리한다.

## 오류와 재시도

| 상황 | 처리 |
|---|---|
| HTTP 500 | 지수 백오프로 재시도 |
| HTTP 429 | `Retry-After` 우선, 없으면 지수 백오프로 재시도 |
| HTTP 401 / `UNAUTHORIZED` | 토큰 재발급 후 원인 확인. 무한 재시도 금지 |
| `INVALID_ARGUMENT` | 요청 수정 후 재시도. 같은 요청 반복 금지 |
| `SHARELINK_OPENAPI_ACCESS_DENIED` | 인증 정보·등록 IP 확인. 재시도하지 않음 |
| `SHARELINK_OPENAPI_QUOTA_EXCEEDED` | KST 자정까지 재시도하지 않음 |
| 알 수 없는 `errorCode` | 로그 기록 후 기본적으로 재시도하지 않음 |

GET 조회 API는 멱등이므로 일시적 500/429에 안전하게 재시도할 수 있다. 링크 발급은 저장·중복 방지와 함께 사용한다.

## 호출 제한과 캐시

### Rate limit

- 파트너 전체 엔드포인트 합산: 10 requests/sec
- 순간 burst: 최대 30
- 초과: HTTP 429 + `Retry-After`

### 일일 quota

- 조회 상품 수: 하루 10,000개
- 새로 발급한 링크 수: 하루 10,000개
- 인증 정보 단위
- KST 자정에 리셋
- 초과 응답: HTTP 200 + `resultType: FAIL` + `SHARELINK_OPENAPI_QUOTA_EXCEEDED`

조회 quota는 요청 횟수가 아니라 응답으로 받은 상품 수 기준이다. 링크 quota는 새로 발급된 링크 수 기준이며 기존 링크 재반환은 새 발급으로 세지 않는다.

따라서 다음을 지킨다.

- 상품 목록 응답을 저장하고 최소 1시간 이상 재사용한다.
- 발급된 sharelink를 `tacaItemId + publisherId` 기준으로 저장한다.
- 같은 상품을 매 요청마다 조회하거나 링크를 매번 발급하지 않는다.
- API 결과와 `shortUrl` 캐시에는 만료/갱신 정책을 둔다.

## Cursor pagination

첫 요청에는 `cursor`를 넣지 않는다. 응답의 `hasNext`가 `true`이면 `nextCursor`를 다음 요청의 `cursor`로 그대로 전달한다.

```text
GET ...?size=100
GET ...?size=100&cursor=<previous-nextCursor>
```

커서 문자열을 해석하거나 직접 만들지 않는다. `hasNext`가 `false`가 될 때까지 반복한다. 상품 목록 응답의 `size`는 범위를 벗어나면 보정될 수 있으므로 실제 응답 개수를 기준으로 quota를 계산한다.

## 상품 데이터 주의사항

- `displayPrice`에는 상품 1개 기준 배송비가 이미 반영되어 있다.
- 개인화 쿠폰·배송지·적립 정보는 제공되지 않는다.
- 성인 상품은 제공되지 않는다.
- `productUrl`은 수익 추적 링크가 아니다.
- `categoryIds`는 빈 배열일 수 있다.
- 가격·품절 상태는 실시간으로 바뀔 수 있다.
- 제공 데이터는 제휴 목적 범위에서만 사용한다.

## API 목록

| API | 목적 | 주요 스코프 |
|---|---|---|
| 쉐어링크 발급 | 수익 집계용 추적 링크 발급 | `sharelink:write` |
| 카테고리 베스트 상품 조회 | 특정 카테고리 인기 상품 조회 | `sharelink:read` |
| 카테고리 조회 | 카테고리 트리 조회 | `sharelink:read` |
| 하루특가 상품 조회 | 당일 특가 상품과 종료 시각 조회 | `sharelink:read` |
| 베스트 상품 조회 | 전체 인기 상품 조회 | `sharelink:read` |
| 상품 상세 조회 | 최신 가격·품절·상세 이미지 조회 | `sharelink:read` |
| subTag 관리 | 하위 채널 식별자 등록·관리 | `sharelink:write` |
| 실적 조회 | 기간별 클릭·판매·예상 수익 조회 | `sharelink:read` |
| 정산 실적 조회 | 정산 회차별 확정 수익 조회 | `sharelink:read` |

## API 상세: 쉐어링크 발급

게시글에 넣을 추적 링크는 반드시 이 API로 발급한다. 조회 API의 `productUrl`은 수익 집계 대상이 아니다.

```text
POST https://sharelink.toss.im/openapi/links
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "tacaItemId": 12345,
  "publisherId": "<publisher-uuid>"
}
```

### 요청 필드

| 필드 | 필수 | 설명 |
|---|---|---|
| `publisherId` | 필수 | 발급 주체 UUID |
| `tacaItemId` | 조건부 | 발급할 상품 옵션 ID. `tacaId`보다 우선 |
| `tacaId` | 조건부 | 상품 그룹 ID. `tacaItemId`가 없을 때 대표 옵션으로 발급 |
| `subTagId` | 선택 | 미리 등록한 하위 채널 식별자 |

`tacaItemId`와 `tacaId` 중 하나는 반드시 있어야 한다.

| 입력 | 처리 |
|---|---|
| `tacaItemId`만 제공 | 해당 옵션으로 발급 |
| `tacaId`만 제공 | 대표 옵션을 자동 선택. 실제 옵션은 응답의 `tacaItemId` 확인 |
| 둘 다 제공 | `tacaItemId` 우선 |
| 둘 다 없음 | HTTP 400 |

### 응답

```json
{
  "resultType": "SUCCESS",
  "success": {
    "tacaItemId": 12345,
    "publisherId": "<publisher-uuid>",
    "shortUrl": "https://toss.im/_m/<id>",
    "originUrl": "https://toss.shopping/t/<id>?k=<tracking>&referrer=affiliate"
  }
}
```

`shortUrl`과 `originUrl`은 같은 상품으로 이동하며 수익 집계 효과는 같다.

- 일반 게시글: `shortUrl` 권장
- 단축 URL을 허용하지 않는 지면: `originUrl` 사용

### subTag로 채널별 귀속

하위 채널별 실적을 나누려면 먼저 subTag를 등록하고 요청에 `subTagId`를 넣는다.

```json
{
  "tacaItemId": 12345,
  "publisherId": "<publisher-uuid>",
  "subTagId": "creator_a1"
}
```

- 등록된 `subTagId`: 해당 채널에 귀속
- 생략: 채널 구분 없이 귀속
- 등록되지 않았거나 삭제된 값: `SHARELINK_OPENAPI_ACCESS_DENIED`
- 다른 거래처의 값: `SHARELINK_OPENAPI_ACCESS_DENIED`
- `subTagId`는 링크 URL에 노출되지 않음

### 중복 발급과 동일성

같은 `tacaItemId + publisherId + subTagId` 조합으로 재요청하면 기존 링크가 반환된다. 새 링크가 중복 생성되지 않지만, 발급 결과는 저장해 재사용한다.

`subTagId`가 다르면 같은 상품·발급 주체라도 다른 링크가 발급되며, 채널별 성과를 나누는 의도된 동작이다.

`tacaId`로 요청하면 대표 옵션이 바뀔 때 다른 `tacaItemId`로 해석되어 새 링크가 발급될 수 있다. 기존 링크는 계속 동작하지만 성과가 나뉘므로, 상품별 링크를 안정적으로 관리하려면 `tacaItemId`를 사용한다.

### 발급 실패와 수익 귀속

- 상품·셀러 정책에 따라 일부 상품은 발급이 제한될 수 있다.
- 목록 조회 당시 가능했던 상품도 발급 시점에 실패할 수 있다.
- 발급 실패 상품은 노출 대상에서 제외한다.
- 제휴사가 직접 발급해 게시한 링크를 통한 구매만 수익으로 집계된다.
- 사이트의 모든 Toss 링크를 자동 변환해 귀속하는 기능은 없다.

## API 상세: 상품 조회

### 카테고리 베스트 상품

특정 카테고리의 인기 상품을 조회한다.

```text
GET /openapi/products/best-categories/{categoryId}
필요 스코프: sharelink:read
쿼리: cursor(선택), size(선택, 기본 30, 1~100)
```

`categoryId`는 카테고리 트리에서 얻는다. 모든 레벨의 ID를 사용할 수 있지만 랭킹이 없는 카테고리도 있다.

```json
{
  "resultType": "SUCCESS",
  "success": {
    "category": {"categoryId": 101, "displayName": "여성의류"},
    "items": [],
    "nextCursor": null,
    "hasNext": false
  }
}
```

- 존재하지 않는 `categoryId`: `INVALID_ARGUMENT`
- 유효하지만 랭킹이 없음: 빈 `items` + `hasNext: false`인 정상 응답
- 랭킹은 하루 한 번 갱신되므로 하루 단위 캐시 권장
- 게시에는 각 상품의 `tacaItemId`로 발급한 `shortUrl`을 사용

### 카테고리 트리

```text
GET /openapi/categories
필요 스코프: sharelink:read
```

파라미터가 없으며, `children`이 같은 구조로 중첩된다.

```json
{
  "resultType": "SUCCESS",
  "success": {
    "categories": [
      {
        "categoryId": 100,
        "level": 1,
        "displayName": "패션",
        "children": [
          {"categoryId": 101, "level": 2, "displayName": "여성의류", "children": []}
        ]
      }
    ]
  }
}
```

카테고리 트리는 자주 바뀌지 않으므로 하루 한 번 정도 저장한다. 상품의 `categoryIds`는 이 트리의 ID 체계와 같으며, 이름 변환은 재귀 순회한 캐시에서 처리한다. 상품의 `categoryIds`가 빈 배열인 경우는 미분류로 처리한다.

### 하루특가 상품

```text
GET /openapi/products/today-deals
필요 스코프: sharelink:read
쿼리: cursor(선택), size(선택, 기본 30, 1~30)
```

상품 카드 공통 필드에 `endAt`이 추가된다.

```json
{
  "resultType": "SUCCESS",
  "success": {
    "items": [
      {
        "rank": 1,
        "tacaItemId": 12345,
        "displayName": "상품명",
        "displayPrice": 9900,
        "isSoldOut": false,
        "endAt": "2026-08-04T23:59:59+09:00"
      }
    ],
    "nextCursor": null,
    "hasNext": false
  }
}
```

- `endAt`: ISO 8601 형식의 KST 종료 시각
- 편성 없는 날의 빈 `items`는 정상 응답
- 캐시는 `endAt`을 넘기지 않도록 만료 설정
- 종료 상품은 서버 응답에서 자동 제외되므로 주기적으로 재조회

### 통합 베스트 상품

```text
GET /openapi/products/best-selling
필요 스코프: sharelink:read
쿼리: cursor(선택), size(선택, 기본 30, 1~100)
```

응답 순서가 인기 순서이므로 별도 정렬하지 않고 그대로 사용한다. 랭킹은 1시간 단위 배치 결과이므로 1시간 이상 캐시한다.

### 상품 상세

최신 가격·품절 여부와 상세 이미지를 최대 30건까지 조회한다.

```text
GET /openapi/products/detail
필요 스코프: sharelink:read
쿼리: tacaItemIds 또는 tacaIds 중 하나, 콤마 구분
```

```text
GET /openapi/products/detail?tacaItemIds=12345,12346,12347
```

규칙:

- `tacaItemIds`와 `tacaIds` 중 하나만 전달
- 둘 다 전달하면 `tacaItemIds`만 사용
- 최대 30건
- 숫자가 아닌 값, 둘 다 없음, 30건 초과는 HTTP 400
- 같은 ID를 여러 번 넣어도 한 번만 조회
- `tacaItemIds` 사용을 권장. `tacaIds`는 대표 옵션이 바뀔 수 있음

응답의 상세 데이터:

```json
{
  "resultType": "SUCCESS",
  "success": {
    "items": [
      {
        "tacaItemId": 12345,
        "tacaId": 9876,
        "displayName": "상품명",
        "thumbnailUrl": "https://example.com/thumb.jpg",
        "mainImageUrls": ["https://example.com/main.jpg"],
        "displayPrice": 19900,
        "isSoldOut": false,
        "categoryIds": [100, 101],
        "description": {
          "detailImageUrls": ["https://example.com/detail.jpg"],
          "noticeImageUrl": null,
          "htmlUrl": null
        }
      }
    ],
    "notFoundIds": [12346]
  }
}
```

- `mainImageUrls`: 상세 상단 이미지
- `description.detailImageUrls`: 본문 이미지
- `description.noticeImageUrl`: 셀러 공지 이미지
- `description.htmlUrl`: HTML 상세 설명 주소
- 이미지 상세는 등록 방식에 따라 `detailImageUrls` 또는 `htmlUrl`이 비어 있을 수 있으므로 양쪽 처리
- 일부 상품 미조회는 오류가 아니라 `notFoundIds`로 반환되는 부분 성공
- `notFoundIds`는 요청한 ID를 그대로 유지하고 요청 순서도 보존
- `notFoundIds` 대상은 즉시 재시도하지 않고 노출에서 제외. 이후 주기적으로 재조회
- 일시 장애는 `notFoundIds`가 아니라 HTTP 5xx이므로 재시도 규칙을 적용
- 이 API는 링크 발급을 대체하지 않으며, 게시 링크는 별도로 쉐어링크 발급 API를 사용

## API 상세: subTag 관리

subTag는 거래처 내부의 크리에이터·매체·구좌별 실적을 나누는 식별자다. 링크 발급에 사용하려면 먼저 등록해야 한다.

```text
POST /openapi/sub-tags/create
GET  /openapi/sub-tags
POST /openapi/sub-tags/label/update
POST /openapi/sub-tags/delete
```

- 목록 조회: `sharelink:read`
- 등록·라벨 수정·삭제: `sharelink:write`
- subTag 자체는 일일 상품 조회/링크 발급 quota를 차감하지 않음

### 값 규칙

| 항목 | 규칙 |
|---|---|
| `subTagId` 길이 | 1~64자 |
| 허용 문자 | 영문 대소문자, 숫자, `-`, `_`, `.` |
| 금지 문자 | 공백, 한글, `/`, `?`, `&`, `#` 등 |
| 대소문자 | 구분함 |
| 유일성 | 거래처 안에서 유일 |
| 변경 | 불가 |
| `label` | 선택, 100자 이하, 표시용 |

`subTagId` 앞뒤 공백은 허용하지 않는다. 값이 다르게 저장되어 링크 발급 키가 어긋나는 것을 막기 위해 조용히 trim하지 않는다. `label`은 앞뒤 공백을 제거하며 빈 값은 없음으로 저장한다.

### 등록

```text
POST /openapi/sub-tags/create
필요 스코프: sharelink:write
```

한 번에 1~100건이다. 대량 등록은 100건씩 나눈다.

```json
{
  "subTags": [
    {"subTagId": "creator_a1", "label": "A 크리에이터"},
    {"subTagId": "creator_b2"}
  ]
}
```

`results`는 요청 순서와 같은 순서로 반환된다.

| status | 의미 |
|---|---|
| `CREATED` | 신규 등록 |
| `RESTORED` | 삭제된 subTag 복구 |
| `ALREADY_EXISTS` | 이미 존재. label은 덮어쓰지 않음 |
| `INVALID_FORMAT` | 해당 항목만 형식 오류 |
| `UNKNOWN` | 미등록으로 처리하고 문의 |

항목별 형식 오류는 부분 성공할 수 있다. 단, 전체 요청은 다음 오류로 거절된다.

- 빈 배열 또는 100건 초과: `OPENAPI_SUB_TAG_BULK_SIZE_INVALID`
- 같은 `subTagId`가 한 요청에 중복: `OPENAPI_SUB_TAG_DUPLICATED_IN_REQUEST`

삭제된 subTag를 label과 함께 다시 등록하면 `RESTORED`와 함께 label을 교체한다. label 없이 복구하면 기존 label을 유지한다.

### 목록 조회

```text
GET /openapi/sub-tags
필요 스코프: sharelink:read
쿼리: cursor(선택)
```

한 페이지 100건 고정이며 size 파라미터가 없다. 삭제된 subTag는 반환하지 않는다. `nextCursor`는 그대로 다음 요청에 전달한다.

### 표시 이름 수정

```text
POST /openapi/sub-tags/label/update
필요 스코프: sharelink:write
```

```json
{"subTagId": "creator_a1", "label": "A 크리에이터 (유튜브)"}
```

`subTagId` 자체는 변경할 수 없다. `label: null` 또는 빈 문자열은 표시 이름을 삭제한다. 미등록·삭제 상태는 `OPENAPI_SUB_TAG_NOT_FOUND`다.

### 삭제

```text
POST /openapi/sub-tags/delete
필요 스코프: sharelink:write
```

삭제는 신규 링크 발급에서만 제외한다. 기존 링크와 기존 실적·정산 기록은 유지된다. 같은 요청은 멱등이며 두 번째부터 `alreadyDeleted: true`가 된다.

### subTag 오류 코드

| 오류 코드 | 처리 |
|---|---|
| `OPENAPI_SUB_TAG_BULK_SIZE_INVALID` | 1~100건으로 분할 |
| `OPENAPI_SUB_TAG_DUPLICATED_IN_REQUEST` | 요청 내 중복 제거 |
| `OPENAPI_SUB_TAG_INVALID_FORMAT` | `subTagId` 규칙 수정 |
| `OPENAPI_SUB_TAG_LABEL_INVALID` | label을 100자 이하로 수정 |
| `OPENAPI_SUB_TAG_NOT_FOUND` | 목록에서 상태 확인 |

등록하지 않은 subTag를 링크 발급에 넣으면 `SHARELINK_OPENAPI_ACCESS_DENIED`가 반환된다. `subTagId`는 링크 URL에 포함되지 않는다.

## API 상세: 실적 조회

결제일 기준의 잠정 실적을 상품 단위로 조회한다. 판매 직후 반영되지만 취소·환불로 금액이 줄어들 수 있으므로 확정 지표로 사용하지 않는다.

```text
GET /openapi/performance
필요 스코프: sharelink:read
```

쿼리:

| 파라미터 | 필수 | 설명 |
|---|---|---|
| `fromDate` | 필수 | 시작일, `YYYY-MM-DD` |
| `toDate` | 필수 | 종료일, `fromDate` 이상 |
| `subTagId` | 선택 | 특정 하위 채널. 생략하면 거래처 전체 |
| `attribution` | 선택 | `DIRECT`, `INDIRECT`, `UNKNOWN` |
| `cursor` | 선택 | 다음 페이지 위치 |
| `size` | 선택 | 기본 50, 1~100 |

조회 기간은 최대 31일이다. 31일을 넘으면 기간을 나눠 호출한다.

```text
GET /openapi/performance?fromDate=2026-08-01&toDate=2026-08-31&size=50
```

입력 오류는 HTTP 200이어도 `resultType: FAIL`로 내려온다.

- `fromDate > toDate` 또는 31일 초과: `INVALID_ARGUMENT`
- `size`가 1~100 밖: `INVALID_ARGUMENT`
- 미등록/타 거래처 `subTagId`: `SHARELINK_OPENAPI_ACCESS_DENIED`
- 조건에 맞는 실적 없음: 빈 `items`, 합계 금액 0인 정상 응답

### 응답 구조

```json
{
  "resultType": "SUCCESS",
  "success": {
    "fromDate": "2026-08-01",
    "toDate": "2026-08-31",
    "subTagId": null,
    "summary": {
      "clickCount": 1820,
      "soldQuantity": 64,
      "refundedQuantity": 3,
      "salesAmount": 1284000,
      "discountAmount": 96000,
      "netPaymentAmount": 1188000,
      "expectedCommissionAmount": 59400,
      "confirmedCommissionAmount": 41200,
      "lastUpdatedAt": "2026-09-02T10:30:00"
    },
    "items": [],
    "nextCursor": null,
    "hasNext": false,
    "size": 50
  }
}
```

### 금액·상품 필드

- `clickCount`: 링크 클릭 후 토스 앱 상품 상세까지 진입한 수. `summary`에만 있음
- `soldQuantity`: 환불 전 판매 수량
- `refundedQuantity`: 환불 수량
- `salesAmount`: 배송비 포함 판매금액. 환불분이 반영될 수 있음
- `discountAmount`: 쿠폰·포인트 등 할인금액
- `netPaymentAmount`: 실 결제금액 = `salesAmount - discountAmount`
- `expectedCommissionAmount`: 예상 수익금(세전). 환불 시 감소 가능
- `confirmedCommissionAmount`: 구매확정된 주문의 확정 수익금(세전)
- `lastUpdatedAt`: 마지막 반영 시각(KST). 실적이 없으면 `null`
- `items[].productId`: 상품 옵션 ID이며 `tacaItemId`와 동일
- `items[].attribution`: `DIRECT`, `INDIRECT`, `UNKNOWN`

상품별 행은 예상 수익금이 높은 순이다. 같은 `productId`라도 `attribution`이 다르면 별도 행으로 내려오므로 합산할 때는 필요에 따라 `productId`로 묶는다.

`DIRECT`는 공유한 상품이 구매된 경우, `INDIRECT`는 링크 유입 후 다른 상품이 구매된 경우다. 간접 구매도 같은 수수료율이며, 클릭 후 24시간 안의 구매가 대상이다.

실적은 결제일 기준이다. 과거 기간도 환불 시 금액이 바뀔 수 있다. 방금 발생한 판매가 즉시 보이지 않을 수 있으므로 `lastUpdatedAt`을 함께 기록한다. 발급 API가 아닌 일반 링크의 클릭은 집계되지 않는다.

## API 상세: 정산 실적 조회

구매확정된 주문만 포함하는 확정 실적을 정산 회차별로 조회한다.

```text
GET /openapi/settlements/{settlementMonth}
필요 스코프: sharelink:read
```

경로 및 쿼리:

| 파라미터 | 위치 | 필수 | 설명 |
|---|---|---|---|
| `settlementMonth` | 경로 | 필수 | `YYYY-MM`, 예: `2026-08` |
| `subTagId` | 쿼리 | 선택 | 특정 하위 채널 |
| `attribution` | 쿼리 | 선택 | `DIRECT`, `INDIRECT`, `UNKNOWN` |
| `cursor` | 쿼리 | 선택 | 다음 페이지 위치 |
| `size` | 쿼리 | 선택 | 기본 50, 1~100 |

```text
GET /openapi/settlements/2026-08?size=50
```

- 잘못된 형식/없는 달: `INVALID_ARGUMENT`
- `size`가 1~100 밖: `INVALID_ARGUMENT`
- 미등록/타 거래처 `subTagId`: `SHARELINK_OPENAPI_ACCESS_DENIED`
- 확정 실적 없음: 빈 `items`, 합계 금액 0인 정상 응답

### 응답과 금액

```json
{
  "resultType": "SUCCESS",
  "success": {
    "settlementMonth": "2026-08",
    "subTagId": null,
    "summary": {
      "orderProductCount": 58,
      "productAmount": 1160000,
      "promotionCost": 84000,
      "settlementBase": 1076000,
      "commissionAmount": 53800,
      "latestConfirmedAt": "2026-08-31T21:14:02"
    },
    "items": [],
    "nextCursor": null,
    "hasNext": false,
    "size": 50
  }
}
```

- `orderProductCount`: 구매확정 건수
- `productAmount`: 할인 전 확정 판매금액. 배송비 포함
- `promotionCost`: 쿠폰·포인트 등 할인금액
- `settlementBase`: 실 결제금액 = `productAmount - promotionCost`
- `commissionAmount`: 확정 수익금(세전)
- `latestConfirmedAt`: 가장 최근 구매확정 시각(KST)
- `items[].productId`: `tacaItemId`와 동일한 상품 옵션 ID
- `items[].attribution`: 실적 조회와 같은 기여 구분

수수료는 주문별로 계산하고 원 단위 반올림 후 합산한다. 따라서 `settlementBase × 수수료율`로 다시 계산하지 말고 응답의 `commissionAmount`를 사용한다.

### 실적 조회와의 차이

| 구분 | 실적 조회 | 정산 실적 조회 |
|---|---|---|
| 기준 | 결제일 | 구매확정일 |
| 성격 | 잠정 | 확정 수익 중심 |
| API | `/openapi/performance` | `/openapi/settlements/{YYYY-MM}` |
| 주요 금액 | 예상 수익금 | 확정 수익금 |
| 변동 | 취소·환불로 감소 가능 | 회차 마감 전 증가, 환불 시 감소 가능 |

구매확정은 배송 완료 후 최장 7일 뒤일 수 있어 결제 월과 정산 회차가 다를 수 있다. 회차 마감 전 수치는 계속 변하며, 세금·이월 수익·지급 상태·실제 입금액은 이 API에 포함되지 않는다.

두 API 모두 상품을 반환하지 않는 호출이므로 일일 상품 조회/링크 발급 quota를 차감하지 않는다.

## 용어 사전

### 상품 식별자

토스쇼핑 상품은 상품 그룹(`tacaId`) 아래에 실제 판매 옵션(`tacaItemId`)이 여러 개 있는 구조다.

```text
tacaId: 무선 이어폰 A
├── tacaItemId: 무선 이어폰 A - 화이트
└── tacaItemId: 무선 이어폰 A - 블랙
```

| 용어 | 의미 | 사용처 |
|---|---|---|
| `tacaItemId` | 색상·용량 등 실제 판매 옵션 식별자 | 상품 목록 응답, 상세 조회, 링크 발급 |
| `tacaId` | 여러 옵션을 묶는 상품 그룹 식별자 | 상품 페이지 주소 `/t/{tacaId}`, 상세 조회 |
| 대표 상품 (winner) | 현재 대표로 노출되는 옵션 | `tacaId` 요청 시 서버가 자동 선택 |

`tacaId`를 사용하면 시점에 따라 대표 옵션이 바뀌어 링크와 성과가 나뉠 수 있다. 상품 목록에서 받은 값은 항상 `tacaItemId`를 우선 사용한다. 상품 페이지 주소만 알고 있을 때만 `tacaId`를 사용한다.

### 링크 식별자

| 용어 | 의미 | 수익 집계 |
|---|---|---|
| `productUrl` | 조회 API가 주는 일반 상품 페이지 주소 | 집계되지 않음 |
| `shortUrl` | 발급 API가 주는 단축 추적 링크 | 집계됨 |
| `originUrl` | 발급 API가 주는 추적 원본 링크 | 집계됨 |
| `publisherId` | 발급 주체 UUID. 링크 발급 필수값 | 이 값으로 수익 귀속 |

게시글에는 반드시 `shortUrl` 또는 `originUrl`을 넣는다. `productUrl`은 구매가 발생해도 수익으로 잡히지 않는다.

### 하위 채널 식별자

인증 정보가 거래처 단위로 1벌인 경우, 크리에이터·매체·구좌별 실적은 `subTag`로 나눈다.

| 용어 | 의미 |
|---|---|
| `subTag` | 하위 채널을 구분하는 등록 단위 |
| `subTagId` | 제휴사가 직접 정하는 거래처 내 유일한 식별자. 영문·숫자·`-`·`_`·`.`만 사용, 64자 이하, 대소문자 구분, 등록 후 변경 불가 |
| `label` | `subTag`의 표시명. 선택값이며 식별에는 사용하지 않음 |

`subTagId`는 링크 발급 시 선택값이다. 생략하면 채널 구분 없이 발급된다.

### 실적·정산

| 용어 | 의미 |
|---|---|
| `attribution` | `DIRECT`(공유 상품 구매), `INDIRECT`(유입 후 다른 상품 구매), `UNKNOWN` |
| `productId` | 실적·정산 응답의 상품 ID. `tacaItemId`와 같은 값 |
| `netPaymentAmount` | 할인 후 실제 결제금액(원) |
| `expectedCommissionAmount` | 판매 직후의 예상 수익금(세전). 환불 시 감소 가능 |
| `confirmedCommissionAmount` | 구매확정 후 확정된 수익금(세전) |
| `settlementBase` | 정산 수수료 계산의 기준이 되는 실 결제금액(원) |
| `commissionAmount` | 정산 실적의 확정 수익금(세전) |
| 정산 회차 | `YYYY-MM` 형식. 해당 월에 구매확정된 주문의 묶음 |

실적 조회와 정산 실적 조회는 기간 기준이 다르다. 실적은 결제 기준, 정산은 구매확정 기준이므로 숫자가 일치하지 않을 수 있다.

### 인증

| 용어 | 의미 |
|---|---|
| Access Key | OAuth `client_id`에 해당. 토큰 발급에 사용 |
| Secret Key | OAuth `client_secret`에 해당. 발급 직후 1회만 표시 |
| 액세스 토큰 | Bearer 인증에 넣는 만료성 토큰 |
| `sharelink:read` | 상태를 바꾸지 않는 조회 권한 |
| `sharelink:write` | 링크 발급, `subTag` 등록·수정·삭제 권한 |

### 응답·상품 필드

| 용어 | 의미 |
|---|---|
| `resultType` | `SUCCESS` 또는 `FAIL`. 성공·실패의 1차 판정값 |
| `success` | 성공 시 실제 응답 데이터 |
| `error` | 실패 시 `errorCode`, `reason` 등이 담기는 객체 |
| `errorCode` | 오류 원인 판별에 사용하는 문자열 |
| `errorType` | 일부 오류에만 포함되는 숫자. 주된 분기 기준으로 사용하지 않음 |
| `cursor` / `nextCursor` | 다음 페이지 위치. 해석하지 않고 그대로 전달 |
| `hasNext` | 다음 페이지 존재 여부 |
| `notFoundIds` | 상세 조회에서 찾지 못한 요청 ID 목록 |
| `endAt` | 하루특가 종료 시각(KST) |
| `displayName` | 상품명 |
| `displayPrice` | 배송비가 포함된 실제 판매가(원) |
| `categoryIds` | 상위→하위 카테고리 ID 경로. 빈 배열 가능 |
| `originalPrice` | 할인 전 정가(원) |
| `discountRate` | 할인율(%) |
| `isSoldOut` | 품절 여부 |
| `rank` | 목록 내 순위. 페이지가 바뀌어도 연속 |
| `mainImageUrls` | 상세 페이지 상단 메인 이미지 목록 |
| `detailImageUrls` | 상세 페이지 본문 이미지 목록 |

`categoryIds`는 빈 배열일 수 있으므로 `[0]` 또는 마지막 값을 바로 읽지 않는다.

## cnubot 구현 체크리스트

- [ ] Access/Secret/Publisher ID를 `.env`에만 저장
- [ ] 토큰을 메모리 또는 캐시에 저장하고 매 요청 재발급하지 않기
- [ ] `resultType`과 `error.errorCode` 처리
- [ ] HTTP 429의 `Retry-After` 처리
- [ ] 500/429만 제한적으로 지수 백오프
- [ ] 상품·sharelink 캐시 구현
- [ ] `productUrl` 대신 `shortUrl` 게시
- [ ] `tacaItemId` 사용
- [ ] `categoryIds` 빈 배열 처리
- [ ] 요청/응답 로그에서 토큰, Secret, 내부 IP 제거
- [ ] 운영 API만 있으므로 실제 상품/링크 발급을 테스트로 남발하지 않기

공식 문서: https://sharelink-docs.toss.im/guide/open-api/readme
