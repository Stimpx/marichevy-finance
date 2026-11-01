"""Fictional date/month picker regression: native values, limits and keyboard."""
import json
import os
from pathlib import Path
import sys
import unittest

import test_local_data_safety as harness
sys.path.insert(0, str(Path(harness.__file__).resolve().parents[1] / 'tools'))
from check_touch_flows import enlarge_text


class GlobalCalendars(unittest.TestCase):
    @classmethod
    def setUpClass(cls): harness.LocalDataSafety.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls): harness.LocalDataSafety.tearDownClass.__func__(cls)
    setUp = harness.LocalDataSafety.setUp
    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open
    snapshot = harness.LocalDataSafety.snapshot

    def prepare(self):
        self.open()
        self.page.wait_for_function("typeof v108RefreshCalendars==='function'")
        self.page.evaluate("""() => {
          session=null;stopCloudSync();state=blankState();localStorage.clear();
          const stamp=new Date().toISOString(),m=month(),old=previousMonthKey(m);
          state.entries=[
            {id:'fictional-cal-old',type:'expense',date:old+'-12',amount:31.25,
             category:'Продукты',beneficiary:'Общее',who:'Общее',store:'Учебный магазин',created_at:stamp},
            {id:'fictional-cal-current',type:'expense',date:m+'-01',amount:7.5,
             category:'Дом',beneficiary:'Общее',who:'Общее',store:'Учебный дом',created_at:stamp}
          ];
          showApp();renderAll();go('dates');v108RefreshCalendars();
        }""")

    def popup(self): return self.page.locator('#v108CalendarPanel')

    def open_date(self, selector='#bdDate'):
        self.page.locator(selector).click()
        self.assertTrue(self.popup().is_visible())

    def choose_year_month(self, year, month, is_month=False):
        if not is_month:
            self.popup().get_by_role('button', name='Выбрать месяц и год', exact=True).click()
        year_control = self.popup().get_by_role('spinbutton', name='Год', exact=True)
        year_control.fill(str(year));year_control.press('Enter')
        self.popup().locator(f'[data-month="{month}"]').click()

    def test_all_native_controls_enhance_in_place_and_fill_still_works(self):
        self.prepare();before=self.snapshot()
        controls=self.page.evaluate("""() => [...document.querySelectorAll('input[type=date],input[type=month]')]
          .map(e=>({id:e.id,type:e.type,enhanced:e.hasAttribute('data-v108-calendar'),wrapper:e.parentElement.className}))""")
        self.assertGreater(len(controls),5)
        self.assertTrue(all(e['enhanced'] for e in controls))
        self.page.locator('#bdDate').fill('1987-06-15')
        self.assertEqual(self.page.locator('#bdDate').input_value(),'1987-06-15')
        self.assertFalse(self.popup().is_visible())
        self.assertEqual(self.snapshot(),before)

    def test_leap_date_commits_once_and_reset_does_not_reuse_previous_view(self):
        self.prepare();before=self.snapshot()
        self.page.evaluate("""() => {window.__calendarEvents=[];for(const type of ['input','change'])
          bdDate.addEventListener(type,()=>window.__calendarEvents.push(type));}""")
        self.open_date();self.choose_year_month(2024,2)
        self.popup().locator('[data-date="2024-02-29"]').click()
        self.assertEqual(self.page.locator('#bdDate').input_value(),'2024-02-29')
        self.assertEqual(self.page.evaluate('window.__calendarEvents'),['input','change'])
        self.assertFalse(self.popup().is_visible());self.assertEqual(self.snapshot(),before)
        self.page.evaluate('resetBirthdayForm();v108RefreshCalendars()')
        self.assertEqual(self.page.locator('#bdDate').input_value(),'')
        self.open_date()
        today=self.page.evaluate('today()')
        self.assertEqual(self.popup().locator('[aria-current="date"]').get_attribute('data-date'),today)
        self.assertEqual(self.snapshot(),before)

    def test_history_month_changes_only_filter_and_clear_restores_all_periods(self):
        self.prepare();self.page.evaluate("go('history');v108RefreshCalendars()")
        before=self.snapshot();old=self.page.evaluate('previousMonthKey(month())')
        self.open_date('#fMonth');self.choose_year_month(int(old[:4]),int(old[5:]),is_month=True)
        self.assertEqual(self.page.locator('#fMonth').input_value(),old)
        self.assertEqual(self.page.locator('#historyBody .v76-entry-row').count(),1)
        self.assertIn('Учебный магазин',self.page.locator('#historyBody').inner_text())
        self.open_date('#fMonth')
        self.popup().get_by_role('button',name='Очистить Месяц или все даты',exact=True).click()
        self.assertEqual(self.page.locator('#fMonth').input_value(),'')
        self.assertEqual(self.page.locator('#historyBody .v76-entry-row').count(),2)
        self.assertEqual(self.snapshot(),before)

    def test_keyboard_arrows_escape_enter_tab_and_outside_do_not_autosave(self):
        self.prepare();self.page.locator('#bdDate').fill('2024-02-28');before=self.snapshot()
        field=self.page.locator('#bdDate');field.focus();field.press('Alt+ArrowDown')
        self.page.keyboard.press('ArrowRight')
        self.assertEqual(field.input_value(),'2024-02-28')
        self.page.keyboard.press('Escape')
        self.assertFalse(self.popup().is_visible())
        self.assertEqual(self.page.evaluate('document.activeElement.id'),'bdDate')
        self.assertEqual(field.input_value(),'2024-02-28')
        field.press('Alt+ArrowDown');self.page.keyboard.press('ArrowRight');self.page.keyboard.press('Enter')
        self.assertEqual(field.input_value(),'2024-02-29');self.assertEqual(self.snapshot(),before)
        field.press('Alt+ArrowDown')
        for _ in range(6):
            if not self.popup().is_visible():break
            self.page.keyboard.press('Tab')
        self.assertFalse(self.popup().is_visible())
        self.assertEqual(field.input_value(),'2024-02-29')
        self.open_date();self.page.locator('#bdName').click()
        self.assertFalse(self.popup().is_visible());self.assertEqual(self.snapshot(),before)

    def test_limits_required_readonly_and_removed_dynamic_control(self):
        self.prepare();before=self.snapshot()
        self.page.evaluate("""() => {
          const field=document.createElement('input');field.type='date';field.id='fictionalBoundedDate';
          field.min='2024-02-10';field.max='2024-02-20';field.value='2024-02-15';
          document.querySelector('#dates .birthday-form').appendChild(field);
        }""")
        field=self.page.locator('#fictionalBoundedDate')
        self.page.wait_for_function("fictionalBoundedDate.hasAttribute('data-v108-calendar')")
        self.open_date('#fictionalBoundedDate')
        for day in (9,21):self.assertTrue(self.popup().locator(f'[data-date="2024-02-{day:02}"]').is_disabled())
        for day in (10,20):self.assertTrue(self.popup().locator(f'[data-date="2024-02-{day:02}"]').is_enabled())
        self.assertTrue(self.popup().get_by_role('button',name='Выбрать сегодня',exact=True).is_disabled())
        self.page.evaluate('fictionalBoundedDate.required=true;v108RefreshCalendars()')
        self.assertFalse(self.popup().is_visible());self.open_date('#fictionalBoundedDate')
        self.assertTrue(self.popup().get_by_role('button',name='Очистить Дата',exact=True).is_disabled())
        self.page.evaluate('fictionalBoundedDate.readOnly=true;v108RefreshCalendars()')
        self.assertFalse(self.popup().is_visible())
        self.page.evaluate('fictionalBoundedDate.click()');self.assertFalse(self.popup().is_visible())
        self.page.evaluate('fictionalBoundedDate.readOnly=false;v108RefreshCalendars()')
        self.open_date('#fictionalBoundedDate');self.page.evaluate('fictionalBoundedDate.remove()')
        self.page.wait_for_function("document.getElementById('v108CalendarPanel').hidden")
        self.assertEqual(self.snapshot(),before)

    def test_dynamic_editor_selection_navigation_logout_and_foreign_picker_close(self):
        self.prepare();before=self.snapshot()
        self.page.evaluate("openEdit('fictional-cal-old');v108RefreshCalendars()")
        self.open_date('#xDate')
        self.assertTrue(self.popup().locator('[data-date]').count()>0)
        self.page.keyboard.press('Escape');self.page.evaluate('closeEdit()')
        self.assertEqual(self.snapshot(),before)
        self.page.evaluate("go('dates');v108RefreshCalendars()")
        self.open_date();self.page.evaluate("document.dispatchEvent(new CustomEvent('v107-picker-open',{detail:{kind:'select'}}))")
        self.assertFalse(self.popup().is_visible())
        self.open_date();self.page.evaluate("go('home')")
        self.assertFalse(self.popup().is_visible())
        self.page.evaluate("go('dates');v108RefreshCalendars()")
        self.open_date();self.page.evaluate('logout()')
        self.assertFalse(self.popup().is_visible())
        self.page.evaluate('bdDate.click()');self.assertFalse(self.popup().is_visible())

    def test_detached_old_day_and_month_handlers_cannot_affect_a_new_picker(self):
        self.prepare();before=self.snapshot()
        self.page.locator('#bdDate').fill('2024-02-15');self.open_date()
        self.page.evaluate("window.__oldCalendarDay=v108CalendarPanel.querySelector('[data-date=\"2024-02-16\"]');v108CloseCalendars();go('today');v90Extra.open=true;v108RefreshCalendars()")
        field=self.page.locator('#eDate');field.fill('2026-11-01');self.open_date('#eDate')
        self.page.evaluate('window.__oldCalendarDay.click()')
        self.assertTrue(self.popup().is_visible())
        self.assertEqual(field.input_value(),'2026-11-01')
        self.assertEqual(self.page.locator('#bdDate').input_value(),'2024-02-15')
        self.page.keyboard.press('Escape');self.page.evaluate("go('dates');v108RefreshCalendars()")
        self.open_date();self.popup().get_by_role('button',name='Выбрать месяц и год',exact=True).click()
        self.page.evaluate("window.__oldCalendarMonth=v108CalendarPanel.querySelector('[data-month=\"2\"]')")
        year=self.popup().get_by_role('spinbutton',name='Год',exact=True);year.fill('2025');year.press('Enter')
        self.page.evaluate('window.__oldCalendarMonth.click()')
        self.assertEqual(self.popup().get_by_role('spinbutton',name='Год',exact=True).input_value(),'2025')
        self.assertEqual(self.page.locator('#bdDate').input_value(),'2024-02-15')
        self.assertEqual(self.snapshot(),before)

    def test_typed_year_then_single_month_click_uses_new_year_without_enter(self):
        self.prepare();before=self.snapshot()
        self.page.locator('#bdDate').fill('2024-02-15');self.open_date()
        self.popup().get_by_role('button',name='Выбрать месяц и год',exact=True).click()
        self.popup().get_by_role('spinbutton',name='Год',exact=True).fill('1991')
        self.popup().locator('[data-month="3"]').click()
        self.assertTrue(self.popup().get_by_role('button',name='Выбрать месяц и год',exact=True).is_visible())
        self.popup().locator('[data-date="1991-03-15"]').click()
        self.assertEqual(self.page.locator('#bdDate').input_value(),'1991-03-15')
        self.page.evaluate("""() => {
          const field=document.createElement('input');field.type='month';field.id='fictionalYearMonth';
          field.setAttribute('aria-label','Учебный месяц');field.value='2024-02';
          document.querySelector('#dates .birthday-form').appendChild(field);v108RefreshCalendars();
        }""")
        self.open_date('#fictionalYearMonth')
        self.popup().get_by_role('spinbutton',name='Год',exact=True).fill('1991')
        self.popup().locator('[data-month="3"]').click()
        self.assertFalse(self.popup().is_visible())
        self.assertEqual(self.page.locator('#fictionalYearMonth').input_value(),'1991-03')
        self.assertEqual(self.snapshot(),before)

    def test_geometry_phone_tablet_zoom_and_large_text(self):
        self.prepare()
        for width,height,scale in [(320,740,1),(390,844,1),(768,1024,1),(1280,800,1),(1920,1080,1),(320,740,2),(390,844,1.5)]:
            with self.subTest(width=width,scale=scale):
                self.page.set_viewport_size({'width':width,'height':height})
                self.page.evaluate("go('dates');bdDate.value='2024-02-29';v108RefreshCalendars()")
                self.open_date()
                if scale!=1:enlarge_text(self.page,scale)
                self.page.evaluate('v108RefreshCalendars()')
                info=self.popup().evaluate("""panel=>{
                  const r=panel.getBoundingClientRect();
                  return {x:r.x,right:r.right,y:r.y,bottom:r.bottom,sw:panel.scrollWidth,cw:panel.clientWidth,
                    keys:[...panel.querySelectorAll('.v108-day')].map(el=>{const r=el.getBoundingClientRect();return{w:r.width,h:r.height}})}
                }""")
                self.assertGreaterEqual(info['x'],0);self.assertLessEqual(info['right'],width+1)
                self.assertGreaterEqual(info['y'],0);self.assertLessEqual(info['bottom'],height+1)
                self.assertLessEqual(info['sw'],info['cw']+1)
                for key in info['keys']:
                    self.assertGreaterEqual(key['h'],44);self.assertGreaterEqual(key['w'],43.9)
                directory=os.environ.get('CALENDAR_SCREENSHOT_DIR')
                if directory and scale==1 and width in (390,1280):
                    Path(directory).mkdir(exist_ok=True,parents=True)
                    self.page.screenshot(path=str(Path(directory)/f'calendar-{width}.png'))
                self.page.keyboard.press('Escape')
                # Fresh nodes reset enlarged-text approximation between profiles.
                if scale!=1:self.prepare()


if __name__=='__main__':unittest.main()
