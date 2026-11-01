"""Native date text and touch picker; fictional data, external network blocked.

Chromium exposes native date shadow text through CDP, so geometry measures the
painted value instead of merely checking the outer input. This is not an iOS
WebKit verification; the managed environment has no WebKit executable.
"""
from pathlib import Path
import sys
import unittest

import test_local_data_safety as harness

sys.path.insert(0, str(Path(harness.__file__).resolve().parents[1] / 'tools'))
from check_touch_flows import enlarge_text


class MobileDateAlignment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.LocalDataSafety.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        harness.LocalDataSafety.tearDownClass.__func__(cls)

    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open
    snapshot = harness.LocalDataSafety.snapshot

    def setUp(self):
        self.context = self.browser.new_context(
            viewport={'width': 393, 'height': 852}, device_scale_factor=3,
            is_mobile=True, has_touch=True, locale='ru-RU',
            timezone_id='Europe/Moscow', service_workers='block')
        self.context.route('**/*', lambda route: route.continue_()
                           if route.request.url.startswith(self.base) else route.abort())
        self.page = self.context.new_page()
        self.page.set_default_timeout(4000)
        self.page.on('dialog', lambda dialog: dialog.accept())
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))

    def prepare(self):
        self.open()
        self.page.evaluate("""() => {
          session=null;stopCloudSync();localStorage.clear();state=blankState();
          showApp();renderAll();go('accounts');v108RefreshCalendars();
        }""")
        self.cdp = self.context.new_cdp_session(self.page)
        self.before = self.snapshot()

    @staticmethod
    def walk(node):
        attributes = node.get('attributes', [])
        yield node, dict(zip(attributes[::2], attributes[1::2]))
        for key in ('children', 'shadowRoots'):
            for child in node.get(key, []):
                yield from MobileDateAlignment.walk(child)

    def painted_value(self, identifier):
        tree = self.cdp.send('DOM.getDocument', {'depth': -1, 'pierce': True})['root']
        target = next(node for node, attrs in self.walk(tree) if attrs.get('id') == identifier)
        wrapper = next(node for node, attrs in self.walk(target)
                       if attrs.get('pseudo') == '-webkit-datetime-edit-fields-wrapper')
        handle = self.cdp.send('DOM.resolveNode', {'nodeId': wrapper['nodeId']})['object']['objectId']
        result = self.cdp.send('Runtime.callFunctionOn', {
            'objectId': handle, 'returnByValue': True,
            'functionDeclaration': """function(){
              const range=document.createRange();range.selectNodeContents(this);
              const r=range.getBoundingClientRect();
              return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,height:r.height,text:range.toString()};
            }"""})['result']['value']
        self.cdp.send('Runtime.releaseObject', {'objectId': handle})
        return result

    def test_native_date_values_stay_centered_and_inside_controls_on_phone(self):
        self.prepare()
        for scale in (1, 2):
            if scale == 2:
                enlarge_text(self.page, 2)
            for width in (320, 393, 430):
                self.page.set_viewport_size({'width': width, 'height': 852})
                for route, fields in (
                    ('accounts', ('v117ManualDate', 'v117SnapshotDate')),
                    ('planning', ('v118PlanMonth', 'v118PeriodFrom', 'v118PeriodUntil'))):
                    self.page.evaluate('(route)=>{go(route);v108RefreshCalendars()}', route)
                    for identifier in fields:
                        with self.subTest(width=width, scale=scale, field=identifier):
                            node = self.page.locator('#' + identifier)
                            node.scroll_into_view_if_needed()
                            box = node.bounding_box()
                            text = self.painted_value(identifier)
                            self.assertTrue(text['text'], text)
                            self.assertGreater(text['height'], 0, text)
                            self.assertGreaterEqual(text['top'], box['y'] + .5, (box, text))
                            self.assertLessEqual(text['bottom'], box['y'] + box['height'] - .5, (box, text))
                            self.assertLessEqual(abs((text['top'] + text['bottom']) / 2
                                                     - (box['y'] + box['height'] / 2)), 3, (box, text))
                            self.assertGreaterEqual(text['left'], box['x'] + .5, (box, text))
                            self.assertLessEqual(text['right'], box['x'] + box['width'] - 24, (box, text))
                            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),
                                                 width + 1)
        self.assertEqual(self.snapshot(), self.before)
        self.assertEqual(self.errors, [])

    def test_account_touch_calendar_commits_only_the_date_draft(self):
        self.prepare()
        field = self.page.locator('#v117ManualDate')
        field.fill('2024-02-28')
        field.tap()
        popup = self.page.locator('#v108CalendarPanel')
        self.assertTrue(popup.is_visible())
        popup.locator('[data-date="2024-02-29"]').tap()
        self.assertEqual(field.input_value(), '2024-02-29')
        self.assertFalse(popup.is_visible())
        self.assertEqual(self.snapshot(), self.before)
        field.tap()
        popup.locator('.v108-cancel').tap()
        self.assertEqual(field.input_value(), '2024-02-29')
        self.assertEqual(self.snapshot(), self.before)
        self.assertEqual(self.errors, [])


if __name__ == '__main__':
    unittest.main()
