"""Blank-account income credits the shared family bank without replaying current-balance facts.

Run: python -m unittest discover -s tests -p test_general_budget_income.py
All browser data is synthetic and every external request is blocked.
"""
from pathlib import Path
import os
import shutil
import unittest

from playwright.sync_api import sync_playwright


HTML = (Path(__file__).resolve().parents[1] / 'index.html').read_text()
BASE = 'http://127.0.0.1:9865/'


class GeneralBudgetIncome(unittest.TestCase):
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
        self.page.wait_for_function("typeof v165CashflowAccountId==='function'")
        self.page.evaluate('''() => {
          const NativeDate=Date;let clock=NativeDate.parse('2026-11-15T12:00:00.000Z');
          window.Date=class extends NativeDate {
            constructor(...args){super(...(args.length?args:[clock]))}
            static now(){return clock}
          };
          window.advanceIncomeClock=ms=>{clock+=ms};
          session=null;localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=null;
          localStorage.clear();state=blankState();saveAll=async()=>true;
          today=()=>new Date().toISOString().slice(0,10);month=()=>today().slice(0,7);
          window.incomeAccount=(id='main',opening=1000,fields={})=>{
            const stamp='2026-11-01T09:00:00.000Z',revision='verified-'+id;
            return {id,name:id==='main'?'Общий счёт':'Второй счёт',amount:opening,
              snapshotDate:'2026-11-01',snapshotRevision:revision,created_at:stamp,updated_at:stamp,
              snapshotVerification:{amount:opening,date:'2026-11-01',revision,
                verifiedAt:stamp,accountUpdatedAt:stamp},
              ledger:{version:1,enabled:true,startDate:'2026-11-01',openingBalance:opening,
                kind:'asset',includeInSpending:true},...fields};
          };
          window.incomeEntry=(id,amount,fields={})=>({id,type:'income',amount,date:today(),
            category:'Доход',who:'Сергей',beneficiary:'',store:'Синтетический доход',
            comment:'Ручная заметка',created_at:new Date().toISOString(),
            updated_at:new Date().toISOString(),...fields});
          state.intelligence.accounts=[incomeAccount()];state.entries=[];
          showApp();go('home');document.getElementById('homeMonth').value='2026-11';renderHome();
          window.incomeBank=()=>v150HomeBankData().total;
          window.incomeBankText=()=>document.getElementById('v121HomeAvailable').textContent.replaceAll('\\u00a0',' ');
          window.incomeBalances=()=>Object.fromEntries(v150HomeBankData().items.map(a=>[a.id,a.balance]));
          window.saveActualIncomeBalance=async(amount)=>{
            v150OpenHomeAccount('main');document.getElementById('v150AccountName').value='Общий счёт';
            document.getElementById('v150AccountOpening').value=String(amount);
            return v150SaveHomeAccount();
          };
        }''')

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def evaluate(self, code):
        return self.page.evaluate('async () => {' + code + '}')

    def test_income_and_expense_cents_change_one_shared_bank_without_rewriting_saved_records(self):
        result = self.evaluate('''
          const saved=incomeAccount('saved',500);saved.ledger.includeInSpending=false;
          state.intelligence.accounts.push(saved);
          state.entries=[incomeEntry('blank-a',100.10),incomeEntry('blank-b',.20),
            incomeEntry('explicit',10.05,{accountId:'main'}),
            incomeEntry('expense',50.25,{type:'expense',category:'Продукты',beneficiary:'Общее'}),
            incomeEntry('transfer',20,{type:'transfer',category:'Движение денег',fromAccountId:'main',toAccountId:'saved'})];
          const history=JSON.stringify(state.entries),accounts=JSON.stringify(state.intelligence.accounts);
          renderAll();renderHome();return {total:incomeBank(),text:incomeBankText(),balances:incomeBalances(),
            ids:state.entries.map(e=>v165CashflowAccountId(e)),needs:[...state.entries.slice(0,2)].map(e=>v117EntryNeedsAccount(e)),
            income:v111MonthBalance('2026-11').income,expense:v111MonthBalance('2026-11').expense,
            storeTotal:v163StoreSpending('2026-11').total,categoryTotal:v165CategorySpending('2026-11').total,
            sameHistory:JSON.stringify(state.entries)===history,sameAccounts:JSON.stringify(state.intelligence.accounts)===accounts};
        ''')
        self.assertEqual(result['total'], 1560.10)
        self.assertEqual(result['text'], '1 560,10 ₽')
        self.assertEqual(result['balances'], {'main': 1040.10, 'saved': 520})
        self.assertEqual(result['ids'][:4], ['main', 'main', 'main', 'main'])
        self.assertEqual(result['needs'], [False, False])
        self.assertEqual(result['income'], 110.35)
        self.assertEqual(result['expense'], 50.25)
        self.assertEqual(result['storeTotal'], 50.25)
        self.assertEqual(result['categoryTotal'], 50.25)
        self.assertTrue(result['sameHistory'])
        self.assertTrue(result['sameAccounts'])

    def test_current_balance_covers_old_income_even_with_clock_skew_and_new_same_millisecond_id_credits_once(self):
        result = self.evaluate('''
          state.entries=[incomeEntry('old-income',100,{date:'2026-11-05',created_at:'2026-11-05T08:00:00.000Z'}),
            incomeEntry('already-today',500,{created_at:new Date(Date.now()+24*3600000).toISOString()}),
            incomeEntry('scheduled-income',500,{date:'2026-11-16'})];
          const history=JSON.stringify(state.entries);const ok=await saveActualIncomeBalance(800000);
          const exact=incomeBank(),anchor=v117AccountRecord('main').ledger.currentBalanceAnchor;
          advanceIncomeClock(2000);
          state.entries.push(incomeEntry('new-income',25.25,{created_at:anchor.recordedAt}));renderAll();
          const afterIncome=incomeBank();state.entries.push(incomeEntry('new-expense',10.10,
            {type:'expense',category:'Продукты',beneficiary:'Общее'}));renderAll();
          const total=incomeBank();state.entries.push(incomeEntry('late-old-income',1000,{date:'2026-11-14'}));
          const afterBackfill=incomeBank();advanceIncomeClock(24*3600000);renderAll();
          return {ok,exact,afterIncome,total,afterBackfill,afterFutureDate:incomeBank(),
            difference:v117AccountBalance('main').difference,
            newId:v165CashflowAccountId(state.entries.find(e=>e.id==='new-income')),
            oldId:v165CashflowAccountId(state.entries.find(e=>e.id==='already-today')),
            rawUnchanged:JSON.stringify(state.entries.slice(0,3))===history};
        ''')
        self.assertTrue(result['ok'])
        self.assertEqual(result['exact'], 800000)
        self.assertEqual(result['afterIncome'], 800025.25)
        self.assertEqual(result['total'], 800015.15)
        self.assertEqual(result['afterBackfill'], 800015.15)
        self.assertEqual(result['afterFutureDate'], 800515.15)
        self.assertEqual(result['difference'], 0)
        self.assertEqual(result['newId'], 'main')
        self.assertFalse(result['oldId'])
        self.assertTrue(result['rawUnchanged'])

    def test_explicit_account_priority_and_unavailable_or_disabled_defaults_do_not_redirect_income(self):
        result = self.evaluate('''
          const saved=incomeAccount('saved',500);saved.ledger.includeInSpending=false;
          const debt=incomeAccount('debt',-200);debt.ledger.kind='debt';debt.ledger.includeInSpending=false;
          state.intelligence.accounts=[incomeAccount(),saved,debt,incomeAccount('closed',0,{archived:true})];
          state.settings.preferences.unassignedExpenseAccountId='main';
          state.entries=[incomeEntry('blank',100),incomeEntry('saved-income',50,{accountId:'saved'}),
            incomeEntry('debt-income',70,{accountId:'debt'}),incomeEntry('closed-income',80,{accountId:'closed'}),
            incomeEntry('unknown-income',90,{accountId:'missing-account'}),
            incomeEntry('bad-reference',100,{accountId:42})];
          const explicit={total:incomeBank(),balances:incomeBalances(),
            ids:state.entries.map(e=>v165CashflowAccountId(e)),debt:v117AccountBalance('debt').balance};
          state.intelligence.accounts=[incomeAccount(),incomeAccount('other',500)];
          state.entries=[incomeEntry('blank',100)];delete state.settings.preferences.unassignedExpenseAccountId;
          const ambiguous=incomeBank();
          state.intelligence.accounts=[incomeAccount()];state.settings.preferences.unassignedExpenseAccountId='';
          const disabled=incomeBank();state.settings.preferences.unassignedExpenseAccountId='missing';
          const invalid=incomeBank();delete state.settings.preferences.unassignedExpenseAccountId;
          state.intelligence.accounts=[debt];const onlyDebt={total:incomeBank(),id:v165CashflowAccountId(state.entries[0])};
          state.intelligence.accounts=[{id:'manual',name:'Снимок',amount:1000,snapshotDate:today(),
            created_at:new Date().toISOString(),updated_at:new Date().toISOString()}];
          return {explicit,ambiguous,disabled,invalid,onlyDebt,manual:{total:incomeBank(),id:v165CashflowAccountId(state.entries[0])}};
        ''')
        self.assertEqual(result['explicit']['total'], 1650)
        self.assertEqual(result['explicit']['balances'], {'main': 1100, 'saved': 550})
        self.assertEqual(result['explicit']['ids'][:5], ['main', 'saved', 'debt', 'closed', 'missing-account'])
        self.assertFalse(result['explicit']['ids'][5])
        self.assertEqual(result['explicit']['debt'], -130)
        self.assertEqual(result['ambiguous'], 1500)
        self.assertEqual(result['disabled'], 1000)
        self.assertEqual(result['invalid'], 1000)
        self.assertIsNone(result['onlyDebt']['total'])
        self.assertFalse(result['onlyDebt']['id'])
        self.assertEqual(result['manual']['total'], 1000)
        self.assertFalse(result['manual']['id'])

    def test_actual_income_form_edit_assign_unassign_delete_and_undo_refresh_bank_without_double_credit(self):
        result = self.evaluate('''
          const saved=incomeAccount('saved',500);saved.ledger.includeInSpending=false;
          state.intelligence.accounts.push(saved);renderAll();
          openEntry('income');document.getElementById('eAmount').value='12.34';
          document.getElementById('eWho').value='Сергей';document.getElementById('eIncomeSource').value='Тестовый доход';
          document.getElementById('eDate').value=today();document.getElementById('eAccountId').value='';
          await addEntry();const record=state.entries.at(-1),id=record.id;
          const added={total:incomeBank(),text:incomeBankText(),rawId:record.accountId||''};
          openEdit(id);document.getElementById('xAmount').value='20.05';
          document.getElementById('xAccountId').value='saved';await saveEdit();
          const assigned={total:incomeBank(),balances:incomeBalances()};
          openEdit(id);document.getElementById('xAccountId').value='';await saveEdit();
          const unassigned={total:incomeBank(),balances:incomeBalances()};
          await deleteEntry(id);const removed=incomeBank();await v119UndoDelete();
          return {added,assigned,unassigned,removed,restored:incomeBank(),text:incomeBankText(),
            count:state.entries.length,record:state.entries[0]};
        ''')
        self.assertEqual(result['added'], {'total': 1512.34, 'text': '1 512,34 ₽', 'rawId': ''})
        self.assertEqual(result['assigned'], {'total': 1520.05, 'balances': {'main': 1000, 'saved': 520.05}})
        self.assertEqual(result['unassigned'], {'total': 1520.05, 'balances': {'main': 1020.05, 'saved': 500}})
        self.assertEqual(result['removed'], 1500)
        self.assertEqual(result['restored'], 1520.05)
        self.assertEqual(result['text'], '1 520,05 ₽')
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['record']['type'], 'income')
        self.assertEqual(result['record']['amount'], 20.05)
        self.assertEqual(result['record']['store'], 'Тестовый доход')
        self.assertNotIn('accountId', result['record'])

    def test_reentering_current_actual_balance_covers_prior_income_and_survives_reload_or_profile_change(self):
        result = self.evaluate('''
          state.entries=[incomeEntry('old-income',100,{date:'2026-11-05',created_at:'2026-11-05T08:00:00.000Z'})];
          const original=JSON.stringify(state.entries);await saveActualIncomeBalance(2000);
          const first=incomeBank();advanceIncomeClock(2000);state.entries.push(incomeEntry('first-new',100));renderAll();
          const credited=incomeBank();advanceIncomeClock(2000);await saveActualIncomeBalance(2000);
          const reset=incomeBank();state=normalize(JSON.parse(JSON.stringify(state)));
          currentProfile=()=>({id:'another-user',name:'Другой участник'});renderHome();
          const reloaded=incomeBank();advanceIncomeClock(2000);state.entries.push(incomeEntry('next-new',.20));renderAll();
          return {first,credited,reset,reloaded,total:incomeBank(),income:v111MonthBalance('2026-11').income,
            originalUnchanged:JSON.stringify(state.entries.slice(0,1))===original,
            count:state.entries.length,corrections:state.entries.filter(e=>e.balanceAdjustment).length};
        ''')
        self.assertEqual(result['first'], 2000)
        self.assertEqual(result['credited'], 2100)
        self.assertEqual(result['reset'], 2000)
        self.assertEqual(result['reloaded'], 2000)
        self.assertEqual(result['total'], 2000.20)
        self.assertEqual(result['income'], 200.20)
        self.assertTrue(result['originalUnchanged'])
        self.assertEqual(result['count'], 3)
        self.assertEqual(result['corrections'], 0)

    def test_reconciliation_cutoff_sees_income_once_and_new_adjustments_are_income_aware(self):
        result = self.evaluate('''
          await saveActualIncomeBalance(1000);advanceIncomeClock(2000);
          state.entries.push(incomeEntry('first-income',100));renderAll();
          v117OpenReconcile('main');document.getElementById('v117SnapshotAmount').value='1100';
          await v117SaveSnapshot();const firstSnapshot=JSON.parse(JSON.stringify(v117AccountRecord('main').snapshotVerification));
          const firstDifference=v117AccountBalance('main').difference;await v117AdjustAccount('main');
          const firstCount=state.entries.length;advanceIncomeClock(2000);
          state.entries.push(incomeEntry('second-income',25,{created_at:firstSnapshot.verifiedAt}));renderAll();
          const before={total:incomeBank(),difference:v117AccountBalance('main').difference};
          v117OpenReconcile('main');document.getElementById('v117SnapshotAmount').value='1130';
          await v117SaveSnapshot();await v117AdjustAccount('main');await v117AdjustAccount('main');
          const oldPoint=v117LedgerAt(v117AccountRecord('main'),today(),{
            at:firstSnapshot.verifiedAt,revision:firstSnapshot.revision,
            existingSameDayEntryIds:firstSnapshot.existingSameDayEntryIds}).balance;
          return {firstDifference,firstCount,before,total:incomeBank(),oldPoint,
            income:v111MonthBalance('2026-11').income,
            corrections:state.entries.filter(e=>e.balanceAdjustment).map(e=>({amount:e.amount,
              direction:e.adjustmentDirection,type:e.type,incomeAware:e.unassignedIncomeVersion,
              expenseAware:e.unassignedExpenseVersion}))};
        ''')
        self.assertEqual(result['firstDifference'], 0)
        self.assertEqual(result['firstCount'], 1)
        self.assertEqual(result['before'], {'total': 1125, 'difference': 0})
        self.assertEqual(result['total'], 1130)
        self.assertEqual(result['oldPoint'], 1100)
        self.assertEqual(result['income'], 125)
        self.assertEqual(result['corrections'], [{'amount': 5, 'direction': 1, 'type': 'transfer',
                                                'incomeAware': 1, 'expenseAware': 1}])
        cutoffs = self.evaluate('''
          const results=[];
          for(const type of ['expense','income']){
            state.intelligence.accounts=[incomeAccount()];
            state.entries=[incomeEntry('flow',100,{type,date:'2026-11-09',
              created_at:'2026-11-09T10:00:00.000Z'}),
              incomeEntry('late-adjustment',20,{type:'transfer',date:'2026-11-09',
                accountId:'main',balanceAdjustment:true,adjustmentDirection:1,
                reconciliationRevision:'R1',created_at:'2026-11-09T12:00:00.000Z'})];
            const cutoff={at:'2026-11-09T11:00:00.000Z',revision:'R2',existingSameDayEntryIds:['flow']};
            const beforeLateCorrection=v117LedgerAt(v117AccountRecord('main'),'2026-11-09',cutoff);
            Object.assign(state.entries[1],{reconciliationRevision:'R2',
              unassignedIncomeVersion:1,unassignedExpenseVersion:1});
            const sameReconciliation=v117LedgerAt(v117AccountRecord('main'),'2026-11-09',cutoff);
            results.push({type,before:beforeLateCorrection.balance,adjustments:beforeLateCorrection.adjustments,
              sameReconciliation:sameReconciliation.balance});
          }
          return results;
        ''')
        self.assertEqual(cutoffs, [
            {'type': 'expense', 'before': 900, 'adjustments': 0, 'sameReconciliation': 920},
            {'type': 'income', 'before': 1100, 'adjustments': 0, 'sameReconciliation': 1120},
        ])

    def test_legacy_expense_aware_adjustment_already_covering_income_is_not_credited_twice(self):
        result = self.evaluate('''
          const main=v117AccountRecord('main'),revision='old-income-verification';
          main.amount=1100;main.snapshotDate='2026-11-08';main.snapshotRevision=revision;
          main.snapshotVerification={amount:1100,date:'2026-11-08',revision,
            verifiedAt:'2026-11-08T12:00:00.000Z',accountUpdatedAt:main.updated_at};
          state.entries=[incomeEntry('covered-income',100,{date:'2026-11-05',created_at:'2026-11-05T08:00:00.000Z'}),
            incomeEntry('old-adjustment',100,{type:'transfer',category:'Движение денег',date:'2026-11-08',
              accountId:'main',balanceAdjustment:true,adjustmentDirection:1,unassignedExpenseVersion:1,
              reconciliationRevision:revision,expectedBalance:1000,actualBalance:1100,
              created_at:'2026-11-08T12:00:00.000Z',updated_at:'2026-11-08T12:00:00.000Z'})];
          const history=JSON.stringify(state.entries);renderHome();const covered=incomeBank();
          state.entries.push(incomeEntry('later-income',25,{date:'2026-11-09',created_at:'2026-11-09T08:00:00.000Z'}),
            incomeEntry('later-expense',10,{type:'expense',category:'Продукты',date:'2026-11-09',created_at:'2026-11-09T09:00:00.000Z'}));
          renderHome();return {covered,total:incomeBank(),difference:v117AccountBalance('main').difference,
            coveredId:v165CashflowAccountId(state.entries[0]),
            rawUnchanged:JSON.stringify(state.entries.slice(0,2))===history};
        ''')
        self.assertEqual(result['covered'], 1100)
        self.assertEqual(result['total'], 1115)
        self.assertEqual(result['difference'], 0)
        self.assertFalse(result['coveredId'])
        self.assertTrue(result['rawUnchanged'])

    def test_invalid_deleted_before_start_and_future_income_do_not_credit_today_and_internal_moves_are_not_income(self):
        result = self.evaluate('''
          const saved=incomeAccount('saved',500);saved.ledger.includeInSpending=false;
          state.intelligence.accounts.push(saved);
          state.entries=[incomeEntry('valid-a',100.10),incomeEntry('valid-b',.20),
            incomeEntry('before-start',400,{date:'2026-10-31'}),incomeEntry('future',500,{date:'2026-11-16'}),
            incomeEntry('deleted',600,{created_at:'2026-11-05T08:00:00.000Z',updated_at:'2026-11-05T08:00:00.000Z'}),
            incomeEntry('boolean',true),incomeEntry('array',[1]),incomeEntry('negative',-100),incomeEntry('zero',0),
            incomeEntry('string-amount','100'),incomeEntry('bad-date',100,{date:'2026-11-31'}),
            incomeEntry('wrong-fields',100,{fromAccountId:'main'}),
            incomeEntry('transfer',50,{type:'transfer',category:'Движение денег',fromAccountId:'main',toAccountId:'saved'}),
            incomeEntry('cash',30,{type:'cash',category:'Движение денег',fromAccountId:'main',toAccountId:'saved'})];
          state.deletedEntries={deleted:'2026-11-06T08:00:00.000Z'};
          const history=JSON.stringify(state.entries);const total=incomeBank(),balances=incomeBalances();
          return {total,balances,ids:Object.fromEntries(state.entries.map(e=>[e.id,v165CashflowAccountId(e)])),
            unchanged:JSON.stringify(state.entries)===history};
        ''')
        self.assertEqual(result['total'], 1600.30)
        self.assertEqual(result['balances'], {'main': 1020.30, 'saved': 580})
        for name in ['before-start', 'future', 'boolean', 'array', 'negative', 'zero', 'string-amount',
                     'bad-date', 'wrong-fields', 'transfer', 'cash']:
            self.assertFalse(result['ids'][name], name)
        self.assertTrue(result['unchanged'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
