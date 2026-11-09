"""Offline mortgage reconciliation regressions with synthetic ledger entries.

Run: python -m unittest discover -s tests -p test_bank_mortgage_history.py
Requires Playwright and Chromium; CHROMIUM_EXECUTABLE may override the browser.
No authenticated account or external network is used.
"""
from pathlib import Path
import hashlib, os, shutil, unittest
from playwright.sync_api import sync_playwright

SOURCE = Path(__file__).resolve().parents[1] / 'index.html'
HTML = SOURCE.read_text()
BASE = 'http://127.0.0.1:9891/'

class BankMortgageHistory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = sync_playwright().start()
        executable = os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium') or shutil.which('chromium-browser')
        cls.browser = cls.p.chromium.launch(headless=True, **({'executable_path': executable} if executable else {}))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.p.stop()

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width':1280,'height':1000}, timezone_id='Europe/Moscow', service_workers='block')
        self.context.route('**/*', lambda r: r.fulfill(status=200, content_type='text/html', body=HTML) if r.request.url == BASE else r.abort())
        self.page = self.context.new_page()
        self.errors=[]; self.page.on('pageerror', lambda e:self.errors.append(str(e)))
        self.page.goto(BASE, wait_until='domcontentloaded')
        self.page.wait_for_function("typeof v128OpenBankHistory==='function'")
        self.page.evaluate('''() => {
          session=null; localStorage.clear(); state=blankState(); localRecoveryBlocked=false; window.__FINANCE_BRIDGE__=null;
          today=()=> '2026-11-02'; month=()=> '2026-11';
          window.clone=x=>JSON.parse(JSON.stringify(x));
          window.mkExpense=(id,amount,date='2026-11-02',fields={})=>({id,type:'expense',category:'Кредит',amount,date,who:'Общее',store:'Synthetic payment',pay:'Карта',accountId:'synthetic-old-account',customUnknown:{keep:true},created_at:date+'T12:00:00.000Z',updated_at:date+'T12:00:00.000Z',...fields});
          state.entries=[{id:'synthetic-income',type:'income',date:'2026-11-02',amount:345626,category:'Зарплата',who:'Общее',store:'Synthetic employer',created_at:'2026-11-02T12:00:00.000Z',updated_at:'2026-11-02T12:00:00.000Z'}];
          showApp(); go('loans'); window.initialDebt=v125MortgageProgress().balance;
          window.pick=(id,value)=>{document.getElementById(id).value=value;v128BankHistoryPreview()};
        }''')

    def tearDown(self):
        self.context.close()

    def evaluate(self, js):
        return self.page.evaluate('async () => {'+js+'}')

    def test_missing_payments_are_created_once_and_reduce_cash_not_debt_twice(self):
        r=self.evaluate('''const before=v111MonthBalance('2026-11').closing;v128OpenBankHistory();await v128ApplyBankHistory();const expenses=state.entries.filter(e=>e.type==='expense');return {before,closing:v111MonthBalance('2026-11').closing,amounts:expenses.map(e=>e.amount).sort((a,b)=>a-b),dates:expenses.map(e=>e.date),records:expenses.every(e=>!!v125MortgageRecord(e)),included:expenses.every(e=>e.mortgageAllocation.afterCheckpoint===false),debt:v125MortgageProgress().balance,initialDebt,missing:v128BankHistoryState().missingAmount};''')
        self.assertEqual(r, {'before':345626,'closing':143795.79,'amounts':[40000,161830.21],'dates':['2026-11-02','2026-11-02'],'records':True,'included':True,'debt':4458197.19,'initialDebt':4458197.19,'missing':0})
        self.assertFalse(self.errors, self.errors)

    def test_repeat_apply_reopen_and_reconciliation_are_idempotent(self):
        r=self.evaluate('''v128OpenBankHistory();await v128ApplyBankHistory();await v128ApplyBankHistory();const reopened=v128OpenBankHistory();await v128ApplyBankHistory();return {count:state.entries.length,closing:v111MonthBalance('2026-11').closing,reopened,keys:state.entries.filter(e=>e.type==='expense').map(e=>e.paymentKey)};''')
        self.assertEqual(r['count'],3); self.assertEqual(r['closing'],143795.79); self.assertFalse(r['reopened']); self.assertEqual(len(set(r['keys'])),2)

    def test_local_save_and_reload_preserve_real_expenses(self):
        self.evaluate('''v128OpenBankHistory();await v128ApplyBankHistory();validateBackup(state);''')
        self.page.reload(wait_until='domcontentloaded'); self.page.wait_for_function("typeof v128OpenBankHistory==='function'")
        r=self.evaluate('''state=normalize(JSON.parse(localStorage.getItem(KEYS.state)));today=()=> '2026-11-02';return {count:state.entries.length,closing:v111MonthBalance('2026-11').closing,missing:v128BankHistoryState().missingAmount,debt:v125MortgageProgress().balance};''')
        self.assertEqual(r, {'count':3,'closing':143795.79,'missing':0,'debt':4458197.19})

    def test_existing_separate_expenses_preserve_date_amount_account_and_unknown_fields(self):
        r=self.evaluate('''state.entries.push(mkExpense('old-regular',161830.21,'2026-10-30'),mkExpense('old-early',40000,'2026-11-02'));const before=clone(state.entries);const cash=v111MonthBalance('2026-11').closing;v128OpenBankHistory();pick('v128BankRegular','old-regular');pick('v128BankEarly','old-early');await v128ApplyBankHistory();return {count:state.entries.length,cashBefore:cash,cashAfter:v111MonthBalance('2026-11').closing,kept:state.entries.every(e=>{const old=before.find(x=>x.id===e.id);return ['id','date','amount','accountId','customUnknown'].every(k=>cloudJSONEqual(e[k],old[k]))}),missing:v128BankHistoryState().missingAmount,debt:v125MortgageProgress().balance};''')
        self.assertEqual(r,{'count':3,'cashBefore':143795.79,'cashAfter':143795.79,'kept':True,'missing':0,'debt':4458197.19})

    def test_existing_combined_expense_is_linked_without_changing_cash(self):
        r=self.evaluate('''state.entries.push(mkExpense('combined',201830.21,'2026-10-30'));const cash=v111MonthBalance('2026-11').closing;v128OpenBankHistory();pick('v128BankCombined','combined');await v128ApplyBankHistory();const e=state.entries.find(x=>x.id==='combined');return {count:state.entries.length,cashBefore:cash,cashAfter:v111MonthBalance('2026-11').closing,date:e.date,account:e.accountId,principal:e.mortgageAllocation?.principal,interest:e.mortgageAllocation?.interest,extra:e.mortgageAllocation?.extraPrincipal,missing:v128BankHistoryState().missingAmount,debt:v125MortgageProgress().balance};''')
        self.assertEqual(r,{'count':2,'cashBefore':143795.79,'cashAfter':143795.79,'date':'2026-10-30','account':'synthetic-old-account','principal':41802.81,'interest':160027.4,'extra':40000,'missing':0,'debt':4458197.19})

    def test_same_amount_candidate_is_never_automatically_reclassified(self):
        r=self.evaluate('''const e=mkExpense('unrelated',161830.21,'2026-10-10',{category:'Продукты',store:'Synthetic groceries'});state.entries.push(e);const before=clone(e);v128OpenBankHistory();const selected=document.getElementById('v128BankRegular').value;await v128ApplyBankHistory();return {selected,count:state.entries.length,unchanged:cloudJSONEqual(e,before)};''')
        self.assertEqual(r,{'selected':'','count':2,'unchanged':True})

    def test_partial_source_coverage_blocks_creating_a_full_duplicate(self):
        r=self.evaluate('''const e=mkExpense('partial',1000);e.mortgageAllocation={version:1,kind:'regular',date:e.date,amount:1000,principal:0,interest:1000,charges:0,extraPrincipal:0,dueDate:'2026-11-02',checkpointKey:v125SnapshotKey(BANK_LOAN_RECONCILIATION),afterCheckpoint:false};state.entries.push(e);const before=clone(state.entries);v128OpenBankHistory();await v128ApplyBankHistory();return {partial:v128BankHistoryState().bits[0].partial,unchanged:cloudJSONEqual(state.entries,before),count:state.entries.length};''')
        self.assertEqual(r,{'partial':True,'unchanged':True,'count':2})

    def test_deleted_canonical_record_is_not_silently_recreated(self):
        r=self.evaluate('''state.deletedEntries={[v128BankPaymentId('regular')]:'2026-11-02T12:00:00.000Z'};const before=clone(state);v128OpenBankHistory();const options=[...document.getElementById('v128BankRegular').options].map(o=>o.value);await v128ApplyBankHistory();return {offersNew:options.includes('new'),unchanged:cloudJSONEqual(state,before)};''')
        self.assertEqual(r,{'offersNew':False,'unchanged':True})

    def test_existing_edited_canonical_record_blocks_duplicate_creation(self):
        r=self.evaluate('''state.entries.push(mkExpense(v128BankPaymentId('regular'),100));const before=clone(state.entries);v128OpenBankHistory();await v128ApplyBankHistory();return {count:state.entries.length,unchanged:cloudJSONEqual(state.entries,before)};''')
        self.assertEqual(r,{'count':2,'unchanged':True})

    def test_stale_auth_context_cannot_commit(self):
        r=self.evaluate('''v128OpenBankHistory();authEpoch++;await v128ApplyBankHistory();return state.entries.length;'''); self.assertEqual(r,1)

    def test_new_concurrent_expense_forces_preview_refresh(self):
        r=self.evaluate('''v128OpenBankHistory();state.entries.push(mkExpense('concurrent',161830.21));await v128ApplyBankHistory();return {count:state.entries.length,created:state.entries.some(e=>e.id===v128BankPaymentId('regular')),error:document.getElementById('v128BankHistoryError').textContent};''')
        self.assertEqual(r['count'],2); self.assertFalse(r['created']); self.assertIn('изменилась',r['error'])

    def test_deleted_snapshot_change_cannot_commit(self):
        r=self.evaluate('''v128OpenBankHistory();state.deletedEntries={other:'2026-11-02T12:00:00.000Z'};await v128ApplyBankHistory();return state.entries.length;'''); self.assertEqual(r,1)

    def test_read_only_actor_cannot_open_or_apply(self):
        r=self.evaluate('''window.__FINANCE_BRIDGE__={active:true,role:'viewer'};const opened=v128OpenBankHistory();window.__FINANCE_BRIDGE__=null;v128OpenBankHistory();window.__FINANCE_BRIDGE__={active:true,role:'viewer'};await v128ApplyBankHistory();return {opened,count:state.entries.length};''')
        self.assertEqual(r,{'opened':False,'count':1})

    def test_future_bank_source_is_not_recorded_early(self):
        r=self.evaluate('''today=()=> '2026-11-01';const info=v128BankHistoryState(),opened=v128OpenBankHistory();await v128ApplyBankHistory();return {source:info.source,missing:info.missingAmount,opened,count:state.entries.length};''')
        self.assertEqual(r,{'source':None,'missing':0,'opened':False,'count':1})

    def test_linked_installment_expense_is_not_offered_as_mortgage(self):
        r=self.evaluate('''const e=mkExpense('split',40000);state.entries.push(e);state.installments=[{id:'plan',amount:40000,parts:[{id:'part',date:e.date,amount:40000}],links:{part:e.id}}];return v128BankCandidates(40000).map(e=>e.id);''')
        self.assertEqual(r,[])

    def test_preexisting_regular_allocation_creates_only_missing_early_payment(self):
        r=self.evaluate('''const e=mkExpense('regular',161830.21);e.mortgageAllocation=v128BankAllocation('regular',e,BANK_LOAN_RECONCILIATION);state.entries.push(e);v128OpenBankHistory();await v128ApplyBankHistory();return {count:state.entries.length,regularCount:state.entries.filter(e=>e.amount===161830.21).length,earlyCount:state.entries.filter(e=>e.amount===40000).length,missing:v128BankHistoryState().missingAmount,closing:v111MonthBalance('2026-11').closing};''')
        self.assertEqual(r,{'count':3,'regularCount':1,'earlyCount':1,'missing':0,'closing':143795.79})

    def test_account_ledger_reduces_once_and_manual_snapshot_is_unchanged(self):
        r=self.evaluate('''const account={id:'synthetic-cash',name:'Synthetic cash',amount:345626,snapshotDate:'2026-11-01',ledger:{version:1,enabled:true,startDate:'2026-11-01',openingBalance:345626,kind:'asset',includeInSpending:true}};state.intelligence.accounts=[account];const before=clone(account);v128OpenBankHistory();document.getElementById('v128BankAccount').value=account.id;await v128ApplyBankHistory();return {snapshotUnchanged:cloudJSONEqual(account,before),ledger:v117LedgerAt(account,'2026-11-02').balance,assigned:state.entries.filter(e=>e.type==='expense').every(e=>e.accountId===account.id)};''')
        self.assertEqual(r,{'snapshotUnchanged':True,'ledger':143795.79,'assigned':True})

    def test_bank_confirmation_is_separate_from_history_and_forecast(self):
        r=self.evaluate("""const before=v78Obligations('2026-11'),row=v78ObligationRows(before).find(r=>r.date==='2026-11-02'),calendar=v86CalendarEvents('2026-11').find(r=>r.date==='2026-11-02');const forecast=v86Forecast('2026-11-15');return {planned:before.planned,paid:before.paid,bank:before.bankConfirmed,remaining:before.remaining,status:v128ObligationStatus(row),settled:row.paid,rowExpense:row.expenseAllocated,rowBank:row.bankAllocated,calendarExpense:calendar.expenseAllocated,calendarBank:calendar.bankAllocated,forecastMortgage:forecast.mortgage};""")
        self.assertEqual(r, {'planned':247715.21,'paid':0,'bank':161830.21,'remaining':85885,'status':'По сверке банка','settled':True,'rowExpense':0,'rowBank':161830.21,'calendarExpense':0,'calendarBank':161830.21,'forecastMortgage':0})

    def test_real_recorded_expenses_replace_bank_only_status_without_new_debt(self):
        r=self.evaluate("""v128OpenBankHistory();await v128ApplyBankHistory();const o=v78Obligations('2026-11'),row=v78ObligationRows(o).find(r=>r.date==='2026-11-02'),calendar=v86CalendarEvents('2026-11').find(r=>r.date==='2026-11-02');return {paid:o.paid,bank:o.bankConfirmed,remaining:o.remaining,status:v128ObligationStatus(row),rowExpense:row.expenseAllocated,rowBank:row.bankAllocated,calendarExpense:calendar.expenseAllocated,calendarBank:calendar.bankAllocated,debt:v125MortgageProgress().balance};""")
        self.assertEqual(r, {'paid':161830.21,'bank':0,'remaining':85885,'status':'Учтено в расходах','rowExpense':161830.21,'rowBank':0,'calendarExpense':161830.21,'calendarBank':0,'debt':4458197.19})

    def test_recording_mortgage_updates_history_without_inventing_account_money(self):
        r=self.evaluate("""go('home');const read=()=>({title:document.getElementById('v121HomeAvailableTitle').textContent,bank:v150HomeBankData().total,missing:v128BankHistoryState().missingAmount,ledger:v111MonthBalance('2026-11').closing});const before=read();v128OpenBankHistory();await v128ApplyBankHistory();go('home');return {before,after:read()};""")
        self.assertEqual(r['before'], {'title':'Общий банк семьи по всем счетам','bank':None,'missing':201830.21,'ledger':345626})
        self.assertEqual(r['after'], {'title':'Общий банк семьи по всем счетам','bank':None,'missing':0,'ledger':143795.79})

    def test_future_dated_expense_does_not_confirm_present_cash_payment(self):
        r=self.evaluate("""const e=mkExpense('future',161830.21,'2026-11-03');e.mortgageAllocation=v128BankAllocation('regular',e,BANK_LOAN_RECONCILIATION);state.entries.push(e);return {history:v125ScheduledExpenseAllocated('2026-11-02',loanScheduleData()),missing:v128BankHistoryState().missingAmount};""")
        self.assertEqual(r, {'history':0,'missing':201830.21})

    def test_unmatched_older_early_allocation_requires_explicit_review(self):
        r=self.evaluate("""const e=mkExpense('old-early',40000,'2026-10-25');e.mortgageAllocation={version:1,kind:'early',date:e.date,amount:40000,principal:40000,interest:0,charges:0,extraPrincipal:40000,checkpointKey:'older-checkpoint',afterCheckpoint:false};state.entries.push(e);const before=clone(state.entries);v128OpenBankHistory();const selections=['v128BankRegular','v128BankEarly'].map(id=>document.getElementById(id).value);await v128ApplyBankHistory();return {selections,unchanged:cloudJSONEqual(state.entries,before)};""")
        self.assertEqual(r, {'selections':['',''],'unchanged':True})

    def test_invalid_combined_allocation_is_not_assumed_absent(self):
        r=self.evaluate("""const e=mkExpense('stale-combined',201830.21,'2026-10-30');e.mortgageAllocation={version:1,kind:'regular',date:e.date,amount:999,principal:41802.81,interest:160027.4,charges:0,extraPrincipal:40000,dueDate:'2026-11-02'};state.entries.push(e);const before=clone(state.entries);v128OpenBankHistory();const selections=['v128BankRegular','v128BankEarly'].map(id=>document.getElementById(id).value);await v128ApplyBankHistory();return {selections,unchanged:cloudJSONEqual(state.entries,before)};""")
        self.assertEqual(r, {'selections':['',''],'unchanged':True})

    def test_failed_second_selection_does_not_partially_add_first_expense(self):
        r=self.evaluate("""state.entries.push(mkExpense('wrong-value',100));const before=clone(state.entries);v128OpenBankHistory();document.getElementById('v128BankEarly').add(new Option('Invalid test selection','wrong-value'));pick('v128BankEarly','wrong-value');await v128ApplyBankHistory();return {unchanged:cloudJSONEqual(state.entries,before),count:state.entries.length};""")
        self.assertEqual(r, {'unchanged':True,'count':2})

    def test_prior_expense_date_is_visible_under_its_november_obligation(self):
        r=self.evaluate("""state.entries.push(mkExpense('october-regular',161830.21,'2026-10-30'));v128OpenBankHistory();pick('v128BankRegular','october-regular');await v128ApplyBankHistory();const row=v78ObligationRows(v78Obligations('2026-11')).find(r=>r.date==='2026-11-02');return {due:row.date,hasActualDate:row.subtitle.includes(v77DateLabel('2026-10-30')),hasHistoryLabel:row.subtitle.includes('Расход в истории:')};""")
        self.assertEqual(r, {'due':'2026-11-02','hasActualDate':True,'hasHistoryLabel':True})

if __name__ == '__main__':
    print('SOURCE SHA256',hashlib.sha256(HTML.encode()).hexdigest(),flush=True)
    unittest.main(verbosity=2)
