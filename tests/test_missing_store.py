"""Analytics-only unassigned merchants retain exact expense identity and edit scope."""
import unittest
import test_store_spending as store_base


class MissingStore(unittest.TestCase):
    setUpClass = classmethod(store_base.StoreSpending.setUpClass.__func__)
    tearDownClass = classmethod(store_base.StoreSpending.tearDownClass.__func__)
    setUp = store_base.StoreSpending.setUp
    tearDown = store_base.StoreSpending.tearDown
    evaluate = store_base.StoreSpending.evaluate

    def test_missing_row_first_only_in_analytics_and_named_totals_and_global_history_unchanged(self):
        result = self.evaluate('''
          state.entries=[storeEntry('blank',10,''),storeEntry('spaces',20,'  '),
            storeEntry('placeholder',30,' БЕЗ МАГАЗИНА '),storeEntry('missing',40,undefined),
            storeEntry('null',50,null),storeEntry('non-string',60,42),
            storeEntry('old',70,'',{date:'2026-10-05'}),
            storeEntry('named',100,'missing-store'),storeEntry('named-text',11,'Без магазина №1'),
            storeEntry('bank',1000,'',{category:'Кредит'}),
            storeEntry('installment',2000,'',{installmentPartId:'part'}),
            storeEntry('income',3000,'',{type:'income'}),
            storeEntry('adjustment',4000,'',{balanceAdjustment:true}),
            storeEntry('deleted',5000,''),storeEntry('invalid',6000,'',{date:'2026-11-31'})];
          state.deletedEntries={deleted:'2026-11-06T00:00:00.000Z'};
          const before=JSON.stringify({state,month:v111MonthBalance('2026-11'),
            all:sum(v130AnalyticsExpenses('all')),categories:v165CategorySpending('all')});
          const named=v163StoreSpending('2026-11'),missing=v163StoreSpending('2026-11','missing-store');
          go('analytics');renderAll();
          const row=document.querySelector('#v163AnalyticsStoresList button');
          return {named,ids:missing.entries.map(e=>e.id).sort(),
            allIds:v163StoreSpending('all','missing-store').entries.map(e=>e.id).sort(),
            distinct:v163StoreSpending('all','store:missing-store').entries.map(e=>e.id),
            home:storeNames('#v163HomeStoresList'),analytics:storeNames('#v163AnalyticsStoresList'),
            widths:[...document.querySelectorAll('#v163AnalyticsStoresList .v163-store-bar>span')].map(e=>parseFloat(e.style.width)),
            first:{key:row.dataset.v163StoreKey,amount:row.querySelector('.v163-store-amount').textContent,
              mark:row.querySelector('[data-merchant-mark]').dataset.merchantMark,
              brand:row.querySelector('[data-merchant-mark]').dataset.merchantBrand||'',
              icon:row.querySelectorAll('svg').length,shareHint:row.querySelector('.v163-store-share').title},
            unchanged:before===JSON.stringify({state,month:v111MonthBalance('2026-11'),
              all:sum(v130AnalyticsExpenses('all')),categories:v165CategorySpending('all')})};
        ''')
        self.assertEqual(result['ids'], ['blank','missing','non-string','null','placeholder','spaces'])
        self.assertEqual(result['allIds'], ['blank','missing','non-string','null','old','placeholder','spaces'])
        self.assertEqual(result['distinct'], ['named'])
        self.assertEqual((result['named']['total'],result['named']['count'],result['named']['unknownTotal']), (111,2,210))
        self.assertAlmostEqual(sum(row['share'] for row in result['named']['rows']),100)
        self.assertEqual(result['home'],['missing-store','Без магазина No1'])
        self.assertEqual(result['analytics'],['Без магазина','missing-store','Без магазина No1'])
        self.assertEqual(result['first']['key'],'missing-store');self.assertEqual(result['first']['amount'],'210,00 ₽')
        self.assertEqual((result['first']['mark'],result['first']['brand'],result['first']['icon']),('missing','',1))
        self.assertIn('включая расходы без магазина',result['first']['shareHint'])
        self.assertAlmostEqual(sum(result['widths']),100,places=3)
        self.assertAlmostEqual(result['widths'][0],210/321*100,places=3)
        self.assertTrue(result['unchanged'])

    def test_real_first_row_opens_exact_missing_month_and_all_records_not_text_search(self):
        result=self.evaluate('''
          state.entries=[storeEntry('missing',10,''),storeEntry('old',20,null,{date:'2026-10-05'}),
            storeEntry('similar',30,'Без магазина №1'),storeEntry('comment',40,'Ozon',{comment:'Без магазина'}),
            storeEntry('bank',100,'',{category:'Кредит'})];
          go('analytics');renderAll();
          const read=()=>({mode:v96DrillContext.mode,key:v96DrillContext.key,
            scope:v96DrillContext.scope,title:document.getElementById('v84DrillTitle').textContent,
            total:document.getElementById('v96DrillTotal').textContent,
            ids:[...document.querySelectorAll('#v84DrillEntries [data-v141-operation-id]')].map(e=>e.dataset.v141OperationId).sort()});
          document.querySelector('#v163AnalyticsStoresList button').click();const monthly=read();v84CloseDrill();
          document.getElementById('analyticsScope').value='all';v130AnalyticsScopeChanged();
          document.querySelector('#v163AnalyticsStoresList button').click();const all=read();
          return {monthly,all};
        ''')
        self.assertEqual(result['monthly'],{'mode':'store','key':'missing-store','scope':'month','title':'Без магазина','total':'10,00 ₽','ids':['missing']})
        self.assertEqual(result['all'],{'mode':'store','key':'missing-store','scope':'all','title':'Без магазина','total':'30,00 ₽','ids':['missing','old']})

    def test_edit_missing_to_named_reflows_both_periods_and_keeps_empty_all_drill_title(self):
        result=self.evaluate('''
          state.entries=[storeEntry('missing',10,''),storeEntry('old',20,'',{date:'2026-10-05'})];
          document.getElementById('analyticsScope').value='all';go('analytics');renderAll();
          document.querySelector('#v163AnalyticsStoresList button').click();
          const read=()=>({key:v96DrillContext.key,scope:v96DrillContext.scope,
            title:document.getElementById('v84DrillTitle').textContent,
            total:document.getElementById('v96DrillTotal').textContent,
            count:Number(document.getElementById('v96DrillCount').textContent)});
          v96EditFromDrill('missing');document.getElementById('xStore').value='WB';await saveEdit();const first=read();
          const intermediate={names:storeNames('#v163AnalyticsStoresList'),monthlyMissing:v163StoreSpending('2026-11','missing-store').entries.length};
          v96EditFromDrill('old');document.getElementById('xStore').value='ВБ';await saveEdit();const empty=read();
          const final={names:storeNames('#v163AnalyticsStoresList'),data:v163StoreSpending('all'),allScope:document.getElementById('analyticsScope').value};
          v84CloseDrill();return {first,intermediate,empty,final,amounts:state.entries.map(e=>e.amount)};
        ''')
        self.assertEqual(result['first'],{'key':'missing-store','scope':'all','title':'Без магазина','total':'20,00 ₽','count':1})
        self.assertEqual(result['intermediate'],{'names':['Без магазина','Wildberries'],'monthlyMissing':0})
        self.assertEqual(result['empty'],{'key':'missing-store','scope':'all','title':'Без магазина','total':'0,00 ₽','count':0})
        self.assertEqual(result['final']['names'],['Wildberries']);self.assertEqual(result['final']['data']['total'],30)
        self.assertEqual(result['final']['data']['unknownCount'],0);self.assertEqual(result['final']['allScope'],'all');self.assertEqual(result['amounts'],[10,20])

    def test_delete_and_undo_return_to_the_same_monthly_missing_group(self):
        result=self.evaluate('''
          state.entries=[storeEntry('missing',12.34,''),storeEntry('old',20,'',{date:'2026-10-05'})];
          go('analytics');renderAll();document.querySelector('#v163AnalyticsStoresList button').click();
          v96DeleteFromDrill('missing');await Promise.resolve();await Promise.resolve();
          const empty={scope:v96DrillContext.scope,title:document.getElementById('v84DrillTitle').textContent,
            count:document.getElementById('v96DrillCount').textContent,names:storeNames('#v163AnalyticsStoresList')};
          const undo=await v119UndoDelete();v96RestoreDrill({...v96DrillContext},'',true);
          return {empty,undo,restored:{scope:v96DrillContext.scope,title:document.getElementById('v84DrillTitle').textContent,
            total:document.getElementById('v96DrillTotal').textContent,count:document.getElementById('v96DrillCount').textContent,
            names:storeNames('#v163AnalyticsStoresList')}};
        ''')
        self.assertEqual(result['empty'],{'scope':'month','title':'Без магазина','count':'0','names':[]});self.assertTrue(result['undo'])
        self.assertEqual(result['restored'],{'scope':'month','title':'Без магазина','total':'12,34 ₽','count':'1','names':['Без магазина']})

    def test_only_missing_is_one_hundred_percent_and_empty_bank_only_is_neutral(self):
        result=self.evaluate('''
          state.entries=[storeEntry('missing',.01,''),storeEntry('bank',999,'',{category:'Кредит'})];
          go('analytics');renderAll();const row=document.querySelector('#v163AnalyticsStoresList button');
          const only={names:storeNames('#v163AnalyticsStoresList'),share:row.querySelector('.v163-store-share').textContent,
            width:row.querySelector('.v163-store-bar>span').style.width,home:storeNames('#v163HomeStoresList')};
          state.entries=state.entries.filter(e=>e.id==='bank');renderAll();
          const empty={names:storeNames('#v163AnalyticsStoresList'),text:document.getElementById('v163AnalyticsStoresList').textContent};
          v84Drill('store','missing-store','analytics');return {only,empty,title:document.getElementById('v84DrillTitle').textContent,count:document.getElementById('v96DrillCount').textContent};
        ''')
        self.assertEqual(result['only'],{'names':['Без магазина'],'share':'100%','width':'100%','home':[]})
        self.assertEqual(result['empty']['names'],[]);self.assertNotRegex(result['empty']['text'],'NaN|Infinity')
        self.assertEqual((result['title'],result['count']),('Без магазина','0'))

    def test_missing_row_keyboard_and_geometry_fit_phone_tablet_and_desktop(self):
        self.evaluate("state.entries=[storeEntry('missing',12.34,''),storeEntry('named',20,'Ozon')];go('analytics');renderAll();")
        for width in [320,390,768,1024,1440,1920]:
            self.page.set_viewport_size({'width':width,'height':1000})
            self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth>document.documentElement.clientWidth+1'),width)
            self.assertFalse(self.page.locator('#v163AnalyticsStoresList').evaluate('e=>e.scrollWidth>e.clientWidth+1'),width)
            row=self.page.locator('#v163AnalyticsStoresList [data-v163-store-key="missing-store"]')
            self.assertGreaterEqual(row.bounding_box()['height'],44)
        row.focus();row.press('Enter')
        self.assertEqual(self.page.locator('#v84DrillTitle').inner_text(),'Без магазина')
        self.page.keyboard.press('Escape');self.assertTrue(row.evaluate('e=>document.activeElement===e'))


if __name__=='__main__':unittest.main()
