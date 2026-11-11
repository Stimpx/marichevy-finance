"""Entering a current bank balance starts from that fact, without replaying old purchases.

Run: python -m unittest discover -s tests -p test_current_account_balance.py
Every browser request is isolated synthetic data; external requests are blocked.
"""
from pathlib import Path
import os
import shutil
import unittest

from playwright.sync_api import sync_playwright


HTML = (Path(__file__).resolve().parents[1] / 'index.html').read_text()
BASE = 'http://127.0.0.1:9868/'


class CurrentAccountBalance(unittest.TestCase):
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
        self.page.wait_for_function("typeof v161CurrentBalanceAnchor==='function'")
        self.page.evaluate('''() => {
          const NativeDate=Date;let currentTime=NativeDate.parse('2026-11-12T12:00:00.000Z');
          window.Date=class extends NativeDate {
            constructor(...args){super(...(args.length?args:[currentTime]))}
            static now(){return currentTime}
          };
          window.advanceBalanceTime=ms=>{currentTime+=ms};
          session=null;localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=null;
          localStorage.clear();state=blankState();saveAll=async()=>true;
          today=()=>new Date().toISOString().slice(0,10);month=()=>today().slice(0,7);
          window.actualAccount=(id='main',opening=810000,fields={})=>{
            const at='2026-10-01T09:00:00.000Z',revision='opening-'+id;
            return {id,name:id==='main'?'Общий счёт':'Накопления',amount:opening,
              snapshotDate:'2026-10-01',snapshotRevision:revision,
              created_at:at,updated_at:at,
              snapshotVerification:{amount:opening,date:'2026-10-01',revision,
                verifiedAt:at,accountUpdatedAt:at},
              ledger:{version:1,enabled:true,startDate:'2026-10-01',
                openingBalance:opening,kind:'asset',includeInSpending:true},...fields};
          };
          window.actualEntry=(id,amount,fields={})=>({id,type:'expense',amount,date:today(),
            category:'Продукты',beneficiary:'Общее',who:'Общее',store:'Синтетическая покупка',
            comment:'Ручная заметка',pay:'Карта',
            created_at:new Date().toISOString(),updated_at:new Date().toISOString(),...fields});
          state.intelligence.accounts=[actualAccount()];
          state.entries=Array.from({length:272},(_,i)=>{
            const period=i<136?'2026-10':'2026-11',day=String(i%11+1).padStart(2,'0'),date=period+'-'+day;
            return actualEntry('old-'+i,i===271?125000:2000,{date,
              created_at:date+'T08:00:00.000Z',updated_at:date+'T08:00:00.000Z',
              ...(i%2?{accountId:'main'}:{})});
          });
          state.entries.push(actualEntry('old-income',811300,{type:'income',category:'Доход',
            date:'2026-11-01',created_at:'2026-11-01T08:00:00.000Z',updated_at:'2026-11-01T08:00:00.000Z'}));
          showApp();go('home');document.getElementById('homeMonth').value='2026-11';renderHome();
          window.currentBank=()=>v150HomeBankData().total;
          window.currentBankText=()=>document.getElementById('v121HomeAvailable').textContent.replaceAll('\\u00a0',' ');
          window.fillCurrentBalance=(amount,name='Общий счёт')=>{
            document.getElementById('v150AccountName').value=name;
            document.getElementById('v150AccountOpening').value=String(amount);
          };
          window.captureActualReports=()=>({
            october:v111MonthBalance('2026-10').expense,november:v111MonthBalance('2026-11').expense,
            year:sum(state.entries.filter(e=>isExpense(e)&&e.date.startsWith('2026-'))),
            income:sum(state.entries.filter(e=>e.type==='income')),
            allExpenses:sum(state.entries.filter(isExpense))});
        }''')

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def evaluate(self, code):
        return self.page.evaluate('async () => {' + code + '}')

    def test_current_800000_replaces_old_computed_143000_without_changing_history_or_reports(self):
        result = self.evaluate('''
          const before=currentBank(),history=JSON.stringify(state.entries),reports=captureActualReports();
          v150OpenHomeAccount('main');fillCurrentBalance(800000);const ok=await v150SaveHomeAccount();
          const account=v117AccountRecord('main');renderHome();
          let backupAccepted=true;try{validateBackup(JSON.parse(JSON.stringify(state)))}catch{backupAccepted=false}
          return {before,ok,total:currentBank(),text:currentBankText(),
            unchanged:JSON.stringify(state.entries)===history,reports,sameReports:JSON.stringify(captureActualReports())===JSON.stringify(reports),
            anchor:account.ledger.currentBalanceAnchor,snapshot:account.amount,
            difference:v117AccountBalance('main').difference,
            pastBalance:v117LedgerAt(account,'2026-11-11').balance,backupAccepted,count:state.entries.length};
        ''')
        self.assertEqual(result['before'], 143000)
        self.assertTrue(result['ok'])
        self.assertEqual(result['total'], 800000)
        self.assertEqual(result['text'], '800 000,00 ₽')
        self.assertEqual(result['snapshot'], 800000)
        self.assertEqual(result['difference'], 0)
        self.assertEqual(result['pastBalance'], 143000)
        self.assertTrue(result['backupAccepted'])
        self.assertEqual(result['anchor']['version'], 1)
        self.assertEqual(result['anchor']['amount'], 800000)
        self.assertEqual(result['anchor']['date'], '2026-11-12')
        self.assertTrue(result['anchor']['recordedAt'])
        self.assertEqual(result['count'], 273)
        self.assertTrue(result['unchanged'])
        self.assertTrue(result['sameReports'])
        self.assertEqual(result['reports']['allExpenses'], 667000)
        self.assertEqual(result['reports']['income'], 811300)

    def test_first_account_current_balance_also_ignores_existing_history(self):
        result = self.evaluate('''
          state.intelligence.accounts=[];renderHome();const history=JSON.stringify(state.entries);
          v150OpenHomeAccount();fillCurrentBalance(800000,'Новый общий счёт');
          const ok=await v150SaveHomeAccount();renderHome();
          return {ok,total:currentBank(),count:v117AccountRecords().length,
            unchanged:JSON.stringify(state.entries)===history,
            shared:v157SharedExpenseAccount().id,accountId:v117AccountRecords()[0]?.id};
        ''')
        self.assertTrue(result['ok'])
        self.assertEqual(result['total'], 800000)
        self.assertEqual(result['count'], 1)
        self.assertTrue(result['unchanged'])
        self.assertEqual(result['shared'], result['accountId'])

    def test_new_same_day_purchase_debits_the_actual_balance_immediately(self):
        result = self.evaluate('''
          v150OpenHomeAccount('main');fillCurrentBalance(800000);await v150SaveHomeAccount();
          const original=JSON.stringify(state.entries);advanceBalanceTime(2000);
          openEntry('expense');document.getElementById('eAmount').value='100';v90Choose('Продукты');
          document.getElementById('eDate').value=today();document.getElementById('eAccountId').value='';
          await addEntry();
          return {total:currentBank(),text:currentBankText(),amount:state.entries.at(-1).amount,
            sameOld:JSON.stringify(state.entries.slice(0,-1))===original,
            current:v117AccountBalance('main').balance,
            implicit:v157ImplicitExpenseRows('main').map(e=>e.id),newId:state.entries.at(-1).id};
        ''')
        self.assertEqual(result['total'], 799900)
        self.assertEqual(result['text'], '799 900,00 ₽')
        self.assertEqual(result['amount'], 100)
        self.assertEqual(result['current'], 799900)
        self.assertEqual(result['implicit'], [result['newId']])
        self.assertTrue(result['sameOld'])

    def test_pre_anchor_same_day_flows_edits_and_later_old_dated_backfill_are_not_replayed(self):
        result = self.evaluate('''
          state.entries.push(actualEntry('already-spent-today',300,{accountId:'main',
              created_at:new Date(Date.now()+24*3600000).toISOString()}),
            actualEntry('already-earned-today',500,{type:'income',accountId:'main'}),
            actualEntry('already-moved-today',200,{type:'transfer',fromAccountId:'main',toAccountId:'outside'}));
          advanceBalanceTime(2000);v150OpenHomeAccount('main');fillCurrentBalance(800000);
          await v150SaveHomeAccount();advanceBalanceTime(2000);
          state.entries.push(actualEntry('late-history',1000,{date:'2026-10-20'}));
          const old=state.entries.find(e=>e.id==='already-spent-today');old.amount=900;
          old.updated_at=new Date().toISOString();renderAll();
          const afterOld=currentBank();
          state.entries.push(actualEntry('new-purchase',100,{
            created_at:v117AccountRecord('main').ledger.currentBalanceAnchor.recordedAt}));renderAll();
          return {afterOld,total:currentBank(),implicit:v157ImplicitExpenseRows('main').map(e=>e.id),
            difference:v117AccountBalance('main').difference};
        ''')
        self.assertEqual(result['afterOld'], 800000)
        self.assertEqual(result['total'], 799900)
        self.assertEqual(result['implicit'], ['new-purchase'])
        self.assertEqual(result['difference'], 0)

    def test_future_explicit_money_flows_apply_when_their_date_arrives(self):
        result = self.evaluate('''
          const saved=actualAccount('saved',500);saved.ledger.includeInSpending=false;
          state.intelligence.accounts.push(saved);state.settings.preferences.unassignedExpenseAccountId='main';
          state.entries.push(actualEntry('tomorrow-expense',100,{date:'2026-11-13',accountId:'main'}),
            actualEntry('tomorrow-income',200,{type:'income',date:'2026-11-13',accountId:'main'}),
            actualEntry('tomorrow-transfer',50,{type:'transfer',date:'2026-11-13',fromAccountId:'main',toAccountId:'saved'}));
          v150OpenHomeAccount('main');fillCurrentBalance(800000);await v150SaveHomeAccount();
          const before={total:currentBank(),main:v117AccountBalance('main').balance};
          advanceBalanceTime(24*3600000);renderAll();
          return {before,after:{total:currentBank(),main:v117AccountBalance('main').balance,
            saved:v117AccountBalance('saved').balance}};
        ''')
        self.assertEqual(result['before'], {'total': 800500, 'main': 800000})
        self.assertEqual(result['after'], {'total': 800600, 'main': 800050, 'saved': 550})

    def test_current_balance_form_defaults_to_today_and_does_not_offer_october_opening_as_current(self):
        result = self.evaluate('''
          v150OpenHomeAccount('main');
          return {date:document.getElementById('v150AccountDate').value,
            readOnly:document.getElementById('v150AccountDate').readOnly,
            entered:document.getElementById('v150AccountOpening').value,
            title:document.getElementById('v150HomeAccountTitle').textContent,
            oldStart:v117AccountRecord('main').ledger.startDate};
        ''')
        self.assertEqual(result['date'], '2026-11-12')
        self.assertTrue(result['readOnly'])
        self.assertEqual(result['entered'], '')
        self.assertNotIn('Начальный остаток', result['title'])
        self.assertEqual(result['oldStart'], '2026-10-01')

    def test_reentering_actual_balance_resets_once_and_anchor_survives_reload_and_profile_change(self):
        result = self.evaluate('''
          const originalCount=state.entries.length;
          v150OpenHomeAccount('main');fillCurrentBalance(800000);await v150SaveHomeAccount();
          advanceBalanceTime(2000);state.entries.push(actualEntry('after-first',100));renderHome();
          const afterFirst=currentBank();advanceBalanceTime(2000);
          v150OpenHomeAccount('main');fillCurrentBalance(800000);await v150SaveHomeAccount();
          const afterSecond=currentBank();state=normalize(JSON.parse(JSON.stringify(state)));
          currentProfile=()=>({id:'another-member',name:'Другой участник'});renderHome();
          const afterReload=currentBank();advanceBalanceTime(2000);
          state.entries.push(actualEntry('after-second',50));renderHome();
          const final=currentBank();advanceBalanceTime(24*3600000);
          v150OpenHomeAccount('main');fillCurrentBalance(800000);await v150SaveHomeAccount();
          return {afterFirst,afterSecond,afterReload,final,laterCurrent:currentBank(),
            earlierDay:v117LedgerAt(v117AccountRecord('main'),'2026-11-12').balance,
            count:state.entries.length,originalCount,
            corrections:state.entries.filter(e=>e.balanceAdjustment).length,
            income:sum(state.entries.filter(e=>e.type==='income')),
            anchor:v117AccountRecord('main').ledger.currentBalanceAnchor};
        ''')
        self.assertEqual(result['afterFirst'], 799900)
        self.assertEqual(result['afterSecond'], 800000)
        self.assertEqual(result['afterReload'], 800000)
        self.assertEqual(result['final'], 799950)
        self.assertEqual(result['laterCurrent'], 800000)
        self.assertEqual(result['earlierDay'], 799950)
        self.assertEqual(result['count'], result['originalCount'] + 2)
        self.assertEqual(result['corrections'], 0)
        self.assertEqual(result['income'], 811300)
        self.assertEqual(result['anchor']['amount'], 800000)

    def test_failed_or_stale_current_balance_save_rolls_back_and_scope_change_cannot_touch_new_family(self):
        result = self.evaluate('''
          const oldAccount=JSON.stringify(v117AccountRecord('main')),history=JSON.stringify(state.entries);
          v150OpenHomeAccount('main');fillCurrentBalance(800000);v89StorageFailed=true;
          saveAll=async()=>false;const failed=await v150SaveHomeAccount();
          const rollback={total:currentBank(),account:JSON.stringify(v117AccountRecord('main'))===oldAccount,
            history:JSON.stringify(state.entries)===history};
          v150OpenHomeAccount('main');fillCurrentBalance(800000);
          const main=v117AccountRecord('main');main.name='Изменён на другом устройстве';
          main.updated_at=v117RecordStamp(main);let saves=0;
          saveAll=async()=>{saves++;return true};const stale=await v150SaveHomeAccount();
          const staleAccount={name:v117AccountRecord('main').name,
            hasAnchor:!!v117AccountRecord('main').ledger.currentBalanceAnchor};
          window.__FINANCE_BRIDGE__={active:true,role:'viewer'};
          const denied=await v150SaveHomeAccount();window.__FINANCE_BRIDGE__=null;
          v150OpenHomeAccount('main');fillCurrentBalance(800000);
          saveAll=async()=>{authEpoch++;state=blankState();return true};
          const switched=await v150SaveHomeAccount();
          return {failed,rollback,stale,staleAccount,denied,saves,switched,
            accounts:v117AccountRecords().length,entries:state.entries.length};
        ''')
        self.assertFalse(result['failed'])
        self.assertEqual(result['rollback'], {'total': 143000, 'account': True, 'history': True})
        self.assertFalse(result['stale'])
        self.assertEqual(result['staleAccount'], {'name': 'Изменён на другом устройстве', 'hasAnchor': False})
        self.assertFalse(result['denied'])
        self.assertEqual(result['saves'], 0)
        self.assertFalse(result['switched'])
        self.assertEqual(result['accounts'], 0)
        self.assertEqual(result['entries'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
