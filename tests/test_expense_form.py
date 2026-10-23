"""PR4 expense form regressions; synthetic state, no outbound connections."""
import argparse
from pathlib import Path
import unittest

import test_local_data_safety as harness


class ExpenseForm(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.LocalDataSafety.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        harness.LocalDataSafety.tearDownClass.__func__(cls)

    setUp = harness.LocalDataSafety.setUp
    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open

    def prepare(self):
        self.open()
        self.page.evaluate("""() => {session=null;state=blankState();localStorage.clear();
            showApp();
            clearEntry();openEntry('expense');}""")

    def test_defaults_and_four_fields_in_order(self):
        self.prepare()
        result=self.page.evaluate("""() => ({date:eDate.value,today:today(),target:eBeneficiary.value,
            people:[...eBeneficiary.options].map(x=>[x.value,x.textContent]),
            order:[...document.querySelector('.v91-form').children].slice(1,5).map(x=>x.querySelector('input,select').id),
            merchantOutsideDetails:!eStore.closest('details'),detailsOpen:v90Extra.open})""")
        self.assertEqual(result['date'],result['today'])
        self.assertEqual(result['target'],'Общее')
        self.assertEqual(result['people'], [[x,x] for x in ['Общее','Сергей','Виктория','Алиса','Майя','Дени','Макс']])
        self.assertEqual(result['order'],['eAmount','v90Search','eBeneficiary','eStore'])
        self.assertTrue(result['merchantOutsideDetails'])
        self.assertFalse(result['detailsOpen'])

    def test_quick_control_cases_use_existing_ids_and_details(self):
        self.prepare()
        expected=[('Вкусняшки','Вкусняшки',''),('Школьное питание','Школа и занятия','Школьное питание'),
                  ('Английский','Школа и занятия','Английский язык'),('Танцы','Школа и занятия','Танцы'),
                  ('Корм питомцу','Животные','Корм'),('Подарок','Подарки',''),
                  ('Ресторан','Рестораны и кафе','Ресторан'),('Чаевые','Рестораны и кафе','')]
        for label,category,detail in expected:
            with self.subTest(label=label):
                self.page.locator('#v90Quick button').filter(has_text=label).click()
                self.assertEqual(self.page.locator('#eCategory').input_value(),category)
                self.assertEqual(self.page.locator('#eSubcategory').input_value(),detail)
                self.assertEqual(self.page.locator('#eBeneficiary').input_value(),'Общее')

    def test_search_recognizes_every_control_case(self):
        self.prepare()
        result=self.page.evaluate("""() => Object.fromEntries(['жвачка','чипсы','школьное питание','английский','танцы','корм','подарок','ресторан','чаевые'].map(q=>[q,v92Matches(q)[0]?.key]))""")
        self.assertEqual(result,{'жвачка':'Вкусняшки','чипсы':'Вкусняшки','школьное питание':'Школа и занятия',
            'английский':'Школа и занятия','танцы':'Школа и занятия','корм':'Животные',
            'подарок':'Подарки','ресторан':'Рестораны и кафе','чаевые':'Рестораны и кафе'})

    def test_same_snacks_category_saves_independent_recipients_without_rewriting_history(self):
        self.prepare()
        result=self.page.evaluate("""async () => {
            const old={id:'fictional-old',type:'expense',date:today(),amount:3,category:'Вкусняшки',who:'Виктория'};
            state.entries=[old];const before=JSON.stringify(old);
            for(const target of ['Алиса','Сергей']){eAmount.value=17;v90Choose('Вкусняшки');eBeneficiary.value=target;await addEntry()}
            return {oldUnchanged:JSON.stringify(state.entries[0])===before,
                rows:state.entries.slice(1).map(e=>({category:e.category,target:e.beneficiary,amount:e.amount}))};
        }""")
        self.assertTrue(result['oldUnchanged'])
        self.assertEqual(result['rows'],[{'category':'Вкусняшки','target':target,'amount':17} for target in ['Алиса','Сергей']])

    def test_russian_decimal_and_grouping_preserve_kopecks(self):
        self.prepare()
        for text in ['1 250,50','1\u00a0250,50','1250.50']:
            with self.subTest(text=text):
                self.page.locator('#eAmount').fill(text)
                self.page.evaluate("v90Choose('Продукты')")
                self.page.evaluate('addEntry()')
                self.assertEqual(self.page.evaluate('state.entries.at(-1).amount'),1250.50)
        self.page.locator('#eAmount').fill('12,345')
        count=self.page.evaluate('state.entries.length')
        self.page.evaluate('addEntry()')
        self.assertEqual(self.page.evaluate('state.entries.length'),count)
        self.assertIn('сумм',self.page.locator('#saveMsg').inner_text())

    def test_income_and_transfer_still_save(self):
        self.prepare()
        self.page.evaluate("openEntry('income')")
        self.assertFalse(self.page.locator('#eStore').is_visible())
        self.assertFalse(self.page.locator('#v90Search').is_visible())
        self.assertTrue(self.page.locator('#eIncomeSource').is_visible())
        result=self.page.evaluate("""async () => {
            openEntry('income');eAmount.value=100;eWho.value='Виктория';eIncomeSource.value='Fictional income';await addEntry();
            openEntry('transfer');eAmount.value=20;eFrom.value='Карта';eTo.value='Накопления';await addEntry();
            return state.entries.map(e=>({type:e.type,who:e.who,store:e.store,from:e.from,to:e.to}));
        }""")
        self.assertEqual(result,[{'type':'income','who':'Виктория','store':'Fictional income','from':'','to':''},
                                 {'type':'transfer','who':'Общее','store':'','from':'Карта','to':'Накопления'}])

    def test_edit_preserves_unknown_historical_category_and_beneficiary(self):
        self.prepare()
        result=self.page.evaluate("""async () => {
            const old={id:'fictional-legacy',type:'expense',date:today(),amount:31,category:'Fictional legacy category',
                subcategory:'Fictional detail',beneficiary:'Fictional recipient',who:'Сергей',store:'Fictional store',comment:'Fictional note'};
            state.entries=[old];openEdit(old.id);
            return {category:xCat.value,detail:xSubcategory.value,target:xBeneficiary.value};
        }""")
        self.assertEqual(result,{'category':'Fictional legacy category','detail':'Fictional detail','target':'Fictional recipient'})

    def test_desktop_and_mobile_fields_fit_and_merchant_visible(self):
        self.prepare()
        for width in [1280,390,320]:
            with self.subTest(width=width):
                self.page.set_viewport_size({'width':width,'height':844})
                fields=self.page.evaluate("""() => ['eAmount','v90Search','eBeneficiary','eStore','v90Save'].map(id=>{
                    const r=document.getElementById(id).getBoundingClientRect();return {id,left:r.left,right:r.right,width:r.width,visible:!!r.height}})""")
                for field in fields:
                    self.assertTrue(field['visible'],field)
                    self.assertGreater(field['width'],0,field)
                    self.assertGreaterEqual(field['left'],0,field)
                    self.assertLessEqual(field['right'],width+1,field)
                if width<=600:
                    save=self.page.locator('#v90Save').bounding_box()
                    self.assertLessEqual(save['y']+save['height'],844-80)
                    self.assertTrue(self.page.locator('#v90Save').evaluate("node=>{const r=node.getBoundingClientRect();return node.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}"))


if __name__=='__main__':
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--html',type=Path)
    args,remaining=parser.parse_known_args()
    if args.html:
        harness.HTML=args.html.resolve()
    unittest.main(argv=[__file__,*remaining])
