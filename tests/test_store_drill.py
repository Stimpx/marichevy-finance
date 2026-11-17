"""Store buttons open exactly the ranked named purchases and retain CRUD scope."""
import unittest

import test_store_spending as store_base


class StoreDrill(unittest.TestCase):
    setUpClass = classmethod(store_base.StoreSpending.setUpClass.__func__)
    tearDownClass = classmethod(store_base.StoreSpending.tearDownClass.__func__)
    setUp = store_base.StoreSpending.setUp
    tearDown = store_base.StoreSpending.tearDown
    evaluate = store_base.StoreSpending.evaluate

    def test_missing_stores_never_take_a_top_five_place_or_share_denominator(self):
        result = self.evaluate('''
          state.entries=[storeEntry('blank',100000,''),storeEntry('spaces',200000,'  '),
            storeEntry('placeholder',50000,'  БЕЗ МАГАЗИНА  '),
            storeEntry('bank',900000,'УралСиб',{category:'Прочее'}),
            ...[60,50,40,30,20,10].map((amount,i)=>storeEntry('named-'+i,amount,'Магазин '+i))];
          const before=JSON.stringify(state),data=v163StoreSpending('2026-11');
          renderAll();go('analytics');const analyticsNames=storeNames('#v163AnalyticsStoresList');
          document.querySelector('#v163AnalyticsStoresList button:last-child').click();
          return {data,names:storeNames('#v163HomeStoresList'),analyticsNames,
            lastStore:{title:document.getElementById('v84DrillTitle').textContent,
              count:Number(document.getElementById('v96DrillCount').textContent),
              total:Number(document.getElementById('v96DrillTotal').textContent.replace(/[^0-9,.-]/g,'').replace(',','.'))},
            analyticsHeading:document.getElementById('v163AnalyticsStoreTitle').textContent,
            missing:document.querySelectorAll('#v163HomeStoresList [data-merchant-mark="missing"]').length,
            noSummaryOrFooter:!document.querySelector('#v163HomeStores .v163-store-summary,#v163HomeStoreNote,#v163AnalyticsStoreNote'),
            unchanged:JSON.stringify(state)===before};
        ''')
        self.assertEqual(result['data']['total'], 210)
        self.assertEqual(result['data']['count'], 6)
        self.assertEqual(result['data']['unknownTotal'], 350000)
        self.assertEqual(result['data']['bankExcludedTotal'], 900000)
        self.assertEqual(result['names'], ['Магазин '+str(i) for i in range(5)])
        self.assertEqual(result['analyticsNames'], ['Магазин '+str(i) for i in range(6)])
        self.assertEqual(result['lastStore'], {'title': 'Магазин 5', 'count': 1, 'total': 10})
        self.assertEqual(result['analyticsHeading'], 'Расходы по магазинам')
        self.assertAlmostEqual(sum(row['share'] for row in result['data']['rows']), 100)
        self.assertEqual(result['missing'], 0)
        self.assertTrue(result['noSummaryOrFooter'])
        self.assertTrue(result['unchanged'])

    def test_actual_store_buttons_keep_canonical_aliases_and_exact_month_or_all_scope(self):
        result = self.evaluate('''
          state.entries=[storeEntry('a',10,'WB'),storeEntry('b',20,'ВБ'),
            storeEntry('old',5,'Wildberries',{date:'2026-10-05'}),
            storeEntry('tail',7,'Wildberries сервис'),storeEntry('blank',1000,''),
            storeEntry('loan',2000,'WB',{category:'Кредит'}),
            storeEntry('income',3000,'WB',{type:'income'}),storeEntry('deleted',4000,'WB')];
          state.deletedEntries={deleted:'2026-11-06T00:00:00.000Z'};renderAll();
          const open=(source,period,key='store:wildberries')=>{
            if(source==='home'){document.getElementById('homeMonth').value=period;go('home');renderHome()}
            else{document.getElementById('analyticsScope').value=period==='all'?'all':'month';
              if(period!=='all')document.getElementById('analyticsMonth').value=period;go('analytics');renderAnalytics()}
            const prefix=source==='home'?'v163Home':'v163Analytics';
            [...document.querySelectorAll('#'+prefix+'StoresList button')].find(button=>button.dataset.v163StoreKey===key).click();
            const result={source:v96DrillContext.source,scope:v96DrillContext.scope,
              month:v96DrillContext.month,count:Number(document.getElementById('v96DrillCount').textContent),
              total:Number(document.getElementById('v96DrillTotal').textContent.replace(/[^0-9,.-]/g,'').replace(',','.')),
              title:document.getElementById('v84DrillTitle').textContent};v84CloseDrill();return result;
          };
          return {home:open('home','2026-11'),homeAll:open('home','all'),
            october:open('analytics','2026-10'),analyticsAll:open('analytics','all'),
            distinct:open('analytics','all','store:wildberries сервис')};
        ''')
        self.assertEqual((result['home']['scope'], result['home']['count'], result['home']['total']), ('month', 2, 30))
        self.assertEqual((result['homeAll']['scope'], result['homeAll']['count'], result['homeAll']['total']), ('all', 3, 35))
        self.assertEqual((result['october']['month'], result['october']['count'], result['october']['total']), ('2026-10', 1, 5))
        self.assertEqual((result['analyticsAll']['source'], result['analyticsAll']['scope'], result['analyticsAll']['total']), ('analytics', 'all', 35))
        self.assertEqual(result['analyticsAll']['title'], 'Wildberries')
        self.assertEqual((result['distinct']['count'], result['distinct']['total']), (1, 7))

    def test_store_drill_edit_delete_empty_and_undo_preserve_the_store_identity(self):
        result = self.evaluate('''
          state.entries=[storeEntry('a',10,'WB'),storeEntry('b',20,'ВБ'),
            storeEntry('old',5,'Wildberries',{date:'2026-10-05'})];
          document.getElementById('analyticsScope').value='all';renderAll();go('analytics');
          document.querySelector('#v163AnalyticsStoresList button').click();
          const read=()=>({mode:v96DrillContext.mode,scope:v96DrillContext.scope,
            title:document.getElementById('v84DrillTitle').textContent,
            count:Number(document.getElementById('v96DrillCount').textContent),
            total:Number(document.getElementById('v96DrillTotal').textContent.replace(/[^0-9,.-]/g,'').replace(',','.'))});
          v96EditFromDrill('a');document.getElementById('xAmount').value='15';
          document.getElementById('xStore').value='WB сервис';await saveEdit();const edit=read();
          v96DeleteFromDrill('b');await Promise.resolve();await Promise.resolve();const deleted=read();
          v96DeleteFromDrill('old');await Promise.resolve();await Promise.resolve();const empty=read();
          const undo=await v119UndoDelete();v96RestoreDrill({...v96DrillContext},'',true);
          return {edit,deleted,empty,undo,restored:read(),
            currentMerchant:state.entries.find(entry=>entry.id==='a').store,
            eligible:v163StoreSpending('all','store:wildberries').entries.map(entry=>entry.id)};
        ''')
        self.assertEqual((result['edit']['mode'], result['edit']['scope'], result['edit']['total']), ('store', 'all', 25))
        self.assertEqual((result['deleted']['count'], result['deleted']['total']), (1, 5))
        self.assertEqual((result['empty']['title'], result['empty']['count'], result['empty']['total']), ('Wildberries', 0, 0))
        self.assertTrue(result['undo'])
        self.assertEqual((result['restored']['count'], result['restored']['total']), (1, 5))
        self.assertEqual(result['currentMerchant'], 'WB сервис')
        self.assertEqual(result['eligible'], ['old'])


if __name__ == '__main__':
    unittest.main()
