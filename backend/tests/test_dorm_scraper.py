import unittest
from datetime import date
from unittest import mock

from bs4 import BeautifulSoup

from app.scrapers.dorm import (
    _parse_chart_data,
    _parse_inwon,
    extract_menus_from_cell,
    scrape_current_week_dorm_menu,
)


class DormScraperTest(unittest.TestCase):
    def test_english_menu_section_does_not_leak_into_korean_menu(self):
        cell = BeautifulSoup(
            """
            <td class="left last">메인A(780kcal)판매식<br>
            잡곡밥[쌀,흑미,현미:국내산]<br>
            들깨무채국 5,6,16<br>
            춘천st닭갈비 2,5,6,12,15,16,18<br>
            캐모마일차<br>
            <br>
            Menu A(780kcal) (Retail)<br>
            Multi-Grain Rice<br>
            Perilla Seed Shredded Radish Soup<br>
            Chamomile Tea<br>
            </td>
            """,
            "html.parser",
        ).td

        menus = extract_menus_from_cell(cell)

        self.assertEqual(len(menus), 1)
        self.assertEqual(menus[0]["type"], "메인A")
        self.assertEqual(menus[0]["calorie"], "780")
        self.assertEqual(
            menus[0]["menu"],
            [
                "잡곡밥[쌀,흑미,현미:국내산]",
                "들깨무채국",
                "춘천st닭갈비",
                "캐모마일차",
            ],
        )

    def test_special_event_menu_without_calorie_is_preserved(self):
        cell = BeautifulSoup(
            """
            <td class="left last">메인A(이벤트식)<br>
            *이벤트식*<br>
            반계탕 5,6,15,16<br>
            [계육:국내산]<br>
            방울토마토<br>
            <br>
            Menu A(Special Event)<br>
            *Special Event Meal*<br>
            Half Chicken Ginseng Soup<br>
            Cherry Tomatoes<br>
            </td>
            """,
            "html.parser",
        ).td

        menus = extract_menus_from_cell(cell)

        self.assertEqual(len(menus), 1)
        self.assertEqual(menus[0]["type"], "메인A")
        self.assertEqual(menus[0]["calorie"], "")
        self.assertEqual(
            menus[0]["menu"],
            ["*이벤트식*", "반계탕", "[계육:국내산]", "방울토마토"],
        )

    def test_parse_crowding_current_and_available_counts(self):
        self.assertEqual(_parse_inwon("12|308"), (12, 308))

    def test_parse_crowding_chart_data(self):
        self.assertEqual(_parse_chart_data("1,2,3,4,5,6,7,8,9"), list(range(1, 10)))

    @mock.patch("app.scrapers.dorm.scrape_dorm_menu")
    def test_current_week_chooses_page_containing_today(self, scrape):
        scrape.side_effect = [
            {"date": "10/05 ~ 10/11", "menu": ["next"]},
            {"date": "09/28 ~ 10/04", "menu": ["current"]},
        ]

        result = scrape_current_week_dorm_menu(
            "https://example.test/menu?page={page}", today=date(2026, 9, 28)
        )

        self.assertEqual(result["menu"], ["current"])
        self.assertEqual(
            [call.args[0] for call in scrape.call_args_list],
            [
                "https://example.test/menu?page=1",
                "https://example.test/menu?page=2",
            ],
        )

    @mock.patch("app.scrapers.dorm.scrape_dorm_menu")
    def test_current_week_fails_when_no_candidate_contains_today(self, scrape):
        scrape.side_effect = [
            {"date": "10/05 ~ 10/11", "menu": ["next"]},
            {"date": "09/21 ~ 09/27", "menu": ["previous"]},
        ]

        with self.assertRaises(ValueError):
            scrape_current_week_dorm_menu(
                "https://example.test/menu?page={page}", today=date(2026, 9, 28)
            )


if __name__ == "__main__":
    unittest.main()
