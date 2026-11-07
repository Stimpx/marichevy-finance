"""Child hygiene category selection and historical detail preservation, offline.

Run: python -m unittest discover -s tests -p test_child_hygiene.py
All records are synthetic and external browser requests are blocked.
"""
from pathlib import Path
import os
import shutil
import unittest
from playwright.sync_api import sync_playwright

HTML = (Path(__file__).resolve().parents[1] / 'index.html').read_text()
BASE = 'http://127.0.0.1:9893/'


class ChildHygiene(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = sync_playwright().start()
        executable = os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium') or shutil.which('chromium-browser')
        cls.browser = cls.p.chromium.launch(headless=True, **({'executable_path': executable} if executable else {}))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.p.stop()

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 1280, 'height': 1100}, timezone_id='Europe/Moscow', service_workers='block')
        self.context.route('**/*', lambda r: r.fulfill(status=200, content_type='text/html', body=HTML) if r.request.url == BASE else r.abort())
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.on('dialog', lambda dialog: dialog.accept())
        self.page.goto(BASE, wait_until='domcontentloaded')
        self.page.wait_for_function("typeof v92HygieneCategory==='function'")
        self.page.evaluate('''() => {
          session=null;localStorage.clear();state=blankState();localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=null;
          showApp();go('today');clearEntry();
        }''')

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def choose_from_search(self, query, category='Дети'):
        self.page.locator('#v90Search').fill(query)
        self.page.locator(f'#v90Quick [data-cat="{category}"]').first.click()

    def test_children_options_are_products_and_alias_is_form_only(self):
        result = self.page.evaluate('''() => ({
          options:v81DetailOptions('Дети'),aliasOptions:v81DetailOptions('Детские товары'),
          presentationCanonical:v99PurposeCategory('Детские товары'),
          aliasDetail:v99PurchaseDetail('Детские товары','подгузники')
        })''')
        self.assertIn('Гигиена', result['options'])
        self.assertIn('Детское питание', result['options'])
        for old_lesson in ['Английский язык', 'Танцы', 'Спорт и секции', 'Репетитор']:
            self.assertNotIn(old_lesson, result['options'])
        self.assertEqual(result['aliasOptions'], result['options'])
        self.assertEqual(result['presentationCanonical'], 'Детские товары')
        self.assertEqual(result['aliasDetail'], 'Гигиена')

    def test_diapers_and_explicit_child_wipes_choose_hygiene_without_comment(self):
        queries = ['подгузники', 'памперсы', 'детские влажные салфетки', 'салфетки для ребёнка', 'влажные салфетки для малыша']
        for query in queries:
            with self.subTest(query=query):
                self.page.evaluate('clearEntry()')
                self.assertEqual(self.page.evaluate('(q)=>v92Matches(q)[0].key', query), 'Дети')
                self.choose_from_search(query)
                self.assertEqual(self.page.locator('#eCategory').input_value(), 'Дети')
                self.assertEqual(self.page.locator('#eSubcategory').input_value(), 'Гигиена')
                self.assertEqual(self.page.locator('#eComment').input_value(), '')
        self.page.evaluate('clearEntry()')
        self.choose_from_search('салфетки')
        self.assertEqual(self.page.locator('#eSubcategory').input_value(), 'Гигиена')

    def test_real_save_records_child_hygiene_and_preserves_personal_comment(self):
        self.page.locator('#eAmount').fill('1250,50')
        self.page.locator('[data-v133-target="eBeneficiary"][data-v133-recipient="Алиса"]').click()
        self.choose_from_search('детские влажные салфетки')
        self.page.locator('#v90Extra > summary').click()
        self.page.locator('#eComment').fill('Для поездки')
        self.page.locator('#v90Save').click()
        self.page.wait_for_function('state.entries.length===1')
        result = self.page.evaluate('''() => {
          const e=state.entries[0];return {category:e.category,subcategory:e.subcategory,amount:e.amount,beneficiary:e.beneficiary,comment:e.comment};
        }''')
        self.assertEqual(result, {'category':'Дети','subcategory':'Гигиена','amount':1250.5,'beneficiary':'Алиса','comment':'Для поездки'})

    def test_old_education_detail_survives_edit_and_repeat_without_history_change(self):
        result = self.page.evaluate('''() => {
          state.entries=[{id:'legacy-child-lesson',type:'expense',date:'2026-10-10',amount:900,category:'Дети',subcategory:'Английский язык',beneficiary:'Алиса',who:'Алиса',store:'Занятия',comment:'Мой сохранённый комментарий',pay:'Карта',created_at:'2026-10-10T12:00:00Z',updated_at:'2026-10-10T12:00:00Z'}];
          const original=JSON.stringify(state.entries);openEdit('legacy-child-lesson');
          const edited={selected:document.getElementById('xSubcategory').value,options:[...document.getElementById('xSubcategory').options].map(o=>o.value)};
          closeEdit();v97RepeatEntry('legacy-child-lesson');
          return {edited,repeated:document.getElementById('eSubcategory').value,comment:document.getElementById('eComment').value,unchanged:JSON.stringify(state.entries)===original};
        }''')
        self.assertEqual(result['edited']['selected'], 'Английский язык')
        self.assertIn('Английский язык', result['edited']['options'])
        self.assertIn('Гигиена', result['edited']['options'])
        self.assertEqual(result['repeated'], 'Английский язык')
        self.assertEqual(result['comment'], 'Мой сохранённый комментарий')
        self.assertTrue(result['unchanged'])

    def test_adult_pet_and_ambiguous_wipes_do_not_force_child_hygiene(self):
        result = self.page.evaluate('''() => {
          const query=q=>({first:v92Matches(q)[0]?.key,detail:v99PurchaseDetail('Дети',q)});
          return {
            adult:query('подгузники для взрослых'),pet:query('памперсы для собаки'),
            adultWipes:query('влажные салфетки для взрослых'),tableWipes:query('салфетки для стола'),
            ambiguous:['салфетки','влажные салфетки'].map(q=>({keys:v92Matches(q).map(x=>x.key),detail:v99PurchaseDetail('Дети',q),homeDetail:v99PurchaseDetail('Дом',q)}))
          };
        }''')
        self.assertEqual(result['adult'], {'first':'Аптека и медицина','detail':''})
        self.assertEqual(result['pet'], {'first':'Животные','detail':''})
        self.assertNotEqual(result['adultWipes']['first'], 'Дети')
        self.assertNotEqual(result['tableWipes']['first'], 'Дети')
        self.assertEqual(result['adultWipes']['detail'], '')
        for ambiguous in result['ambiguous']:
            self.assertIn('Дом', ambiguous['keys'])
            self.assertIn('Дети', ambiguous['keys'])
            self.assertEqual(ambiguous['detail'], 'Гигиена')
            self.assertNotEqual(ambiguous['homeDetail'], 'Гигиена')


if __name__ == '__main__':
    unittest.main()
