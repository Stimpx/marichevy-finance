"""Category search never authors expense comments; offline synthetic browser checks.

Run: python -m unittest discover -s tests -p test_search_comments.py
Requires Playwright and Chromium; no authenticated account or external requests.
"""
from pathlib import Path
import os, shutil, unittest
from playwright.sync_api import sync_playwright

HTML=(Path(__file__).resolve().parents[1]/'index.html').read_text()
BASE='http://127.0.0.1:9893/'

class SearchComments(unittest.TestCase):
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
        self.page.wait_for_function("typeof v90Choose==='function'")
        self.page.evaluate('''() => {
          session=null;localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=null;localStorage.clear();state=blankState();
          const stamp=today()+'T12:00:00.000Z';
          const expense={id:'saved-expense',type:'expense',date:today(),amount:300,category:'Продукты',subcategory:'',beneficiary:'Общее',who:'Общее',store:'Тестовый магазин',comment:'Написанный ранее комментарий',pay:'Карта',created_at:stamp,updated_at:stamp};
          state.entries=[expense];state.intelligence.favorites=[{...expense,id:'saved-favorite',name:'Тестовый вариант',comment:'Комментарий избранного'}];
          showApp();go('today');clearEntry();window.originalEntries=JSON.stringify(state.entries);
        }''')

    def tearDown(self):
        errors=self.errors;self.context.close();self.assertEqual(errors,[])

    def choose(self,query,category):
        self.page.locator('#v90Search').fill(query)
        self.page.locator('#v90Quick button[data-cat="'+category+'"]').first.click()

    def test_query_is_not_saved_as_comment_or_shown_in_edit(self):
        self.page.locator('#eAmount').fill('1225')
        self.page.locator('[data-v133-target="eBeneficiary"][data-v133-recipient="Алиса"]').click()
        self.choose('табл','Аптека и медицина')
        self.assertEqual(self.page.locator('#eComment').input_value(),'')
        self.assertEqual(self.page.locator('#eCategory').input_value(),'Аптека и медицина')
        self.page.locator('#v90Save').click()
        self.page.wait_for_function('state.entries.length===2&&!v90Saving')
        record=self.page.evaluate('state.entries.at(-1)')
        self.assertEqual(record['comment'],'')
        self.assertEqual(record['category'],'Аптека и медицина')
        self.page.evaluate("id=>openEdit(id)",record['id'])
        self.assertEqual(self.page.locator('#xComment').input_value(),'')

    def test_manual_repeat_and_favorite_comments_survive_category_selection(self):
        self.page.locator('#v90Extra > summary').click()
        self.page.locator('#eComment').fill('Комментарий, который я ввела сама')
        self.choose('табл','Аптека и медицина')
        self.assertEqual(self.page.locator('#eComment').input_value(),'Комментарий, который я ввела сама')
        self.choose('парковка','Авто и транспорт')
        self.assertEqual(self.page.locator('#eComment').input_value(),'Комментарий, который я ввела сама')
        self.assertTrue(self.page.evaluate("v97RepeatEntry('saved-expense')"))
        self.choose('табл','Аптека и медицина')
        self.assertEqual(self.page.locator('#eComment').input_value(),'Написанный ранее комментарий')
        self.assertTrue(self.page.evaluate("v97OpenFavorite('saved-favorite')"))
        self.choose('парковка','Авто и транспорт')
        self.assertEqual(self.page.locator('#eComment').input_value(),'Комментарий избранного')
        self.assertTrue(self.page.evaluate('JSON.stringify(state.entries)===originalEntries'))

    def test_quick_choice_description_does_not_create_a_comment(self):
        self.page.locator('#v90Search').fill('чаевые')
        self.page.locator('#v90Quick button').filter(has_text='Чаевые').click()
        self.assertEqual(self.page.locator('#eCategory').input_value(),'Рестораны и кафе')
        self.assertEqual(self.page.locator('#eComment').input_value(),'')
        self.assertTrue(self.page.evaluate('JSON.stringify(state.entries)===originalEntries'))

if __name__=='__main__':unittest.main(verbosity=2)
