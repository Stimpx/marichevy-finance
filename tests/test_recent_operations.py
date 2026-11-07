"""Latest added operations on offline synthetic data.

Run: python -m unittest discover -s tests -p test_recent_operations.py
Requires Playwright and Chromium; all external requests are blocked.
"""
from pathlib import Path
import os, shutil, unittest
from playwright.sync_api import sync_playwright

HTML=(Path(__file__).resolve().parents[1]/'index.html').read_text()
BASE='http://127.0.0.1:9896/'


class RecentOperations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p=sync_playwright().start()
        executable=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium') or shutil.which('chromium-browser')
        cls.browser=cls.p.chromium.launch(headless=True,**({'executable_path':executable} if executable else {}))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.p.stop()

    def setUp(self):
        self.context=self.browser.new_context(timezone_id='Europe/Moscow',service_workers='block',viewport={'width':1280,'height':1000})
        self.context.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html',body=HTML) if route.request.url==BASE else route.abort())
        self.page=self.context.new_page();self.errors=[]
        self.page.on('pageerror',lambda error:self.errors.append(str(error)))
        self.page.on('dialog',lambda dialog:dialog.accept())
        self.page.goto(BASE,wait_until='domcontentloaded')
        self.page.wait_for_function("typeof v137RecentAddedEntries==='function'")
        self.page.evaluate('''() => {
          session=null;localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=null;
          localStorage.clear();state=blankState();showApp();go('today');clearEntry();
          window.testRecentEntry=(id,date,created_at)=>({id,type:'expense',date,amount:123,category:'Продукты',subcategory:'',beneficiary:'Общее',who:'Не указано',store:id,comment:'Синтетическая запись',pay:'Карта',...(created_at===undefined?{}:{created_at})});
          window.testRecentIds=()=>[...document.querySelectorAll('#todayList [data-v137-recent-id]')].map(node=>node.dataset.v137RecentId);
        }''')

    def tearDown(self):
        self.context.close();self.assertEqual(self.errors,[])

    def evaluate(self,code):
        return self.page.evaluate('async () => {'+code+'}')

    def test_backdated_new_entry_is_first_after_actual_save(self):
        result=self.evaluate('''
          state.entries=[testRecentEntry('older-added',today(),'2026-01-01T10:00:00Z')];
          document.getElementById('eAmount').value='42';document.getElementById('eDate').value='2026-09-01';
          v90Choose('Продукты');v133ChooseRecipient('eBeneficiary','Общее');
          await addEntry();
          return {ids:testRecentIds(),newId:state.entries[1]?.id,newDate:state.entries[1]?.date,firstDate:document.querySelector('#todayList small')?.textContent};
        ''')
        self.assertEqual(result['newDate'],'2026-09-01')
        self.assertEqual(result['ids'],[result['newId'],'older-added'])
        self.assertIn('01.09.2026',result['firstDate'])

    def test_creation_time_handles_offsets_and_ignores_operation_date(self):
        result=self.evaluate('''
          state.entries=[testRecentEntry('future-operation','2030-01-01','2026-11-01T12:00:00Z'),testRecentEntry('latest-added','2025-01-01','2026-11-02T12:00:00Z'),testRecentEntry('offset-stamp','2026-11-07','2026-11-02T13:00:00+03:00')];
          renderToday();return testRecentIds();
        ''')
        self.assertEqual(result,['latest-added','offset-stamp','future-operation'])

    def test_edit_timestamp_does_not_move_old_entry_above_newly_added(self):
        result=self.evaluate('''
          state.entries=[testRecentEntry('old','2026-10-01','2026-11-01T12:00:00Z'),testRecentEntry('new','2026-10-02','2026-11-02T12:00:00Z')];
          renderToday();const before=testRecentIds();state.entries[0].updated_at='2030-12-31T23:59:59Z';state.entries[0].date='2030-12-31';
          renderToday();return {before,after:testRecentIds()};
        ''')
        self.assertEqual(result['before'],['new','old']);self.assertEqual(result['after'],result['before'])

    def test_equal_and_legacy_timestamps_use_stable_reverse_append_order(self):
        result=self.evaluate('''
          state.entries=[testRecentEntry('missing','2030-01-01'),testRecentEntry('empty','2031-01-01',''),testRecentEntry('invalid','2032-01-01','bad-stamp'),testRecentEntry('tie-a','2025-01-01','2026-11-01T12:00:00Z'),testRecentEntry('tie-b','2024-01-01','2026-11-01T12:00:00Z')];
          state.entries[0].updated_at='2040-01-01T00:00:00Z';const original=JSON.stringify(state.entries);
          renderToday();const first=testRecentIds();renderToday();return {first,second:testRecentIds(),unchanged:JSON.stringify(state.entries)===original};
        ''')
        self.assertEqual(result['first'],['tie-b','tie-a','invalid','empty','missing'])
        self.assertEqual(result['first'],result['second']);self.assertTrue(result['unchanged'])

    def test_list_is_bounded_to_ten_and_does_not_mutate_history(self):
        result=self.evaluate('''
          state.entries=Array.from({length:15},(_,index)=>testRecentEntry('entry-'+index,'2026-09-01',new Date(Date.UTC(2026,10,index+1,12)).toISOString()));
          const original=JSON.stringify(state.entries);renderToday();return {ids:testRecentIds(),unchanged:JSON.stringify(state.entries)===original,count:state.entries.length};
        ''')
        self.assertEqual(result['ids'],['entry-'+str(i) for i in range(14,4,-1)])
        self.assertEqual(result['count'],15);self.assertTrue(result['unchanged'])

    def test_row_actions_remain_available_and_delete_respects_viewer_permission(self):
        result=self.evaluate('''
          state.entries=[testRecentEntry('controlled','2026-10-10','2026-11-01T12:00:00Z')];renderToday();
          const actions=[...document.querySelectorAll('#todayList button[data-record-action]')].map(node=>node.dataset.recordAction);
          const original=JSON.stringify(state.entries);window.__FINANCE_BRIDGE__={active:true,role:'viewer'};
          document.querySelector('#todayList [data-record-action="entry-delete"]').click();
          return {actions,unchanged:JSON.stringify(state.entries)===original};
        ''')
        self.assertEqual(result['actions'],['entry-edit','entry-repeat','favorite-from-entry','entry-delete'])
        self.assertTrue(result['unchanged'])

    def test_empty_block_names_added_operations(self):
        result=self.evaluate("renderToday();return {title:document.getElementById('todayList').previousElementSibling.textContent,text:document.getElementById('todayList').textContent};")
        self.assertEqual(result['title'],'Последние добавленные операции')
        self.assertEqual(result['text'],'Добавленных операций пока нет.')


if __name__=='__main__':unittest.main(verbosity=2)
