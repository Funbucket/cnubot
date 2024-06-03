from app.utils import kakao_json_response


def create_help_center_response():
    kakao_response = kakao_json_response.KakaoJsonResponse()
    return kakao_response.add_output_to_response(
        {
            "textCard": kakao_response.create_text_card(
                title="츠누봇을 함께 만들어가요 👊",
                description="• 잘못된 정보가 있나요?\n\n• 새로운 기능이 있으면 필요한가요?",
                buttons=[
                    {
                        "action": "operator",
                        "label": "고객센터 연결",
                    }
                ],
            )
        }
    )
