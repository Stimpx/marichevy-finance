"""Family category totals combine every recipient once and drill into the same period.

Run: python -m unittest discover -s tests -p test_category_summary.py
Every browser request is isolated synthetic data; external requests are blocked.
"""
from pathlib import Path
import os
import shutil
import unittest

from playwright.sync_api import sync_playwright


HTML = (Path(__file__).resolve().parents[1] / 'index.html').read_text()
BASE = 'http://127.0.0.1:9866/'


class CategorySummary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = sync_playwright().start()
        executable = (os.environ.get('CHROMIUM_EXECUTABLE')
                      or shutil.which('chromium') or shutil.which('chromium-browser'))
        cls.browser = cls.p.chromium.launch(
            headless=True, **({'executable_path': executable} if executable else {}))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.p.stop()

    def setUp(self):
        self.context = self.browser.new_context(
            viewport={'width': 1440, 'height': 1100},
            timezone_id='Europe/Moscow', service_workers='block')
        self.context.route('**/*', lambda route: route.fulfill(
            status=200, content_type='text/html', body=HTML)
            if route.request.url == BASE else route.abort())
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.on('dialog', lambda dialog: dialog.accept())
        self.page.goto(BASE, wait_until='domcontentloaded')
        self.page.wait_for_function("typeof v165CategorySpending==='function'")
        self.page.evaluate('''() => {
          session=null;localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=null;
          localStorage.clear();state=blankState();saveAll=async()=>true;
          today=()=> '2026-11-12';month=()=> '2026-11';
          window.categoryEntry=(id,amount,category,beneficiary='Общее',fields={})=>({id,type:'expense',amount,
            date:'2026-11-05',category,beneficiary,who:'Общее',store:'Тестовый магазин',
            subcategory:'',comment:'Ручная заметка',pay:'Карта',
            created_at:'2026-11-05T12:00:00.000Z',updated_at:'2026-11-05T12:00:00.000Z',...fields});
          state.entries=[
            categoryEntry('cafe-v',4017,'Рестораны и кафе','Виктория'),
            categoryEntry('cafe-s',1895,'Кафе и доставка','Сергей'),
            categoryEntry('cafe-shared',2290,'  КАФЕ   И ДОСТАВКА  '),
            categoryEntry('food',100.10,'Продукты'),categoryEntry('medicine',20.20,'Аптека и медицина','Алиса'),
            categoryEntry('sport',30.30,'Спорт','Виктория'),categoryEntry('custom',40.40,'Своя статья','Сергей'),
            categoryEntry('missing',50.50,'  '),
            categoryEntry('prior-cafe',1000.25,'Рестораны и кафе','Виктория',{date:'2026-10-05'}),
            categoryEntry('prior-food',200.05,'Продукты','Общее',{date:'2026-10-05'}),
            categoryEntry('income',99999,'Рестораны и кафе','Виктория',{type:'income'}),
            categoryEntry('transfer',88888,'Рестораны и кафе','Виктория',{type:'transfer'})];
          showApp();document.getElementById('homeMonth').value='2026-11';
          document.getElementById('analyticsMonth').value='2026-11';
          document.getElementById('analyticsScope').value='month';go('analytics');renderAll();
          window.originalCategoryHistory=JSON.stringify(state.entries);
          window.categoryButton=key=>[...document.querySelectorAll('#aCatsDetails [data-v165-category]')]
            .find(button=>button.dataset.v165Category===key);
          window.readCategoryDrill=()=>({context:{...v96DrillContext},
            total:document.getElementById('v96DrillTotal').textContent.replaceAll('\\u00a0',' '),
            count:Number(document.getElementById('v96DrillCount').textContent),
            period:document.getElementById('v84DrillPeriod').textContent,
            ids:[...document.querySelectorAll('#v84DrillEntries [data-v141-operation-id]')]
              .map(row=>row.dataset.v141OperationId),
            filters:[...document.querySelectorAll('#v84DrillBody button[data-v84-sub]')]
              .map(button=>({key:button.dataset.v84Sub,text:button.textContent.replaceAll('\\u00a0',' ')}))});
        }''')

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def evaluate(self, code):
        return self.page.evaluate('async () => {' + code + '}')

    def test_family_category_combines_all_three_recipients_once_with_exact_total_and_share(self):
        result = self.evaluate('''
          const before={entries:JSON.stringify(state.entries),accounts:JSON.stringify(state.intelligence.accounts),
            monthly:v111MonthBalance('2026-11').expense},data=v165CategorySpending('2026-11');
          renderAnalytics();renderAnalytics();
          const button=categoryButton('Рестораны и кафе');
          return {data,cafeText:button?.textContent.replaceAll('\\u00a0',' '),
            cafeRows:document.querySelectorAll('#aCatsDetails [data-v165-category="Рестораны и кафе"]').length,
            visible:!!document.getElementById('v165CategorySummary').getClientRects().length,
            listCount:document.querySelectorAll('#aCatsDetails').length,
            sameEntries:JSON.stringify(state.entries)===before.entries,
            sameAccounts:JSON.stringify(state.intelligence.accounts)===before.accounts,
            sameMonthly:v111MonthBalance('2026-11').expense===before.monthly};
        ''')
        data = result['data']
        self.assertEqual(data['total'], 8443.50)
        self.assertEqual(data['count'], 8)
        self.assertEqual(data['excludedCount'], 0)
        self.assertEqual(len(data['rows']), 6)
        cafe = next(row for row in data['rows'] if row['key'] == 'Рестораны и кафе')
        self.assertEqual(cafe['label'], 'Кафе и доставка')
        self.assertEqual(cafe['amount'], 8202)
        self.assertEqual(cafe['count'], 3)
        self.assertAlmostEqual(cafe['share'], 8202 / 8443.50 * 100, places=8)
        self.assertEqual(sum(round(row['amount'] * 100) for row in data['rows']), 844350)
        self.assertEqual(sum(row['count'] for row in data['rows']), 8)
        self.assertAlmostEqual(sum(row['share'] for row in data['rows']), 100, places=8)
        self.assertIn('8 202,00 ₽', result['cafeText'])
        self.assertEqual(result['cafeRows'], 1)
        self.assertTrue(result['visible'])
        self.assertEqual(result['listCount'], 1)
        self.assertTrue(result['sameEntries'])
        self.assertTrue(result['sameAccounts'])
        self.assertTrue(result['sameMonthly'])

    def test_exact_display_and_legacy_aliases_merge_but_custom_and_missing_categories_are_preserved(self):
        result = self.evaluate('''
          state.entries=[categoryEntry('c1',1.10,' кафе   и доставка '),categoryEntry('c2',2.20,'Рестораны и кафе'),
            categoryEntry('s1',3.30,'Спорт'),categoryEntry('s2',4.40,'Фитнес'),categoryEntry('s3',5.50,'Спорт и здоровье'),
            categoryEntry('m1',6.60,'Медицина'),categoryEntry('m2',7.70,'Медицина и аптеки'),
            categoryEntry('t1',8.80,'Авто и транспорт','Общее',{subcategory:'Такси'}),categoryEntry('t2',9.90,'Такси'),
            categoryEntry('a1',10.10,'Авто и транспорт','Автомобиль',{subcategory:'Ремонт'}),
            categoryEntry('u1',11.11,'Своя статья'),categoryEntry('u2',12.12,' своя   статья '),
            categoryEntry('u3',13.13,'Своя статья 2'),categoryEntry('blank',14.14,' '),
            categoryEntry('absent',15.15,undefined),categoryEntry('not-food',16.16,'Не Продукты')];
          const original=JSON.stringify(state.entries),data=v165CategorySpending('2026-11');
          return {data,unchanged:JSON.stringify(state.entries)===original};
        ''')
        rows = {row['key']: row for row in result['data']['rows']}
        self.assertEqual(result['data']['total'], 141.41)
        self.assertEqual(result['data']['count'], 16)
        self.assertEqual(len(rows), 9)
        self.assertEqual(rows['Рестораны и кафе']['amount'], 3.30)
        self.assertEqual(rows['Спорт и здоровье']['amount'], 13.20)
        self.assertEqual(rows['Аптека и медицина']['amount'], 14.30)
        self.assertEqual(rows['Транспорт']['amount'], 18.70)
        self.assertEqual(rows['Авто и транспорт']['amount'], 10.10)
        self.assertEqual(rows['missing']['label'], 'Без категории')
        self.assertEqual(rows['missing']['amount'], 29.29)
        unknown = [row for row in rows.values() if row['key'].startswith('unknown:')]
        self.assertEqual(len(unknown), 3)
        custom = next(row for row in unknown if row['label'].casefold() == 'своя статья')
        self.assertEqual(custom['amount'], 23.23)
        self.assertEqual(custom['count'], 2)
        self.assertNotIn('Продукты', rows)
        self.assertTrue(result['unchanged'])

    def test_summary_switches_between_selected_month_and_all_history_without_changing_other_periods(self):
        result = self.evaluate('''
          const scope=document.getElementById('analyticsScope'),monthField=document.getElementById('analyticsMonth');
          const monthly=v165CategorySpending('2026-11');scope.value='all';scope.dispatchEvent(new Event('change',{bubbles:true}));
          const all={data:v165CategorySpending('all'),text:categoryButton('Рестораны и кафе').textContent.replaceAll('\\u00a0',' ')};
          v81SetFocus('auto');const afterSeparateFocus=v165CategorySpending('all');
          scope.value='month';scope.dispatchEvent(new Event('change',{bubbles:true}));
          monthField.value='2026-10';monthField.dispatchEvent(new Event('change',{bubbles:true}));
          return {monthly,all,sameFocus:JSON.stringify(afterSeparateFocus)===JSON.stringify(all.data),
            october:v165CategorySpending('2026-10'),octoberText:categoryButton('Рестораны и кафе').textContent.replaceAll('\\u00a0',' '),
            sameHistory:JSON.stringify(state.entries)===originalCategoryHistory};
        ''')
        self.assertEqual(result['monthly']['total'], 8443.50)
        self.assertEqual(result['all']['data']['total'], 9643.80)
        self.assertEqual(result['all']['data']['count'], 10)
        all_cafe = next(row for row in result['all']['data']['rows'] if row['key'] == 'Рестораны и кафе')
        self.assertEqual(all_cafe['amount'], 9202.25)
        self.assertEqual(all_cafe['count'], 4)
        self.assertIn('9 202,25 ₽', result['all']['text'])
        self.assertTrue(result['sameFocus'])
        self.assertEqual(result['october']['total'], 1200.30)
        self.assertEqual(len(result['october']['rows']), 2)
        self.assertIn('1 000,25 ₽', result['octoberText'])
        self.assertTrue(result['sameHistory'])

    def test_real_category_row_opens_recipient_breakdown_and_filters_the_same_operations(self):
        self.page.locator('#aCatsDetails [data-v165-category="Рестораны и кафе"]').click()
        result = self.evaluate('''
          const all=readCategoryDrill();
          document.querySelector('#v84DrillBody button[data-v84-sub="Виктория"]').click();
          const victoria=readCategoryDrill();
          document.querySelector('#v84DrillBody button[data-v84-sub="Сергей"]').click();
          const sergey=readCategoryDrill();
          document.querySelector('#v84DrillBody button[data-v84-sub="Общее"]').click();
          const shared=readCategoryDrill();
          document.querySelector('#v84DrillBody button[data-v84-sub=""]').click();
          return {all,victoria,sergey,shared,reset:readCategoryDrill(),
            sameHistory:JSON.stringify(state.entries)===originalCategoryHistory};
        ''')
        self.assertEqual(result['all']['context']['mode'], 'category')
        self.assertEqual(result['all']['context']['key'], 'Рестораны и кафе')
        self.assertEqual(result['all']['context']['scope'], 'month')
        self.assertEqual(result['all']['context']['month'], '2026-11')
        self.assertEqual(result['all']['total'], '8 202,00 ₽')
        self.assertEqual(result['all']['count'], 3)
        self.assertEqual(set(result['all']['ids']), {'cafe-v', 'cafe-s', 'cafe-shared'})
        filters = {row['key']: row['text'] for row in result['all']['filters']}
        for recipient, amount in [('Виктория', '4 017,00 ₽'), ('Сергей', '1 895,00 ₽'), ('Общее', '2 290,00 ₽')]:
            self.assertIn(amount, filters[recipient])
        for key, recipient, amount, operation in [
                ('victoria', 'Виктория', '4 017,00 ₽', 'cafe-v'),
                ('sergey', 'Сергей', '1 895,00 ₽', 'cafe-s'),
                ('shared', 'Общее', '2 290,00 ₽', 'cafe-shared')]:
            self.assertEqual(result[key]['context']['sub'], recipient)
            self.assertEqual(result[key]['total'], amount)
            self.assertEqual(result[key]['ids'], [operation])
        self.assertEqual(result['reset']['total'], '8 202,00 ₽')
        self.assertEqual(result['reset']['count'], 3)
        self.assertTrue(result['sameHistory'])

    def test_edit_and_delete_return_to_category_recipient_and_all_time_period_with_updated_totals(self):
        result = self.evaluate('''
          document.getElementById('analyticsScope').value='all';renderAnalytics();
          categoryButton('Рестораны и кафе').click();
          document.querySelector('#v84DrillBody button[data-v84-sub="Виктория"]').click();
          const others=JSON.stringify(state.entries.filter(e=>!['cafe-v','prior-cafe'].includes(e.id)));
          v96EditFromDrill('cafe-v');document.getElementById('xAmount').value='4027.01';await saveEdit();
          const edited=readCategoryDrill(),editedSummary=v165CategorySpending('all');
          v96DeleteFromDrill('prior-cafe');await new Promise(requestAnimationFrame);
          return {edited,editedSummary,deleted:readCategoryDrill(),summary:v165CategorySpending('all'),
            scope:document.getElementById('analyticsScope').value,
            month:document.getElementById('analyticsMonth').value,
            originalOthers:JSON.stringify(state.entries.filter(e=>!['cafe-v','prior-cafe'].includes(e.id)))===others,
            november:v111MonthBalance('2026-11').expense};
        ''')
        for point in ['edited', 'deleted']:
            self.assertEqual(result[point]['context']['mode'], 'category')
            self.assertEqual(result[point]['context']['key'], 'Рестораны и кафе')
            self.assertEqual(result[point]['context']['scope'], 'all')
            self.assertEqual(result[point]['context']['sub'], 'Виктория')
            self.assertIn('За всё время', result[point]['period'])
        self.assertEqual(result['edited']['total'], '5 027,26 ₽')
        self.assertEqual(result['edited']['count'], 2)
        self.assertEqual(result['editedSummary']['total'], 9653.81)
        self.assertEqual(result['deleted']['total'], '4 027,01 ₽')
        self.assertEqual(result['deleted']['ids'], ['cafe-v'])
        cafe = next(row for row in result['summary']['rows'] if row['key'] == 'Рестораны и кафе')
        self.assertEqual(cafe['amount'], 8212.01)
        self.assertEqual(cafe['count'], 3)
        self.assertEqual(result['summary']['total'], 8653.56)
        self.assertEqual(result['scope'], 'all')
        self.assertEqual(result['month'], '2026-11')
        self.assertEqual(result['november'], 8453.51)
        self.assertTrue(result['originalOthers'])

    def test_custom_category_text_is_escaped_and_prototype_names_remain_plain_groups(self):
        result = self.evaluate('''
          const malicious='<img src=x onerror="window.badCategory=1">';
          state.entries=[categoryEntry('unsafe-label',20.01,malicious),
            categoryEntry('proto-label',5.03,'__proto__'),categoryEntry('constructor-label',4.04,'constructor'),
            categoryEntry('plain',1.05,'Продукты')];
          const before=JSON.stringify(state.entries);renderAnalytics();
          return {data:v165CategorySpending('2026-11'),text:document.getElementById('aCatsDetails').textContent,
            unsafe:!!document.querySelector('#aCatsDetails [onerror],#aCatsDetails script'),
            bad:window.badCategory||null,polluted:Object.prototype.badCategory||null,
            unchanged:JSON.stringify(state.entries)===before};
        ''')
        self.assertEqual(result['data']['total'], 30.13)
        self.assertEqual(result['data']['count'], 4)
        self.assertEqual(len(result['data']['rows']), 4)
        self.assertIn('<img src=x onerror="window.badCategory=1">', result['text'])
        self.assertIn('__proto__', result['text'])
        self.assertIn('constructor', result['text'])
        self.assertFalse(result['unsafe'])
        self.assertIsNone(result['bad'])
        self.assertIsNone(result['polluted'])
        self.assertTrue(result['unchanged'])

    def test_live_valid_expenses_match_summary_and_drill_while_invalid_or_empty_data_are_transparent(self):
        result = self.evaluate('''
          state.entries=[categoryEntry('valid',1.01,'Продукты'),categoryEntry('income',9999,'Продукты','Общее',{type:'income'}),
            categoryEntry('transfer',9999,'Продукты','Общее',{type:'transfer'}),
            categoryEntry('adjustment',9999,'Продукты','Общее',{balanceAdjustment:true}),
            categoryEntry('bad-date',9999,'Продукты','Общее',{date:'2026-11-31'}),
            categoryEntry('bool',true,'Продукты'),categoryEntry('array',[1],'Продукты'),
            categoryEntry('negative',-10,'Продукты'),categoryEntry('zero',0,'Продукты'),
            categoryEntry('bad-amount','bad','Продукты'),categoryEntry('deleted',9999,'Продукты')];
          state.deletedEntries={deleted:'2026-11-06T12:00:00.000Z'};
          const data=v165CategorySpending('2026-11');v165RenderCategorySummary('2026-11');
          categoryButton('Продукты').click();const drill=readCategoryDrill();v84CloseDrill();
          state.entries=state.entries.filter(e=>e.type==='income');const before=JSON.stringify(state.entries);
          v165RenderCategorySummary('2026-11');return {data,drill,empty:v165CategorySpending('2026-11'),
            rows:document.querySelectorAll('#aCatsDetails [data-v165-category]').length,
            text:document.getElementById('aCatsDetails').textContent,
            unchanged:JSON.stringify(state.entries)===before};
        ''')
        self.assertEqual(result['data']['total'], 1.01)
        self.assertEqual(result['data']['count'], 1)
        self.assertEqual(result['data']['excludedCount'], 6)
        self.assertEqual(result['drill']['total'], '1,01 ₽')
        self.assertEqual(result['drill']['count'], 1)
        self.assertEqual(result['drill']['ids'], ['valid'])
        self.assertEqual(result['empty']['total'], 0)
        self.assertEqual(result['empty']['rows'], [])
        self.assertEqual(result['empty']['excludedCount'], 0)
        self.assertEqual(result['rows'], 0)
        self.assertNotIn('NaN', result['text'])
        self.assertNotIn('Infinity', result['text'])
        self.assertTrue(result['unchanged'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
