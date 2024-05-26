class KakaoJsonResponse:
    def __init__(self):
        # https://kakaobusiness.gitbook.io/main/tool/chatbot/skill_guide/answer_json_format#skillresponse
        self.response = {
            "version": "2.0",
            "template": {"outputs": [], "quickReplies": []},
        }

    @staticmethod
    def create_simple_text(text: str):
        # https://kakaobusiness.gitbook.io/main/tool/chatbot/skill_guide/answer_json_format#simpletext
        return {"simpleText": {"text": text}}

    @staticmethod
    def create_basic_card(title: str, description: str, thumbnail: dict, buttons: list):
        # https://kakaobusiness.gitbook.io/main/tool/chatbot/skill_guide/answer_json_format#basiccard
        return {
            "title": title,
            "description": description,
            "thumbnail": thumbnail,
            "buttons": buttons,
        }

    @staticmethod
    def create_text_card(title: str, description: str, buttons: list):
        # https://kakaobusiness.gitbook.io/main/tool/chatbot/skill_guide/answer_json_format#textcard
        return {
            "title": title,
            "description": description,
            "buttons": buttons,
        }

    @staticmethod
    def create_carousel(items: list, type: str = "textCard"):
        # https://kakaobusiness.gitbook.io/main/tool/chatbot/skill_guide/answer_json_format#carousel
        return {"carousel": {"type": type, "items": items}}

    @staticmethod
    def create_quick_reply(
        label: str,
        message_text: str,
        action: str = "message",
        block_id: str = None,
        extra: dict = None,
    ):
        # https://kakaobusiness.gitbook.io/main/tool/chatbot/skill_guide/answer_json_format#quickreplies-1
        quick_reply = {"label": label, "action": action, "messageText": message_text}

        if block_id:
            quick_reply["blockId"] = block_id
        if extra:
            quick_reply["extra"] = extra

        return quick_reply

    def add_output_to_response(self, output: dict):
        if "outputs" not in self.response["template"]:
            self.response["template"]["outputs"] = []
        self.response["template"]["outputs"].append(output)
        return self

    def add_quick_replies(self, replies: list):
        if "quickReplies" not in self.response["template"]:
            self.response["template"]["quickReplies"] = []
        self.response["template"]["quickReplies"].extend(replies)
        return self

    def get_response(self):
        return self.response


if __name__ == "__main__":
    kakao_response = KakaoJsonResponse()

    basic_card = kakao_response.create_basic_card(
        title="보물상자",
        description="보물상자 안에는 뭐가 있을까?",
        thumbnail={
            "imageUrl": "https://t1.kakaocdn.net/openbuilder/sample/lj3JUcmrzC53YIjNDkqbWK.jpg"
        },
        buttons=[
            {
                "action": "message",
                "label": "열어보기",
                "messageText": "짜잔! 우리가 찾던 보물입니다",
            },
            {
                "action": "webLink",
                "label": "구경하기",
                "webLinkUrl": "https://e.kakao.com/t/hello-ryan",
            },
        ],
    )

    another_basic_card = kakao_response.create_basic_card(
        title="비밀의 상자",
        description="이 상자 안에는 어떤 비밀이 숨겨져 있을까?",
        thumbnail={
            "imageUrl": "https://t1.kakaocdn.net/openbuilder/sample/lj3JUcmrzC53YIjNDkqbWK.jpg"
        },
        buttons=[
            {
                "action": "message",
                "label": "열어보기",
                "messageText": "놀라운 비밀이 여기 있네!",
            },
            {
                "action": "webLink",
                "label": "더 알아보기",
                "webLinkUrl": "https://e.kakao.com/t/hello-ryan",
            },
        ],
    )

    carousel = kakao_response.create_carousel([basic_card, another_basic_card])

    response = (
        kakao_response.add_output_to_response(carousel)
        .add_quick_replies(
            [
                kakao_response.create_quick_reply(label="예", message_text="예"),
                kakao_response.create_quick_reply(
                    label="아니오", message_text="아니오"
                ),
            ]
        )
        .get_response()
    )

    print(response)
