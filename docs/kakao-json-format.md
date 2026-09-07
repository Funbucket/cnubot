# Kakao Chatbot Skill JSON Format

공식 문서: https://kakaobusiness.gitbook.io/main/tool/chatbot/skill_guide/answer_json_format

이 문서는 cnubot의 카카오 챗봇 스킬 서버 개발에 필요한 JSON 규칙만 요약한다. 공식 문서가 원본이며, 플랫폼 제한이 바뀌면 공식 문서를 우선한다.

## 프로젝트 코드

- 응답 유틸: `backend/app/utils/kakao_json_response.py`
- 라우터: `backend/app/routers/`
- 기본 응답 버전: `2.0`

## Skill Request

카카오가 스킬 서버로 보내는 요청은 보통 다음 구조다.

```json
{
  "userRequest": {
    "timezone": "Asia/Seoul",
    "block": {"id": "<block-id>", "name": "<block-name>"},
    "utterance": "사용자 발화",
    "lang": "ko",
    "user": {
      "id": "<botUserKey>",
      "type": "botUserKey",
      "properties": {
        "botUserKey": "<botUserKey>",
        "plusfriendUserKey": "<channel-user-key>",
        "appUserId": "<optional-app-user-id>",
        "isFriend": true
      }
    },
    "params": {},
    "contexts": []
  },
  "bot": {"id": "<bot-id>", "name": "<bot-name>"},
  "action": {
    "id": "<action-id>",
    "name": "<action-name>",
    "params": {},
    "detailParams": {},
    "clientExtra": {}
  },
  "flow": {
    "trigger": {
      "type": "TEXT_INPUT",
      "referrerBlock": {"id": "<block-id>", "name": "<block-name>"}
    },
    "lastBlock": {"id": "<block-id>", "name": "<block-name>"}
  }
}
```

### Parameters

- `action.params`: 엔티티 이름과 추출값의 맵
- `action.detailParams`: `origin`, `value`, `groupName`을 포함한 상세 추출값
- `action.clientExtra`: 바로가기/블록 연결에서 전달한 사용자 정의 값
- `userRequest.user.id`: 봇 범위의 사용자 식별 키. 비밀번호나 인증 토큰으로 사용하지 않는다.

## Skill Response

항상 `version: "2.0"`을 포함한다.

```json
{
  "version": "2.0",
  "template": {
    "outputs": [],
    "quickReplies": []
  },
  "context": {},
  "data": {}
}
```

### Template 제한

- `outputs`: 1~3개
- `quickReplies`: 최대 10개
- `outputs` 컴포넌트: `simpleText`, `simpleImage`, `textCard`, `basicCard`, `commerceCard`, `listCard`, `itemCard`, `carousel`

## 자주 쓰는 출력

### Simple text

텍스트는 최대 1,000자이며, 500자를 넘으면 일부가 접힐 수 있다.

```json
{
  "version": "2.0",
  "template": {
    "outputs": [{"simpleText": {"text": "안녕하세요."}}]
  }
}
```

### Basic card

`thumbnail`이 필수다. 버튼은 가로 최대 2개, 세로 최대 3개다.

```json
{
  "version": "2.0",
  "template": {
    "outputs": [{
      "basicCard": {
        "title": "메뉴 안내",
        "description": "오늘의 메뉴를 확인하세요.",
        "thumbnail": {"imageUrl": "https://example.com/image.jpg"},
        "buttons": [
          {"action": "message", "label": "오늘 메뉴", "messageText": "오늘 메뉴"},
          {"action": "webLink", "label": "웹에서 보기", "webLinkUrl": "https://example.com"}
        ]
      }
    }]
  }
}
```

### Commerce card

가격은 `price`가 필수이며 `currency`는 현재 `won`을 사용한다. 상품 추천에는 `thumbnails`를 사용한다.

- `discountedPrice`가 있으면 실제 노출 가격은 이 값을 우선한다.
- `discountRate`를 사용하려면 `discountedPrice`도 제공한다.
- 썸네일은 현재 1개만 지원된다.

### List card

- `header`와 `items`가 필수
- 일반형 `items` 최대 5개
- 리스트 아이템은 `link`, `action: message`, `action: block`을 사용할 수 있다.

### Carousel

```json
{
  "version": "2.0",
  "template": {
    "outputs": [{
      "carousel": {
        "type": "basicCard",
        "items": [
          {"title": "A", "thumbnail": {"imageUrl": "https://example.com/a.jpg"}},
          {"title": "B", "thumbnail": {"imageUrl": "https://example.com/b.jpg"}}
        ]
      }
    }]
  }
}
```

- `type`: `basicCard`, `commerceCard`, `listCard`, `itemCard`
- 최대 10개 아이템; `listCard`는 최대 5개
- 한 carousel 안의 이미지는 1:1 또는 2:1 비율 중 하나로 통일한다.

## Buttons

지원 action:

- `webLink`: `webLinkUrl` 필수
- `message`: `messageText`를 사용자 발화로 전달
- `block`: `blockId` 필수, 필요하면 `extra` 전달
- `phone`: `phoneNumber` 필수
- `share`: 말풍선 공유
- `operator`: 상담 연결

버튼은 `label`이 필수다. `buttonLayout`은 `horizontal` 또는 `vertical`이다.

## Quick replies

```json
{
  "quickReplies": [
    {"label": "오늘 메뉴", "action": "message", "messageText": "오늘 메뉴"},
    {"label": "도움말", "action": "block", "blockId": "<block-id>"}
  ]
}
```

`message`는 사용자의 발화처럼 처리되고, `block`은 발화와 관계없이 지정 블록을 호출한다. `block` 방식은 사용자가 같은 문구를 직접 입력해도 같은 블록이 실행된다는 보장이 없으므로 꼭 필요한 경우에만 사용한다.

## Images and accessibility

- 이미지 URL은 공개적으로 접근 가능해야 한다.
- `altText`는 스크린 리더용 대체 텍스트이며 최대 50자다.
- carousel 내부 이미지는 동일한 비율로 맞춘다.
- `thumbnail.fixedRatio: true`는 1:1, `false`는 2:1 표시다.

## cnubot 구현 규칙

- 응답은 `version: "2.0"`으로 시작한다.
- 외부 URL과 이미지 URL은 환경변수 또는 서비스 설정에서 관리한다.
- 사용자 식별자는 기능 식별용으로만 사용하고 secret으로 취급하지 않는다.
- 버튼/quick reply의 `extra`에는 secret, API key, 내부 IP를 넣지 않는다.
- 카카오 제한을 넘기기보다 여러 메시지/출력 그룹으로 나누거나 텍스트로 단순화한다.

## Trigger types

주요 값:

- `TEXT_INPUT`: 사용자 발화
- `CARD_BUTTON_MESSAGE`, `CARD_BUTTON_BLOCK`: 기본 카드 버튼
- `LIST_ITEM_MESSAGE`, `LIST_ITEM_BLOCK`: 리스트 아이템
- `QUICKREPLY_BUTTON_MESSAGE`, `QUICKREPLY_BUTTON_BLOCK`: 바로가기 응답

공식 문서: https://kakaobusiness.gitbook.io/main/tool/chatbot/skill_guide/answer_json_format
