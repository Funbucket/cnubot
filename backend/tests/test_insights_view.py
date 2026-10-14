"""Rendering checks for ambiguous rates and misleading zero-click bars."""
import unittest
from datetime import date

from bs4 import BeautifulSoup

from app.services.insights_view import render_insights


class InsightsViewTest(unittest.TestCase):
    def test_entry_rate_describes_list_entry_not_product_clicks(self):
        page = BeautifulSoup(render_insights({"paths": [{
            "path": "entry", "reach_users": 100, "action_users": 20,
            "clicked_users": 3,
        }]}), "html.parser")
        metric = page.select_one(".metric")
        self.assertIn("목록 진입률 20.0%", metric.get_text())
        self.assertNotIn("상품 클릭률", metric.get_text())

    def test_zero_click_day_has_no_visible_bar_but_remains_accessible(self):
        page = BeautifulSoup(render_insights({"daily": [{
            "day": date(2026, 10, 8), "exposed_users": 100,
            "clicked_users": 0, "click_events": 0,
        }]}), "html.parser")
        self.assertEqual(page.select_one(".chart-bar")["style"], "height:0.0%")
        self.assertIn("클릭 0명", page.select_one(".chart-day")["aria-label"])
        self.assertIn("2026-10-08", page.select_one(".trend table").get_text())

    def test_product_names_are_escaped_in_table_and_search_attributes(self):
        name = '<script>alert("sample")</script>'
        page = BeautifulSoup(render_insights({"products": [{
            "product_key": "sample", "product_name": name,
            "exposed_users": 0, "clicked_users": 1,
        }]}), "html.parser")
        product = page.select_one("[data-product]")
        self.assertEqual(product.select_one("b").get_text(), name)
        self.assertIn(name, product["data-name"])
        self.assertIsNone(product.select_one("script"))
        self.assertEqual(product.select("td")[3].get_text(), "—")
