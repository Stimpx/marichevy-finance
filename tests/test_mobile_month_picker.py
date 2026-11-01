"""Month popup readability at phone widths; fictional data, blocked network."""
import unittest
import sys
from pathlib import Path

import test_local_data_safety as harness
sys.path.insert(0, str(Path(harness.__file__).resolve().parents[1] / 'tools'))
from check_touch_flows import enlarge_text


class MobileMonthPicker(unittest.TestCase):
    @classmethod
    def setUpClass(cls): harness.LocalDataSafety.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls): harness.LocalDataSafety.tearDownClass.__func__(cls)
    setUp = harness.LocalDataSafety.setUp
    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open
    snapshot = harness.LocalDataSafety.snapshot

    def prepare(self, width=393):
        self.page.set_viewport_size({'width': width, 'height': 852})
        self.open()
        self.page.evaluate("""() => {
          session=null;stopCloudSync();state=blankState();localStorage.clear();
          today=()=> '2026-11-02';month=()=> '2026-11';
          state.entries=['2026-09','2026-10','2026-11'].map((m,i)=>({
            id:'fictional-month-'+i,type:'expense',date:m+'-01',amount:1.25,
            category:'Продукты',who:'Учебный участник',beneficiary:'Общее',
            store:'Вымышленный магазин',futureField:{keep:[true,null]}}));
          weatherCache.data={temperature_2m:10,weather_code:0};weatherCache.at=Date.now();
          showApp();renderAll();go('analytics');analyticsMonth.value='2026-11';
          renderAnalytics();v107RefreshSelects();
        }""")
        self.before = self.snapshot()

    def trigger(self):
        return self.page.locator('#analyticsMonth').locator('..').locator('.v107-select-trigger')

    def panel(self):
        return self.page.locator('.v107-select-panel:not([hidden])')

    def geometry(self):
        return self.panel().evaluate("""list=>{
          const rect=el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height}};
          return {viewport:innerWidth,list:rect(list),scroll:list.scrollWidth,client:list.clientWidth,
            rows:[...list.querySelectorAll('.v107-select-option-text')].map(el=>{
              const range=document.createRange();range.selectNodeContents(el);
              return {text:el.textContent,lines:range.getClientRects().length,lineHeight:parseFloat(getComputedStyle(el).lineHeight),
                textHeight:range.getBoundingClientRect().height,scroll:el.scrollWidth,client:el.clientWidth,...rect(el)};
            })};
        }""")

    def assert_bounded(self, geometry):
        self.assertGreaterEqual(geometry['list']['x'], 7, geometry)
        self.assertLessEqual(geometry['list']['right'], geometry['viewport'] - 7, geometry)
        self.assertGreaterEqual(geometry['list']['y'], 0, geometry)
        self.assertLessEqual(geometry['list']['bottom'], 853, geometry)
        self.assertLessEqual(geometry['scroll'], geometry['client'] + 1, geometry)
        self.assertTrue(all(row['scroll'] <= row['client'] + 1 for row in geometry['rows']), geometry)

    def test_month_labels_fit_one_line_on_regular_phone_widths(self):
        for width in (320, 390, 393, 430):
            with self.subTest(width=width):
                self.prepare(width)
                self.trigger().click()
                geometry = self.geometry()
                self.assert_bounded(geometry)
                self.assertEqual([row['lines'] for row in geometry['rows']], [1, 1, 1], geometry)
                self.trigger().press('Escape')
                self.assertEqual(self.snapshot(), self.before)

    def test_large_text_stays_in_view_and_keeps_month_labels_readable(self):
        for width in (320, 390, 393, 430):
            with self.subTest(width=width):
                self.prepare(width)
                self.trigger().click()
                enlarge_text(self.page, 2)
                self.trigger().press('Escape')
                self.trigger().scroll_into_view_if_needed()
                self.trigger().click()
                geometry = self.geometry()
                self.assert_bounded(geometry)
                self.assertTrue(all(row['lines'] <= 2 for row in geometry['rows']), geometry)
                self.trigger().press('Escape')
                self.assertEqual(self.snapshot(), self.before)

    def test_month_commit_dispatches_once_and_escape_keeps_financial_data(self):
        self.prepare()
        self.page.evaluate("""() => {window.monthEvents={input:0,change:0};
          analyticsMonth.addEventListener('input',()=>monthEvents.input++);
          analyticsMonth.addEventListener('change',()=>monthEvents.change++);
        }""")
        self.trigger().click()
        self.panel().get_by_role('option', name='сентябрь 2026 г.', exact=True).click()
        self.assertEqual(self.page.locator('#analyticsMonth').input_value(), '2026-09')
        self.assertEqual(self.page.evaluate('monthEvents'), {'input': 1, 'change': 1})
        self.trigger().click()
        self.trigger().press('End')
        self.trigger().press('Escape')
        self.assertEqual(self.page.locator('#analyticsMonth').input_value(), '2026-09')
        self.assertEqual(self.snapshot(), self.before)

    def test_intrinsic_width_keeps_long_generic_options_wrapped_inside_phone(self):
        self.prepare(320)
        self.page.evaluate("""() => {
          go('dates');
          bdGroup.add(new Option('Очень длинное пользовательское название '.repeat(12)+'БезПробелов'.repeat(20),'fictional-long'));
          v107RefreshSelects();
        }""")
        trigger=self.page.locator('#bdGroup').locator('..').locator('.v107-select-trigger')
        trigger.scroll_into_view_if_needed();trigger.click()
        geometry=self.geometry()
        self.assert_bounded(geometry)
        self.assertGreater(geometry['rows'][-1]['lines'], 2, geometry)
        trigger.press('Escape')
        self.assertEqual(self.page.locator('#bdGroup').input_value(), 'Близкие')
        self.assertEqual(self.snapshot(), self.before)


if __name__ == '__main__': unittest.main()
