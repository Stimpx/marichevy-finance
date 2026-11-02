"""Global dropdown behavior on fictional data with every external request blocked."""
import json
import os
from pathlib import Path
import re
import sys
import unittest

import test_local_data_safety as harness
sys.path.insert(0,str(Path(harness.__file__).resolve().parents[1]/'tools'))
from check_touch_flows import enlarge_text


class GlobalSelects(unittest.TestCase):
    @classmethod
    def setUpClass(cls): harness.LocalDataSafety.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls): harness.LocalDataSafety.tearDownClass.__func__(cls)
    setUp=harness.LocalDataSafety.setUp
    tearDown=harness.LocalDataSafety.tearDown
    open=harness.LocalDataSafety.open
    snapshot=harness.LocalDataSafety.snapshot

    def prepare(self):
        self.open()
        self.page.evaluate("""() => {
          session=null;stopCloudSync();state=blankState();localStorage.clear();
          state.entries=[{id:'fictional-select-entry',type:'expense',date:month()+'-01',amount:12.50,
            category:'Продукты',beneficiary:'Сергей',who:'Legacy fictional',store:'Fictional shop',
            comment:'Fictional unchanged note',extension:{keep:['unknown']}}];
          showApp();renderAll();go('dates');v107RefreshSelects();
        }""")
        self.before=self.snapshot()

    def trigger(self, identifier):
        return self.page.locator(f'#{identifier}').locator('..').locator('.v107-select-trigger')

    def listbox(self):
        return self.page.locator('.v107-select-panel:not([hidden])')

    def test_native_select_option_and_programmatic_reset_keep_visible_value_in_sync(self):
        self.prepare()
        self.page.locator('#bdGroup').select_option(label='Коллеги')
        self.assertEqual(self.trigger('bdGroup').inner_text(),'Коллеги')
        self.page.evaluate('resetBirthdayForm();v107RefreshSelects()')
        self.assertEqual(self.trigger('bdGroup').inner_text(),'Близкие')
        self.assertEqual(self.page.locator('#bdGroup').input_value(),'Близкие')
        self.assertEqual(self.snapshot(),self.before)

    def test_pointer_commit_dispatches_once_and_category_submit_uses_original_select(self):
        self.prepare()
        self.page.evaluate("""() => {window.__selectEvents={input:0,change:0};
          bdGroup.addEventListener('input',()=>window.__selectEvents.input++);
          bdGroup.addEventListener('change',()=>window.__selectEvents.change++);
        }""")
        self.trigger('bdGroup').click()
        self.listbox().get_by_role('option',name='Друзья',exact=True).click()
        self.assertEqual(self.page.evaluate('window.__selectEvents'),{'input':1,'change':1})
        self.assertEqual(self.page.locator('#bdGroup').input_value(),'Друзья')
        self.assertEqual(self.snapshot(),self.before)
        self.page.locator('#bdName').fill('Fictional dropdown contact')
        self.page.locator('#bdDate').fill('1991-07-14')
        self.page.locator('#birthdaySubmitBtn').click()
        self.page.wait_for_function("state.birthdays.some(row=>row.name==='Fictional dropdown contact')")
        saved=self.page.evaluate("state.birthdays.find(row=>row.name==='Fictional dropdown contact')")
        self.assertEqual(saved['group'],'Друзья')
        self.assertEqual(self.page.evaluate('JSON.stringify(state.entries)'),json.dumps(json.loads(self.before['state'])['entries'],ensure_ascii=False,separators=(',',':')))
        self.assertEqual(self.trigger('bdGroup').inner_text(),'Близкие')

    def test_keyboard_navigation_cancel_typeahead_and_label_focus(self):
        self.prepare();trigger=self.trigger('bdGroup')
        self.page.locator('label[for="bdGroup"]').click()
        self.assertTrue(trigger.evaluate('el=>el===document.activeElement'))
        trigger.press('ArrowDown');trigger.press('End');trigger.press('Escape')
        self.assertEqual(self.page.locator('#bdGroup').input_value(),'Близкие')
        self.assertEqual(self.listbox().count(),0)
        trigger.press('ArrowDown');trigger.dispatch_event('keydown',{'key':'с'});trigger.press('Enter')
        self.assertEqual(self.page.locator('#bdGroup').input_value(),'Соседи')
        self.assertTrue(trigger.evaluate('el=>el===document.activeElement'))
        trigger.click();trigger.press('Home');trigger.press('Tab')
        self.assertEqual(self.page.locator('#bdGroup').input_value(),'Соседи')
        self.assertEqual(self.listbox().count(),0)
        self.assertEqual(self.snapshot(),self.before)

    def test_dynamic_editor_legacy_options_disabled_and_html_remain_data(self):
        self.prepare()
        self.page.evaluate("""() => {
          go('today');openEdit('fictional-select-entry');v107RefreshSelects();
          window.__selectInjected=false;
          const option=new Option('<img id=select-injected src=x onerror=window.__selectInjected=true>','fictional-legacy');
          xCat.add(option);xCat.value='fictional-legacy';
          const disabled=new Option('Fictional disabled','disabled');disabled.disabled=true;xCat.add(disabled);
          v107RefreshSelects();
        }""")
        trigger=self.trigger('xCat')
        self.assertIn('<img id=select-injected',trigger.inner_text())
        trigger.click()
        disabled=self.listbox().get_by_role('option',name='Fictional disabled',exact=True)
        self.assertEqual(disabled.get_attribute('aria-disabled'),'true')
        disabled.dispatch_event('click')
        self.assertEqual(self.page.locator('#xCat').input_value(),'fictional-legacy')
        self.assertEqual(self.page.locator('#select-injected').count(),0)
        self.assertFalse(self.page.evaluate('window.__selectInjected'))
        trigger.press('Escape')
        self.assertEqual(self.snapshot(),self.before)

    def test_visible_anchor_follows_scroll_and_offscreen_navigation_foreign_picker_and_logout_close(self):
        self.prepare();trigger=self.trigger('bdGroup')
        trigger.click();self.page.locator('#bdName').click()
        self.assertEqual(self.listbox().count(),0)
        trigger.click();self.page.evaluate("document.dispatchEvent(new Event('scroll'))")
        self.assertEqual(self.listbox().count(),1)
        self.assertEqual(self.snapshot(),self.before)
        self.page.evaluate("document.documentElement.style.scrollBehavior='auto';document.body.style.minHeight='2400px';window.scrollTo(0,2000)")
        self.page.wait_for_function("!document.querySelector('.v107-select-panel:not([hidden])')")
        self.assertEqual(self.page.locator('#bdGroup').input_value(),'Близкие')
        self.page.evaluate("window.scrollTo(0,0)")
        trigger.click();self.page.evaluate("document.dispatchEvent(new CustomEvent('v107-picker-open',{detail:{type:'calendar'}}))")
        self.assertEqual(self.listbox().count(),0)
        trigger.click();self.page.evaluate("go('history')")
        self.page.wait_for_function("!document.querySelector('.v107-select-panel:not([hidden])')")
        self.assertEqual(self.snapshot(),self.before)
        self.page.evaluate("go('dates')");trigger.click();self.page.evaluate('logout()')
        self.page.wait_for_function("!document.querySelector('.v107-select-panel:not([hidden])')")
        self.assertEqual(trigger.get_attribute('aria-expanded'),'false')

    def test_programmatic_hidden_and_disabled_native_state_propagates(self):
        self.prepare();trigger=self.trigger('bdGroup')
        self.page.evaluate("bdGroup.style.display='none';v107RefreshSelects()")
        self.assertFalse(trigger.is_visible())
        self.page.evaluate("bdGroup.style.display='';v107RefreshSelects()")
        self.assertTrue(trigger.is_visible())
        trigger.click()
        self.page.evaluate("bdGroup.disabled=true;v107RefreshSelects()")
        self.assertTrue(trigger.is_disabled())
        self.assertEqual(self.listbox().count(),0)
        self.page.evaluate("bdGroup.disabled=false;v107RefreshSelects()")
        self.assertFalse(trigger.is_disabled())
        self.assertEqual(self.snapshot(),self.before)

    def test_programmatic_native_focus_reaches_visible_combobox_without_changes(self):
        self.prepare()
        self.page.evaluate("go('today');openEdit('fictional-select-entry');v107RefreshSelects();document.getElementById('xCat').focus()")
        trigger=self.trigger('xCat')
        self.assertTrue(trigger.is_visible())
        self.assertTrue(trigger.evaluate('el=>el===document.activeElement'))
        self.assertEqual(trigger.get_attribute('role'),'combobox')
        self.assertEqual(self.page.locator('#xCat').input_value(),'Продукты')
        self.assertEqual(self.snapshot(),self.before)

    def test_every_section_dynamic_controls_and_phone_geometry(self):
        self.prepare()
        sections=self.page.evaluate("[...document.querySelectorAll('#nav [data-page]')].map(el=>el.dataset.page)")
        for section in sections:
            self.page.evaluate('(section)=>{go(section);v107RefreshSelects()}',section)
            values=self.page.evaluate("""() => [...document.querySelectorAll('select')].filter(el=>!el.multiple&&el.size<=1&&!el.hidden&&el.getBoundingClientRect().width&&getComputedStyle(el).display!=='none').map(el=>({id:el.id,enhanced:el.classList.contains('v107-native-select')}))""")
            self.assertTrue(all(value['enhanced'] for value in values),values)
        self.page.evaluate("go('dates');v107RefreshSelects()")
        for width,height,scale in [(320,740,1),(390,844,1),(820,1180,1),(1536,900,1),(320,740,2),(390,844,1.5)]:
            with self.subTest(width=width,scale=scale):
                if scale!=1:
                    self.prepare();self.page.evaluate("go('dates')")
                self.page.set_viewport_size({'width':width,'height':height})
                if scale!=1: enlarge_text(self.page,scale)
                trigger=self.trigger('bdGroup');trigger.scroll_into_view_if_needed();trigger.click()
                if scale==1:
                    self.assertAlmostEqual(trigger.bounding_box()['height'],self.page.locator('#bdDate').bounding_box()['height'],delta=1)
                bounds=self.page.evaluate("""() => {
                  const list=document.querySelector('.v107-select-panel:not([hidden])');
                  const rect=el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,h:r.height,w:r.width}};
                  return {list:rect(list),scroll:list.scrollWidth,client:list.clientWidth,options:[...list.querySelectorAll('[role=option]')].map(rect)};
                }""")
                self.assertGreaterEqual(bounds['list']['x'],0)
                self.assertLessEqual(bounds['list']['right'],width+1)
                self.assertGreaterEqual(bounds['list']['y'],0)
                self.assertLessEqual(bounds['list']['bottom'],height+1)
                self.assertLessEqual(bounds['scroll'],bounds['client']+1)
                self.assertTrue(all(option['h']>=44 for option in bounds['options']))
                if width==1536 and os.environ.get('SELECT_SCREENSHOT_DIR'):
                    directory=Path(os.environ['SELECT_SCREENSHOT_DIR']);directory.mkdir(exist_ok=True)
                    self.page.screenshot(path=str(directory/'select-dates.png'))
                trigger.press('Escape')


if __name__=='__main__':unittest.main()
