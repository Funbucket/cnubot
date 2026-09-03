from app.utils import kakao_json_response

TALKN_URL = "https://talkn.world"


def create_talkn_response():
    kakao_response = kakao_json_response.KakaoJsonResponse()
    card = kakao_response.create_text_card(
        title="취향이 통하는 인연",
        description=(
            "🎬 영화·🎧 음악·📚 책 취향이 비슷한 대학생을\n"
            "하루 한 명씩 소개해드려요.\n\n"
            "학교 이메일 인증으로 대학생만 이용할 수 있어요."
        ),
        buttons=[
            {
                "action": "webLink",
                "label": "오늘의 인연 만나기",
                "webLinkUrl": TALKN_URL,
            }
        ],
    )
    return kakao_response.add_output_to_response({"textCard": card}).get_response()
