"""Shared family spending debits the effective account once, without rewriting history.

Run: python -m unittest discover -s tests -p test_general_budget_expenses.py
All browser requests are isolated synthetic data; every external request is blocked.
"""
from pathlib import Path
import os
import shutil
import unittest

from playwright.sync_api import sync_playwright


HTML = (Path(__file__).resolve().parents[1] / 'index.html').read_text()
BASE = 'http://127.0.0.1:9869/'


class GeneralBudgetExpenses(unittest.TestCase):
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
        self.page.wait_for_function("typeof v157ExpenseAccountId==='function'")
        self.page.evaluate('''() => {
          session=null;localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=null;
          localStorage.clear();state=blankState();saveAll=async()=>true;
          today=()=> '2026-11-12';month=()=> '2026-11';
          window.budgetAccount=(id,opening,fields={})=>{
            const stamp=new Date().toISOString(),revision='snapshot-'+id;
            return {id,name:id==='main'?'Общий счёт':'Второй счёт',amount:opening,
              snapshotDate:'2026-11-01',snapshotRevision:revision,
              created_at:stamp,updated_at:stamp,
              snapshotVerification:{amount:opening,date:'2026-11-01',revision,
                verifiedAt:stamp,accountUpdatedAt:stamp},
              ledger:{version:1,enabled:true,startDate:'2026-11-01',
                openingBalance:opening,kind:'asset',includeInSpending:true},...fields};
          };
          window.budgetEntry=(id,amount,fields={})=>({id,type:'expense',amount,
            date:'2026-11-05',category:'Продукты',beneficiary:'Общее',who:'Общее',
            store:'Синтетическая покупка',comment:'',pay:'Карта',
            created_at:'2026-11-05T12:00:00.000Z',
            updated_at:'2026-11-05T12:00:00.000Z',...fields});
          state.intelligence.accounts=[budgetAccount('main',1000)];state.entries=[];
          showApp();go('home');document.getElementById('homeMonth').value='2026-11';
          renderHome();
          window.budgetTotal=()=>v150HomeBankData().total;
          window.budgetBalances=()=>Object.fromEntries(v150HomeBankData().items.map(x=>[x.id,x.balance]));
          window.budgetText=()=>document.getElementById('v121HomeAvailable').textContent.replaceAll('\\u00a0',' ');
          window.sharedChoice=(id)=>{document.getElementById('v157SharedExpenseAccount').value=id};
        }''')

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def evaluate(self, code):
        return self.page.evaluate('async () => {' + code + '}')

    def test_existing_expenses_reduce_810000_budget_and_account_once_without_rewriting_history(self):
        result = self.evaluate('''
          state.intelligence.accounts=[budgetAccount('main',810000)];
          state.entries=[budgetEntry('a',100000),budgetEntry('b',238903.21),
            budgetEntry('income',811300,{type:'income',category:'Доход'})];
          const original=JSON.stringify(state.entries),opening=JSON.stringify(state.intelligence.accounts);
          renderHome();renderHome();
          const before=budgetTotal();
          const period=document.getElementById('homeMonth');period.add(new Option('октябрь 2026','2026-10'));
          period.value='2026-10';renderHome();
          return {before,afterMonthChange:budgetTotal(),balances:budgetBalances(),
            displayed:document.getElementById('v121HomeAvailable').textContent.replaceAll('\\u00a0',' '),
            account:v157SharedExpenseAccount().id,effective:state.entries.map(v157ExpenseAccountId),
            sameHistory:JSON.stringify(state.entries)===original,
            sameOpening:JSON.stringify(state.intelligence.accounts)===opening};
        ''')
        self.assertEqual(result['before'], 471096.79)
        self.assertEqual(result['afterMonthChange'], 471096.79)
        self.assertEqual(result['balances'], {'main': 471096.79})
        self.assertEqual(result['displayed'], '471 096,79 ₽')
        self.assertEqual(result['account'], 'main')
        self.assertEqual(result['effective'][:2], ['main', 'main'])
        self.assertFalse(result['effective'][2])
        self.assertTrue(result['sameHistory'])
        self.assertTrue(result['sameOpening'])

    def test_dates_tombstones_explicit_references_and_other_money_movements_are_not_extra_spending(self):
        result = self.evaluate('''
          const saving=budgetAccount('saved',200);saving.ledger.includeInSpending=false;
          state.intelligence.accounts=[budgetAccount('main',1000),saving,
            budgetAccount('closed',0,{archived:true})];
          state.settings.preferences.unassignedExpenseAccountId='main';
          state.entries=[budgetEntry('unassigned',40.15),
            budgetEntry('assigned',9.85,{accountId:'main'}),
            budgetEntry('income-unassigned',99,{type:'income'}),
            budgetEntry('income-assigned',100,{type:'income',accountId:'main'}),
            budgetEntry('transfer',50,{type:'transfer',fromAccountId:'main',toAccountId:'saved'}),
            budgetEntry('cash',500,{type:'cash'}),
            budgetEntry('future',700,{date:'2026-12-01'}),
            budgetEntry('prior',200,{date:'2026-10-31'}),
            budgetEntry('deleted',800),
            budgetEntry('unknown-reference',500,{accountId:'unknown-account'}),
            budgetEntry('archived-reference',500,{accountId:'closed'}),
            budgetEntry('malformed-reference',500,{accountId:42}),
            budgetEntry('unexpected-pair',500,{fromAccountId:'main'}),
            budgetEntry('adjustment',500,{type:'transfer',balanceAdjustment:true}),
            budgetEntry('negative',-30),budgetEntry('zero',0)];
          state.deletedEntries={deleted:'2026-11-06T12:00:00.000Z'};
          const before=JSON.stringify(state.entries);renderHome();
          return {total:budgetTotal(),balances:budgetBalances(),
            unchanged:JSON.stringify(state.entries)===before,
            resolved:Object.fromEntries(state.entries.map(e=>[e.id,v157ExpenseAccountId(e)]))};
        ''')
        self.assertEqual(result['total'], 1250)
        self.assertEqual(result['balances'], {'main': 1000, 'saved': 250})
        self.assertEqual(result['resolved']['unassigned'], 'main')
        self.assertEqual(result['resolved']['assigned'], 'main')
        self.assertEqual(result['resolved']['unknown-reference'], 'unknown-account')
        self.assertEqual(result['resolved']['archived-reference'], 'closed')
        for name in ['future', 'prior', 'malformed-reference', 'unexpected-pair', 'cash', 'negative', 'zero']:
            self.assertFalse(result['resolved'][name], name)
        self.assertTrue(result['unchanged'])

    def test_real_add_edit_assign_unassign_delete_and_undo_keep_one_debit(self):
        result = self.evaluate('''
          const saved=budgetAccount('saved',500);saved.ledger.includeInSpending=false;
          state.intelligence.accounts=[budgetAccount('main',1000),saved];
          state.settings.preferences.unassignedExpenseAccountId='main';renderAll();
          openEntry('expense');document.getElementById('eAmount').value='100';
          document.getElementById('eDate').value=today();v90Choose('Продукты');
          document.getElementById('eAccountId').value='';await addEntry();
          const record=state.entries.at(-1),id=record.id,
            afterAdd=budgetTotal(),afterAddText=budgetText(),addedWithoutAccount=!record.accountId;
          openEdit(id);document.getElementById('xAmount').value='150';
          document.getElementById('xAccountId').value='saved';await saveEdit();
          const afterAssign=budgetTotal(),assignedBalances=budgetBalances();
          openEdit(id);document.getElementById('xAccountId').value='';await saveEdit();
          const afterUnassign=budgetTotal(),afterUnassignText=budgetText(),unassignedBalances=budgetBalances();
          await deleteEntry(id);const afterDelete=budgetTotal();await v119UndoDelete();
          return {afterAdd,afterAddText,addedWithoutAccount,afterAssign,assignedBalances,
            afterUnassign,afterUnassignText,unassignedBalances,afterDelete,afterUndo:budgetTotal(),afterUndoText:budgetText(),
            count:state.entries.length,finalAmount:state.entries[0]?.amount};
        ''')
        self.assertEqual(result['afterAdd'], 1400)
        self.assertEqual(result['afterAddText'], '1 400,00 ₽')
        self.assertTrue(result['addedWithoutAccount'])
        self.assertEqual(result['afterAssign'], 1350)
        self.assertEqual(result['assignedBalances'], {'main': 1000, 'saved': 350})
        self.assertEqual(result['afterUnassign'], 1350)
        self.assertEqual(result['afterUnassignText'], '1 350,00 ₽')
        self.assertEqual(result['unassignedBalances'], {'main': 850, 'saved': 500})
        self.assertEqual(result['afterDelete'], 1500)
        self.assertEqual(result['afterUndo'], 1350)
        self.assertEqual(result['afterUndoText'], '1 350,00 ₽')
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['finalAmount'], 150)

    def test_reconciliation_sees_implicit_expenses_and_only_adds_actual_extra_difference(self):
        result = self.evaluate('''
          state.entries=[budgetEntry('purchase',100)];renderAll();
          v117OpenReconcile('main');document.getElementById('v117SnapshotAmount').value='900';
          await v117SaveSnapshot();const exact=v117AccountBalance('main').difference;
          await v117AdjustAccount('main');const afterExact={total:budgetTotal(),count:state.entries.length};
          v117OpenReconcile('main');document.getElementById('v117SnapshotAmount').value='850';
          await v117SaveSnapshot();const difference=v117AccountBalance('main').difference;
          await v117AdjustAccount('main');await v117AdjustAccount('main');renderHome();
          return {exact,afterExact,difference,total:budgetTotal(),
            corrections:state.entries.filter(e=>e.balanceAdjustment).map(e=>({
              amount:e.amount,direction:e.adjustmentDirection,type:e.type})),
            expense:v111MonthBalance('2026-11').expense,
            original:state.entries.find(e=>e.id==='purchase')};
        ''')
        self.assertEqual(result['exact'], 0)
        self.assertEqual(result['afterExact'], {'total': 900, 'count': 1})
        self.assertEqual(result['difference'], -50)
        self.assertEqual(result['total'], 850)
        self.assertEqual(result['corrections'], [{'amount': 50, 'direction': -1, 'type': 'transfer'}])
        self.assertEqual(result['expense'], 100)
        self.assertNotIn('accountId', result['original'])

    def test_multiple_accounts_require_shared_choice_and_profile_or_viewer_cannot_redirect_it(self):
        result = self.evaluate('''
          state.intelligence.accounts=[budgetAccount('main',1000),budgetAccount('other',500)];
          state.entries=[budgetEntry('spend',100)];renderHome();
          const before=budgetTotal(),automatic=v157SharedExpenseAccount().id;
          sharedChoice('main');const ok=await v157SaveSharedExpenseAccount();
          const chosen=state.settings.preferences.unassignedExpenseAccountId,after=budgetTotal();
          const reloadedChoice=normalize(JSON.parse(JSON.stringify(state))).settings.preferences.unassignedExpenseAccountId;
          state.settings.preferences.defaultAccountByProfile={'other-user':'other'};
          currentProfile=()=>({id:'other-user',name:'Другой участник'});renderHome();
          const otherProfile=budgetTotal();
          state.settings.preferences.unassignedExpenseAccountId='other';
          state.settings.updated_at=v119MonotonicStamp(state.settings.updated_at);
          sharedChoice('main');const stale=await v157SaveSharedExpenseAccount(),
            staleChoice=state.settings.preferences.unassignedExpenseAccountId;
          state.settings.preferences.unassignedExpenseAccountId='main';renderHome();
          window.__FINANCE_BRIDGE__={active:true,role:'viewer'};
          sharedChoice('other');const denied=await v157SaveSharedExpenseAccount();
          const finalChoice=state.settings.preferences.unassignedExpenseAccountId,total=budgetTotal();
          window.__FINANCE_BRIDGE__=null;renderHome();sharedChoice('');
          const disabled=await v157SaveSharedExpenseAccount();
          state.intelligence.accounts=state.intelligence.accounts.filter(a=>a.id==='main');renderHome();
          const disabledTotal=budgetTotal(),disabledChoice=state.settings.preferences.unassignedExpenseAccountId;
          state.settings.preferences.unassignedExpenseAccountId='missing';renderHome();
          const invalidSaved=v157SharedExpenseAccount().invalid,invalidSavedTotal=budgetTotal();
          state.intelligence.accounts=[{id:'manual',name:'Ручной снимок',amount:1000,
            snapshotDate:today(),created_at:new Date().toISOString(),updated_at:new Date().toISOString()}];
          delete state.settings.preferences.unassignedExpenseAccountId;renderHome();
          const manualAutomatic=v157SharedExpenseAccount().id;
          state.settings.preferences.unassignedExpenseAccountId='manual';renderHome();
          return {before,automatic,ok,chosen,reloadedChoice,after,otherProfile,stale,staleChoice,denied,finalChoice,total,
            disabled,disabledTotal,disabledChoice,invalidSaved,invalidSavedTotal,manualAutomatic,
            manualInvalid:v157SharedExpenseAccount().invalid,manualTotal:budgetTotal()};
        ''')
        self.assertEqual(result['before'], 1500)
        self.assertFalse(result['automatic'])
        self.assertTrue(result['ok'])
        self.assertEqual(result['chosen'], 'main')
        self.assertEqual(result['reloadedChoice'], 'main')
        self.assertEqual(result['after'], 1400)
        self.assertEqual(result['otherProfile'], 1400)
        self.assertFalse(result['stale'])
        self.assertEqual(result['staleChoice'], 'other')
        self.assertFalse(result['denied'])
        self.assertEqual(result['finalChoice'], 'main')
        self.assertEqual(result['total'], 1400)
        self.assertTrue(result['disabled'])
        self.assertEqual(result['disabledChoice'], '')
        self.assertEqual(result['disabledTotal'], 1000)
        self.assertTrue(result['invalidSaved'])
        self.assertEqual(result['invalidSavedTotal'], 1000)
        self.assertFalse(result['manualAutomatic'])
        self.assertTrue(result['manualInvalid'])
        self.assertEqual(result['manualTotal'], 1000)

    def test_failed_shared_choice_rolls_back_and_old_family_completion_cannot_modify_new_family(self):
        result = self.evaluate('''
          state.intelligence.accounts=[budgetAccount('main',1000),budgetAccount('other',500)];
          state.entries=[budgetEntry('spend',100)];
          state.settings.preferences.unassignedExpenseAccountId='main';renderHome();
          const before=JSON.stringify(state.entries);saveAll=async()=>false;v89StorageFailed=true;
          sharedChoice('other');const failed=await v157SaveSharedExpenseAccount();
          const rollback={choice:state.settings.preferences.unassignedExpenseAccountId,total:budgetTotal(),
            unchanged:JSON.stringify(state.entries)===before};
          saveAll=async()=>{authEpoch++;state=blankState();return true};
          renderHome();sharedChoice('other');const switched=await v157SaveSharedExpenseAccount();
          return {failed,rollback,switched,newAccounts:v117AccountRecords().length,
            newEntries:state.entries.length,newChoice:state.settings.preferences.unassignedExpenseAccountId||null};
        ''')
        self.assertFalse(result['failed'])
        self.assertEqual(result['rollback'], {'choice': 'main', 'total': 1400, 'unchanged': True})
        self.assertFalse(result['switched'])
        self.assertEqual(result['newAccounts'], 0)
        self.assertEqual(result['newEntries'], 0)
        self.assertIsNone(result['newChoice'])

    def test_adding_second_account_through_each_editor_pins_original_default(self):
        for path in ['home', 'manual', 'ledger']:
            with self.subTest(path=path):
                result = self.evaluate('''
                  state=blankState();state.intelligence.accounts=[budgetAccount('main',1000)];
                  state.entries=[budgetEntry('spend',100)];renderAll();
                  const original=JSON.stringify(state.entries),before=budgetTotal();
                ''' + {
                    'home': '''
                      v150OpenHomeAccount();document.getElementById('v150AccountName').value='Второй счёт';
                      document.getElementById('v150AccountDate').value='2026-11-01';
                      document.getElementById('v150AccountOpening').value='500';await v150SaveHomeAccount();
                    ''',
                    'manual': '''
                      go('accounts');document.getElementById('v84AccountName').value='Второй счёт';
                      document.getElementById('v84AccountAmount').value='500';
                      document.getElementById('v117ManualDate').value='2026-11-01';await v84SaveAccount();
                    ''',
                    'ledger': '''
                      state.intelligence.accounts.push({id:'other',name:'Второй счёт',amount:500,
                        snapshotDate:'2026-11-01',created_at:new Date().toISOString(),updated_at:new Date().toISOString()});
                      v117OpenLedger('other');document.getElementById('v117LedgerDate').value='2026-11-01';
                      document.getElementById('v117LedgerOpening').value='500';
                      document.getElementById('v117LedgerKind').value='asset';
                      document.getElementById('v117LedgerSpending').value='yes';
                      document.getElementById('v117OpeningConfirmed').checked=true;await v117SaveLedger();
                    ''',
                }[path] + '''
                  renderHome();return {before,total:budgetTotal(),choice:state.settings.preferences.unassignedExpenseAccountId,
                    effective:v157ExpenseAccountId(state.entries[0]),unchanged:JSON.stringify(state.entries)===original};
                ''')
                self.assertEqual(result['before'], 900)
                self.assertEqual(result['total'], 1400)
                self.assertEqual(result['choice'], 'main')
                self.assertEqual(result['effective'], 'main')
                self.assertTrue(result['unchanged'])

    def test_shared_account_cannot_close_until_implicit_history_is_explicitly_assigned(self):
        result = self.evaluate('''
          const main=budgetAccount('main',100),saved=budgetAccount('saved',500);
          saved.ledger.includeInSpending=false;state.intelligence.accounts=[main,saved];
          state.entries=[budgetEntry('spend',100)];
          state.settings.preferences.unassignedExpenseAccountId='main';
          v117VerifySnapshot(main,0,today(),v117RecordStamp(main));renderAll();
          const blocked=await v117ArchiveAccount('main'),firstArchived=main.archived===true;
          state.entries[0].accountId='main';state.entries[0].updated_at=new Date().toISOString();
          const closed=await v117ArchiveAccount('main');
          state.entries.push(budgetEntry('new-spend',25));renderHome();
          const shared=v157SharedExpenseAccount();
          return {blocked,firstArchived,closed,unavailable:shared.invalid||shared.disabled,
            effective:v157ExpenseAccountId(state.entries.at(-1)),total:budgetTotal()};
        ''')
        self.assertFalse(result['blocked'])
        self.assertFalse(result['firstArchived'])
        self.assertTrue(result['closed'])
        self.assertTrue(result['unavailable'])
        self.assertFalse(result['effective'])
        self.assertEqual(result['total'], 500)

    def test_legacy_reconciliation_already_covering_old_unassigned_expenses_is_not_debited_twice(self):
        result = self.evaluate('''
          const main=budgetAccount('main',1000),revision='legacy-verification';
          main.amount=900;main.snapshotDate='2026-11-08';main.snapshotRevision=revision;
          main.snapshotVerification={amount:900,date:'2026-11-08',revision,
            verifiedAt:'2026-11-08T12:00:00.000Z',accountUpdatedAt:main.updated_at};
          state.intelligence.accounts=[main];
          state.entries=[budgetEntry('old-unassigned',100),
            budgetEntry('legacy-adjustment',100,{type:'transfer',date:'2026-11-08',
              accountId:'main',balanceAdjustment:true,adjustmentDirection:-1,
              reconciliationRevision:revision,expectedBalance:1000,actualBalance:900,
              created_at:'2026-11-08T12:00:00.000Z',updated_at:'2026-11-08T12:00:00.000Z'})];
          const before=JSON.stringify(state.entries);renderHome();const legacy=budgetTotal(),
            beforeReconciliation=v117LedgerAt(main,'2026-11-07').balance;
          state.entries.push(budgetEntry('after-reconciliation',25,{date:'2026-11-09'}));renderHome();
          return {legacy,beforeReconciliation,after:budgetTotal(),unchanged:JSON.stringify(state.entries.slice(0,2))===before,
            balance:v117AccountBalance('main').balance};
        ''')
        self.assertEqual(result['legacy'], 900)
        self.assertEqual(result['beforeReconciliation'], 900)
        self.assertEqual(result['after'], 875)
        self.assertEqual(result['balance'], 875)
        self.assertTrue(result['unchanged'])

    def test_failed_saves_restore_shared_choice_without_losing_concurrent_unrelated_preferences(self):
        result = self.evaluate('''
          state.intelligence.accounts=[budgetAccount('main',1000),budgetAccount('other',500)];
          state.entries=[budgetEntry('spend',100)];
          state.settings.preferences.unassignedExpenseAccountId='main';renderHome();
          let unrelatedStamp;
          saveAll=async()=>{
            state.settings.preferences.unrelatedView='changed-during-save';
            state.settings.updated_at=v119MonotonicStamp(state.settings.updated_at);
            unrelatedStamp=state.settings.updated_at;return false;
          };v89StorageFailed=true;
          sharedChoice('other');const selectionResult=await v157SaveSharedExpenseAccount();
          const selection={ok:selectionResult,choice:state.settings.preferences.unassignedExpenseAccountId,
            unrelated:state.settings.preferences.unrelatedView,total:budgetTotal(),
            stampPreserved:state.settings.updated_at>=unrelatedStamp};
          state=blankState();state.entries=[budgetEntry('spend',100)];renderAll();
          v150OpenHomeAccount();document.getElementById('v150AccountName').value='Новый счёт';
          document.getElementById('v150AccountDate').value='2026-11-01';
          document.getElementById('v150AccountOpening').value='1000';
          const accountResult=await v150SaveHomeAccount();
          return {selection,account:{ok:accountResult,count:v117AccountRecords().length,
            danglingChoice:Object.hasOwn(state.settings.preferences,'unassignedExpenseAccountId'),
            unrelated:state.settings.preferences.unrelatedView,total:budgetTotal(),
            stampPreserved:state.settings.updated_at>=unrelatedStamp}};
        ''')
        self.assertEqual(result['selection'], {
            'ok': False, 'choice': 'main', 'unrelated': 'changed-during-save',
            'total': 1400, 'stampPreserved': True})
        self.assertEqual(result['account'], {
            'ok': False, 'count': 0, 'danglingChoice': False,
            'unrelated': 'changed-during-save', 'total': None, 'stampPreserved': True})


if __name__ == '__main__':
    unittest.main(verbosity=2)
