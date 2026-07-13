import unittest

from bs4 import BeautifulSoup

from app.scrapers.dorm import extract_menus_from_cell


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


if __name__ == "__main__":
    unittest.main()
