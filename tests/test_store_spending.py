"""Named-store spending uses canonical merchants and shares of named purchases.

Run: python -m unittest discover -s tests -p test_store_spending.py
Every browser request is isolated synthetic data; external requests are blocked.
"""
from pathlib import Path
import os
import shutil
import unittest

from playwright.sync_api import sync_playwright


HTML = (Path(__file__).resolve().parents[1] / 'index.html').read_text()
BASE = 'http://127.0.0.1:9867/'


class StoreSpending(unittest.TestCase):
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
        self.page.wait_for_function("typeof v163StoreSpending==='function'")
        self.page.evaluate('''() => {
          session=null;localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=null;
          localStorage.clear();state=blankState();saveAll=async()=>true;
          today=()=> '2026-11-12';month=()=> '2026-11';
          window.storeEntry=(id,amount,store,fields={})=>({id,type:'expense',amount,
            date:'2026-11-05',category:'Продукты',beneficiary:'Общее',who:'Общее',
            store,comment:'Синтетическая запись',pay:'Карта',
            created_at:'2026-11-05T12:00:00.000Z',updated_at:'2026-11-05T12:00:00.000Z',...fields});
          state.entries=[storeEntry('p1',100.10,'Пятёрочка'),storeEntry('p2',.20,'5ka'),
            storeEntry('o1',90.05,'OZON',{category:'Дом',beneficiary:'Сергей'}),
            storeEntry('o2',.05,'Озон',{category:'Дом',beneficiary:'Сергей'}),
            storeEntry('wb',80.01,'WB',{category:'Одежда',beneficiary:'Виктория'}),
            storeEntry('local',70.02,'Аптека у дома',{category:'Аптека и медицина',beneficiary:'Алиса'}),
            storeEntry('sam',60.03,'Самокат'),storeEntry('sixth',50.04,'Мастерская',{category:'Спорт и здоровье'}),
            storeEntry('blank',49.50,'  '),storeEntry('missing',5,undefined,{beneficiary:'Сергей'}),
            storeEntry('oct-ozon',1000.15,'ozon.ru',{date:'2026-10-05'}),
            storeEntry('oct-shop',20.25,'Старая лавка',{date:'2026-10-05'}),
            storeEntry('prior-year',500.01,'Озон',{date:'2025-09-05'}),
            storeEntry('income',99999,'Не магазин',{type:'income',category:'Доход'}),
            storeEntry('transfer',88888,'Не магазин',{type:'transfer'}),
            storeEntry('cash',77777,'Не магазин',{type:'cash'})];
          showApp();document.getElementById('homeMonth').value='2026-11';
          document.getElementById('analyticsMonth').value='2026-11';
          document.getElementById('analyticsScope').value='month';go('home');renderAll();
          window.storeNames=(root)=>[...document.querySelectorAll(root+' .v163-store-row .v163-store-name')].map(e=>e.textContent);
          window.storeTotalText=(id)=>document.getElementById(id).textContent.replaceAll('\\u00a0',' ');
          window.originalStoreHistory=JSON.stringify(state.entries);
        }''')

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def evaluate(self, code):
        return self.page.evaluate('async () => {' + code + '}')

    def test_top_five_use_exact_cents_and_shares_of_named_period_purchases(self):
        result = self.evaluate('''
          const beforeIncome=v111MonthBalance('2026-11').income,
            beforeExpense=v111MonthBalance('2026-11').expense,data=v163StoreSpending('2026-11');
          renderHome();renderHome();
          return {data,names:storeNames('#v163HomeStoresList'),
            summaryRemoved:!document.querySelector('#v163HomeStores .v163-store-summary'),
            footerRemoved:!document.getElementById('v163HomeStoreNote'),
            excludedAttribute:document.getElementById('v163HomeStores').dataset.excludedCount,
            rowAmounts:[...document.querySelectorAll('#v163HomeStoresList .v163-store-amount')].map(e=>e.textContent.replaceAll('\\u00a0',' ')),
            sameHistory:JSON.stringify(state.entries)===originalStoreHistory,
            sameIncome:v111MonthBalance('2026-11').income===beforeIncome,
            sameExpense:v111MonthBalance('2026-11').expense===beforeExpense};
        ''')
        data = result['data']
        self.assertEqual(data['period'], '2026-11')
        self.assertEqual(data['total'], 450.50)
        self.assertEqual(data['count'], 8)
        self.assertEqual(data['excludedCount'], 0)
        self.assertEqual(data['unknownTotal'], 54.50)
        self.assertEqual(data['unknownCount'], 2)
        self.assertEqual(len(data['rows']), 6)
        self.assertEqual([row['name'] for row in data['top5']],
                         ['Пятёрочка', 'Ozon', 'Wildberries', 'Аптека у дома', 'Самокат'])
        self.assertEqual([row['amount'] for row in data['top5']],
                         [100.30, 90.10, 80.01, 70.02, 60.03])
        self.assertEqual([row['count'] for row in data['top5']], [2, 2, 1, 1, 1])
        self.assertEqual(sum(round(row['amount'] * 100) for row in data['rows']), 45050)
        for row in data['rows']:
            self.assertAlmostEqual(row['share'], row['amount'] / 450.50 * 100, places=8)
        self.assertLess(sum(row['share'] for row in data['top5']), 90)
        self.assertEqual(result['names'], [row['name'] for row in data['top5']])
        self.assertTrue(result['summaryRemoved'])
        self.assertTrue(result['footerRemoved'])
        self.assertEqual(result['excludedAttribute'], '0')
        self.assertEqual(result['rowAmounts'],
                         ['100,30 ₽', '90,10 ₽', '80,01 ₽', '70,02 ₽', '60,03 ₽'])
        self.assertTrue(result['sameHistory'])
        self.assertTrue(result['sameIncome'])
        self.assertTrue(result['sameExpense'])

    def test_analytics_scope_and_month_drive_the_store_card_while_separate_drills_do_not_rewrite_it(self):
        result = self.evaluate('''
          go('analytics');const scope=document.getElementById('analyticsScope'),
            period=document.getElementById('analyticsMonth');
          const monthly={names:storeNames('#v163AnalyticsStoresList'),total:v163StoreSpending('2026-11').total};
          scope.value='all';scope.dispatchEvent(new Event('change',{bubbles:true}));
          const all={data:v163StoreSpending('all'),names:storeNames('#v163AnalyticsStoresList'),
            home:v163StoreSpending(homeMonth()).total};
          const unchangedCard=document.getElementById('v163AnalyticsStoresList').textContent;
          v81SetFocus('auto');v84Drill('person','Сергей','analytics');
          const focusUnchanged=document.getElementById('v163AnalyticsStoresList').textContent===unchangedCard;
          v84CloseDrill();scope.value='month';scope.dispatchEvent(new Event('change',{bubbles:true}));
          period.value='2026-10';period.dispatchEvent(new Event('change',{bubbles:true}));
          return {monthly,all,focusUnchanged,october:{names:storeNames('#v163AnalyticsStoresList'),
            data:v163StoreSpending('2026-10')},
            sameHistory:JSON.stringify(state.entries)===originalStoreHistory};
        ''')
        self.assertEqual(result['monthly']['names'][0], 'Пятёрочка')
        self.assertEqual(result['monthly']['total'], 450.50)
        self.assertEqual(result['all']['data']['total'], 1970.91)
        self.assertEqual(result['all']['data']['count'], 11)
        self.assertEqual(result['all']['data']['top5'][0]['name'], 'Ozon')
        self.assertEqual(result['all']['data']['top5'][0]['amount'], 1590.26)
        self.assertEqual(result['all']['names'][0], 'Ozon')
        self.assertEqual(result['all']['home'], 450.50)
        self.assertTrue(result['focusUnchanged'])
        self.assertEqual(result['october']['data']['total'], 1020.40)
        self.assertEqual(result['october']['names'], ['Ozon', 'Старая лавка'])
        self.assertTrue(result['sameHistory'])

    def test_merchant_aliases_and_generic_names_merge_without_guessing_unknown_merchants(self):
        result = self.evaluate('''
          state.entries=[storeEntry('p1',10.10,'Пятерочка'),storeEntry('p2',.20,'5ka'),
            storeEntry('branch',1.05,'Пятерочка ул Ленина 1'),
            storeEntry('local',5.10,'  Местная   Лавка  '),storeEntry('local-case',.20,'местная лавка'),
            storeEntry('legacy-amount','0.20','местная лавка'),
            storeEntry('not-chain',3.30,'Не Пятёрочка'),storeEntry('unknown-tail',2.20,'Пятерочка сервис'),
            storeEntry('punctuation',1.11,'Точка №1'),storeEntry('different-place',1.12,'Точка 1'),
            storeEntry('blank',2.01,''),storeEntry('null',2.02,null),
            storeEntry('missing',2.03,undefined),storeEntry('non-string',2.04,42)];
          const before=JSON.stringify(state.entries),data=v163StoreSpending('2026-11');
          return {data,unchanged:JSON.stringify(state.entries)===before};
        ''')
        rows = {row['name']: row for row in result['data']['rows']}
        self.assertEqual(result['data']['total'], 24.58)
        self.assertEqual(rows['Пятёрочка']['amount'], 11.35)
        self.assertEqual(rows['Пятёрочка']['count'], 3)
        local = next(row for row in result['data']['rows'] if row['name'].casefold() == 'местная лавка')
        self.assertEqual(local['amount'], 5.50)
        self.assertEqual(local['count'], 3)
        self.assertEqual(rows['Не Пятёрочка']['amount'], 3.30)
        self.assertEqual(rows['Пятерочка сервис']['amount'], 2.20)
        self.assertIn('Точка 1', rows)
        with_punctuation = next(row for row in result['data']['rows'] if row['amount'] == 1.11)
        self.assertNotEqual(with_punctuation['key'], rows['Точка 1']['key'])
        self.assertNotIn('Без магазина', rows)
        self.assertEqual(result['data']['unknownCount'], 4)
        self.assertEqual(result['data']['unknownTotal'], 8.10)
        self.assertTrue(result['unchanged'])

    def test_only_live_valid_positive_expenses_contribute_and_empty_data_does_not_invent_stores(self):
        result = self.evaluate('''
          state.entries=[storeEntry('a',.10,'Ozon'),storeEntry('b','0.20','Озон'),
            storeEntry('oct',.40,'Ozon',{date:'2026-10-01'}),
            storeEntry('income',9999,'Доход',{type:'income'}),
            storeEntry('transfer',9999,'Перевод',{type:'transfer'}),
            storeEntry('cash',9999,'Наличные',{type:'cash'}),
            storeEntry('adjustment',9999,'Корректировка',{balanceAdjustment:true}),
            storeEntry('bad-date',9999,'Ошибка',{date:'2026-02-30'}),
            storeEntry('bad-current-date',9999,'Ошибка',{date:'2026-11-31'}),
            storeEntry('negative',-99,'Ошибка'),storeEntry('zero',0,'Ошибка'),
            storeEntry('bad-amount','bad','Ошибка'),storeEntry('infinity',Infinity,'Ошибка'),
            storeEntry('boolean',true,'Ошибка'),storeEntry('array',[1],'Ошибка'),
            storeEntry('deleted',9999,'Удалённый')];
          state.deletedEntries={deleted:'2026-11-06T12:00:00.000Z'};
          const monthly=v163StoreSpending('2026-11'),all=v163StoreSpending('all');
          v163RenderStoreSpending('home','2026-11');v163RenderStoreSpending('analytics','all');
          const attributes={home:document.getElementById('v163HomeStores').dataset.excludedCount,
            all:document.getElementById('v163AnalyticsStores').dataset.excludedCount};
          state.entries=state.entries.filter(e=>['income','transfer'].includes(e.id));
          const before=JSON.stringify(state.entries);renderAll();
          return {monthly,all,attributes,empty:v163StoreSpending('2026-11'),
            homeRows:document.querySelectorAll('#v163HomeStoresList .v163-store-row').length,
            analyticsRows:document.querySelectorAll('#v163AnalyticsStoresList .v163-store-row').length,
            homeText:document.getElementById('v163HomeStoresList').textContent,
            noExtraText:!document.querySelector('#v163HomeStores .v163-store-summary,#v163AnalyticsStores .v163-store-summary,#v163HomeStoreNote,#v163AnalyticsStoreNote'),
            unchanged:JSON.stringify(state.entries)===before};
        ''')
        self.assertEqual(result['monthly']['total'], .30)
        self.assertEqual(result['monthly']['count'], 2)
        self.assertEqual(result['monthly']['excludedCount'], 7)
        self.assertEqual(result['all']['total'], .70)
        self.assertEqual(result['all']['count'], 3)
        self.assertEqual(result['all']['excludedCount'], 8)
        self.assertEqual(result['attributes'], {'home': '7', 'all': '8'})
        self.assertEqual(result['empty']['total'], 0)
        self.assertEqual(result['empty']['excludedCount'], 0)
        self.assertEqual(result['empty']['rows'], [])
        self.assertEqual(result['empty']['top5'], [])
        self.assertEqual(result['homeRows'], 0)
        self.assertEqual(result['analyticsRows'], 0)
        self.assertIn('покупок с указанным магазином пока нет', result['homeText'])
        self.assertNotIn('NaN', result['homeText'])
        self.assertNotIn('Infinity', result['homeText'])
        self.assertTrue(result['noExtraText'])
        self.assertTrue(result['unchanged'])

    def test_store_labels_are_escaped_in_both_cards_and_prototype_names_remain_data(self):
        result = self.evaluate('''
          const malicious='<img src=x onerror="window.badStore=1">',script='\"><script>window.badStore=2</script>';
          state.entries=[storeEntry('html',20.01,malicious),storeEntry('script',10.02,script),
            storeEntry('proto-label',5.03,'__proto__'),storeEntry('constructor-label',4.04,'constructor'),storeEntry('safe',1.05,'Ozon')];
          const before=JSON.stringify(state.entries);renderAll();
          return {data:v163StoreSpending('2026-11'),
            home:document.getElementById('v163HomeStoresList').textContent,
            analytics:document.getElementById('v163AnalyticsStoresList').textContent,
            unsafe:!!document.querySelector('#v163HomeStoresList [onerror],#v163HomeStoresList script,#v163AnalyticsStoresList [onerror],#v163AnalyticsStoresList script'),
            bad:window.badStore||null,polluted:Object.prototype.badStore||null,
            unchanged:JSON.stringify(state.entries)===before};
        ''')
        self.assertEqual(result['data']['total'], 40.15)
        self.assertEqual(result['data']['count'], 5)
        self.assertIn('<img src=x onerror="window.badStore=1">', result['home'])
        self.assertIn('<script>window.badStore=2</script>', result['analytics'])
        self.assertIn('__proto__', result['home'])
        self.assertIn('constructor', result['analytics'])
        self.assertFalse(result['unsafe'])
        self.assertIsNone(result['bad'])
        self.assertIsNone(result['polluted'])
        self.assertTrue(result['unchanged'])

    def test_actual_add_edit_and_delete_refresh_home_and_all_time_analytics_without_duplicate_amounts(self):
        result = self.evaluate('''
          state.entries=[storeEntry('nov',100.10,'Ozon'),storeEntry('oct',10.20,'Озон',{date:'2026-10-05'})];
          const original=JSON.stringify(state.entries);document.getElementById('analyticsScope').value='all';
          renderAll();openEntry('expense');document.getElementById('eAmount').value='250.25';
          v90Choose('Продукты');document.getElementById('eStore').value='Новый магазин';
          document.getElementById('eDate').value=today();await addEntry();const added=state.entries.at(-1);
          const read=()=>({home:v163StoreSpending(homeMonth()),all:v163StoreSpending('all'),
            homeNames:storeNames('#v163HomeStoresList'),allNames:storeNames('#v163AnalyticsStoresList')});
          const afterAdd=read();openEdit(added.id);document.getElementById('xAmount').value='50.05';
          document.getElementById('xStore').value='ozon.ru';await saveEdit();const afterEdit=read();
          await deleteEntry(added.id);const afterDelete=read();
          return {afterAdd,afterEdit,afterDelete,scope:document.getElementById('analyticsScope').value,
            oldUnchanged:JSON.stringify(state.entries)===original};
        ''')
        self.assertEqual(result['afterAdd']['home']['total'], 350.35)
        self.assertEqual(result['afterAdd']['all']['total'], 360.55)
        self.assertEqual(result['afterAdd']['homeNames'], ['Новый магазин', 'Ozon'])
        self.assertEqual(result['afterEdit']['home']['total'], 150.15)
        self.assertEqual(result['afterEdit']['all']['total'], 160.35)
        self.assertEqual(result['afterEdit']['homeNames'], ['Ozon'])
        self.assertEqual(result['afterEdit']['allNames'], ['Ozon'])
        self.assertEqual(result['afterDelete']['home']['total'], 100.10)
        self.assertEqual(result['afterDelete']['all']['total'], 110.30)
        self.assertEqual(result['scope'], 'all')
        self.assertTrue(result['oldUnchanged'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
