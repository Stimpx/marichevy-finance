"""Touch navigation across the sidebar breakpoint; fictional local data only."""
from pathlib import Path
import os
import unittest

from playwright.sync_api import expect

import test_local_data_safety as harness


PRIMARY = ('home', 'today', 'history', 'analytics')
MORE = ('accounts', 'planning', 'income', 'car', 'loans', 'goals', 'chores', 'dates', 'settings', 'help', 'plans')


class MobileMoreNavigation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.LocalDataSafety.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        harness.LocalDataSafety.tearDownClass.__func__(cls)

    def setUp(self):
        self.context = self.browser.new_context(
            viewport={'width': 390, 'height': 844}, has_touch=True, is_mobile=True,
            timezone_id='Europe/Moscow', service_workers='block', reduced_motion='reduce')
        self.context.route('**/*', lambda route: route.continue_()
                           if route.request.url.startswith(self.base) else route.abort())
        self.page = self.context.new_page()
        self.page.set_default_timeout(4000)
        self.page.on('dialog', lambda dialog: dialog.accept())

    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open
    snapshot = harness.LocalDataSafety.snapshot

    def prepare(self, width, height):
        self.page.set_viewport_size({'width': width, 'height': height})
        self.open()
        self.page.evaluate("""() => {
          session=null;stopCloudSync();localStorage.clear();state=blankState();
          state.entries=[{id:'fictional-menu-entry',type:'expense',amount:17.25,
            date:'2026-10-21',category:'Продукты',who:'Сергей',beneficiary:'Сергей',
            store:'Учебный магазин',comment:'Только тестовые данные',
            unknownExtension:{preserve:[true,null,{menu:'touch'}]}}];
          state.settings.menuUnknownExtension={preserve:'fictional'};
          weatherCache.data={temperature_2m:10,weather_code:0};weatherCache.at=Date.now();
          loanScheduleData=()=>[{n:1,payDate:'2099-12-01',periodEnd:'2099-12-01',
            payment:1,interest:0,body:1,balance:0}];
          localStorage.setItem('fictional-menu-sentinel','keep');
          showApp();renderAll();go('home');
        }""")
        self.before = self.snapshot()
        self.initial_overflow = self.page.evaluate('document.body.style.overflow')

    def assert_closed(self):
        expect(self.page.locator('#v74MoreToggle')).to_have_attribute('aria-expanded', 'false')
        expect(self.page.locator('#v74MorePanel')).to_have_attribute('aria-hidden', 'true')
        expect(self.page.locator('#v74MorePanel')).to_be_hidden()
        expect(self.page.locator('#v74MoreShade')).to_be_hidden()
        self.assertEqual(self.page.evaluate('document.body.style.overflow'), self.initial_overflow)

    def open_menu(self):
        self.page.locator('#v74MoreToggle').tap()
        expect(self.page.locator('#v74MoreToggle')).to_have_attribute('aria-expanded', 'true')
        expect(self.page.locator('#v74MorePanel')).to_have_attribute('aria-hidden', 'false')
        expect(self.page.locator('#v74MorePanel')).to_be_visible()
        expect(self.page.locator('#v74MoreShade')).to_be_visible()
        self.assertEqual(self.page.evaluate('document.body.style.overflow'), 'hidden')
        expect(self.page.locator('#v74MorePanel [aria-label="Закрыть меню"]')).to_be_focused()
        self.page.wait_for_function('''()=>{
          const panel=document.querySelector('#v74MorePanel');
          const r=panel.getBoundingClientRect(),n=mobileNav.getBoundingClientRect();
          return r.top>=0&&r.bottom<=n.top&&r.left>=0&&r.right<=innerWidth&&
            panel.scrollWidth<=panel.clientWidth+1;
        }''')
        for button in self.page.locator('#v74MorePanel button').all():
            box=button.bounding_box()
            self.assertGreaterEqual(box['width'], 44)
            self.assertGreaterEqual(box['height'], 44)

    def assert_destination(self, name, desktop=False):
        expect(self.page.locator(f'#{name}')).to_be_visible()
        self.assertEqual(self.page.evaluate("document.querySelector('.section.active').id"), name)
        expect(self.page.locator(f'#nav button[data-page="{name}"]')).to_have_class('active')
        if not desktop:
            self.assert_closed()
            if name in PRIMARY:
                expect(self.page.locator(f'#mobileNav button[data-page="{name}"]')).to_have_class('active')
                expect(self.page.locator('#v74MoreToggle')).not_to_have_class('active')
            else:
                expect(self.page.locator('#v74MoreToggle')).to_have_class('active')
        self.assertEqual(self.snapshot(), self.before, 'Navigation must not write financial data or storage')

    def test_touch_reaches_all_daily_destinations_at_breakpoint_and_device_sizes(self):
        for width,height in ((320,740),(390,844),(760,1024),(761,1024),(820,1180),
                             (844,390),(1024,768),(1025,768)):
            with self.subTest(width=width,height=height):
                self.prepare(width,height)
                desktop=width>1024
                expect(self.page.locator('.side')).to_be_visible() if desktop else expect(self.page.locator('.side')).to_be_hidden()
                expect(self.page.locator('#mobileNav')).to_be_hidden() if desktop else expect(self.page.locator('#mobileNav')).to_be_visible()
                if desktop:
                    for name in PRIMARY+MORE:
                        self.page.locator(f'#nav button[data-page="{name}"]').tap()
                        self.assert_destination(name,desktop=True)
                    self.assert_closed()
                else:
                    for button in self.page.locator('#mobileNav button').all():
                        box=button.bounding_box()
                        self.assertGreaterEqual(box['width'],44)
                        self.assertGreaterEqual(box['height'],44)
                    for name in PRIMARY:
                        self.page.locator(f'#mobileNav button[data-page="{name}"]').tap()
                        self.assert_destination(name)
                    for name in MORE:
                        self.open_menu()
                        self.page.locator(f'#v74MorePanel button[data-page="{name}"]').tap()
                        self.assert_destination(name)

    def test_outside_close_button_escape_and_focus_cycle_restore_state(self):
        for width,height in ((390,844),(761,1024),(844,390),(1024,768)):
            with self.subTest(width=width,height=height):
                self.prepare(width,height)
                for close in ('outside','button','escape'):
                    self.open_menu()
                    close_button=self.page.locator('#v74MorePanel [aria-label="Закрыть меню"]')
                    expect(close_button).to_be_focused()
                    self.page.keyboard.press('Shift+Tab')
                    expect(self.page.locator('#v74MorePanel button').last).to_be_focused()
                    self.page.keyboard.press('Tab')
                    expect(close_button).to_be_focused()
                    if close=='outside':
                        self.page.touchscreen.tap(2,2)
                    elif close=='button':
                        close_button.tap()
                    else:
                        self.page.keyboard.press('Escape')
                    self.assert_closed()
                    expect(self.page.locator('#v74MoreToggle')).to_be_focused()
                    self.assertEqual(self.snapshot(),self.before)

    def test_first_animated_open_focuses_menu_for_touch_and_mouse(self):
        self.page.emulate_media(reduced_motion='no-preference')
        for width,activate in ((760,'click'),(761,'tap'),(820,'click'),(1024,'tap')):
            with self.subTest(width=width,activate=activate):
                self.prepare(width,768)
                getattr(self.page.locator('#v74MoreToggle'),activate)()
                expect(self.page.locator('#v74MorePanel [aria-label="Закрыть меню"]')).to_be_focused()
                self.page.keyboard.press('Escape')
                self.assert_closed()
                expect(self.page.locator('#v74MoreToggle')).to_be_focused()
                self.assertEqual(self.snapshot(),self.before)

    def test_touching_primary_navigation_while_menu_open_closes_shade_then_routes(self):
        for width,height in ((390,844),(761,1024),(820,1180),(844,390),(1024,768)):
            with self.subTest(width=width,height=height):
                self.prepare(width,height)
                self.open_menu()
                # This is a physical touch at the underlying tab: the menu's
                # outside-dismiss surface receives the first gesture.
                history=self.page.locator('#mobileNav [data-page="history"]')
                box=history.bounding_box()
                self.page.touchscreen.tap(box['x']+box['width']/2,box['y']+box['height']/2)
                self.assert_closed()
                self.assert_destination('home')
                expect(self.page.locator('#v74MoreToggle')).to_be_focused()
                history.tap()
                self.assert_destination('history')

    def test_open_menu_resizes_within_mobile_then_closes_when_sidebar_returns(self):
        self.prepare(390,844)
        self.page.evaluate("document.body.style.overflow='clip'")
        self.initial_overflow='clip'
        self.open_menu()
        for width,height in ((844,390),(820,1180),(1024,768),(760,1024)):
            self.page.set_viewport_size({'width':width,'height':height})
            expect(self.page.locator('#v74MorePanel')).to_be_visible()
            self.assertTrue(self.page.locator('#v74MorePanel').evaluate('''panel=>{
              const r=panel.getBoundingClientRect();return r.top>=0&&r.bottom<=mobileNav.getBoundingClientRect().top;
            }'''))
            expect(self.page.locator('#v74MorePanel [aria-label="Закрыть меню"]')).to_be_focused()
        self.page.set_viewport_size({'width':1025,'height':768})
        self.assert_closed()
        expect(self.page.locator('#nav button[data-page="home"]')).to_be_focused()
        self.page.set_viewport_size({'width':761,'height':1024})
        self.assert_closed()
        self.open_menu()
        self.page.locator('#v74MorePanel button[data-page="settings"]').tap()
        self.assert_destination('settings')

    def test_large_text_all_menu_items_remain_touch_reachable_portrait_landscape_tablet(self):
        for width,height in ((320,740),(390,844),(844,390),(820,1180),(1024,768)):
            with self.subTest(width=width,height=height):
                self.prepare(width,height)
                self.page.evaluate('''()=>{
                  const nodes=[...document.querySelectorAll('body,body *')]
                    .filter(el=>!['SCRIPT','STYLE','SVG','PATH'].includes(el.tagName));
                  const sizes=nodes.map(el=>parseFloat(getComputedStyle(el).fontSize));
                  nodes.forEach((el,i)=>{if(sizes[i])el.style.setProperty('font-size',sizes[i]*2+'px','important')});
                }''')
                for name in MORE:
                    self.open_menu()
                    button=self.page.locator(f'#v74MorePanel button[data-page="{name}"]')
                    button.scroll_into_view_if_needed()
                    self.assertTrue(button.evaluate('''el=>{
                      const r=el.getBoundingClientRect(),p=el.closest('section').getBoundingClientRect();
                      const y=(Math.max(r.top,p.top)+Math.min(r.bottom,p.bottom))/2;
                      const target=document.elementFromPoint(r.left+r.width/2,y);
                      return r.left>=p.left&&r.right<=p.right&&el.contains(target);
                    }'''), 'The menu item must have an uncovered touch target')
                    button.tap()
                    self.assert_destination(name)
                shot_dir=os.environ.get('MARICHEVY_MENU_SCREENSHOTS')
                if shot_dir:
                    self.open_menu()
                    Path(shot_dir).mkdir(parents=True,exist_ok=True)
                    self.page.screenshot(path=str(Path(shot_dir)/f'more-{width}x{height}-text200.png'))
                    self.page.keyboard.press('Escape')


if __name__=='__main__':
    unittest.main()
