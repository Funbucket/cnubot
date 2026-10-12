import unittest
from datetime import date, timedelta
from unittest import mock

from bs4 import BeautifulSoup
import requests

from app.scrapers.dorm import (
    _parse_chart_data,
    _parse_inwon,
    extract_menus_from_cell,
    is_current_week_dorm_menu,
    scrape_current_week_dorm_menu,
    scrape_dorm_menu,
)


def week_menu(monday: date) -> dict:
    sunday = monday + timedelta(days=6)
    return {
        "place": "dorm", "date": f"{monday:%m/%d} ~ {sunday:%m/%d}",
        "date_start": monday.isoformat(), "date_end": sunday.isoformat(),
        "menu": [{"day": day, "breakfast": [],
                  "lunch": [{"type": "메인A", "menu": ["잡곡밥", "된장국"]}],
                  "dinner": []} for day in "월화수목금토일"],
    }


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
            week_menu(date(2026, 10, 5)),
            week_menu(date(2026, 9, 28)),
        ]

        result = scrape_current_week_dorm_menu(
            "https://example.test/menu?page={page}", today=date(2026, 9, 28)
        )

        self.assertEqual(result["date"], "09/28 ~ 10/04")
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
            week_menu(date(2026, 10, 5)),
            week_menu(date(2026, 9, 21)),
        ]

        with self.assertRaises(ValueError):
            scrape_current_week_dorm_menu(
                "https://example.test/menu?page={page}", today=date(2026, 9, 28)
            )

    @mock.patch("app.scrapers.dorm.scrape_dorm_menu")
    def test_page_one_success_does_not_depend_on_page_two(self, scrape):
        scrape.side_effect = [week_menu(date(2026, 10, 12)), requests.Timeout()]
        result = scrape_current_week_dorm_menu(
            "https://example.com/menu?page={page}", today=date(2026, 10, 12)
        )
        self.assertEqual(result["date"], "10/12 ~ 10/18")
        scrape.assert_called_once()

    @mock.patch("app.scrapers.dorm.scrape_dorm_menu")
    def test_first_page_failure_still_checks_second(self, scrape):
        scrape.side_effect = [requests.Timeout(), week_menu(date(2026, 10, 12))]
        result = scrape_current_week_dorm_menu(
            "https://example.com/menu?page={page}", today=date(2026, 10, 12)
        )
        self.assertEqual(result["date"], "10/12 ~ 10/18")
        self.assertEqual(scrape.call_count, 2)

    def test_sunday_file_becomes_stale_on_monday(self):
        menu = week_menu(date(2026, 10, 5))
        self.assertTrue(is_current_week_dorm_menu(menu, date(2026, 10, 11)))
        self.assertFalse(is_current_week_dorm_menu(menu, date(2026, 10, 12)))

    def test_year_boundary_and_old_year(self):
        menu = week_menu(date(2026, 12, 28))
        self.assertTrue(is_current_week_dorm_menu(menu, date(2027, 1, 1)))
        menu.pop("date_start")
        menu.pop("date_end")
        self.assertTrue(is_current_week_dorm_menu(menu, date(2027, 1, 1)))
        menu = week_menu(date(2026, 10, 12))
        menu.update(date_start="2025-10-12", date_end="2025-10-18")
        self.assertFalse(is_current_week_dorm_menu(menu, date(2026, 10, 12)))

    def test_rejects_missing_duplicate_or_empty_rows(self):
        for variant in ("missing", "duplicate", "empty", "invalid"):
            menu = week_menu(date(2026, 10, 12))
            if variant == "missing":
                menu["menu"].pop()
            elif variant == "duplicate":
                menu["menu"][-1]["day"] = "월"
            elif variant == "invalid":
                menu["menu"][0]["lunch"] = None
            else:
                for row in menu["menu"]:
                    row["lunch"] = []
            with self.subTest(variant=variant):
                self.assertFalse(is_current_week_dorm_menu(menu, date(2026, 10, 12)))

    @mock.patch("app.scrapers.dorm.scrape_dorm_menu")
    def test_incomplete_page_is_skipped_for_complete_week(self, scrape):
        incomplete = week_menu(date(2026, 10, 12))
        incomplete["menu"].pop()
        scrape.side_effect = [incomplete, week_menu(date(2026, 10, 12))]
        result = scrape_current_week_dorm_menu(
            "https://example.com/menu?page={page}", today=date(2026, 10, 12)
        )
        self.assertEqual(len(result["menu"]), 7)
        self.assertEqual(scrape.call_count, 2)

    @mock.patch("app.scrapers.dorm.requests.get")
    def test_html_preserves_source_year_and_parses_complete_week(self, get):
        rows = "".join(
            f"<tr><td>10/{12+i}({day})</td><td></td>"
            "<td>메인A(700kcal)<br>잡곡밥<br>된장국</td><td></td></tr>"
            for i, day in enumerate("월화수목금토일")
        )
        html = ('<div class="diet_table_top"><strong>2026-10-12 ~ 2026-10-18</strong></div>'
                f'<table class="default_view diet_table"><tbody>{rows}</tbody></table>')
        get.return_value = mock.Mock(content=html.encode())
        menu = scrape_dorm_menu("https://example.com/menu?page=1")
        self.assertEqual(menu["date_start"], "2026-10-12")
        self.assertEqual(menu["date_end"], "2026-10-18")
        self.assertTrue(is_current_week_dorm_menu(menu, date(2026, 10, 12)))


if __name__ == "__main__":
    unittest.main()
