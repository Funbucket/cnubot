import copy
import tempfile
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from app.services import cafeteria, experiments, menu_button_experiment as subject


class MenuButtonExperimentTest(unittest.IsolatedAsyncioTestCase):
    def test_button_module_changes_do_not_change_frozen_inline_policy(self):
        lab = subject.experiment_lab
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for source in Path(lab.__file__).parent.glob('*.py'):
                (root/source.name).write_bytes(source.read_bytes())
            with patch.object(lab,'__file__',str(root/'experiment_lab.py')):
                frozen = lab.policy_checksum()
                button_file = root/'menu_button_experiment.py'
                button_file.write_text(button_file.read_text()+'\n# changed button copy\n')
                self.assertEqual(lab.policy_checksum(),frozen)
                inline_file = root/'promotions.py'
                inline_file.write_text(inline_file.read_text()+'\n# changed inline policy\n')
                self.assertNotEqual(lab.policy_checksum(),frozen)

    def response(self, inline=None):
        meal = {"type": "한식", "menu": ["밥"]}
        return cafeteria.create_menu_response("월요일", {
            "breakfast": [], "lunch": [meal], "dinner": [meal]}, "기숙사",
            inline_product_output=inline)

    async def test_assignment_only_when_button_rendered_and_qa_excluded(self):
        with patch.object(subject.experiment_lab, "is_qa", return_value=False), \
             patch.object(experiments, "get_active_variant", new_callable=AsyncMock) as assign:
            await subject.apply("user", self.response({"simpleText": {"text": "상품"}}))
            assign.assert_not_awaited()
        with patch.object(subject.experiment_lab, "is_qa", return_value=True), \
             patch.object(experiments, "get_active_variant", new_callable=AsyncMock) as assign:
            await subject.apply("qa", self.response())
            assign.assert_not_awaited()

    async def test_variants_keep_share_and_navigation_and_record_actual_policy(self):
        for key, policy in subject.VARIANTS.items():
            response = self.response()
            replies = copy.deepcopy(response["template"]["quickReplies"])
            with patch.object(subject.experiment_lab, "is_qa", return_value=False), \
                 patch.object(experiments, "get_active_variant", AsyncMock(return_value={"variant_key": key})), \
                 patch.object(experiments, "record_event", new_callable=AsyncMock) as record:
                await subject.apply("user", response)
            cards = [card for output in response["template"]["outputs"] for card in output["carousel"]["items"]]
            self.assertEqual(cards[0]["buttons"][0], {"label": "식단 공유하기", "action": "share"})
            self.assertEqual(cards[0]["buttons"][1]["label"], policy["label"])
            self.assertEqual(cards[0]["buttons"][1]["messageText"], policy["messageText"])
            self.assertEqual(len(cards[1]["buttons"]), 1)
            self.assertEqual(response["template"]["quickReplies"], replies)
            self.assertEqual(record.await_args.kwargs["properties"]["collection_id"], policy["collection_id"])

    async def test_missing_metadata_and_no_prior_exposure_do_not_count(self):
        pool = unittest.mock.Mock(fetchval=AsyncMock(return_value=False))
        with patch.object(subject.experiment_lab, "is_qa", return_value=False), \
             patch.object(subject, "get_pool", return_value=pool), \
             patch.object(experiments, "record_event", new_callable=AsyncMock) as record:
            await subject.record_click("user", {"source": "unknown"}, "food")
            pool.fetchval.assert_not_awaited()
            await subject.record_click("user", {"source": "menu_button", "button_id": subject.BUTTON_ID,
                                                "button_label": subject.VARIANTS["control"]["label"]}, "food")
            record.assert_not_awaited()
            pool.fetchval.return_value = True
            await subject.record_click("user", {"source": "menu_button", "button_id": subject.BUTTON_ID,
                                                "button_label": subject.VARIANTS["treatment"]["label"]}, "today_deals")
            record.assert_awaited_once()
            self.assertEqual(record.await_args.args[2], "menu_button_click")
