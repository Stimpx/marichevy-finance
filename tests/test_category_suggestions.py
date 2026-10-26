"""Purpose-aware categories through the real form; fictional data, no network."""
import argparse
from pathlib import Path
import unittest

import test_local_data_safety as harness


class CategorySuggestions(unittest.TestCase):
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
        self.page.evaluate("""() => {
            session=null;state=blankState();localStorage.clear();
            showApp();clearEntry();openEntry('expense');
        }""")

    def test_digital_description_offers_existing_categories_without_selecting(self):
        self.prepare()
        for query in ('ChatGPT', 'подписка ChatGPT', 'OpenAI', 'чат GPT'):
            with self.subTest(query=query):
                self.page.locator('#v90Search').fill(query)
                result = self.page.evaluate("""() => ({
                    keys:[...document.querySelectorAll('#v90Quick button')].map(b=>b.dataset.cat),
                    selected:eCategory.value,entries:state.entries.length,
                    hint:document.getElementById('v92SearchHint').textContent
                })""")
                self.assertIn('Подписки', result['keys'])
                self.assertIn('Работа', result['keys'])
                self.assertIn(result['keys'][0], ('Подписки', 'Работа'))
                self.assertEqual(result['selected'], '')
                self.assertEqual(result['entries'], 0)
                self.assertIn('выберите', result['hint'].lower())

    def test_mislabeled_history_does_not_outrank_digital_service_or_change_history(self):
        self.prepare()
        result = self.page.evaluate("""() => {
            state.entries=Array.from({length:8},(_,i)=>({id:'fictional-old-'+i,
                type:'expense',date:today(),amount:17.25,category:'Развлечения',
                comment:'подписка ChatGPT',store:'Fictional merchant',unknown:{keep:i}}));
            const before=JSON.stringify(state);
            v90Search.value='подписка ChatGPT';v90Paint();
            return {first:document.querySelector('#v90Quick button').dataset.cat,
                selected:eCategory.value,unchanged:JSON.stringify(state)===before,
                subscriptionGroup:expenseGroup('Подписки'),workGroup:expenseGroup('Работа')};
        }""")
        self.assertIn(result['first'], ('Подписки', 'Работа'))
        self.assertEqual(result['selected'], '')
        self.assertTrue(result['unchanged'])
        # Current analytics separates services and work; saved budget scopes are tested separately.
        self.assertEqual(result['subscriptionGroup'], 'Подписки и сервисы')
        self.assertEqual(result['workGroup'], 'Работа')

    def test_explicit_choice_saves_exact_existing_ids_and_preserves_historical_rows(self):
        self.prepare()
        self.page.evaluate("""() => {
            state.entries=[{id:'fictional-history',type:'expense',date:today(),amount:11,
                category:'Развлечения',comment:'ChatGPT',who:'Fictional historical owner',
                futureField:{preserve:true}}];
            window.__historicalCategorySnapshot=JSON.stringify(state.entries);
        }""")
        for category in ('Подписки', 'Работа'):
            with self.subTest(category=category):
                self.page.locator('#v90Search').fill('подписка ChatGPT')
                button = self.page.locator('#v90Quick button[data-cat="'+category+'"]')
                self.assertEqual(button.count(), 1)
                button.click()
                self.page.locator('#eAmount').fill('1250,50')
                self.page.locator('#eStore').fill('OpenAI')
                self.assertEqual(self.page.locator('#eCategory').input_value(), category)
                self.page.evaluate('addEntry()')
                row = self.page.evaluate("""() => ({category:state.entries.at(-1).category,
                    amount:state.entries.at(-1).amount,store:state.entries.at(-1).store,
                    historicalUnchanged:JSON.stringify(state.entries.slice(0,1))===window.__historicalCategorySnapshot})""")
                self.assertEqual(row, {'category':category,'amount':1250.50,
                                      'store':'OpenAI','historicalUnchanged':True})

    def test_merchant_suggestions_never_replace_explicit_owner_choice(self):
        self.prepare()
        self.page.locator('#eStore').fill('OPENAI')
        self.assertEqual(self.page.locator('#eCategory').input_value(), '')
        self.assertIn(self.page.locator('#v90Quick button').first.get_attribute('data-cat'), ('Подписки', 'Работа'))
        self.assertEqual(self.page.locator('#v90Quick button[data-cat="Подписки"]').count(), 1)
        work = self.page.locator('#v90Quick button[data-cat="Работа"]')
        self.assertEqual(work.count(), 1)
        work.click()
        self.page.locator('#eStore').fill('Fictional leisure merchant')
        self.assertEqual(self.page.locator('#eCategory').input_value(), 'Работа')
        self.assertEqual(self.page.evaluate('state.entries.length'), 0)

    def test_explicit_category_search_and_cinema_keep_their_meaning(self):
        self.prepare()
        result = self.page.evaluate("""() => Object.fromEntries(
            ['Подписки','Работа','кино'].map(q=>[q,v92Matches(q)[0]?.key]))""")
        self.assertEqual(result, {'Подписки':'Подписки','Работа':'Работа','кино':'Развлечения'})

    def test_all_categories_remain_available_for_digital_merchant(self):
        self.prepare()
        self.page.locator('#eStore').fill('OpenAI')
        self.page.locator('#v91All').click()
        for category in ('Подписки', 'Работа', 'Развлечения', 'Продукты'):
            self.assertEqual(self.page.locator('#v90Quick button[data-cat="'+category+'"]').count(), 1)
        self.page.locator('#v90Quick button[data-cat="Развлечения"]').click()
        self.page.locator('#eStore').fill('ChatGPT')
        self.assertEqual(self.page.locator('#eCategory').input_value(), 'Развлечения')

    def test_diaper_products_outrank_wrong_household_history_without_selecting_recipient(self):
        self.prepare()
        self.page.evaluate("""() => {
            state.entries=Array.from({length:8},(_,i)=>({id:'fictional-household-'+i,
                type:'expense',date:today(),amount:13.25,category:'Дом',comment:'подгузники',
                who:'Fictional historical owner',futureField:{keep:i}}));
            window.__diaperHistory=JSON.stringify(state.entries);
        }""")
        for query in ('подгузники','Памперсы','Pampers','пелёнки'):
            with self.subTest(query=query):
                self.page.locator('#v90Search').fill(query)
                result=self.page.evaluate("""() => ({
                    first:document.querySelector('#v90Quick button')?.dataset.cat,
                    selected:eCategory.value,target:eBeneficiary.value,
                    unchanged:JSON.stringify(state.entries)===window.__diaperHistory
                })""")
                self.assertEqual(result,{'first':'Дети','selected':'','target':'Общее','unchanged':True})

    def test_child_goods_choice_saves_existing_id_and_preserves_owner_target_and_history(self):
        self.prepare()
        self.page.evaluate("""() => {
            state.entries=[{id:'fictional-old-diapers',type:'expense',date:today(),amount:13.25,
                category:'Дом',comment:'подгузники',who:'Fictional historical owner',
                futureField:{preserve:true}}];
            window.__diaperHistory=JSON.stringify(state.entries);
        }""")
        self.page.locator('#eBeneficiary').select_option('Сергей')
        self.page.locator('#v90Search').fill('подгузники')
        button=self.page.locator('#v90Quick button[data-cat="Дети"]')
        self.assertEqual(button.count(),1)
        self.assertEqual(button.inner_text(),'Детские товары')
        button.click()
        self.assertEqual(self.page.locator('#eBeneficiary').input_value(),'Сергей')
        self.page.locator('#eAmount').fill('210,35')
        self.page.evaluate('addEntry()')
        result=self.page.evaluate("""() => ({category:state.entries.at(-1).category,
            amount:state.entries.at(-1).amount,beneficiary:state.entries.at(-1).beneficiary,
            historicalUnchanged:JSON.stringify(state.entries.slice(0,1))===window.__diaperHistory})""")
        self.assertEqual(result,{'category':'Дети','amount':210.35,'beneficiary':'Сергей',
                                'historicalUnchanged':True})

    def test_adult_and_pet_diaper_contexts_are_distinct_and_do_not_assign_targets(self):
        self.prepare()
        cases={'подгузники для взрослых':'Аптека и медицина',
               'взрослые памперсы':'Аптека и медицина',
               'пеленки для собак':'Животные',
               'пеленки для кошек':'Животные',
               'пеленки для кота':'Животные',
               'подгузники для взрослой собаки':'Животные'}
        self.page.evaluate("""queries => {
            state.entries=queries.flatMap((q,n)=>Array.from({length:8},(_,i)=>({
                id:'fictional-wrong-purpose-'+n+'-'+i,type:'expense',date:today(),amount:7.25,
                category:'Дом',comment:q,who:'Fictional historical owner'})));
            window.__diaperHistory=JSON.stringify(state.entries);
        }""",list(cases))
        for query,category in cases.items():
            with self.subTest(query=query):
                self.page.locator('#v90Search').fill(query)
                result=self.page.evaluate("""() => ({
                    first:document.querySelector('#v90Quick button')?.dataset.cat,
                    selected:eCategory.value,target:eBeneficiary.value,
                    unchanged:JSON.stringify(state.entries)===window.__diaperHistory
                })""")
                self.assertEqual(result,{'first':category,'selected':'','target':'Общее','unchanged':True})

    def test_household_goods_keep_their_category_and_child_goods_are_manually_available(self):
        self.prepare()
        for query in ('стиральный порошок','туалетная бумага','швабра'):
            with self.subTest(query=query):
                self.page.locator('#v90Search').fill(query)
                self.assertEqual(self.page.locator('#v90Quick button').first.get_attribute('data-cat'),'Дом')
                self.assertEqual(self.page.locator('#eCategory').input_value(),'')
        self.page.locator('#v91All').click()
        self.assertEqual(self.page.locator('#v90Quick button[data-cat="Дети"]').count(),1)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--html',type=Path)
    args,remaining=parser.parse_known_args()
    if args.html:
        harness.HTML=args.html.resolve()
    unittest.main(argv=[__file__,*remaining])
