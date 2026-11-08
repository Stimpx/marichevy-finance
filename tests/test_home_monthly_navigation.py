"""Home monthly links open the same period without changing financial records.

Run: python -m unittest discover -s tests -p test_home_monthly_navigation.py
Playwright/Chromium are required; requests stay in an offline synthetic fixture.
"""
import os
import shutil
import unittest

from playwright.sync_api import sync_playwright

import test_home_monthly_cards as monthly_fixture


class HomeMonthlyNavigation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = sync_playwright().start()
        executable = (os.environ.get('CHROMIUM_EXECUTABLE')
                      or shutil.which('chromium') or shutil.which('chromium-browser'))
        cls.browser = cls.p.chromium.launch(
            headless=True, **({'executable_path': executable} if executable else {}))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.p.stop()

    def setUp(self):
        monthly_fixture.HomeMonthlyCards.setUp(self)
        self.page.wait_for_function("typeof v151OpenHomeMonthly==='function'")
        self.page.evaluate('''() => {
          const select=document.getElementById('homeMonth');select.value='2026-10';
          select.dispatchEvent(new Event('change',{bubbles:true}));
          document.getElementById('incomeMonth').value='2026-11';
          document.getElementById('analyticsMonth').value='2026-11';
          document.getElementById('analyticsScope').value='all';
          window.originalNavigationAccounts=JSON.stringify(v84Data().accounts);
        }''')

    def tearDown(self):
        monthly_fixture.HomeMonthlyCards.tearDown(self)

    def assert_finances_unchanged(self):
        self.assertTrue(self.page.evaluate('''() =>
          JSON.stringify(state.entries)===originalMonthlyLedger &&
          JSON.stringify(v84Data().accounts)===originalNavigationAccounts'''))

    def test_income_card_surface_opens_income_for_selected_home_month(self):
        card = self.page.locator('#v146HomeMonthly .v146-income')
        self.assertEqual(card.get_attribute('href'), '#income')
        card.click(position={'x': 8, 'y': 8})
        self.assertTrue(self.page.locator('#income').evaluate("e=>e.classList.contains('active')"))
        self.assertEqual(self.page.locator('#incomeMonth').input_value(), '2026-10')
        self.assertEqual(self.page.locator('#incomeList .v141-operation').count(), 1)
        self.assertIn('октябрь 2026', self.page.locator('#incomePeopleChartHint').inner_text())
        self.assert_finances_unchanged()

    def test_expense_card_enter_opens_selected_month_instead_of_previous_all_time(self):
        card = self.page.locator('#v146HomeMonthly .v146-expense')
        self.assertEqual(card.get_attribute('href'), '#analytics')
        card.focus()
        card.press('Enter')
        self.assertTrue(self.page.locator('#analytics').evaluate("e=>e.classList.contains('active')"))
        self.assertEqual(self.page.locator('#analyticsMonth').input_value(), '2026-10')
        self.assertEqual(self.page.locator('#analyticsScope').input_value(), 'month')
        self.assertEqual(self.page.locator('#v130AnalyticsPeriodTotal').inner_text().replace('\u00a0', ' '),
                         '100,00 ₽')
        self.assertIn('октябрь', self.page.locator('#v130AnalyticsPeriodLabel').inner_text())
        self.assert_finances_unchanged()

    def test_expense_analytics_button_uses_same_selected_period(self):
        self.page.locator('#v147HomeAnalyticsButton').click()
        self.assertTrue(self.page.locator('#analytics').evaluate("e=>e.classList.contains('active')"))
        self.assertEqual(self.page.locator('#analyticsMonth').input_value(), '2026-10')
        self.assertEqual(self.page.locator('#analyticsScope').input_value(), 'month')
        self.assertEqual(self.page.locator('#v130AnalyticsPeriodTotal').inner_text().replace('\u00a0', ' '),
                         '100,00 ₽')
        self.assert_finances_unchanged()


if __name__ == '__main__':
    unittest.main(verbosity=2)
