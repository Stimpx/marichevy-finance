"""Family category rules through the browser; fictional rows and no external requests."""
import json
import unittest

import test_local_data_safety as harness


class WifeCategories(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.LocalDataSafety.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        harness.LocalDataSafety.tearDownClass.__func__(cls)

    setUp = harness.LocalDataSafety.setUp
    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open
    snapshot = harness.LocalDataSafety.snapshot

    def prepare(self):
        self.open()
        self.page.evaluate("""()=>{
          session=null;stopCloudSync();state=blankState();localStorage.clear();showApp();
          clearEntry();openEntry('expense');
          window.wifeRow=(id,fields={})=>({id,type:'expense',date:today(),amount:12.34,
            category:'Аптека и медицина',beneficiary:'Виктория',who:'Original author',
            comment:'Пилатес',subcategory:'',store:'Fictional pharmacy',
            updated_at:'2020-01-01T00:00:00Z',unknown:{keep:[null,true,id]},...fields});
        }""")

    def test_two_named_categories_are_available_to_both_people_and_others(self):
        self.prepare()
        actual = self.page.evaluate("""()=>{
          const result={};for(const person of ['Сергей','Виктория','Алиса','Майя','Дени']){
            eBeneficiary.value=person;v91Expanded=true;v90Paint();
            result[person]=[...document.querySelectorAll('#v90Quick button')]
              .filter(b=>['Аптека и медицина','Спорт и здоровье'].includes(b.dataset.cat))
              .map(b=>[b.dataset.cat,b.textContent.trim()]);
          }return result;
        }""")
        for choices in actual.values():
            self.assertEqual(choices, [['Аптека и медицина', 'Медицина и аптеки'],
                                       ['Спорт и здоровье', 'Спорт и здоровье']])

    def test_purchase_purpose_beats_wrong_history_without_changing_or_selecting_records(self):
        self.prepare()
        cases = {'Пилатес':'Спорт и здоровье', 'Фитнес':'Спорт и здоровье',
                 'Витамин D':'Спорт и здоровье', 'БАДы в аптеке':'Спорт и здоровье',
                 'Очки':'Аптека и медицина', 'Лекарства':'Аптека и медицина',
                 'Приём врача':'Аптека и медицина', 'Анализы':'Аптека и медицина',
                 'Оплата хостинга':'Подписки', 'Продление домена':'Подписки',
                 'Такси домой':'Транспорт'}
        for query, expected in cases.items():
            with self.subTest(query=query):
                result = self.page.evaluate("""q=>{
                  state.entries=Array.from({length:8},(_,i)=>wifeRow('history-'+i,
                    {comment:q,category:q==='Пилатес'?'Аптека и медицина':'Прочее'}));
                  const before=JSON.stringify(state);eCategory.value='';v90Search.value=q;v90Paint();
                  return {key:document.querySelector('#v90Quick button').dataset.cat,
                    selected:eCategory.value,unchanged:before===JSON.stringify(state)};
                }""", query)
                self.assertEqual(result, {'key':expected, 'selected':'', 'unchanged':True})

    def test_pharmacy_and_ambiguous_mixed_description_are_not_reclassified(self):
        self.prepare()
        result = self.page.evaluate("""()=>({
          storeOnly:v98CategoryReviewSignal(wifeRow('a',{comment:'',store:'Пилатес аптека'})),
          mixed:v98CategoryReviewSignal(wifeRow('b',{comment:'Витамины и лекарства'})),
          unknown:v98CategoryReviewSignal(wifeRow('c',{comment:'Покупка для здоровья'})),
          known:v99PurposeCategory(wifeRow('d')),
          alias:v99PurposeCategory({category:'Медицина и аптеки'}),
          foreign:v99PurposeCategory({category:'Своя категория <script>'})
        })""")
        self.assertEqual(result, {'storeOnly':None, 'mixed':None, 'unknown':None,
                                 'known':'Аптека и медицина', 'alias':'Аптека и медицина',
                                 'foreign':'Своя категория <script>'})

    def test_known_old_taxi_categories_are_already_valid_and_do_not_get_false_review(self):
        self.prepare()
        actual = self.page.evaluate("""()=>{
          const rows=[wifeRow('taxi',{category:'Такси',comment:'Такси'}),
            wifeRow('broad',{category:'Авто и транспорт',subcategory:'Такси',comment:'Поездка на такси'})];
          const before=JSON.stringify(rows);return {keys:rows.map(v99PurposeCategory),
            signals:rows.map(v98CategoryReviewSignal),groups:rows.map(expenseEntryGroup),
            unchanged:before===JSON.stringify(rows)};
        }""")
        self.assertEqual(actual, {'keys':['Транспорт','Транспорт'], 'signals':[None,None],
                                  'groups':['Передвижение','Передвижение'], 'unchanged':True})

    def test_explicit_selection_saves_sport_and_detail_with_exact_money(self):
        self.prepare()
        self.page.locator('#eAmount').fill('1250,05')
        self.page.locator('#eBeneficiary').select_option('Виктория')
        self.page.locator('#v90Search').fill('Пилатес')
        self.page.locator('#v90Quick button[data-cat="Спорт и здоровье"]').click()
        self.assertEqual(self.page.locator('#eSubcategory').input_value(), 'Пилатес')
        self.page.evaluate('addEntry()')
        actual = self.page.evaluate("""()=>({category:state.entries.at(-1).category,
          detail:state.entries.at(-1).subcategory,beneficiary:state.entries.at(-1).beneficiary,
          amount:state.entries.at(-1).amount})""")
        self.assertEqual(actual, {'category':'Спорт и здоровье', 'detail':'Пилатес',
                                  'beneficiary':'Виктория', 'amount':1250.05})

    def test_old_medical_vitamin_detail_survives_open_and_cancel(self):
        self.prepare()
        self.page.evaluate("state.entries=[wifeRow('old',{comment:'Витамин D',subcategory:'Витамины'})]")
        before = self.snapshot()
        self.page.evaluate("openEdit('old')")
        self.assertEqual(self.page.locator('#xCat').input_value(), 'Аптека и медицина')
        self.assertEqual(self.page.locator('#xSubcategory').input_value(), 'Витамины')
        self.assertNotIn('Витамины', self.page.evaluate("v81DetailOptions('Аптека и медицина')"))
        self.page.evaluate('closeEdit()')
        self.assertEqual(self.snapshot(), before)

    def test_review_requires_choice_and_preserves_raw_fields_and_family_total(self):
        self.prepare()
        self.page.evaluate("""()=>{
          state.entries=[wifeRow('sport'),wifeRow('hosting',{category:'Прочее',comment:'Хостинг'}),
            wifeRow('taxi',{category:'Авто и транспорт',comment:'Такси',beneficiary:'Сергей'})];
          renderAll();analyticsMonth.value=month();go('analytics');
        }""")
        before = self.snapshot()
        signals = self.page.evaluate('state.entries.map(v98CategoryReviewSignal)')
        self.assertEqual([row['suggestions'] for row in signals],
                         [['Спорт и здоровье'], ['Подписки'], ['Транспорт']])
        self.page.evaluate("v98OpenCategoryReview();v98OpenReviewEntry('sport')")
        self.assertEqual(self.page.locator('#xCat').input_value(), 'Аптека и медицина')
        self.assertEqual(self.snapshot(), before)
        self.page.locator('#editModal [data-record-action="category-review-choose"]').click()
        self.assertEqual(self.snapshot(), before)
        self.page.locator('#editModal').get_by_role('button', name='Сохранить', exact=True).click()
        self.page.wait_for_function("!editModal.classList.contains('open')")
        old = json.loads(before['state'])['entries']
        new = self.page.evaluate('JSON.parse(JSON.stringify(state.entries))')
        self.assertEqual(new[1:], old[1:])
        self.assertEqual(new[0]['category'], 'Спорт и здоровье')
        for row in (old[0], new[0]):
            row.pop('category');row.pop('updated_at')
        self.assertEqual(new[0], old[0])
        self.assertEqual(self.page.evaluate('sum(expenses(month()))'), 37.02)

    def test_taxi_sums_for_each_person_never_become_car_and_legacy_budgets_stay_exact(self):
        self.prepare()
        actual = self.page.evaluate("""()=>{
          state.entries=[wifeRow('s',{category:'Транспорт',subcategory:'Такси',beneficiary:'Сергей',amount:0.10}),
            wifeRow('v',{category:'Авто и транспорт',subcategory:'Такси',beneficiary:'Виктория',amount:0.20}),
            wifeRow('sport',{category:'Спорт и здоровье',amount:0.30}),
            wifeRow('old-med',{comment:'Витамины',amount:0.40})];
          const before=JSON.stringify(state);const legacy={group:'Семья и здоровье',amount:1};
          return {car:sum(carEntries()),transport:v84SpendGroup(month(),'Передвижение'),
            people:Object.fromEntries(v86TargetTotals(expenses(month()))),
            legacy:v84BudgetSpent(month(),legacy),legacyGroupCount:V98_LEGACY_GROUPS.length,
            unchanged:before===JSON.stringify(state),total:sum(expenses(month()))};
        }""")
        self.assertEqual(actual['car'], 0)
        self.assertEqual(actual['transport'], 0.30)
        self.assertEqual(actual['people']['Сергей'], 0.10)
        self.assertEqual(actual['people']['Виктория'], 0.90)
        self.assertEqual(actual['legacy'], 0.40)
        self.assertEqual(actual['legacyGroupCount'], 8)
        self.assertTrue(actual['unchanged'])
        self.assertEqual(actual['total'], 1)


if __name__ == '__main__':
    unittest.main()
