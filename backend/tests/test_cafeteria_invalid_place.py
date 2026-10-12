import unittest
from unittest.mock import AsyncMock, patch
from app.routers import cafeteria
from app.schemas.kakao_request import KakaoRequest
from app.schemas.experiment_lab import Protocol


class InvalidPlaceTest(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_inputs_do_not_open_files(self):
        for handler,utterance in [(cafeteria.get_today_menu,'unknown-cafeteria'),
                                  (cafeteria.get_menu_by_day,'월요일unknown-cafeteria'),
                                  (cafeteria.get_today_menu,'../unknown'),
                                  (cafeteria.get_today_menu,'')]:
            with patch.object(cafeteria.common,'load_data',new=AsyncMock()) as load:
                result=await handler(KakaoRequest(userRequest={'utterance':utterance}))
                self.assertEqual(result['version'],'2.0')
                self.assertIn('식당 이름을 확인',result['template']['outputs'][0]['simpleText']['text'])
                load.assert_not_awaited()

    async def test_exploratory_protocol_requires_explicit_exception(self):
        with self.assertRaises(ValueError):
            Protocol(purpose='exploratory')
        with self.assertRaises(ValueError):
            Protocol(aa_waiver_reason='Do not bypass a formal experiment gate')

    async def test_duration_is_measured_from_start_and_legacy_cap_is_preserved(self):
        from datetime import datetime, timedelta, timezone
        from app.services.experiment_lab import enrollment_end
        start=datetime(2026,10,13,tzinfo=timezone.utc)
        for days in (7,21):
            p=Protocol(purpose='exploratory',exploratory_enrollment_days=days,
                aa_waiver_reason='Explicit owner choice to run before full AA completion')
            self.assertEqual(enrollment_end({'kind':'ab','started_at':start,'protocol':p.model_dump(mode='json')}),start+timedelta(days=days))
        self.assertEqual(enrollment_end({'kind':'ab','started_at':start,'protocol':{}}),start+timedelta(days=28))
