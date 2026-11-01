"""Mobile calendar Tab exit must reveal the next field above real navigation.

Fictional local accounts only. All external requests are blocked by the shared
browser harness; viewport clipping approximates a keyboard, not native iOS.
"""
from pathlib import Path
import sys
import unittest

import test_local_data_safety as harness

sys.path.insert(0, str(Path(harness.__file__).resolve().parents[1] / 'tools'))
from check_touch_flows import enlarge_text


class MobileCalendarFocus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.LocalDataSafety.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        harness.LocalDataSafety.tearDownClass.__func__(cls)

    setUp = harness.LocalDataSafety.setUp
    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open
    snapshot = harness.LocalDataSafety.snapshot

    def prepare(self, width=393, scale=1):
        self.page.set_viewport_size({'width': width, 'height': 844})
        self.open()
        self.page.evaluate("""() => {
          session=null;stopCloudSync();localStorage.clear();state=blankState();
          weatherCache.data={temperature_2m:10,weather_code:0};weatherCache.at=Date.now();
          state.entries=[{id:'fictional-calendar-unchanged',type:'expense',
            date:today(),amount:12.35,category:'Прочее',who:'Учебный участник',
            unknownExtension:{preserve:[true,null,'raw']}}];
          showApp();renderAll();go('accounts');v108RefreshCalendars();
          localStorage.setItem('fictional-calendar-sentinel','keep');
        }""")
        if scale != 1:
            enlarge_text(self.page, scale)
        self.page.wait_for_function("document.getElementById('v117SnapshotDate').hasAttribute('data-v108-calendar')")
        self.page.wait_for_timeout(60)

    def open_at_bottom_edge(self):
        self.page.evaluate("""() => {
          const date=document.getElementById('v117SnapshotDate'),r=date.getBoundingClientRect(),
            nav=document.getElementById('mobileNav').getBoundingClientRect();
          window.scrollTo({top:scrollY+r.top-(nav.top-r.height-12),behavior:'instant'});
        }""")
        self.page.locator('#v117SnapshotDate').click()
        self.page.wait_for_function("document.getElementById('v108CalendarPanel')?.hidden===false")

    def assert_safe_focus(self, selector):
        self.assertTrue(self.page.locator(selector).evaluate('el=>el===document.activeElement'))
        geometry = self.page.locator(selector).evaluate("""el => {
          const r=el.getBoundingClientRect(),v=window.visualViewport,
            top=v?.offsetTop||0,bottom=top+(v?.height||innerHeight),
            nav=document.getElementById('mobileNav').getBoundingClientRect();
          return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,
            safeTop:top,safeBottom:nav.height&&nav.top<bottom?Math.min(bottom,nav.top):bottom,
            safeLeft:v?.offsetLeft||0,safeRight:(v?.offsetLeft||0)+(v?.width||innerWidth)};
        }""")
        self.assertGreaterEqual(geometry['top'], geometry['safeTop'] - 1, geometry)
        self.assertLessEqual(geometry['bottom'], geometry['safeBottom'] - 10, geometry)
        self.assertGreaterEqual(geometry['left'], geometry['safeLeft'] - 1, geometry)
        self.assertLessEqual(geometry['right'], geometry['safeRight'] + 1, geometry)
        self.assertTrue(self.page.locator('#v108CalendarPanel').is_hidden())

    def test_tab_from_calendar_reveals_account_amount_above_growing_navigation(self):
        for width in (320, 393, 430):
            for scale in (1, 2):
                with self.subTest(width=width, scale=scale):
                    self.prepare(width, scale)
                    before = self.snapshot()
                    self.open_at_bottom_edge()
                    self.page.locator('#v108CalendarPanel .v108-cancel').focus()
                    self.page.keyboard.press('Tab')
                    self.assert_safe_focus('#v117SnapshotAmount')
                    self.assertEqual(self.snapshot(), before)

    def test_tab_reveals_amount_inside_clipped_visual_viewport_without_writing(self):
        self.prepare()
        # The synthetic visualViewport cannot supply native keyboard panning.
        # Leave real document scroll room so the safe-area contract is reachable.
        self.page.evaluate("""() => {
          const spacer=document.createElement('div');spacer.style.height='900px';
          spacer.setAttribute('aria-hidden','true');document.getElementById('accounts').appendChild(spacer);
        }""")
        before = self.snapshot()
        self.open_at_bottom_edge()
        self.page.locator('#v108CalendarPanel .v108-cancel').focus()
        self.page.evaluate("""() => {
          const viewport=new EventTarget();Object.assign(viewport,
            {offsetTop:20,offsetLeft:0,width:393,height:410});
          Object.defineProperty(window,'visualViewport',{configurable:true,value:viewport});
        }""")
        self.page.keyboard.press('Tab')
        self.assert_safe_focus('#v117SnapshotAmount')
        self.assertEqual(self.snapshot(), before)

    def test_reverse_tab_reveals_preceding_amount_without_changing_date_or_data(self):
        self.prepare()
        self.page.evaluate("""() => {
          const spacer=document.createElement('div');spacer.style.height='900px';
          spacer.setAttribute('aria-hidden','true');document.getElementById('accounts').appendChild(spacer);
          const date=document.getElementById('v117ManualDate'),r=date.getBoundingClientRect();
          window.scrollTo({top:scrollY+r.top-12,behavior:'instant'});
        }""")
        before = self.snapshot()
        date = self.page.locator('#v117ManualDate').input_value()
        self.page.locator('#v117ManualDate').click()
        self.page.wait_for_function("document.getElementById('v108CalendarPanel')?.hidden===false")
        self.page.locator('#v108CalendarPanel .v108-header > button').first.focus()
        self.page.keyboard.press('Shift+Tab')
        self.assert_safe_focus('#v84AccountAmount')
        self.assertEqual(self.page.locator('#v117ManualDate').input_value(), date)
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
