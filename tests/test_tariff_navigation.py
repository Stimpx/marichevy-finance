"""Visible FREE/PRO entry points; fictional data and blocked external I/O."""
from pathlib import Path
import unittest

from playwright.sync_api import expect

import test_local_data_safety as harness


class TariffNavigation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.LocalDataSafety.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        harness.LocalDataSafety.tearDownClass.__func__(cls)

    def setUp(self):
        self.context = self.browser.new_context(
            viewport={'width': 393, 'height': 844}, has_touch=True, is_mobile=True,
            timezone_id='Europe/Moscow', service_workers='block', reduced_motion='reduce')
        self.context.route('**/*', lambda route: route.continue_()
                           if route.request.url.startswith(self.base) else route.abort())
        self.page = self.context.new_page()
        self.page.set_default_timeout(4000)
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))

    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open
    snapshot = harness.LocalDataSafety.snapshot

    def prepare(self, width=393, height=844, scale=1):
        self.page.set_viewport_size({'width': width, 'height': height})
        self.open()
        self.page.evaluate("""() => {
          session=null;stopCloudSync();localStorage.clear();state=blankState();
          state.entries=[{id:'fictional-tariff-row',type:'expense',amount:17.125,
            date:today(),category:'Продукты',who:'Учебный участник',store:'Учебный магазин',
            futureField:{preserve:['raw',null,true]}}];
          state.settings.tariffExtension={preserve:'fictional'};
          loanScheduleData=()=>[{n:1,payDate:'2099-12-01',periodEnd:'2099-12-01',
            payment:1,interest:0,body:1,balance:0}];
          weatherCache.data={temperature_2m:10,weather_code:0};weatherCache.at=Date.now();
          localStorage.setItem('fictional-tariff-sentinel','keep');
          showApp();renderAll();go('home');
        }""")
        if scale != 1:
            self.page.evaluate("""scale => {
              const nodes=[...document.querySelectorAll('body,body *')]
                .filter(n=>!['SCRIPT','STYLE','SVG','PATH'].includes(n.tagName));
              const sizes=nodes.map(n=>parseFloat(getComputedStyle(n).fontSize));
              nodes.forEach((n,i)=>{if(sizes[i])n.style.setProperty('font-size',sizes[i]*scale+'px','important')});
            }""", scale)
        self.before = self.snapshot()

    def assert_tariffs_open(self):
        expect(self.page.locator('#plans')).to_be_visible()
        expect(self.page.locator('#pageTitle')).to_have_text('Тарифы FREE / PRO')
        expect(self.page.locator('#nav [data-page="plans"]')).to_have_attribute('aria-current', 'page')
        self.assertEqual(self.page.locator('#v121ProductPreview').count(), 0)
        for plan in ('free', 'pro'):
            card = self.page.locator(f'#plans [data-plan="{plan}"]')
            expect(card).to_be_visible()
            self.assertFalse(card.evaluate("n=>!!n.closest('details:not([open])')"))
        expect(self.page.locator('#v96FreePrice')).to_have_text('0 ₽')
        expect(self.page.locator('#v96ProPrice')).to_have_text('990 ₽')
        expect(self.page.locator('#v96ProPeriod')).to_have_text('один раз')
        expect(self.page.locator('#v96ProCheckout')).to_be_disabled()
        self.assertIn('Оплата пока не подключена', self.page.locator('#v96PlansPreviewStatus').inner_text())
        self.assertEqual(self.snapshot(), self.before)
        self.assertEqual(self.errors, [])

    def test_sidebar_keyboard_opens_actual_tariffs_without_a_second_disclosure(self):
        self.prepare(width=1440, height=1000)
        button = self.page.locator('#nav [data-page="plans"]')
        expect(button).to_have_accessible_name('Тарифы FREE / PRO')
        button.focus()
        self.page.keyboard.press('Enter')
        self.assert_tariffs_open()
        self.assertLess(self.page.locator('#plans .v96-plan-grid').bounding_box()['y'], 700)

    def test_mobile_more_contains_a_clear_tariff_destination_at_large_text(self):
        for width, height, scale in ((320, 740, 1), (393, 844, 1),
                                     (393, 844, 2), (844, 390, 1)):
            with self.subTest(width=width, scale=scale):
                self.prepare(width, height, scale)
                self.page.locator('#v74MoreToggle').tap()
                button = self.page.locator('#v74MorePanel [data-page="plans"]')
                expect(button).to_have_accessible_name('Тарифы FREE / PRO')
                expect(button).to_be_visible()
                self.assertGreaterEqual(button.bounding_box()['height'], 44)
                button.tap()
                expect(self.page.locator('#v74MorePanel')).to_be_hidden()
                expect(self.page.locator('#v74MoreToggle')).to_have_class('active')
                self.assert_tariffs_open()

    def test_help_shortcut_and_browser_history_keep_tariffs_and_data(self):
        self.prepare()
        self.page.evaluate("go('help')")
        button = self.page.locator('#help').get_by_role('button', name='Тарифы FREE / PRO', exact=True)
        button.click()
        self.assert_tariffs_open()
        self.page.go_back()
        expect(self.page.locator('#help')).to_be_visible()
        self.page.go_forward()
        self.assert_tariffs_open()

    def test_visible_price_cards_fit_phone_and_desktop_with_double_text(self):
        directory = Path('/tmp/tariff-navigation-review')
        directory.mkdir(exist_ok=True)
        for width in (320, 393, 768, 1280, 1920):
            for scale in (1, 2):
                with self.subTest(width=width, scale=scale):
                    self.prepare(width, 1000, scale)
                    self.page.evaluate("go('plans')")
                    self.assert_tariffs_open()
                    geometry = self.page.evaluate("""() => {
                      const cards=[...document.querySelectorAll('#plans .v96-plan-card')];
                      return {doc:document.documentElement.scrollWidth,
                        cards:cards.map(card=>{const r=card.getBoundingClientRect();return {
                          left:r.left,right:r.right,overflow:card.scrollWidth-card.clientWidth,
                          actions:[...card.querySelectorAll('button')].map(n=>{
                            const b=n.getBoundingClientRect();return {width:b.width,height:b.height};})};})};
                    }""")
                    self.assertLessEqual(geometry['doc'], width + 1, geometry)
                    for card in geometry['cards']:
                        self.assertGreaterEqual(card['left'], -1, geometry)
                        self.assertLessEqual(card['right'], width + 1, geometry)
                        self.assertLessEqual(card['overflow'], 1, geometry)
                        for action in card['actions']:
                            self.assertGreaterEqual(action['height'], 44, geometry)
                    if width in (393, 1920):
                        self.page.screenshot(path=str(directory / f'tariffs-{width}-text{scale}.png'), full_page=True)


if __name__ == '__main__':
    unittest.main()
