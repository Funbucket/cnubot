import unittest

from app.services import help


class HelpResponseTest(unittest.TestCase):
    def test_keeps_customer_center_button(self):
        response = help.create_help_center_response()
        buttons = response["template"]["outputs"][0]["textCard"]["buttons"]

        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0]["action"], "operator")


if __name__ == "__main__":
    unittest.main()
