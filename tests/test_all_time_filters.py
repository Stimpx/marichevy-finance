"""All-time report periods retain exact totals, navigation and finite payment schedules.

Run: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests python -m unittest test_all_time_filters
All records are synthetic and all external browser requests are blocked.
"""
from pathlib import Path
import os
import shutil
import unittest

from playwright.sync_api import sync_playwright


HTML = (Path(__file__).resolve().parents[1] / 'index.html').read_text()
BASE = 'http://127.0.0.1:9864/'


class AllTimeFilters(unittest.TestCase):
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
        self.page.wait_for_function("typeof v169HomePeriod==='function'")
        self.page.evaluate('''() => {
          session=null;localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=null;
          localStorage.clear();state=blankState();saveAll=async()=>true;
          today=()=> '2026-11-17';month=()=> '2026-11';
          window.periodEntry=(id,type,date,amount,fields={})=>({id,type,date,amount,
            category:type==='income'?'Доход':'Продукты',subcategory:'',who:'Сергей',
            beneficiary:type==='expense'?'Сергей':'',store:'Тестовый магазин',comment:'Тест периода',
            created_at:'2026-11-17T10:00:00.000Z',updated_at:'2026-11-17T10:00:00.000Z',...fields});
          state.entries=[
            periodEntry('old-food','expense','2025-01-10',.20),
            periodEntry('oct-food','expense','2026-10-10',100.10),
            periodEntry('nov-food','expense','2026-11-10',50.20,{who:'Виктория',beneficiary:'Виктория'}),
            periodEntry('oct-fuel','expense','2026-10-11',20.10,{category:'Авто и транспорт',subcategory:'Бензин',beneficiary:'Автомобиль'}),
            periodEntry('nov-fuel','expense','2026-11-11',30.05,{category:'Авто и транспорт',subcategory:'Бензин',beneficiary:'Автомобиль'}),
            periodEntry('oct-income','income','2026-10-01',200.10),
            periodEntry('nov-income','income','2026-11-01',500.20),
            periodEntry('future-income','income','2026-12-01',1000.01),
            periodEntry('transfer','transfer','2026-11-01',300),
            periodEntry('cash','cash','2026-11-01',400),
            periodEntry('adjustment','transfer','2026-11-01',700,{balanceAdjustment:true}),
            periodEntry('deleted-food','expense','2026-10-10',1000,
              {created_at:'2026-10-10T10:00:00.000Z',updated_at:'2026-10-10T10:00:00.000Z'})];
          state.deletedEntries={'deleted-food':'2026-10-11T10:00:00.000Z'};
          state.intelligence.accounts=[{id:'bank',name:'Общий счёт',amount:5000,snapshotDate:'2025-01-01',
            created_at:'2025-01-01T10:00:00.000Z',updated_at:'2025-01-01T10:00:00.000Z',
            ledger:{version:1,enabled:true,startDate:'2025-01-01',openingBalance:5000,
              kind:'asset',includeInSpending:true}}];
          showApp();go('home');document.getElementById('homeMonth').value='2026-11';
          document.getElementById('analyticsMonth').value='2026-11';
          document.getElementById('analyticsScope').value='month';renderAll();
          window.originalPeriodEntries=JSON.stringify(state.entries);
          window.originalPeriodAccounts=JSON.stringify(state.intelligence.accounts);
          window.periodSet=(id,value)=>{const field=document.getElementById(id);field.value=value;
            field.dispatchEvent(new Event('change',{bubbles:true}));};
          window.periodNumber=id=>Number(document.getElementById(id).textContent
            .replaceAll('\\u00a0','').replace(/\\s|₽/g,'').replace(',','.'));
          window.periodCards=()=>({income:periodNumber('v146HomeIncome'),expense:periodNumber('v146HomeExpense'),
            period:document.getElementById('v146HomeMonthly').dataset.month,
            label:document.getElementById('v146HomeMonthLabel').textContent,
            bars:['v146IncomeBar','v146ExpenseBar'].map(id=>parseFloat(document.getElementById(id).style.width))});
          window.periodUnchanged=()=>JSON.stringify(state.entries)===originalPeriodEntries&&
            JSON.stringify(state.intelligence.accounts)===originalPeriodAccounts;
          window.periodInstallments=()=>{
            loanScheduleData=()=>[];
            state.installments=[{id:'split',title:'Тестовая рассрочка',kind:'split',amount:300.30,
              parts:[{id:'oct-part',date:'2026-10-20',amount:100.10},
                {id:'dec-part',date:'2026-12-20',amount:200.20}],links:{'oct-part':'paid-split'},
              created_at:'2026-10-01T10:00:00.000Z',updated_at:'2026-10-01T10:00:00.000Z'}];
            state.entries=[periodEntry('paid-split','expense','2026-10-20',100.10,
              {category:'Кредит',installmentId:'split',installmentPartId:'oct-part'})];
            state.deletedEntries={};state.intelligence.recurring=[];state.intelligence.budgets=[];
          };
        }''')

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def evaluate(self, code):
        return self.page.evaluate('async () => {' + code + '}')

    def test_home_all_time_totals_rankings_and_store_report_count_each_saved_operation_once(self):
        data = self.evaluate('''
          const bank=v150HomeBankData().total;periodSet('homeMonth','all');
          return {selected:document.getElementById('homeMonth').value,report:v169HomePeriod(),
            forecastMonth:homeMonth(),cards:periodCards(),carry:v169HomeBalance(),
            categories:v147HomeTopCategories('all'),targets:v149HomeTopTargets('all'),
            store:v163StoreSpending('all'),bank,afterBank:v150HomeBankData().total,
            shownStoreTotal:periodNumber('v163HomeStoreTotal'),unchanged:periodUnchanged()};
        ''')
        self.assertEqual((data['selected'], data['report'], data['forecastMonth']), ('all', 'all', '2026-11'))
        self.assertEqual((data['cards']['income'], data['cards']['expense']), (1700.31, 200.65))
        self.assertEqual(data['cards']['period'], 'all')
        self.assertIn('всё время', data['cards']['label'].lower())
        self.assertEqual((data['carry']['income'], data['carry']['expense']), (1700.31, 200.65))
        self.assertEqual(sum(round(row[1] * 100) for row in data['categories']), 20065)
        self.assertEqual(dict(data['targets']), {'Сергей': 100.30, 'Автомобиль': 50.15, 'Виктория': 50.20})
        self.assertEqual((data['store']['total'], data['store']['count']), (200.65, 5))
        self.assertEqual(data['shownStoreTotal'], 200.65)
        self.assertEqual(data['afterBank'], data['bank'])
        self.assertTrue(data['unchanged'])

    def test_home_all_time_switches_back_to_month_and_empty_reports_have_finite_zero_values(self):
        data = self.evaluate('''
          periodSet('homeMonth','all');periodSet('homeMonth','2026-10');const monthly=periodCards();
          state.entries=[];periodSet('homeMonth','all');renderHome();
          return {monthly,empty:periodCards(),carry:v169HomeBalance(),
            categories:v147HomeTopCategories('all'),targets:v149HomeTopTargets('all'),
            text:document.getElementById('home').textContent};
        ''')
        self.assertEqual((data['monthly']['income'], data['monthly']['expense']), (200.10, 120.20))
        self.assertIn('октябрь', data['monthly']['label'])
        self.assertEqual((data['empty']['income'], data['empty']['expense']), (0, 0))
        self.assertEqual(data['empty']['bars'], [0, 0])
        self.assertEqual(data['categories'], [])
        self.assertEqual(data['targets'], [])
        self.assertNotIn('NaN', data['text'])
        self.assertNotIn('Invalid Date', data['text'])

    def test_home_links_open_same_all_time_period_in_income_and_analytics(self):
        self.evaluate("periodSet('homeMonth','all');")
        self.page.locator('#v146HomeMonthly .v146-income').click(position={'x': 8, 'y': 8})
        income = self.evaluate("return {active:document.querySelector('.section.active').id,period:document.getElementById('incomeMonth').value,total:periodNumber('incomePeopleDonutTotal')};")
        self.assertEqual(income, {'active': 'income', 'period': 'all', 'total': 1700.31})
        self.evaluate("go('home');")
        self.page.locator('#v146HomeMonthly .v146-expense').focus()
        self.page.locator('#v146HomeMonthly .v146-expense').press('Enter')
        expense = self.evaluate("return {active:document.querySelector('.section.active').id,scope:document.getElementById('analyticsScope').value,total:periodNumber('v130AnalyticsPeriodTotal')};")
        self.assertEqual(expense, {'active': 'analytics', 'scope': 'all', 'total': 200.65})
        self.evaluate("go('home');")
        self.page.locator('#v147HomeAnalyticsButton').click()
        self.assertEqual(self.page.locator('#analyticsScope').input_value(), 'all')
        self.assertTrue(self.evaluate('return periodUnchanged();'))

    def test_home_drill_edit_delete_and_new_entry_preserve_all_time_context(self):
        data = self.evaluate('''
          periodSet('homeMonth','all');v84Drill('person','Сергей','home');
          const opened={scope:v96DrillContext.scope,total:periodNumber('v96DrillTotal')};
          v96EditFromDrill('oct-food');document.getElementById('xAmount').value='120.25';await saveEdit();
          const edited={scope:v96DrillContext.scope,total:periodNumber('v96DrillTotal'),home:periodCards()};
          v96DeleteFromDrill('old-food');await new Promise(requestAnimationFrame);
          const deleted={scope:v96DrillContext.scope,total:periodNumber('v96DrillTotal'),home:periodCards()};
          v84CloseDrill();openEntry('expense');document.getElementById('eAmount').value='10.10';
          v90Choose('Продукты');v133ChooseRecipient('eBeneficiary','Сергей');await addEntry();
          go('home');return {opened,edited,deleted,afterAdd:periodCards(),period:v169HomePeriod(),
            accounts:JSON.stringify(state.intelligence.accounts)===originalPeriodAccounts};
        ''')
        self.assertEqual(data['opened'], {'scope': 'all', 'total': 100.30})
        self.assertEqual((data['edited']['scope'], data['edited']['total']), ('all', 120.45))
        self.assertEqual(data['edited']['home']['expense'], 220.80)
        self.assertEqual((data['deleted']['scope'], data['deleted']['total']), ('all', 120.25))
        self.assertEqual(data['deleted']['home']['expense'], 220.60)
        self.assertEqual(data['afterAdd']['expense'], 230.70)
        self.assertEqual(data['period'], 'all')
        self.assertTrue(data['accounts'])

    def test_all_time_selections_survive_picker_refresh_and_back_navigation_with_matching_content(self):
        self.evaluate('''
          periodInstallments();renderAll();periodSet('homeMonth','all');periodSet('carMonth','all');
          periodSet('v86CalendarMonth','all');go('loans');periodSet('v78LoanMonth','all');
          go('home');go('history');
          document.getElementById('homeMonth').value='2026-11';
          document.getElementById('carMonth').value='2026-10';
          document.getElementById('v86CalendarMonth').value='2026-11';
          periodSet('v78LoanMonth','2026-11');
        ''')
        self.page.go_back(wait_until='domcontentloaded')
        self.page.wait_for_function("document.querySelector('.section.active').id==='home'")
        data = self.evaluate('''
          refreshHistoryPeriods();refreshHistoryPeriods();renderHome();
          const home={value:document.getElementById('homeMonth').value,cards:periodCards()};
          go('loans');const loans={value:document.getElementById('v78LoanMonth').value,
            title:document.querySelector('#v78LoansObligations h2').textContent,
            values:[...document.querySelectorAll('#v78LoansObligations .v78-obligations-stats b')].map(e=>e.textContent)};
          return {home,loans,car:document.getElementById('carMonth').value,
            calendar:document.getElementById('v86CalendarMonth').value,
            counts:['homeMonth','carMonth','v86CalendarMonth','v78LoanMonth'].map(id=>
              [...document.getElementById(id).options].filter(o=>o.value==='all').length)};
        ''')
        self.assertEqual(data['home']['value'], 'all')
        self.assertEqual(data['home']['cards']['expense'], 100.10)
        self.assertEqual((data['loans']['value'], data['car'], data['calendar']), ('all', 'all', 'all'))
        self.assertIn('всё время', data['loans']['title'].lower())
        self.assertIn('300,30', data['loans']['values'][0])
        self.assertEqual(data['counts'], [1, 1, 1, 1])

    def test_car_all_time_uses_all_car_entries_and_monthly_switch_still_limits_selected_report(self):
        data = self.evaluate('''
          go('car');periodSet('carMonth','all');
          const all={selected:carMonthKey(),total:periodNumber('carMonthTotal'),year:periodNumber('carYearTotal'),
            average:periodNumber('carAvgTotal'),count:v169ReportEntries(carMonthKey()).filter(e=>carCategory(e)).length,
            hint:document.getElementById('carCategoryHint').textContent,
            categories:document.getElementById('carCategories').textContent};
          periodSet('carMonth','2026-10');const monthly={total:periodNumber('carMonthTotal'),
            count:v169ReportEntries(carMonthKey()).filter(e=>carCategory(e)).length};
          state.entries=[];periodSet('carMonth','all');renderCar();
          return {all,monthly,empty:{total:periodNumber('carMonthTotal'),year:periodNumber('carYearTotal'),
            average:periodNumber('carAvgTotal'),text:document.getElementById('car').textContent},unchangedAccounts:
            JSON.stringify(state.intelligence.accounts)===originalPeriodAccounts};
        ''')
        self.assertEqual((data['all']['selected'], data['all']['total']), ('all', 50.15))
        self.assertEqual(data['all']['count'], 2)
        self.assertIn('всё время', data['all']['hint'].lower())
        self.assertIn('50,15', data['all']['categories'])
        self.assertIsInstance(data['all']['year'], (float, int))
        self.assertIsInstance(data['all']['average'], (float, int))
        self.assertEqual(data['monthly'], {'total': 20.10, 'count': 1})
        self.assertEqual((data['empty']['total'], data['empty']['year'], data['empty']['average']), (0, 0, 0))
        self.assertNotIn('NaN', data['empty']['text'])
        self.assertNotIn('Invalid Date', data['empty']['text'])
        self.assertTrue(data['unchangedAccounts'])

    def test_report_all_time_does_not_change_current_bank_forecast_or_writable_month_plan(self):
        data = self.evaluate('''
          const before={bank:v150HomeBankData().total,forecast:v86Forecast(),
            obligation:v78Obligations('2026-11'),month:homeMonth()};
          periodSet('homeMonth','all');periodSet('carMonth','all');periodSet('analyticsScope','all');
          go('planning');document.getElementById('v118PlanMonth').value='2026-11';v118ChangeMonth();
          periodSet('v86CalendarMonth','all');
          const after={bank:v150HomeBankData().total,forecast:v86Forecast(),
            obligation:v78Obligations('2026-11'),month:homeMonth()};
          return {same:cloudJSONEqual(before,after),plan:v118FormPeriod(),
            inputType:document.getElementById('v118PlanMonth').type,home:v169HomePeriod(),
            unchanged:periodUnchanged()};
        ''')
        self.assertTrue(data['same'])
        self.assertEqual((data['plan'], data['inputType'], data['home']), ('2026-11', 'month', 'all'))
        self.assertTrue(data['unchanged'])

    def test_calendar_and_loans_all_time_use_finite_saved_dates_and_keep_paid_filter(self):
        data = self.evaluate('''
          periodInstallments();state.intelligence.recurring=[{id:'rent',name:'Квартплата',amount:50.25,
            day:10,category:'ЖКХ',created_at:'2026-10-01T10:00:00.000Z',updated_at:'2026-10-01T10:00:00.000Z'}];
          state.entries.push(periodEntry('paid-rent','expense','2026-10-10',50.25,
            {category:'ЖКХ',recurringId:'rent',recurringPeriod:'2026-10'}));
          state.intelligence.budgets.push({id:'reserve',kind:'v118-seasonal-reserve',groupVersion:3,
            group:'Будущий расход',amount:80.10,name:'Страховка',target:80.10,saved:0,
            dueDate:'2027-01-10',accountId:'',created_at:'2026-11-01T10:00:00.000Z',updated_at:'2026-11-01T10:00:00.000Z'});
          const original=JSON.stringify(state);renderAll();const loans=v78Obligations('all');
          const events=v86CalendarEvents('all');go('planning');periodSet('v86CalendarMonth','all');
          v86SetFilter('paid');const paidRows=document.querySelectorAll('#v86CalendarList .v86-calendar-row').length;
          v86SetFilter('pending');const pendingRows=document.querySelectorAll('#v86CalendarList .v86-calendar-row').length;
          v86SetFilter('all');const allRows=document.querySelectorAll('#v86CalendarList .v86-calendar-row').length;
          periodSet('v86CalendarMonth','2026-11');
          return {loans,events:events.map(e=>({key:e.key,date:e.date,amount:e.amount,paid:e.paid,kind:e.kind})),
            planned:sum(events),paidRows,pendingRows,allRows,monthly:v86CalendarEvents('2026-11').length,
            unchanged:JSON.stringify(state)===original};
        ''')
        self.assertEqual((data['loans']['month'], data['loans']['planned'], data['loans']['paid'],
                          data['loans']['remaining']), ('all', 300.30, 100.10, 200.20))
        self.assertEqual(len(data['events']), 5)
        self.assertEqual(len({event['key'] for event in data['events']}), 5)
        self.assertEqual(sorted(event['date'] for event in data['events']),
                         ['2026-10-10', '2026-10-20', '2026-11-10', '2026-12-20', '2027-01-10'])
        self.assertEqual(data['planned'], 480.90)
        self.assertEqual((data['paidRows'], data['pendingRows'], data['allRows'], data['monthly']), (2, 3, 5, 1))
        self.assertTrue(data['unchanged'])
        same_date = self.evaluate('''
          state.installments=[];state.intelligence.recurring=[];state.intelligence.budgets=[];
          const dueDate=BANK_LOAN_CURRENT_SCHEDULE.map(row=>row[1].split('.').reverse().join('-'))
            .find(date=>date.startsWith('2040-'));
          const cash=periodEntry('mortgage-cash','expense',today(),50,{category:'Кредит',
            mortgageAllocation:{version:1,kind:'regular',date:today(),dueDate,amount:50,
              principal:50,interest:0,charges:0,extraPrincipal:0}});
          state.entries=[cash];state.deletedEntries={};
          const schedule=[{payDate:dueDate,payment:100},{payDate:dueDate,payment:20}];
          loanScheduleData=()=>schedule;const raw=JSON.stringify({schedule,entries:state.entries});
          const read=()=>{const loans=v78Obligations('all'),calendar=v86CalendarEvents('all'),
            planned=sum(calendar),paid=sum(calendar.map(e=>({amount:e.expenseAllocated||0}))),
            bank=sum(calendar.map(e=>({amount:e.bankAllocated||0})));
            return {loans:{planned:loans.planned,paid:loans.paid,remaining:loans.remaining},
              calendar:{planned,paid,remaining:Math.round((planned-paid-bank)*100)/100,count:calendar.length},
              partIds:calendar.filter(e=>e.kind==='installment').map(e=>e.installmentPartId)};
          };
          const mortgage={valid:!!v125MortgageRecord(cash),...read(),
            unchanged:JSON.stringify({schedule,entries:state.entries})===raw};
          loanScheduleData=()=>[];
          state.installments=[{id:'same-date-plan',title:'Две отдельные части',kind:'split',amount:120,
            parts:[{id:'part-a',date:dueDate,amount:100},{id:'part-b',date:dueDate,amount:20}],
            links:{'part-a':'part-cash'}}];
          state.entries=[periodEntry('part-cash','expense',today(),50,
            {category:'Кредит',installmentId:'same-date-plan',installmentPartId:'part-a'})];
          return {mortgage,installments:read()};
        ''')
        expected = {'planned': 120, 'paid': 50, 'remaining': 70}
        self.assertTrue(same_date['mortgage']['valid'])
        self.assertTrue(same_date['mortgage']['unchanged'])
        self.assertEqual(same_date['mortgage']['loans'], expected)
        self.assertEqual(same_date['mortgage']['calendar'], {**expected, 'count': 1})
        self.assertEqual(same_date['installments']['loans'], expected)
        self.assertEqual(same_date['installments']['calendar'], {**expected, 'count': 2})
        self.assertEqual(set(same_date['installments']['partIds']), {'part-a', 'part-b'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
