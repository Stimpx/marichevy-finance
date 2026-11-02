"""Income participant/source charts and management on offline synthetic data.

Run: python -m unittest discover -s tests -p test_income_dashboard.py
Requires Playwright and Chromium; CHROMIUM_EXECUTABLE may override browser path.
No authenticated account or external requests are used.
"""
from pathlib import Path
import json, os, shutil, unittest
from playwright.sync_api import sync_playwright

SOURCE=Path(os.environ.get('INCOME_TEST_HTML',str(Path(__file__).resolve().parents[1]/'index.html')))
HTML=SOURCE.read_text()
BASE='http://127.0.0.1:9899/'

class IncomeDashboard(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.p=sync_playwright().start();executable=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium') or shutil.which('chromium-browser');cls.browser=cls.p.chromium.launch(headless=True,**({'executable_path':executable} if executable else {}))
 @classmethod
 def tearDownClass(cls):cls.browser.close();cls.p.stop()
 def setUp(self):
  self.context=self.browser.new_context(viewport={'width':1280,'height':1000},timezone_id='Europe/Moscow',service_workers='block');self.context.route('**/*',lambda r:r.fulfill(status=200,content_type='text/html',body=HTML) if r.request.url==BASE else r.abort());self.page=self.context.new_page();self.errors=[];self.page.on('pageerror',lambda e:self.errors.append(str(e)));self.page.on('dialog',lambda d:d.accept());self.page.goto(BASE,wait_until='domcontentloaded');self.page.wait_for_function("typeof v135IncomePeople==='function'")
  self.page.evaluate('''() => {session=null;localStorage.clear();state=blankState();localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=null;
   const mk=(id,amount,who,store,date='2026-10-10',category='Доход',subcategory='')=>({id,type:'income',date,amount,who,store,category,subcategory,comment:'Тестовое поступление',created_at:'2026-10-10T12:00:00.000Z',updated_at:'2026-10-10T12:00:00.000Z'});
   state.entries=[mk('s-pass',300000,'Сергей','Пропуск'),mk('s-consult',165800,'Сергей','Доход','2026-10-11','Консультации'),mk('v-commission',133240,'Виктория','Доход','2026-10-12','Доход','Комиссия'),mk('m-benefit',48000,'Майя','Пособие'),mk('alice-old',1200,'Алиса','Стипендия','2026-09-15'),mk('s-next',1000,'Сергей','Пропуск','2026-11-02'),{id:'expense',type:'expense',date:'2026-10-10',amount:1234,category:'Продукты',who:'Общее',beneficiary:'Общее',store:'Тестовый магазин'},{id:'transfer',type:'transfer',date:'2026-10-10',amount:5000,category:'Движение денег',who:'Общее',from:'Карта',to:'Накопления'}];
   window.originalIncomeEntries=JSON.stringify(state.entries);showApp();go('income');document.getElementById('incomeMonth').value='2026-10';renderIncome();}''')
 def tearDown(self):
  self.assertEqual(self.errors,[]);self.context.close()
 def evaluate(self,js):return self.page.evaluate('async () => {'+js+'}')
 def test_income_totals_saturated_person_colors_and_zero_earner_omission(self):
  r=self.evaluate('''return {total:document.getElementById('incomePeopleDonutTotal').textContent.replaceAll('\\u00a0',' '),people:[...document.querySelectorAll('[data-v135-income-person]')].map(e=>e.dataset.v135IncomePerson),active:v135IncomePeople(),unchanged:JSON.stringify(state.entries)===originalIncomeEntries,rows:[...document.querySelectorAll('#incomePeopleLegend .legend-row')].map(e=>e.textContent),sergeyColor:document.querySelector('[data-v135-income-person="Сергей"] .bar i').style.background};''')
  self.assertEqual(r['total'],'647 040 ₽');self.assertEqual(r['people'],['Сергей','Виктория','Майя']);self.assertNotIn('Алиса',r['active']);self.assertTrue(r['unchanged']);self.assertEqual(len(r['rows']),3);self.assertIn('72%',r['rows'][0]);self.assertEqual(r['sergeyColor'],'rgb(63, 105, 232)')
 def test_sources_use_meaningful_legacy_fields_and_new_store_without_merging_records(self):
  r=self.evaluate('''const s=document.querySelector('[data-v135-person="Сергей"]');return {sources:[...s.querySelectorAll('[data-v135-source]')].map(e=>e.dataset.v135Source),donut:s.querySelector('.v135-source-donut').style.background,commission:!!document.querySelector('[data-v135-person="Виктория"] [data-v135-source="Комиссия"]'),sourceNoGuess:v135IncomeSource({category:'Доход',store:'',comment:'Наверное консультации'}),unchanged:JSON.stringify(state.entries)===originalIncomeEntries};''')
  self.assertEqual(r['sources'],['Пропуск','Консультации']);self.assertTrue(r['commission']);self.assertIn('conic-gradient',r['donut']);self.assertEqual(r['sourceNoGuess'],'Источник не указан');self.assertTrue(r['unchanged'])
 def test_add_remove_reload_does_not_reintroduce_historical_archived_person(self):
  r=self.evaluate('''await v135AddIncomeParticipant('  Антон  ');await v135RemoveIncomeParticipant('Сергей');return {active:v135IncomePeople(),entriesUnchanged:JSON.stringify(state.entries)===originalIncomeEntries,total:document.getElementById('incomePeopleDonutTotal').textContent,archived:document.querySelector('[data-v135-income-person="Сергей"] .v135-archived')?.textContent};''')
  self.assertIn('Антон',r['active']);self.assertNotIn('Сергей',r['active']);self.assertTrue(r['entriesUnchanged']);self.assertEqual(r['archived'],'в архиве');self.assertIn('647',r['total'])
  self.page.reload(wait_until='domcontentloaded');self.page.wait_for_function("typeof v135IncomePeople==='function'")
  r=self.evaluate("return {active:v135IncomePeople(),count:state.entries.length};")
  self.assertIn('Антон',r['active']);self.assertNotIn('Сергей',r['active']);self.assertEqual(r['count'],8)
 def test_default_alice_can_be_restored_and_removed_without_deleting_family_or_history(self):
  r=self.evaluate('''await v135AddIncomeParticipant('алиса');const restored=v135IncomePeople().includes('Алиса');await v135RemoveIncomeParticipant('Алиса');document.getElementById('incomeMonth').value='2026-09';renderIncome();return {restored,active:v135IncomePeople(),family:v99BeneficiaryChoices().includes('Алиса'),total:document.getElementById('incomePeopleDonutTotal').textContent.replaceAll('\\u00a0',' '),oldStillShown:!!document.querySelector('[data-v135-income-person="Алиса"] .v135-archived'),entriesUnchanged:JSON.stringify(state.entries)===originalIncomeEntries};''')
  self.assertTrue(r['restored']);self.assertNotIn('Алиса',r['active']);self.assertTrue(r['family']);self.assertEqual(r['total'],'1 200 ₽');self.assertTrue(r['oldStillShown']);self.assertTrue(r['entriesUnchanged'])
 def test_income_choices_refresh_but_edit_of_archived_income_preserves_recorded_person(self):
  r=self.evaluate('''openEntry('income');document.getElementById('eWho').value='Виктория';await v135RemoveIncomeParticipant('Виктория');const selected=document.getElementById('eWho').value,options=[...document.getElementById('eWho').options].map(e=>e.value);openEdit('v-commission');return {selected,options,editedWho:document.getElementById('xWho').value,editedOptions:[...document.getElementById('xWho').options].map(e=>e.value),entriesUnchanged:JSON.stringify(state.entries)===originalIncomeEntries};''')
  self.assertEqual(r['selected'],'');self.assertNotIn('Виктория',r['options']);self.assertEqual(r['editedWho'],'Виктория');self.assertIn('Виктория',r['editedOptions']);self.assertTrue(r['entriesUnchanged'])
 def test_repeat_archived_income_requires_active_person_and_keeps_legacy_source(self):
  r=self.evaluate('''await v135RemoveIncomeParticipant('Сергей');const opened=v97RepeatEntry('s-consult');return {opened,selected:document.getElementById('eWho').value,options:[...document.getElementById('eWho').options].map(e=>e.value),chip:!!document.querySelector('#v133IncomeRecipients [data-v133-recipient="Сергей"]'),source:document.getElementById('eIncomeSource').value,amount:document.getElementById('eAmount').value,date:document.getElementById('eDate').value,expectedDate:today(),entriesUnchanged:JSON.stringify(state.entries)===originalIncomeEntries};''')
  self.assertTrue(r['opened']);self.assertEqual(r['selected'],'');self.assertNotIn('Сергей',r['options']);self.assertFalse(r['chip']);self.assertEqual(r['source'],'Консультации');self.assertEqual(r['amount'],'165800');self.assertEqual(r['date'],r['expectedDate']);self.assertTrue(r['entriesUnchanged'])
 def test_favorite_of_archived_income_requires_active_person_and_keeps_source(self):
  r=self.evaluate('''const editorOpened=v97SaveFavoriteFromEntry('v-commission');document.getElementById('v97FavoriteName').value='Комиссия из истории';const saved=await v97SubmitFavoriteEditor();const favorite=v97FavoriteRows().find(e=>e.name==='Комиссия из истории'),before=JSON.stringify(favorite);await v135RemoveIncomeParticipant('Виктория');const opened=v97OpenFavorite(favorite.id);return {editorOpened,saved,opened,selected:document.getElementById('eWho').value,options:[...document.getElementById('eWho').options].map(e=>e.value),source:document.getElementById('eIncomeSource').value,amount:document.getElementById('eAmount').value,favoriteUnchanged:JSON.stringify(v97FindFavorite(favorite.id))===before,entriesUnchanged:JSON.stringify(state.entries)===originalIncomeEntries};''')
  self.assertTrue(r['editorOpened']);self.assertTrue(r['saved']);self.assertTrue(r['opened']);self.assertEqual(r['selected'],'');self.assertNotIn('Виктория',r['options']);self.assertEqual(r['source'],'Комиссия');self.assertEqual(r['amount'],'133240');self.assertTrue(r['favoriteUnchanged']);self.assertTrue(r['entriesUnchanged'])
 def test_duplicate_invalid_and_readonly_management_are_rejected(self):
  r=self.evaluate('''await v135AddIncomeParticipant('Антон');const before=JSON.stringify(state.settings),duplicate=await v135AddIncomeParticipant(' антон '),invalid=await v135AddIncomeParticipant('A\\nB'),empty=await v135AddIncomeParticipant('  ');window.__FINANCE_BRIDGE__={active:true,role:'viewer'};const blockedAdd=await v135AddIncomeParticipant('Нельзя'),blockedRemove=await v135RemoveIncomeParticipant('Сергей');renderIncome();return {duplicate,invalid,empty,blockedAdd,blockedRemove,settingsUnchanged:JSON.stringify(state.settings)===before,disabled:[...document.querySelectorAll('#v135IncomeParticipants input,#v135IncomeParticipants button')].every(e=>e.disabled),entriesUnchanged:JSON.stringify(state.entries)===originalIncomeEntries};''')
  self.assertFalse(r['duplicate']);self.assertFalse(r['invalid']);self.assertFalse(r['empty']);self.assertFalse(r['blockedAdd']);self.assertFalse(r['blockedRemove']);self.assertTrue(r['settingsUnchanged']);self.assertTrue(r['disabled']);self.assertTrue(r['entriesUnchanged'])
 def test_month_change_recalculates_each_person_source_and_empty_month(self):
  r=self.evaluate('''document.getElementById('incomeMonth').value='2026-11';renderIncome();const november={total:document.getElementById('incomePeopleDonutTotal').textContent.replaceAll('\\u00a0',' '),people:[...document.querySelectorAll('[data-v135-person]')].map(e=>e.dataset.v135Person),sources:[...document.querySelectorAll('[data-v135-source]')].map(e=>e.dataset.v135Source)};const select=document.getElementById('incomeMonth');select.add(new Option('Январь 2026','2026-01'));select.value='2026-01';renderIncome();return {november,emptyTotal:document.getElementById('incomePeopleDonutTotal').textContent,emptyCards:document.querySelectorAll('[data-v135-person]').length,unchanged:JSON.stringify(state.entries)===originalIncomeEntries};''')
  self.assertEqual(r['november'],{'total':'1 000 ₽','people':['Сергей'],'sources':['Пропуск']});self.assertEqual(r['emptyTotal'],'0 ₽');self.assertEqual(r['emptyCards'],0);self.assertTrue(r['unchanged'])
 def test_compact_legend_and_source_charts_fit_small_and_large_screens(self):
  desktop=self.evaluate('''return [...document.querySelectorAll('#incomePeopleLegend .legend-row')].every(row=>{const ys=[...row.children].map(e=>{const r=e.getBoundingClientRect();return r.y+r.height/2});return Math.max(...ys)-Math.min(...ys)<4});''')
  self.assertTrue(desktop)
  for width in [320,390,768,1280,1920]:
   with self.subTest(width=width):
    self.page.set_viewport_size({'width':width,'height':1000})
    self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth>document.documentElement.clientWidth+1'))
    self.assertFalse(self.page.evaluate("[...document.querySelectorAll('.v135-income-source-card')].some(e=>e.scrollWidth>e.clientWidth+1)"))

if __name__=='__main__':unittest.main(verbosity=2)
