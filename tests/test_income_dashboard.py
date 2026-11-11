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
  self.page.evaluate('''() => {session=null;localStorage.clear();state=blankState();localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=null;today=()=> '2026-11-12';month=()=> '2026-11';
   const mk=(id,amount,who,store,date='2026-10-10',category='Доход',subcategory='')=>({id,type:'income',date,amount,who,store,category,subcategory,comment:'Тестовое поступление',created_at:'2026-10-10T12:00:00.000Z',updated_at:'2026-10-10T12:00:00.000Z'});
   state.entries=[mk('s-pass',300000,'Сергей','Пропуск'),mk('s-consult',165800,'Сергей','Доход','2026-10-11','Консультации'),mk('v-commission',133240,'Виктория','Доход','2026-10-12','Доход','Комиссия'),mk('m-benefit',48000,'Майя','Пособие'),mk('alice-old',1200,'Алиса','Стипендия','2026-09-15'),mk('s-next',1000,'Сергей','Пропуск','2026-11-02'),{id:'expense',type:'expense',date:'2026-10-10',amount:1234,category:'Продукты',who:'Общее',beneficiary:'Общее',store:'Тестовый магазин'},{id:'transfer',type:'transfer',date:'2026-10-10',amount:5000,category:'Движение денег',who:'Общее',from:'Карта',to:'Накопления'}];
   window.originalIncomeEntries=JSON.stringify(state.entries);showApp();go('income');document.getElementById('incomeMonth').value='2026-10';renderIncome();}''')
 def tearDown(self):
  self.assertEqual(self.errors,[]);self.context.close()
 def evaluate(self,js):return self.page.evaluate('async () => {'+js+'}')
 def test_income_totals_saturated_person_colors_and_zero_earner_omission(self):
  r=self.evaluate('''return {total:document.getElementById('incomePeopleDonutTotal').textContent.replaceAll('\\u00a0',' '),people:[...document.querySelectorAll('[data-v135-income-person]')].map(e=>e.dataset.v135IncomePerson),active:v135IncomePeople(),unchanged:JSON.stringify(state.entries)===originalIncomeEntries,shares:[...document.querySelectorAll('#incomePeopleChart .v159-income-share')].map(e=>e.textContent),sergeyWidth:parseFloat(document.querySelector('[data-v135-income-person="Сергей"] .bar i').style.width),sergeyColor:document.querySelector('[data-v135-income-person="Сергей"] .bar i').style.background};''')
  self.assertEqual(r['total'],'647 040 ₽');self.assertEqual(r['people'],['Сергей','Виктория','Майя']);self.assertNotIn('Алиса',r['active']);self.assertTrue(r['unchanged']);self.assertEqual(r['shares'],['72%','21%','7%']);self.assertAlmostEqual(r['sergeyWidth'],465800/647040*100,places=3);self.assertEqual(r['sergeyColor'],'rgb(63, 105, 232)')
 def test_sources_use_meaningful_legacy_fields_and_new_store_without_merging_records(self):
  r=self.evaluate('''const s=document.querySelector('[data-v135-person="Сергей"]');return {sources:[...s.querySelectorAll('[data-v135-source]')].map(e=>e.dataset.v135Source),shares:[...s.querySelectorAll('.v159-source-share')].map(e=>e.textContent),widths:[...s.querySelectorAll('.bar i')].map(e=>parseFloat(e.style.width)),duplicates:!!s.querySelector('.v135-source-visual,.v135-source-donut,.v135-source-legend'),overallDonut:!!document.getElementById('incomePeopleDonut'),commission:!!document.querySelector('[data-v135-person="Виктория"] [data-v135-source="Комиссия"]'),sourceNoGuess:v135IncomeSource({category:'Доход',store:'',comment:'Наверное консультации'}),unchanged:JSON.stringify(state.entries)===originalIncomeEntries};''')
  self.assertEqual(r['sources'],['Пропуск','Консультации']);self.assertEqual(r['shares'],['64%','36%']);self.assertAlmostEqual(r['widths'][0],300000/465800*100,places=3);self.assertAlmostEqual(r['widths'][1],165800/465800*100,places=3);self.assertFalse(r['duplicates']);self.assertFalse(r['overallDonut']);self.assertTrue(r['commission']);self.assertEqual(r['sourceNoGuess'],'Источник не указан');self.assertTrue(r['unchanged'])
 def test_tiny_source_share_is_visible_and_uses_person_total_in_exact_cents(self):
  r=self.evaluate('''const base=state.entries[0];state.entries=[{...base,id:'source-main',amount:99.99,incomeSource:'Основной'},{...base,id:'source-cent',amount:.01,incomeSource:'Копейки'},{...base,id:'other-person',amount:900,who:'Виктория',incomeSource:'Работа'}];const before=JSON.stringify(state.entries);renderIncome();const card=document.querySelector('[data-v135-person="Сергей"]');return {total:card.querySelector('.v135-income-source-head>strong').textContent.replaceAll('\\u00a0',' '),tiny:card.querySelector('[data-v135-source="Копейки"] .v159-source-share').textContent,width:parseFloat(card.querySelector('[data-v135-source="Копейки"] .bar i').style.width),main:card.querySelector('[data-v135-source="Основной"] .v159-source-share').textContent,unchanged:JSON.stringify(state.entries)===before};''')
  self.assertEqual(r['total'],'100 ₽');self.assertEqual(r['tiny'],'<1%');self.assertAlmostEqual(r['width'],.01,places=5);self.assertEqual(r['main'],'100%');self.assertTrue(r['unchanged'])
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
  r=self.evaluate('''document.getElementById('incomeMonth').value='2026-11';renderIncome();const november={total:document.getElementById('incomePeopleDonutTotal').textContent.replaceAll('\\u00a0',' '),people:[...document.querySelectorAll('[data-v135-person]')].map(e=>e.dataset.v135Person),sources:[...document.querySelectorAll('[data-v135-source]')].map(e=>e.dataset.v135Source),shares:[...document.querySelectorAll('#incomePeopleCards .v159-source-share')].map(e=>e.textContent)};const select=document.getElementById('incomeMonth');select.add(new Option('Январь 2026','2026-01'));select.value='2026-01';renderIncome();return {november,emptyTotal:document.getElementById('incomePeopleDonutTotal').textContent,emptyCards:document.querySelectorAll('[data-v135-person]').length,unchanged:JSON.stringify(state.entries)===originalIncomeEntries};''')
  self.assertEqual(r['november'],{'total':'1 000 ₽','people':['Сергей'],'sources':['Пропуск'],'shares':['100%']});self.assertEqual(r['emptyTotal'],'0 ₽');self.assertEqual(r['emptyCards'],0);self.assertTrue(r['unchanged'])
 def test_all_time_counts_only_live_income_and_recalculates_each_person_sources(self):
  r=self.evaluate('''
   state.entries.push({...state.entries[0],id:'deleted-income',amount:1234.56});state.deletedEntries['deleted-income']='2026-12-01T12:00:00.000Z';
   const before=JSON.stringify(state.entries),settings=JSON.stringify(state.settings),select=document.getElementById('incomeMonth');select.value='all';select.dispatchEvent(new Event('change',{bubbles:true}));
   const sergey=document.querySelector('[data-v135-person="Сергей"]');
   return {selected:select.value,option:[...select.options].find(o=>o.value==='all')?.textContent,total:document.getElementById('incomePeopleDonutTotal').textContent.replaceAll('\\u00a0',' '),people:[...document.querySelectorAll('[data-v135-income-person]')].map(e=>e.dataset.v135IncomePerson),shares:[...document.querySelectorAll('#incomePeopleChart .v159-income-share')].map(e=>e.textContent),sourceTotals:[...sergey.querySelectorAll('.v159-source-values>span')].map(e=>e.textContent.replaceAll('\\u00a0',' ')),personTotal:sergey.querySelector('.v135-income-source-head>strong').textContent.replaceAll('\\u00a0',' '),list:document.querySelectorAll('#incomeList [data-v141-operation-id]').length,hint:document.getElementById('incomePeopleChartHint').textContent,unchanged:JSON.stringify(state.entries)===before&&JSON.stringify(state.settings)===settings};
  ''')
  self.assertEqual(r['selected'],'all');self.assertEqual(r['option'],'За всё время');self.assertEqual(r['total'],'649 240 ₽');self.assertEqual(r['people'],['Сергей','Виктория','Майя','Алиса']);self.assertEqual(r['shares'],['72%','21%','7%','<1%']);self.assertEqual(r['sourceTotals'],['301 000 ₽','165 800 ₽']);self.assertEqual(r['personTotal'],'466 800 ₽');self.assertEqual(r['list'],6);self.assertIn('всё время',r['hint'].lower());self.assertTrue(r['unchanged'])
 def test_all_time_survives_period_refresh_and_render_when_income_changes_or_becomes_empty(self):
  r=self.evaluate('''
   const select=document.getElementById('incomeMonth');select.value='all';select.dispatchEvent(new Event('change',{bubbles:true}));
   state.entries.push({...state.entries[0],id:'new-period-income',amount:1.25,date:'2027-01-02'});const before=JSON.stringify(state.entries);refreshHistoryPeriods();renderAll();
   const updated={selected:select.value,total:document.getElementById('incomePeopleDonutTotal').textContent.replaceAll('\\u00a0',' '),allOptions:[...select.options].filter(o=>o.value==='all').length,unchanged:JSON.stringify(state.entries)===before};
   state.entries=state.entries.filter(e=>e.type!=='income');const remaining=JSON.stringify(state.entries);refreshHistoryPeriods();renderAll();
   return {updated,empty:{selected:select.value,total:document.getElementById('incomePeopleDonutTotal').textContent,people:document.querySelectorAll('[data-v135-person]').length,shares:document.querySelectorAll('#incomePeopleCards .v159-source-share').length,unchanged:JSON.stringify(state.entries)===remaining}};
  ''')
  self.assertEqual(r['updated'],{'selected':'all','total':'649 241,25 ₽','allOptions':1,'unchanged':True});self.assertEqual(r['empty'],{'selected':'all','total':'0 ₽','people':0,'shares':0,'unchanged':True})
 def test_browser_back_restores_all_time_income_and_preserves_other_periods(self):
  self.evaluate("document.getElementById('homeMonth').value='2026-11';document.getElementById('incomeMonth').value='all';document.getElementById('incomeMonth').dispatchEvent(new Event('change',{bubbles:true}));await new Promise(requestAnimationFrame);")
  self.evaluate("go('history');document.getElementById('incomeMonth').value='2026-10';")
  self.page.go_back();self.page.wait_for_function("document.getElementById('income').classList.contains('active')")
  r=self.evaluate("return {selected:document.getElementById('incomeMonth').value,total:document.getElementById('incomePeopleDonutTotal').textContent.replaceAll('\\u00a0',' '),home:homeMonth(),unchanged:JSON.stringify(state.entries)===originalIncomeEntries};")
  self.assertEqual(r,{'selected':'all','total':'649 240 ₽','home':'2026-11','unchanged':True})
 def test_home_monthly_income_card_returns_from_all_time_to_selected_month(self):
  self.evaluate("document.getElementById('incomeMonth').value='all';renderIncome();go('home');document.getElementById('homeMonth').value='2026-10';renderHome();")
  self.page.locator('#v146HomeMonthly .v146-income').click()
  r=self.evaluate("return {active:document.querySelector('.section.active').id,selected:document.getElementById('incomeMonth').value,total:document.getElementById('incomePeopleDonutTotal').textContent.replaceAll('\\u00a0',' '),allStillAvailable:[...document.getElementById('incomeMonth').options].some(o=>o.value==='all'),unchanged:JSON.stringify(state.entries)===originalIncomeEntries};")
  self.assertEqual(r,{'active':'income','selected':'2026-10','total':'647 040 ₽','allStillAvailable':True,'unchanged':True})
 def test_income_overview_january_compares_previous_december_without_mixing_year_totals(self):
  r=self.evaluate('''
   const base=state.entries[0];state.entries=[{...base,id:'last-year',date:'2026-01-10',amount:7777},{...base,id:'previous-december',date:'2026-12-10',amount:200.50},{...base,id:'selected-january',date:'2027-01-10',amount:100.25},{...base,id:'later-income',date:'2027-03-10',amount:900},{...base,id:'not-income',type:'expense',date:'2027-01-10',amount:500}];refreshHistoryPeriods();document.getElementById('incomeMonth').value='2027-01';const before=JSON.stringify(state.entries);renderIncome();
   const read=id=>Number(document.getElementById(id).textContent.replaceAll('\\u00a0','').replace(/\\s|₽/g,'').replace(',','.')),data=v159IncomeOverview('2027-01');
   return {period:read('v159IncomePeriodTotal'),year:read('v159IncomeYearTotal'),average:read('v159IncomeAverage'),previousMonth:data.previousMonth,previousTotal:data.previousTotal,difference:data.difference,differencePercent:data.differencePercent,comparisonVisible:!document.getElementById('v159IncomeComparison').hidden,unchanged:JSON.stringify(state.entries)===before};
  ''')
  self.assertEqual(r,{'period':100.25,'year':100.25,'average':100.25,'previousMonth':'2026-12','previousTotal':200.5,'difference':-100.25,'differencePercent':-50,'comparisonVisible':True,'unchanged':True})
 def test_income_overview_averages_zero_months_and_labels_all_time_current_year_anchor(self):
  r=self.evaluate('''
   month=()=> '2027-03';today=()=> '2027-03-12';const base=state.entries[0];state.entries=[{...base,id:'december',date:'2026-12-10',amount:200.50},{...base,id:'january',date:'2027-01-10',amount:100.25},{...base,id:'march',date:'2027-03-10',amount:300.75},{...base,id:'april',date:'2027-04-10',amount:9999}];refreshHistoryPeriods();document.getElementById('incomeMonth').value='2027-03';renderIncome();
   const read=id=>Number(document.getElementById(id).textContent.replaceAll('\\u00a0','').replace(/\\s|₽/g,'').replace(',','.')),monthly=v159IncomeOverview('2027-03');const selected={period:read('v159IncomePeriodTotal'),year:read('v159IncomeYearTotal'),average:read('v159IncomeAverage'),months:monthly.averageMonths,previousTotal:monthly.previousTotal,differencePercent:monthly.differencePercent,finiteComparison:!/(?:Infinity|NaN)/.test(document.getElementById('v159IncomeComparison').textContent)};
   document.getElementById('incomeMonth').value='all';renderIncome();const all=v159IncomeOverview('all');return {selected,all:{period:read('v159IncomePeriodTotal'),year:read('v159IncomeYearTotal'),average:read('v159IncomeAverage'),months:all.averageMonths,yearAnchor:Number(all.year),comparisonHidden:document.getElementById('v159IncomeComparison').hidden,label:document.getElementById('v159IncomePeriodLabel').textContent}};
  ''')
  self.assertEqual(r['selected'],{'period':300.75,'year':401,'average':133.67,'months':3,'previousTotal':0,'differencePercent':None,'finiteComparison':True});self.assertEqual(r['all']['period'],10600.5);self.assertEqual(r['all']['year'],401);self.assertEqual(r['all']['average'],2120.1);self.assertEqual(r['all']['months'],5);self.assertEqual(r['all']['yearAnchor'],2027);self.assertTrue(r['all']['comparisonHidden']);self.assertIn('всё время',r['all']['label'].lower())
 def test_daily_average_uses_entire_past_leap_month_including_zero_income_days(self):
  r=self.evaluate('''
   month=()=> '2028-03';today=()=> '2028-03-12';const base=state.entries[0];state.entries=[{...base,id:'leap-month-income',date:'2028-02-10',amount:2900},{...base,id:'not-income',type:'expense',date:'2028-02-11',amount:500}];refreshHistoryPeriods();document.getElementById('incomeMonth').value='2028-02';const before=JSON.stringify(state.entries);renderIncome();const data=v159IncomeOverview('2028-02');
   return {from:data.dailyFrom,to:data.dailyTo,days:data.averageDays,average:data.dailyAverage,shown:Number(document.getElementById('v159IncomeAverageDay').textContent.replaceAll('\\u00a0','').replace(/\\s|₽/g,'').replace(',','.')),unchanged:JSON.stringify(state.entries)===before};
  ''')
  self.assertEqual(r,{'from':'2028-02-01','to':'2028-02-29','days':29,'average':100,'shown':100,'unchanged':True})
 def test_daily_average_current_partial_period_ends_today_for_month_and_all_time(self):
  r=self.evaluate('''
   const select=document.getElementById('incomeMonth');select.value='2026-11';renderIncome();const read=()=>{const data=v159IncomeOverview(select.value);return {from:data.dailyFrom,to:data.dailyTo,days:data.averageDays,average:data.dailyAverage,shown:Number(document.getElementById('v159IncomeAverageDay').textContent.replaceAll('\\u00a0','').replace(/\\s|₽/g,'').replace(',','.'))}};const monthly=read();state.entries.push({...state.entries[0],id:'future-current-month',date:'2026-11-20',amount:73000});const before=JSON.stringify(state.entries);renderIncome();const future={...read(),period:v159IncomeOverview(select.value).total};select.value='all';renderIncome();return {monthly,future,all:read(),unchanged:JSON.stringify(state.entries)===before};
  ''')
  expected={'from':'2026-09-01','to':'2026-11-12','days':73,'average':8893.7,'shown':8893.7}
  self.assertEqual(r['monthly'],expected);self.assertEqual(r['future'],{**expected,'period':74000});self.assertEqual(r['all'],expected);self.assertTrue(r['unchanged'])
 def test_income_bank_matches_home_accounts_and_discloses_unknown_balance_across_periods(self):
  r=self.evaluate('''
   const stamp=new Date().toISOString(),account=(id,name,opening,spending=true,start='2026-11-01')=>({id,name,amount:opening,snapshotDate:'2026-11-01',snapshotRevision:'revision-'+id,created_at:stamp,updated_at:stamp,snapshotVerification:{amount:opening,date:'2026-11-01',revision:'revision-'+id,verifiedAt:stamp,accountUpdatedAt:stamp},ledger:{version:1,enabled:true,startDate:start,openingBalance:opening,kind:'asset',includeInSpending:spending}});
   state.intelligence.accounts=[account('bank-card','Карта',1000.25),account('bank-savings','Накопления',5000.50,false),account('bank-unknown','Поздний счёт',90000,true,'2027-01-01')];
   const base=state.entries[0];state.entries.push({...base,id:'bound-income',date:'2026-11-05',amount:20.20,accountId:'bank-card'},{...base,id:'bound-expense',type:'expense',category:'Продукты',beneficiary:'Общее',date:'2026-11-06',amount:10.10,accountId:'bank-card'});const before=JSON.stringify(state.entries),accounts=JSON.stringify(state.intelligence.accounts);
   go('home');renderHome();const home=Number(document.getElementById('v121HomeAvailable').textContent.replaceAll('\\u00a0','').replace(/\\s|₽/g,'').replace(',','.')),data=v150HomeBankData();go('income');const values=[];for(const period of ['all','2026-10','2026-11']){document.getElementById('incomeMonth').value=period;renderIncome();values.push(Number(document.getElementById('v159IncomeBankTotal').textContent.replaceAll('\\u00a0','').replace(/\\s|₽/g,'').replace(',','.')))}
   return {home,total:data.total,unknown:data.unknownCount,values,note:document.getElementById('v159IncomeBankNote').textContent,unchanged:JSON.stringify(state.entries)===before&&JSON.stringify(state.intelligence.accounts)===accounts};
  ''')
  self.assertEqual(r['home'],6010.85);self.assertEqual(r['total'],6010.85);self.assertEqual(r['unknown'],1);self.assertEqual(r['values'],[6010.85]*3);self.assertRegex(r['note'].lower(),'не все|не указан|непол|неизвест|не заполн');self.assertTrue(r['unchanged'])
 def test_linear_charts_fit_small_and_large_screens_without_duplicated_donuts(self):
  self.assertEqual(self.page.locator('#income .donut-ring').count(),0)
  for width in [320,390,768,1280,1920]:
   with self.subTest(width=width):
    self.page.set_viewport_size({'width':width,'height':1000})
    self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth>document.documentElement.clientWidth+1'))
    self.assertFalse(self.page.evaluate("[...document.querySelectorAll('.v135-income-source-card')].some(e=>e.scrollWidth>e.clientWidth+1)"))

if __name__=='__main__':unittest.main(verbosity=2)
