"""Preserve arbitrary historical targets and exact cents in recipient scales."""
import json
import unittest

import test_local_data_safety as harness


class TargetTotalsPrecision(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.LocalDataSafety.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        harness.LocalDataSafety.tearDownClass.__func__(cls)

    setUp = harness.LocalDataSafety.setUp
    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open

    def test_legacy_names_cannot_hide_expenses_through_object_prototype_keys(self):
        self.open()
        result = self.page.evaluate("""() => {
          const rows=['__proto__','constructor','toString','Обычный участник'].map((beneficiary,i)=>({
            id:'fictional-target-'+i,type:'expense',amount:0.1+i,beneficiary,who:'',category:'Продукты'}));
          const before=JSON.stringify(rows),actual=v86TargetTotals(rows);
          return {actual,total:sum(actual.map(([,amount])=>({amount}))),
            expected:sum(rows),unchanged:JSON.stringify(rows)===before};
        }""")
        actual = dict(result['actual'])
        self.assertEqual(actual['__proto__'], 0.1)
        self.assertEqual(actual['constructor'], 1.1)
        self.assertEqual(actual['toString'], 2.1)
        self.assertEqual(result['total'], result['expected'])
        self.assertTrue(result['unchanged'])

    def test_cents_are_exact_and_unusual_legacy_subcents_are_not_rounded(self):
        self.open()
        result = self.page.evaluate("""() => {
          const rows=[{amount:.1,beneficiary:'Первый'},{amount:.2,beneficiary:'Первый'},
            {amount:.001,beneficiary:'Старый'},{amount:.002,beneficiary:'Старый'}];
          const before=JSON.stringify(rows);
          return {totals:Object.fromEntries(v86TargetTotals(rows)),unchanged:JSON.stringify(rows)===before};
        }""")
        self.assertEqual(result['totals']['Первый'], 0.3)
        self.assertEqual(result['totals']['Старый'], 0.003)
        self.assertTrue(result['unchanged'])


    def test_custom_prototype_name_updates_donut_and_home_focus_without_rewriting_rows(self):
        self.open()
        self.page.evaluate("""() => {
          session=null;stopCloudSync();state=blankState();localStorage.clear();
          state.settings.preferences.futurePreference={preserve:[true,null,'fictional']};
          weatherCache.data={temperature_2m:10,weather_code:0};weatherCache.at=Date.now();
          state.entries=[{id:'fictional-before-one',type:'expense',date:today(),amount:10,
            category:'Продукты',beneficiary:'Сергей'},
            {id:'fictional-before-two',type:'expense',date:today(),amount:20,
            category:'Продукты',beneficiary:'Виктория'}];
          showApp();renderAll();window.__oldDonut=document.getElementById('peopleDonut').style.background;
          window.__rowsBeforeCustom=JSON.stringify(state.entries);
          v99OpenDirectionEditor('home');
        }""")
        self.page.locator('#v99DirectionName-home').fill('hasOwnProperty')
        self.assertTrue(self.page.evaluate("v99SubmitDirectionEditor('home')"))
        self.assertTrue(self.page.evaluate('JSON.stringify(state.entries)===window.__rowsBeforeCustom'))
        result=self.page.evaluate("""() => {
          state.entries=[{id:'fictional-custom-target',type:'expense',date:today(),amount:1.23,
            category:'ЖКХ',subcategory:'Электричество',beneficiary:'hasOwnProperty',who:'',
            unknownField:{keep:[true,null,'unchanged']}}];
          const before=JSON.stringify(state.entries);renderAll();v81SetFocus('home');
          const after=document.getElementById('peopleDonut').style.background;
          return {donutChanged:after!==window.__oldDonut,donutValid:CSS.supports('background',after),
            donutSingleColor:after.includes('rgb(105, 134, 191) 0deg')&&after.includes('360deg'),
            colors:['hasOwnProperty','toLocaleString','__defineGetter__'].map(key=>({
              person:typeof v84PersonColor(key),group:typeof v84GroupColor(key),
              valid:CSS.supports('color',v84PersonColor(key))&&CSS.supports('color',v84GroupColor(key))})),
            overview:document.getElementById('aPeopleChart').textContent,
            focus:document.getElementById('v81LifePeople').textContent,
            focusTotal:document.querySelector('#v81LifeSummary strong').textContent,
            customLabel:document.querySelector('#v99HomeDirectionTiles [data-v99-direction="custom:hasOwnProperty"]').textContent,
            unchanged:JSON.stringify(state.entries)===before,
            unknownPreference:state.settings.preferences.futurePreference};
        }""")
        self.assertTrue(result['donutChanged'])
        self.assertTrue(result['donutValid'])
        self.assertTrue(result['donutSingleColor'])
        self.assertTrue(all(color == {'person':'string','group':'string','valid':True}
                            for color in result['colors']))
        for field in ('overview','focus','customLabel'):
            self.assertIn('hasOwnProperty',result[field])
            self.assertIn('1,23',result[field])
        self.assertIn('1,23',result['focusTotal'])
        self.assertTrue(result['unchanged'])
        self.assertEqual(result['unknownPreference'],{'preserve':[True,None,'fictional']})

    def test_generic_aggregate_preserves_arbitrary_keys_exact_cents_and_legacy_subcents(self):
        self.open()
        result=self.page.evaluate("""() => {
          const amounts=[['__proto__',.1],['__proto__',.2],['constructor',1.01],
            ['constructor',2.02],['toString',.001],['toString',.002],
            ['hasOwnProperty',10.25],['hasOwnProperty',.25],['<b>Учебное имя</b>',.09],
            ['',.4],['',.5]];
          const rows=amounts.map(([value,amount],i)=>({id:'fictional-aggregate-'+i,value,amount,
            unknownField:{keep:[true,null,i]}}));
          const before=JSON.stringify(rows),totals=aggregate(rows,'value');
          return {totalsJSON:JSON.stringify(totals),keys:Object.keys(totals),
            allNumeric:Object.values(totals).every(value=>typeof value==='number'&&Number.isFinite(value)),
            unchanged:JSON.stringify(rows)===before};
        }""")
        self.assertEqual(json.loads(result['totalsJSON']),{'__proto__':.3,'constructor':3.03,'toString':.003,
                                          'hasOwnProperty':10.5,'<b>Учебное имя</b>':.09,'Не указано':.9})
        self.assertEqual(len(result['keys']),6)
        self.assertTrue(result['allNumeric'])
        self.assertTrue(result['unchanged'])


if __name__ == '__main__':
    unittest.main()
