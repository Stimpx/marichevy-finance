"""Bank/loan payments stay in finance reports but never rank as shopping merchants.

Run: PYTHONPATH=tests python -m unittest test_store_bank_exclusion
All browser requests and data are local synthetic fixtures.
"""
import unittest

import test_store_spending as store_base


class StoreBankExclusion(unittest.TestCase):
    setUpClass = classmethod(store_base.StoreSpending.setUpClass.__func__)
    tearDownClass = classmethod(store_base.StoreSpending.tearDownClass.__func__)
    setUp = store_base.StoreSpending.setUp
    tearDown = store_base.StoreSpending.tearDown
    evaluate = store_base.StoreSpending.evaluate

    def test_financial_payments_leave_ranking_and_denominator_without_changing_reports(self):
        result = self.evaluate('''
          state.entries=[storeEntry('wb',100.10,'WB'),storeEntry('wb-alias',.20,'Вайлдберриз'),
            storeEntry('missing',50,''),storeEntry('ikea',40,'IKEA'),
            storeEntry('levels',30,'5Levels'),storeEntry('retail-bank',20.01,'Банк семян'),
            storeEntry('uralsib',201830.21,'  УРАЛСИБ  ',{category:'Прочее'}),
            storeEntry('bank-fee',2.05,'Сбербанк',{category:'Прочее'}),
            storeEntry('credit',10,'Ozon',{category:'Кредит'}),
            storeEntry('mortgage',11,'Другой получатель',{mortgagePayment:true}),
            storeEntry('installment',12,'Wildberries',{installmentId:'split'}),
            storeEntry('target',13,'Магазин',{beneficiary:'Кредиты и рассрочки'}),
            storeEntry('linked',14,'Ozon'),storeEntry('repayment',15,'Магазин',{debtRepayment:true}),
            storeEntry('bank-category',16,'Неизвестный банк',{category:'Банки'})];
          state.installments=[{id:'plan',links:{payment:'linked'}}];
          const original=JSON.stringify(state),before={expenses:sum(expenses('2026-11')),
            month:v111MonthBalance('2026-11'),categories:v165CategorySpending('2026-11')};
          v163RenderStoreSpending('home','2026-11');v163RenderStoreSpending('analytics','2026-11');
          const data=v163StoreSpending('2026-11');
          return {data,unchanged:JSON.stringify(state)===original,
            reportsUnchanged:JSON.stringify(before)===JSON.stringify({expenses:sum(expenses('2026-11')),
              month:v111MonthBalance('2026-11'),categories:v165CategorySpending('2026-11')}),
            allExpense:before.expenses,cards:['v163Home','v163Analytics'].map(prefix=>({
              names:storeNames('#'+prefix+'StoresList'),
              count:document.getElementById(prefix+'Stores').dataset.bankExcludedCount,
              noSummary:!document.querySelector('#'+prefix+'Stores .v163-store-summary'),
              noFooter:!document.getElementById(prefix+'StoreNote'),
              badges:[...document.querySelectorAll('#'+prefix+'StoresList .v163-store-identity')].map(node=>({
                name:node.querySelector('.v163-store-name').textContent,
                mark:node.querySelector('.v96-merchant-badge')?.dataset.merchantMark,
                brand:node.querySelector('.v96-merchant-badge')?.dataset.merchantBrand||'',
                local:[...node.querySelectorAll('img')].every(img=>img.src.startsWith('data:image/')),
                decorative:node.querySelector('.v96-merchant-badge')?.getAttribute('aria-hidden')}))}))};
        ''')
        data = result['data']
        self.assertEqual(data['total'], 190.31)
        self.assertEqual(data['count'], 5)
        self.assertEqual(data['bankExcludedCount'], 9)
        self.assertEqual(data['bankExcludedTotal'], 201923.26)
        self.assertEqual(data['excludedCount'], 0)
        self.assertEqual(result['allExpense'], 202163.57)
        self.assertEqual([row['name'] for row in data['rows']],
                         ['Wildberries', 'IKEA', '5Levels', 'Банк семян'])
        self.assertAlmostEqual(sum(row['share'] for row in data['rows']), 100)
        self.assertAlmostEqual(data['rows'][0]['share'], 100.30 / 190.31 * 100)
        self.assertTrue(result['unchanged'])
        self.assertTrue(result['reportsUnchanged'])
        for index, card in enumerate(result['cards']):
            self.assertEqual(card['count'], '9')
            self.assertTrue(card['noSummary'])
            self.assertTrue(card['noFooter'])
            self.assertEqual(len(card['badges']), 4+index)
            badges = {row['name']: row for row in card['badges']}
            self.assertEqual(badges['Wildberries']['mark'], 'logo')
            self.assertEqual(badges['IKEA']['mark'], 'logo')
            if index:
                self.assertEqual(card['names'][0], 'Без магазина')
                self.assertEqual(badges['Без магазина']['mark'], 'missing')
                self.assertEqual(badges['Без магазина']['brand'], '')
            else:
                self.assertNotIn('Без магазина', badges)
            self.assertEqual(badges['5Levels']['mark'], 'initials')
            for badge in card['badges']:
                self.assertTrue(badge['local'])
                self.assertEqual(badge['decorative'], 'true')

    def test_exact_financial_aliases_metadata_periods_live_rows_and_empty_bank_only_state(self):
        result = self.evaluate('''
          state.entries=[storeEntry('retail',.10,'Ozon'),storeEntry('retail-alias',.20,'Озон'),
            storeEntry('seeds',1,'Банк семян'),storeEntry('bank-service',2,'Уралсиб сервис'),
            storeEntry('not-bank',3,'не Сбербанк'),storeEntry('mts',4,'МТС'),
            storeEntry('ozon-bank',10.01,'Ozon Bank',{category:'Прочее'}),
            storeEntry('t-bank',20.02,'Т-Банк',{category:'Прочее'}),
            storeEntry('yandex',30.03,'Яндекс Сплит',{category:'Прочее'}),
            storeEntry('metadata',40.04,'Финансовый провайдер',{category:'Прочее'}),
            storeEntry('prior',50.05,'Uralsib',{date:'2026-10-05',category:'Прочее'}),
            storeEntry('deleted',999,'Сбербанк'),storeEntry('bad',-2,'Сбербанк'),
            storeEntry('income',999,'Сбербанк',{type:'income'}),
            storeEntry('transfer',999,'Сбербанк',{type:'transfer'}),
            storeEntry('adjustment',999,'Сбербанк',{balanceAdjustment:true})];
          state.deletedEntries={deleted:'2026-11-06T00:00:00.000Z'};
          V96_MERCHANTS.push({brand:'synthetic-bank',value:'Финансовый провайдер',
            aliases:['ФинПровайдер'],sector:'banking'});
          const original=JSON.stringify(state.entries),monthly=v163StoreSpending('2026-11'),all=v163StoreSpending('all');
          v163RenderStoreSpending('analytics','all');const allPeriod=document.getElementById('v163AnalyticsStorePeriod').textContent;
          state.entries=state.entries.filter(row=>row.id==='t-bank');
          v163RenderStoreSpending('home','2026-11');const bankOnly={data:v163StoreSpending('2026-11'),
            text:document.getElementById('v163HomeStoresList').textContent,
            noFooter:!document.getElementById('v163HomeStoreNote')};
          state.entries=[storeEntry('only-shop',1,'Банк семян')];v163RenderStoreSpending('home','2026-11');
          const noBank={noFooter:!document.getElementById('v163HomeStoreNote'),
            noSummary:!document.querySelector('#v163HomeStores .v163-store-summary')};
          const ambiguousNames=['Альфа','Открытие','Халва','Мокка','Mokka','Подели','Долями','Русский Стандарт'];
          state.entries=ambiguousNames.flatMap((name,index)=>[
            storeEntry('retail-'+index,1,name,{category:index%2?'Продукты':'Кафе и доставка'}),
            storeEntry('credit-'+index,10,name,{category:'Кредит'})]);
          const ambiguous=v163StoreSpending('2026-11');
          return {monthly,all,allPeriod,bankOnly,noBank,ambiguous};
        ''')
        self.assertEqual(result['monthly']['total'], 10.30)
        self.assertEqual(result['monthly']['bankExcludedCount'], 4)
        self.assertEqual(result['monthly']['bankExcludedTotal'], 100.10)
        self.assertEqual(result['monthly']['excludedCount'], 1)
        self.assertEqual(result['all']['bankExcludedCount'], 5)
        self.assertEqual(result['all']['bankExcludedTotal'], 150.15)
        self.assertEqual(result['all']['total'], 10.30)
        self.assertEqual(result['allPeriod'], 'За всё время')
        self.assertEqual(result['bankOnly']['data']['total'], 0)
        self.assertEqual(result['bankOnly']['data']['top5'], [])
        self.assertIn('покупок с указанным магазином пока нет', result['bankOnly']['text'])
        self.assertTrue(result['bankOnly']['noFooter'])
        self.assertNotIn('NaN', result['bankOnly']['text'])
        self.assertTrue(result['noBank']['noFooter'])
        self.assertTrue(result['noBank']['noSummary'])
        self.assertEqual(result['ambiguous']['total'], 8)
        self.assertEqual(result['ambiguous']['bankExcludedTotal'], 80)
        self.assertEqual(result['ambiguous']['bankExcludedCount'], 8)
        self.assertEqual({row['name'] for row in result['ambiguous']['rows']},
                         {'Альфа', 'Открытие', 'Халва', 'Мокка', 'Mokka', 'Подели', 'Долями', 'Русский Стандарт'})

    def test_icons_and_text_stay_safe_and_fit_both_cards_in_forty_viewport_states(self):
        self.evaluate('''
          state.entries=[storeEntry('long',123456789.12,'ОченьДлинноеНазвание'.repeat(12)),
            storeEntry('missing',500,''),storeEntry('ikea',400,'IKEA'),
            storeEntry('wb',300,'WB'),storeEntry('unsafe',200,'<img src=x onerror=window.storeIconXss=1>'),
            storeEntry('bank',999999999,'Уралсиб',{category:'Прочее'})];
          renderAll();
        ''')
        widths = [320, 360, 375, 390, 412, 430, 480, 560, 640, 700,
                  760, 820, 920, 1024, 1100, 1101, 1280, 1440, 1680, 1920]
        for width in widths:
            self.page.set_viewport_size({'width': width, 'height': 1000})
            for route, card in [('home', '#v163HomeStores'),
                                ('analytics', '#v163AnalyticsStores')]:
                result = self.evaluate('''
                  go(''' + repr(route) + ''');renderAll();
                  const card=document.querySelector(''' + repr(card) + ''');
                  return {page:document.documentElement.scrollWidth<=innerWidth+1,
                    overflow:[card,...card.querySelectorAll('.v163-store-row,.v163-store-identity,.v163-store-metrics')]
                      .some(node=>node.scrollWidth>node.clientWidth+1),
                    badges:card.querySelectorAll('.v163-store-identity>.v96-merchant-badge').length,
                    badImage:card.querySelector('.v163-store-name img')!==null,
                    ran:!!window.storeIconXss};
                ''')
                with self.subTest(width=width, route=route):
                    self.assertTrue(result['page'])
                    self.assertFalse(result['overflow'])
                    self.assertEqual(result['badges'], 5 if route=='analytics' else 4)
                    self.assertFalse(result['badImage'])
                    self.assertFalse(result['ran'])


if __name__ == '__main__':
    unittest.main()
