import unittest

from app.services import talkn


class TalknResponseTest(unittest.TestCase):
    def test_returns_single_talkn_link_button(self):
        response = talkn.create_talkn_response()
        card = response["template"]["outputs"][0]["textCard"]

        self.assertEqual(card["title"], "취향이 통하는 인연")
        self.assertEqual(
            card["description"],
            "🎬 영화·🎧 음악·📚 책 취향이 비슷한 대학생을\n"
            "하루 한 명씩 소개해드려요.\n\n"
            "학교 이메일 인증으로 대학생만 이용할 수 있어요.",
        )
        self.assertEqual(len(card["buttons"]), 1)
        self.assertEqual(card["buttons"][0]["label"], "오늘의 인연 만나기")
        self.assertEqual(card["buttons"][0]["action"], "webLink")
        self.assertEqual(card["buttons"][0]["webLinkUrl"], "https://talkn.world")


if __name__ == "__main__":
    unittest.main()
