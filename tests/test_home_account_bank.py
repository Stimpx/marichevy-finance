"""Family bank balances use real account ledgers, without income duplication.

Run: python -m unittest discover -s tests -p test_home_account_bank.py
Playwright and Chromium are required. Every external request is blocked.
"""
from pathlib import Path
import os
import shutil
import unittest

from playwright.sync_api import sync_playwright


HTML = (Path(__file__).resolve().parents[1] / 'index.html').read_text()
BASE = 'http://127.0.0.1:9893/'


class HomeAccountBank(unittest.TestCase):
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
        self.page.wait_for_function("typeof v150HomeBankData==='function'")
        self.page.evaluate('''() => {
          session=null;localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=null;
          localStorage.clear();state=blankState();
          today=()=> '2026-11-09';month=()=> '2026-11';
          window.bankTestAccount=(id,name,opening,extra={})=>{
            const now=new Date().toISOString(),revision='verified-'+id;
            return {id,name,amount:opening,snapshotDate:today(),
              snapshotRevision:revision,created_at:now,updated_at:now,
              snapshotVerification:{amount:opening,date:today(),revision,
                verifiedAt:now,accountUpdatedAt:now},
              ledger:{version:1,enabled:true,startDate:'2026-11-01',
                openingBalance:opening,kind:'asset',includeInSpending:true},...extra};
          };
          window.bankTestEntry=(id,type,amount,extra={})=>({
            id,type,amount,date:'2026-11-05',category:type==='income'?'Доход':'Продукты',
            beneficiary:'Общее',who:'Общее',store:'Тест',comment:'',
            created_at:'2026-11-05T12:00:00.000Z',
            updated_at:'2026-11-05T12:00:00.000Z',...extra});
          state.entries=[bankTestEntry('old-income','income',99999,
            {date:'2026-10-01'})];
          showApp();go('home');
          document.getElementById('homeMonth').value='2026-11';renderHome();
          window.bankTestFill=(name,opening,date='2026-11-01')=>{
            document.getElementById('v150AccountName').value=name;
            document.getElementById('v150AccountOpening').value=String(opening);
            document.getElementById('v150AccountDate').value=date;
          };
          window.readBankText=()=>document.getElementById('v121HomeAvailable')
            .textContent.replaceAll('\\u00a0',' ');
        }''')

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def evaluate(self, code):
        return self.page.evaluate('async () => {' + code + '}')

    def test_real_account_total_includes_protected_savings_and_excludes_debt_and_archived(self):
        result = self.evaluate('''
          const card=bankTestAccount('card','Карта',1000.10),
            savings=bankTestAccount('savings','Накопления',5000.20),
            debt=bankTestAccount('debt','Кредитная карта',-900),
            archived=bankTestAccount('closed','Закрытый',8888,{archived:true});
          savings.ledger.includeInSpending=false;
          debt.ledger={...debt.ledger,kind:'debt',includeInSpending:false,creditLimit:50000};
          state.intelligence.accounts=[card,savings,debt,archived];
          state.entries.push(
            bankTestEntry('income','income',20.20,{accountId:'card'}),
            bankTestEntry('expense','expense',10.10,{accountId:'card'}),
            bankTestEntry('move','transfer',100,{fromAccountId:'card',toAccountId:'savings'}),
            bankTestEntry('future','income',10000,{date:'2026-12-01',accountId:'card'}));
          const before=JSON.stringify(state);renderHome();const data=v150HomeBankData();
          return {total:data.total,unknown:data.unknownCount,text:readBankText(),
            title:document.getElementById('v121HomeAvailableTitle').textContent,
            names:document.getElementById('v150HomeAccounts').textContent,
            unchanged:JSON.stringify(state)===before,
            balances:data.items.map(item=>[item.id,item.balance])};
        ''')
        self.assertAlmostEqual(result['total'], 6010.40)
        self.assertEqual(result['unknown'], 0)
        self.assertEqual(result['text'], '6 010,40 ₽')
        self.assertEqual(result['title'], 'Общий банк семьи по всем счетам')
        self.assertIn('Карта', result['names'])
        self.assertIn('Накопления', result['names'])
        self.assertNotIn('Закрытый', result['names'])
        self.assertNotIn('Кредитная карта', result['names'])
        self.assertEqual(dict(result['balances']), {'card': 910.2, 'savings': 5100.2})
        self.assertTrue(result['unchanged'])

    def test_unknown_account_balance_is_disclosed_without_inventing_money(self):
        result = self.evaluate('''
          const known=bankTestAccount('known','Карта',1200.25),
            unknown=bankTestAccount('unknown','Поздний счёт',9000);
          unknown.ledger.startDate='2026-12-01';
          state.intelligence.accounts=[known,unknown];renderHome();
          const data=v150HomeBankData();
          return {total:data.total,unknown:data.unknownCount,text:readBankText(),
            note:document.getElementById('v121HomeAvailableNote').textContent,
            list:document.getElementById('v150HomeAccounts').textContent};
        ''')
        self.assertEqual(result['total'], 1200.25)
        self.assertEqual(result['unknown'], 1)
        self.assertNotIn('10 200', result['text'])
        self.assertIn('Не все остатки', result['note'])
        self.assertIn('Поздний счёт', result['list'])

    def test_no_accounts_does_not_present_history_carry_as_real_savings(self):
        result = self.evaluate('''
          const before=JSON.stringify(state.entries);renderHome();const data=v150HomeBankData();
          return {total:data.total,text:readBankText(),
            note:document.getElementById('v121HomeAvailableNote').textContent,
            unchanged:JSON.stringify(state.entries)===before};
        ''')
        self.assertIsNone(result['total'])
        self.assertNotIn('99 999', result['text'])
        self.assertIn('сч', result['note'].lower())
        self.assertTrue(result['unchanged'])

    def test_new_opening_balance_is_not_income_and_is_available_in_new_operation(self):
        result = self.evaluate('''
          const before=JSON.stringify(state.entries),income=v111MonthBalance('2026-11').income;
          saveAll=async()=>true;v150OpenHomeAccount();bankTestFill('Накопления',12345.67);
          const ok=await v150SaveHomeAccount(),accounts=v117AccountRecords();renderHome();
          const account=accounts[0],fields=JSON.stringify(state.entries)===before;
          openEntry('expense');
          return {ok,count:accounts.length,account,
            incomeBefore:income,incomeAfter:v111MonthBalance('2026-11').income,
            fields,text:readBankText(),choices:v117SelectableAccounts().map(a=>a.id)};
        ''')
        self.assertTrue(result['ok'])
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['account']['name'], 'Накопления')
        self.assertEqual(result['account']['ledger']['openingBalance'], 12345.67)
        self.assertEqual(result['account']['ledger']['startDate'], '2026-11-01')
        self.assertEqual(result['account']['ledger']['kind'], 'asset')
        self.assertTrue(result['account']['ledger']['enabled'])
        self.assertEqual(result['text'], '12 345,67 ₽')
        self.assertEqual(result['incomeBefore'], result['incomeAfter'])
        self.assertTrue(result['fields'])
        self.assertIn(result['account']['id'], result['choices'])

    def test_edit_starting_balance_preserves_operations_and_recalculates_current_total(self):
        result = self.evaluate('''
          state.intelligence.accounts=[bankTestAccount('card','Карта',1000)];
          state.entries.push(bankTestEntry('income','income',200,{accountId:'card'}),
            bankTestEntry('expense','expense',50.25,{accountId:'card'}));
          const before=JSON.stringify(state.entries),monthly=JSON.stringify(v111MonthBalance('2026-11')),
            snapshot=JSON.parse(JSON.stringify(v117AccountRecord('card').snapshotVerification));
          saveAll=async()=>true;renderHome();v150OpenHomeAccount('card');
          bankTestFill('Карта семьи',1500.50);const ok=await v150SaveHomeAccount();renderHome();
          return {ok,text:readBankText(),count:v117AccountRecords().length,
            opening:v117AccountRecord('card').ledger.openingBalance,
            current:v117AccountBalance('card').balance,
            unchanged:JSON.stringify(state.entries)===before,
            monthlyUnchanged:JSON.stringify(v111MonthBalance('2026-11'))===monthly,
            snapshotBefore:snapshot,snapshotAfter:v117AccountRecord('card').snapshotVerification};
        ''')
        self.assertTrue(result['ok'])
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['opening'], 1500.50)
        self.assertEqual(result['current'], 1650.25)
        self.assertEqual(result['text'], '1 650,25 ₽')
        self.assertTrue(result['unchanged'])
        self.assertTrue(result['monthlyUnchanged'])
        for key in ['amount', 'date', 'revision', 'verifiedAt']:
            self.assertEqual(result['snapshotBefore'][key], result['snapshotAfter'][key])

    def test_viewer_and_concurrent_account_change_cannot_overwrite_balance(self):
        result = self.evaluate('''
          state.intelligence.accounts=[bankTestAccount('card','Карта',1000)];
          let saves=0;saveAll=async()=>{saves++;return true};renderHome();
          v150OpenHomeAccount('card');bankTestFill('Карта',5000);
          const account=v117AccountRecord('card');account.ledger.openingBalance=1700;
          account.updated_at=v117RecordStamp(account);
          const staleResult=await v150SaveHomeAccount();
          window.__FINANCE_BRIDGE__={active:true,role:'viewer'};
          v150OpenHomeAccount('card');bankTestFill('Попытка',9999);
          const viewerResult=await v150SaveHomeAccount();
          return {staleResult,viewerResult,saves,
            opening:v117AccountRecord('card').ledger.openingBalance,
            name:v117AccountRecord('card').name};
        ''')
        self.assertFalse(result['staleResult'])
        self.assertFalse(result['viewerResult'])
        self.assertEqual(result['saves'], 0)
        self.assertEqual(result['opening'], 1700)
        self.assertEqual(result['name'], 'Карта')

    def test_save_completion_after_household_change_does_not_modify_new_family(self):
        result = self.evaluate('''
          saveAll=async()=>{authEpoch++;state=blankState();return true};
          v150OpenHomeAccount();bankTestFill('Старый семейный счёт',1000);
          const ok=await v150SaveHomeAccount();
          return {ok,accounts:v117AccountRecords().length,entries:state.entries.length};
        ''')
        self.assertFalse(result['ok'])
        self.assertEqual(result['accounts'], 0)
        self.assertEqual(result['entries'], 0)

    def test_closing_dialog_during_failed_save_still_rolls_back_own_account_mutation(self):
        result = self.evaluate('''
          const before=JSON.stringify(state.entries);let finish;
          saveAll=()=>new Promise(resolve=>{finish=resolve});v89StorageFailed=true;
          v150OpenHomeAccount();bankTestFill('Незавершённое сохранение',1000.25);
          const pending=v150SaveHomeAccount(),during=v117AccountRecords().length;
          v150CloseHomeAccount();finish(false);const ok=await pending;
          return {ok,during,count:v117AccountRecords().length,
            unchanged:JSON.stringify(state.entries)===before};
        ''')
        self.assertFalse(result['ok'])
        self.assertEqual(result['during'], 1)
        self.assertEqual(result['count'], 0)
        self.assertTrue(result['unchanged'])

    def test_failed_save_retry_does_not_duplicate_account_or_create_income(self):
        result = self.evaluate('''
          const before=JSON.stringify(state.entries);let saves=0;
          saveAll=async()=>{saves++;return saves>1};v89StorageFailed=true;
          v150OpenHomeAccount();bankTestFill('Накопления',1000.25);
          const failed=await v150SaveHomeAccount(),countAfterFailure=v117AccountRecords().length;
          const succeeded=await v150SaveHomeAccount();renderHome();
          return {failed,succeeded,countAfterFailure,count:v117AccountRecords().length,
            text:readBankText(),unchanged:JSON.stringify(state.entries)===before,saves};
        ''')
        self.assertFalse(result['failed'])
        self.assertTrue(result['succeeded'])
        self.assertEqual(result['countAfterFailure'], 0)
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['saves'], 2)
        self.assertEqual(result['text'], '1 000,25 ₽')
        self.assertTrue(result['unchanged'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
