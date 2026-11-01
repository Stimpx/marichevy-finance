"""Actual native year glyphs and limits; fictional state, external I/O blocked.

CDP pierces Chromium's user-agent input shadow tree. Measuring the text Range
against its editing viewport catches clipped digits even when the outer input
and scrollWidth fit. This is not physical Safari evidence.
"""
from pathlib import Path
import sys
import unittest

import test_local_data_safety as harness

sys.path.insert(0, str(Path(harness.__file__).resolve().parents[1] / 'tools'))
from check_touch_flows import enlarge_text


class CalendarYearReadability(unittest.TestCase):
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

    def prepare(self, width=1280, route='planning'):
        self.page.set_viewport_size({'width': width, 'height': 1000})
        self.open()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.evaluate("""route => {
          session=null;stopCloudSync();localStorage.clear();state=blankState();
          showApp();renderAll();go(route);v108RefreshCalendars();
        }""", route)
        self.cdp = self.context.new_cdp_session(self.page)
        self.before = self.snapshot()

    @staticmethod
    def walk(node):
        attrs = node.get('attributes', [])
        yield node, dict(zip(attrs[::2], attrs[1::2]))
        for key in ('children', 'shadowRoots'):
            for child in node.get(key, []):
                yield from CalendarYearReadability.walk(child)

    def painted_year(self):
        tree = self.cdp.send('DOM.getDocument', {'depth': -1, 'pierce': True})['root']
        year = next(node for node, attrs in self.walk(tree)
                    if attrs.get('class') == 'v108-year')
        viewport = next(node for node, attrs in self.walk(year)
                        if attrs.get('id') == 'editing-view-port')
        handle = self.cdp.send('DOM.resolveNode', {'nodeId': viewport['nodeId']})['object']['objectId']
        result = self.cdp.send('Runtime.callFunctionOn', {
            'objectId': handle, 'returnByValue': True,
            'functionDeclaration': """function(){
              const range=document.createRange();range.selectNodeContents(this);
              const text=range.getBoundingClientRect(),clip=this.getBoundingClientRect();
              return {text:range.toString(),left:text.left,right:text.right,
                top:text.top,bottom:text.bottom,clipLeft:clip.left,clipRight:clip.right,
                clipTop:clip.top,clipBottom:clip.bottom};
            }"""})['result']['value']
        self.cdp.send('Runtime.releaseObject', {'objectId': handle})
        return result

    def open_month_view(self, route):
        if route == 'planning':
            self.page.locator('#v118PlanMonth').fill('2026-06')
            self.page.locator('#v118PlanMonth').click()
        else:
            self.page.locator('#bdDate').fill('2026-06-15')
            self.page.locator('#bdDate').click()
            self.page.get_by_role('button', name='Выбрать месяц и год', exact=True).click()
        self.assertTrue(self.page.locator('#v108CalendarPanel').is_visible())

    def test_all_year_digits_fit_native_editing_viewport_and_header_at_large_text(self):
        for width in (320, 393, 1280, 1920):
            for scale in (1, 2):
                for route in ('planning', 'dates'):
                    self.prepare(width, route)
                    self.open_month_view(route)
                    if scale != 1:
                        enlarge_text(self.page, scale)
                        # Enlarging a long birthday form can move its anchor out
                        # of view; reopen at the actual visible anchor.
                        self.page.keyboard.press('Escape')
                        self.open_month_view(route)
                    year = self.page.get_by_role('spinbutton', name='Год', exact=True)
                    for value in ('2026', '9999', '1'):
                        with self.subTest(width=width, scale=scale, route=route, year=value):
                            year.fill(value)
                            year.press('Tab')
                            painted = self.painted_year()
                            self.assertEqual(painted['text'], value)
                            self.assertGreaterEqual(painted['left'], painted['clipLeft'] - .5, painted)
                            self.assertLessEqual(painted['right'], painted['clipRight'] + .5, painted)
                            self.assertGreaterEqual(painted['top'], painted['clipTop'] - .5, painted)
                            self.assertLessEqual(painted['bottom'], painted['clipBottom'] + .5, painted)
                            geometry = self.page.locator('#v108CalendarPanel').evaluate("""panel=>{
                              const r=panel.getBoundingClientRect(),controls=[...panel.querySelectorAll('.v108-header button,.v108-year')];
                              return {left:r.left,right:r.right,sw:panel.scrollWidth,cw:panel.clientWidth,
                                controls:controls.map(el=>{const b=el.getBoundingClientRect();return {left:b.left,right:b.right,w:b.width,h:b.height}})};
                            }""")
                            self.assertGreaterEqual(geometry['left'], -.5)
                            self.assertLessEqual(geometry['right'], width + .5)
                            self.assertLessEqual(geometry['sw'], geometry['cw'] + 1)
                            for control in geometry['controls']:
                                self.assertGreaterEqual(control['left'], geometry['left'] - .5)
                                self.assertLessEqual(control['right'], geometry['right'] + .5)
                                self.assertGreaterEqual(control['w'], 43.9)
                                self.assertGreaterEqual(control['h'], 43.9)
                    self.assertEqual(self.snapshot(), self.before)
                    self.assertEqual(self.errors, [])

    def test_numeric_keyboard_full_year_range_and_bounded_months_do_not_write_finances(self):
        self.prepare(393)
        self.page.evaluate("""() => {
          const field=document.createElement('input');field.type='month';
          field.id='fictionalYearMonth';field.value='2026-07';
          field.setAttribute('aria-label','Учебный месяц');
          document.getElementById('planning').appendChild(field);
          window.yearEvents=[];for(const type of ['input','change'])
            field.addEventListener(type,()=>yearEvents.push(type));v108RefreshCalendars();
        }""")
        field = self.page.locator('#fictionalYearMonth')
        popup = self.page.locator('#v108CalendarPanel')
        field.click()
        year = popup.get_by_role('spinbutton', name='Год', exact=True)
        self.assertEqual((year.get_attribute('min'), year.get_attribute('max')), ('1', '9999'))
        year.focus();year.press('ArrowUp');self.assertEqual(year.input_value(), '2027')
        year.press('ArrowDown');self.assertEqual(year.input_value(), '2026')
        year.fill('1');year.press('Enter')
        self.assertTrue(popup.get_by_role('button', name='Предыдущий год', exact=True).is_disabled())
        popup.locator('[data-month="1"]').click()
        self.assertEqual(field.input_value(), '0001-01')
        field.click();year.fill('9999');year.press('Enter')
        self.assertTrue(popup.get_by_role('button', name='Следующий год', exact=True).is_disabled())
        popup.locator('[data-month="12"]').click()
        self.assertEqual(field.input_value(), '9999-12')
        self.assertEqual(self.page.evaluate('yearEvents'), ['input', 'change', 'input', 'change'])
        self.page.evaluate("fictionalYearMonth.min='2024-05';fictionalYearMonth.max='2027-10';fictionalYearMonth.value='2026-07';v108RefreshCalendars()")
        field.click()
        self.assertEqual((year.get_attribute('min'), year.get_attribute('max')), ('2024', '2027'))
        year.fill('2024');year.press('Enter')
        self.assertTrue(popup.locator('[data-month="4"]').is_disabled())
        self.assertTrue(popup.locator('[data-month="5"]').is_enabled())
        year.fill('2027');year.press('Enter')
        self.assertTrue(popup.locator('[data-month="11"]').is_disabled())
        self.assertTrue(popup.locator('[data-month="10"]').is_enabled())
        year.fill('2028');year.press('Enter')
        self.assertEqual(year.input_value(), '2027')
        self.page.keyboard.press('Escape')
        self.assertEqual(field.input_value(), '2026-07')
        self.assertEqual(self.snapshot(), self.before)
        self.assertEqual(self.errors, [])


if __name__ == '__main__':
    unittest.main()
