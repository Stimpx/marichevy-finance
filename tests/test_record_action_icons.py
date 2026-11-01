"""Transaction icon controls: real actions and responsive geometry, fictional data only."""
import json
import re
from pathlib import Path
import sys
import unittest

import test_local_data_safety as harness
sys.path.insert(0, str(Path(harness.__file__).resolve().parents[1] / 'tools'))
from check_touch_flows import enlarge_text


class RecordActionIcons(unittest.TestCase):
    @classmethod
    def setUpClass(cls): harness.LocalDataSafety.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls): harness.LocalDataSafety.tearDownClass.__func__(cls)
    setUp = harness.LocalDataSafety.setUp
    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open
    snapshot = harness.LocalDataSafety.snapshot

    def prepare(self, malicious=False):
        self.open()
        self.info=self.page.evaluate("""malicious=>{
          session=null;stopCloudSync();localStorage.clear();state=blankState();
          const id=malicious?`x');window.__recordInjected=true;//<img id=record-injected src=x>`:'icon-first';
          const store=malicious?'<img id=record-name-injected src=x onerror="window.__recordInjected=true">':'Fictional first';
          window.__recordInjected=false;
          const row=(id,type,store,category)=>({id,type,date:today(),amount:120.50,category,
            beneficiary:'Сергей',who:'Original author',store,comment:'Fictional comment',
            created_at:today()+'T12:00:00Z',updated_at:today()+'T12:00:00Z',unknown:{keep:[id,true,null]}});
          state.entries=[row(id,'expense',store,'Продукты'),
            row('icon-second','expense','Fictional second','Продукты'),
            row('icon-income','income','Fictional employer','Зарплата')];
          weatherCache.data={temperature_2m:10,weather_code:0};weatherCache.at=Date.now();
          showApp();renderAll();go('history');resetHistoryFilters();
          return {id,store,month:month(),date:today()};
        }""",malicious)
        self.before=self.snapshot()

    def surface(self, name):
        if self.page.locator('#v84DrillModal').is_visible(): self.page.evaluate('v84CloseDrill()')
        if name=='drill':
            self.page.evaluate("go('analytics');analyticsMonth.value=month();renderAnalytics();v84Drill('person','Сергей','analytics')")
            return self.page.locator('#v84DrillEntries')
        self.page.evaluate('(name)=>go(name)',{'recent':'home','today':'today','history':'history','income':'income'}[name])
        return self.page.locator({'recent':'#recent','today':'#todayList','history':'#historyBody','income':'#incomeList'}[name])

    def test_all_transaction_surfaces_have_named_keyboard_reachable_icons(self):
        self.prepare()
        for surface,count in [('recent',12),('today',12),('history',12),('income',4),('drill',6)]:
            with self.subTest(surface=surface):
                root=self.surface(surface)
                buttons=root.locator('button.v112-record-action')
                self.assertEqual(buttons.count(),count)
                info=buttons.evaluate_all("""nodes=>nodes.map(b=>({
                  text:b.textContent.trim(),label:b.getAttribute('aria-label'),title:b.title,
                  tab:b.tabIndex,svg:b.querySelectorAll('svg[aria-hidden="true"]').length,
                  paths:b.querySelectorAll('svg path,svg rect').length}))""")
                self.assertTrue(all(not item['text'] and item['label'] and item['title'] and
                    item['tab']==0 and item['svg']==1 and item['paths']>0 for item in info),info)
                first=buttons.first;first.focus()
                self.assertTrue(first.evaluate('b=>b===document.activeElement'))
        self.assertEqual(self.snapshot(),self.before)

    def test_edit_icon_selects_exact_duplicate_amount_record_and_cancel_keeps_data(self):
        self.prepare();root=self.surface('history')
        row=root.locator('tr').filter(has_text='Fictional second')
        row.locator('button[data-action="edit"]').click()
        self.assertEqual(self.page.evaluate('editId'),'icon-second')
        self.page.locator('#xComment').fill('Unsaved icon edit')
        self.page.locator('#editModal').get_by_role('button',name='Отмена',exact=True).click()
        self.assertFalse(self.page.locator('#editModal').is_visible())
        self.assertEqual(self.snapshot(),self.before)

    def test_repeat_icon_creates_only_draft_for_exact_record_and_never_saves(self):
        self.prepare();root=self.surface('history')
        root.locator('tr').filter(has_text='Fictional second').get_by_role('button',name='Повторить',exact=True).click()
        self.assertEqual(self.page.locator('#eStore').input_value(),'Fictional second')
        self.assertEqual(self.page.locator('#eComment').input_value(),'Fictional comment')
        self.assertEqual(self.page.locator('#eAmount').input_value(),'120,5')
        self.assertEqual(self.page.locator('#eDate').input_value(),self.info['date'])
        self.assertIn('новый черновик',self.page.locator('#v97DraftStatus').inner_text())
        self.assertEqual(self.snapshot(),self.before)

    def test_delete_icon_cancel_keeps_drill_and_all_original_records(self):
        self.prepare();root=self.surface('drill')
        self.page.evaluate('window.confirm=()=>false')
        root.locator('.v85-drill-entry').filter(has_text='Fictional second').get_by_role(
            'button',name=re.compile('^Удалить операцию:')).click()
        self.assertTrue(self.page.locator('#v84DrillModal').is_visible())
        self.assertEqual(self.snapshot(),self.before)
        self.assertEqual(root.locator('.v85-drill-entry').count(),2)

    def test_hostile_record_names_are_escaped_and_edit_handler_keeps_actual_id(self):
        self.prepare(malicious=True)
        for name in ('recent','today','history','drill'):
            root=self.surface(name)
            self.assertFalse(self.page.evaluate('window.__recordInjected'))
            self.assertEqual(self.page.locator('#record-injected,#record-name-injected').count(),0)
            self.assertTrue(any(self.info['store'] in title for title in root.locator(
                'button.v112-record-action').evaluate_all('nodes=>nodes.map(n=>n.title)')))
        root=self.surface('history')
        root.locator('button[data-action="edit"]').first.click()
        self.assertEqual(self.page.evaluate('editId'),self.info['id'])
        self.page.locator('#editModal').get_by_role('button',name='Отмена',exact=True).click()
        self.assertFalse(self.page.evaluate('window.__recordInjected'))
        self.assertEqual(self.snapshot(),self.before)

    def test_hit_targets_fit_rows_and_modal_at_phone_desktop_and_enlarged_text(self):
        for width,scale in [(320,1),(390,1),(1440,1),(320,2),(390,1.5),(1440,2)]:
            with self.subTest(width=width,scale=scale):
                self.prepare();self.page.set_viewport_size({'width':width,'height':1000})
                if scale!=1: enlarge_text(self.page,scale)
                for name in ('recent','today','history','income','drill'):
                    root=self.surface(name)
                    result=root.evaluate("""root=>{
                      const buttons=[...root.querySelectorAll('button.v112-record-action')];
                      const box=el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,w:r.width,h:r.height}};
                      const boundary=box(root.closest('.v84-modal')||root.closest('.card')||root);
                      const icons=buttons.map(b=>({button:box(b),icon:box(b.querySelector('svg'))}));
                      const overlaps=[];
                      for(let i=0;i<icons.length;i++)for(let j=i+1;j<icons.length;j++){
                        const a=icons[i].button,b=icons[j].button;
                        if(Math.min(a.right,b.right)-Math.max(a.x,b.x)>1&&Math.min(a.bottom,b.bottom)-Math.max(a.y,b.y)>1)overlaps.push([i,j]);
                      }
                      return {boundary,icons,overlaps,doc:document.documentElement.scrollWidth,viewport:innerWidth};
                    }""")
                    self.assertLessEqual(result['doc'],result['viewport']+1,(name,result))
                    self.assertEqual(result['overlaps'],[],name)
                    for item in result['icons']:
                        b,i=item['button'],item['icon'];boundary=result['boundary']
                        self.assertGreaterEqual(b['w'],43.99,(name,b));self.assertGreaterEqual(b['h'],43.99,(name,b))
                        self.assertGreaterEqual(b['x'],boundary['x']-1,(name,b,boundary))
                        self.assertLessEqual(b['right'],boundary['right']+1,(name,b,boundary))
                        self.assertLessEqual(i['w'],b['w']);self.assertLessEqual(i['h'],b['h'])
                self.assertEqual(self.snapshot(),self.before)


if __name__=='__main__': unittest.main()
