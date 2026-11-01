"""Opt-in account ledger and reconciliation; fictional local data, blocked network."""
import unittest
from copy import deepcopy

import test_local_data_safety as harness
import test_sync_protocol as protocol


class AccountLedger(unittest.TestCase):
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
        self.page.evaluate("""() => {
          session=null;stopCloudSync();state=blankState();localStorage.clear();
          telegramNotify=()=>Promise.resolve(false);window.confirm=()=>true;
          document.getElementById('appRoot').classList.remove('auth-locked');
          document.getElementById('authGate').style.display='none';
          renderAll=()=>v117RenderAccounts();
          window.ledgerDay=today();
          window.ledgerPast=previousMonthKey(ledgerDay.slice(0,7))+'-01';
          window.ledgerStamp=new Date(Date.now()-120000).toISOString();
          window.testAccount=(id,opening=100,kind='asset',spending=true)=>({
            id,name:'Вымышленный счёт '+id,amount:opening,snapshotDate:ledgerDay,
            snapshotRevision:'fictional-snapshot-'+id,created_at:ledgerStamp,
            updated_at:ledgerStamp,futureField:{keep:['fictional',null,true]},
            ledger:{version:1,enabled:true,startDate:ledgerDay,openingBalance:opening,
              kind,includeInSpending:kind==='asset'&&spending,creditLimit:kind==='debt'?900000:0,
              futureLedger:{keep:true}},
            snapshotVerification:{amount:opening,date:ledgerDay,
              revision:'fictional-snapshot-'+id,verifiedAt:ledgerStamp,accountUpdatedAt:ledgerStamp}});
          window.testFlow=(id,type,amount,fields={})=>({id,type,amount,date:ledgerDay,
            category:type==='income'?'Доход':'Продукты',who:'Учебный участник',
            store:'Учебный источник',created_at:new Date(Date.now()-180000).toISOString(),
            updated_at:new Date(Date.now()-180000).toISOString(),futureField:{preserve:'entry'},...fields});
          window.setSnapshot=(a,amount)=>{a.amount=amount;a.snapshotVerification.amount=amount};
          v117AccountsBusy=false;v117RenderAccounts();go('accounts');
        }""")

    def test_exact_cashflows_transfers_cash_and_debt_are_separate_from_expenses(self):
        self.prepare()
        result = self.page.evaluate("""() => {
          const a=testAccount('own',1000.10),cash=testAccount('cash',0),debt=testAccount('debt',-500,'debt'),reserve=testAccount('reserve',3000,'asset',false);
          state.intelligence.accounts=[a,cash,debt,reserve];
          state.entries=[testFlow('income','income',200.20,{accountId:a.id}),
            testFlow('food','expense',50.10,{accountId:a.id}),
            testFlow('move','transfer',100,{fromAccountId:a.id,toAccountId:cash.id}),
            testFlow('withdraw','cash',20.05,{fromAccountId:a.id,toAccountId:cash.id}),
            testFlow('repayment','transfer',200,{fromAccountId:a.id,toAccountId:debt.id,debtRepayment:true}),
            testFlow('credit-purchase','expense',50,{accountId:debt.id}),
            testFlow('unassigned-history','expense',17.251,{date:ledgerPast})];
          setSnapshot(a,830.15);setSnapshot(cash,120.05);setSnapshot(debt,-350);
          const before=JSON.stringify(state),summary=v117AccountSummary(),carry=v111MonthBalance(ledgerDay.slice(0,7));
          return {summary,carry,unchanged:before===JSON.stringify(state),debtRepaymentBlocked:!v117CheckAccountFields(testFlow('bad-repayment','transfer',20,{fromAccountId:debt.id,debtRepayment:true})).ok};
        }""")
        summary = result['summary']
        self.assertEqual([item['balance'] for item in summary['items']], [830.15, 120.05, -350, 3000])
        self.assertEqual((summary['ownTotal'], summary['spendableTotal'], summary['protectedTotal'],
                          summary['debtTotal'], summary['netTotal']), (3950.20, 950.20, 3000, 350, 3600.20))
        self.assertTrue(summary['complete'])
        self.assertEqual((result['carry']['income'], result['carry']['expense']), (200.20, 100.10))
        self.assertTrue(result['unchanged'])
        self.assertTrue(result['debtRepaymentBlocked'])

    def test_manual_snapshot_never_adds_history_and_old_rows_are_not_assigned(self):
        self.prepare()
        result = self.page.evaluate("""() => {
          const a={id:'legacy',name:'Прежний счёт',amount:2000,updated_at:ledgerStamp,futureField:{preserve:17}};
          state.intelligence.accounts=[a];state.entries=[testFlow('old-income','income',1000,{date:ledgerPast}),testFlow('old-expense','expense',100,{date:ledgerPast})];
          const before=JSON.stringify(state),legacy=v117AccountSummary();
          a.ledger={version:1,enabled:true,startDate:ledgerDay,openingBalance:2000,kind:'asset',includeInSpending:true};
          const configured=v117AccountBalance(a),entries=JSON.stringify(state.entries);
          return {legacy,configured,entries,expectedEntries:JSON.stringify(JSON.parse(before).entries),future:a.futureField};
        }""")
        self.assertEqual(result['legacy']['spendableTotal'], 2000)
        self.assertFalse(result['legacy']['complete'])
        self.assertEqual(result['configured']['balance'], 2000)
        self.assertEqual(result['entries'], result['expectedEntries'])
        self.assertEqual(result['future'], {'preserve': 17})

    def test_unassigned_invalid_and_fractional_legacy_rows_are_visible_without_rewriting(self):
        self.prepare()
        result = self.page.evaluate("""() => {
          const a=testAccount('a');state.intelligence.accounts=[a];
          state.entries=[testFlow('old','expense',17.251,{date:ledgerPast}),testFlow('unassigned','expense',5),testFlow('invalid','income',4,{date:'2026-02-31'})];
          const before=JSON.stringify(state.entries),summary=v117AccountSummary();
          state.entries.push(testFlow('fractional','expense',0.12345,{accountId:a.id}));
          const fractional=v117AccountBalance(a),unknown=v117CheckAccountFields(testFlow('bad','expense',10,{accountId:'missing'}));
          return {summary,fractional,unknown,originalKept:before===JSON.stringify(state.entries.slice(0,3))};
        }""")
        self.assertEqual(result['summary']['unassignedCount'], 1)
        self.assertEqual(result['summary']['invalidDateCount'], 1)
        self.assertFalse(result['summary']['complete'])
        self.assertAlmostEqual(result['fractional']['balance'], 99.87655)
        self.assertFalse(result['fractional']['exact'])
        self.assertFalse(result['unknown']['ok'])
        self.assertTrue(result['originalKept'])

    def test_snapshot_cutoff_and_old_client_changes_do_not_fake_a_verified_balance(self):
        self.prepare()
        result = self.page.evaluate("""() => {
          const a=testAccount('a');state.intelligence.accounts=[a];
          state.entries=[testFlow('earlier','expense',10,{accountId:a.id})];setSnapshot(a,90);
          const first=v117AccountBalance(a);
          state.entries.push(testFlow('newer','expense',20,{accountId:a.id,created_at:new Date().toISOString()}));
          const after=v117AccountBalance(a);
          a.amount=80;a.updated_at=v117RecordStamp(a);const oldClient=v117AccountBalance(a);
          return {first,after,oldClient};
        }""")
        self.assertEqual(result['first']['difference'], 0)
        self.assertEqual(result['after']['balance'], 70)
        self.assertEqual(result['after']['difference'], 0)
        self.assertFalse(result['oldClient']['snapshotTrusted'])
        self.assertIsNone(result['oldClient']['difference'])
        self.assertEqual(result['oldClient']['balance'], 70)

    def test_malformed_source_amounts_and_cancelling_fractional_kopecks_block_completion(self):
        self.prepare()
        result = self.page.evaluate("""async () => {
          const a=testAccount('a');state.intelligence.accounts=[a];
          state.entries=[testFlow('negative','expense',-1000,{accountId:a.id}),testFlow('zero','income',0,{accountId:a.id})];
          const before=JSON.stringify(state.entries),negative=v117AccountSummary();
          state.entries=[testFlow('subcent-out','expense',0.001,{accountId:a.id}),testFlow('subcent-in','income',0.001,{accountId:a.id})];
          const fractional=v117AccountBalance(a);setSnapshot(a,90);await v117AdjustAccount(a.id);
          return {negative,fractional,adjustmentCount:state.entries.filter(e=>e.balanceAdjustment).length,
            preserved:JSON.parse(before)[0].amount===-1000&&negative.items[0].balance===100};
        }""")
        self.assertFalse(result['negative']['complete'])
        self.assertEqual(result['negative']['items'][0]['invalidCount'], 2)
        self.assertEqual(result['fractional']['balance'], 100)
        self.assertFalse(result['fractional']['exact'])
        self.assertEqual(result['adjustmentCount'], 0)
        self.assertTrue(result['preserved'])

    def test_logout_clears_only_account_drafts_and_preserves_inflight_flag(self):
        self.prepare()
        result = self.page.evaluate("""() => {
          const a=testAccount('a');state.intelligence.accounts=[a];v117RenderAccounts();
          v84EditAccount(a.id);v117OpenLedger(a.id);v117OpenReconcile(a.id);
          document.getElementById('v117SnapshotAmount').value='77';v117AccountsBusy=true;
          const before=JSON.stringify(state);v117ClearAccountDrafts();
          return {same:before===JSON.stringify(state),busy:v117AccountsBusy,
            ids:[v84EditingAccountId,v117ConfigId,v117ConfigVersion,v117ManualVersion,v117ReconcileVersion],
            values:['v84AccountName','v84AccountAmount','v117LedgerOpening','v117SnapshotAmount'].map(id=>document.getElementById(id).value),
            hidden:document.getElementById('v117LedgerSetup').hidden};
        }""")
        self.assertTrue(result['same'] and result['busy'] and result['hidden'])
        self.assertEqual(result['ids'], [''] * 5)
        self.assertEqual(result['values'], [''] * 4)

    def test_adjustment_is_audited_transfer_created_once_without_income_or_expense(self):
        self.prepare()
        result = self.page.evaluate("""async () => {
          const a=testAccount('a');setSnapshot(a,90);state.intelligence.accounts=[a];
          const opening=JSON.stringify(a.ledger),future=JSON.stringify(a.futureField);
          await Promise.all([v117AdjustAccount(a.id),v117AdjustAccount(a.id)]);
          const entry=state.entries[0],result=v117AccountBalance(a),pending=JSON.parse(localStorage.getItem(KEYS.pending));
          return {entry,result,count:state.entries.length,openingKept:opening===JSON.stringify(a.ledger),futureKept:future===JSON.stringify(a.futureField),
            totals:v111MonthBalance(ledgerDay.slice(0,7)),pending,valid:!!validateBackup(JSON.parse(JSON.stringify(state)))};
        }""")
        self.assertEqual(result['count'], 1)
        self.assertEqual((result['entry']['type'], result['entry']['amount'], result['entry']['adjustmentDirection']), ('transfer', 10, -1))
        self.assertTrue(result['entry']['balanceAdjustment'])
        self.assertEqual((result['result']['balance'], result['result']['difference']), (90, 0))
        self.assertEqual((result['totals']['income'], result['totals']['expense']), (0, 0))
        self.assertEqual(result['pending']['entries'][0], result['entry'])
        self.assertTrue(result['openingKept'] and result['futureKept'] and result['valid'])

    def test_cancel_viewer_and_logout_during_confirmation_do_not_write(self):
        self.prepare()
        result = self.page.evaluate("""async () => {
          const a=testAccount('a');setSnapshot(a,90);state.intelligence.accounts=[a];
          const snap=()=>JSON.stringify({state,storage:{...localStorage}}),before=snap();
          window.confirm=()=>false;await v117AdjustAccount(a.id);const cancelled=snap()===before;
          window.__FINANCE_BRIDGE__={active:true,role:'viewer'};await v117AdjustAccount(a.id);const viewer=snap()===before;
          delete window.__FINANCE_BRIDGE__;window.confirm=()=>{authEpoch++;document.getElementById('appRoot').classList.add('auth-locked');return true};await v117AdjustAccount(a.id);
          return {cancelled,viewer,logout:snap()===before};
        }""")
        self.assertEqual(result, {'cancelled': True, 'viewer': True, 'logout': True})

    def test_real_account_setup_snapshot_and_adjustment_flow_preserves_kopecks(self):
        self.prepare()
        self.page.locator('#v84AccountName').fill('Учебная карта')
        self.page.locator('#v84AccountAmount').fill('1 250,50')
        self.page.locator('#v84AccountSave').click()
        self.page.wait_for_function('state.intelligence.accounts.length===1&&!v117AccountsBusy')
        identifier = self.page.evaluate('state.intelligence.accounts[0].id')
        self.page.locator('[data-v117-account-action="configure"]').click()
        self.page.locator('#v117LedgerOpening').fill('1 250,50')
        self.page.locator('#v117OpeningConfirmed').check()
        self.page.get_by_role('button', name='Сохранить начало учёта', exact=True).click()
        self.page.wait_for_function('state.intelligence.accounts[0].ledger?.enabled&&!v117AccountsBusy')
        self.assertEqual(self.page.evaluate('v117AccountSummary().spendableTotal'), 1250.50)
        self.assertTrue(self.page.evaluate('v117AccountSummary().complete'))
        self.page.locator('[data-v117-account-action="reconcile"]').click()
        self.page.locator('#v117SnapshotAmount').fill('1 200,25')
        self.page.get_by_role('button', name='Сохранить сверку', exact=True).click()
        self.page.wait_for_function('state.intelligence.accounts[0].amount===1200.25&&!v117AccountsBusy')
        self.page.locator('[data-v117-account-action="adjust"]').click()
        self.page.wait_for_function('state.entries.length===1&&!v117AccountsBusy')
        result = self.page.evaluate('(id)=>v117AccountBalance(id)', identifier)
        self.assertEqual((result['balance'], result['snapshot'], result['difference']), (1200.25, 1200.25, 0))
        self.assertEqual(self.page.evaluate('state.entries[0].amount'), 50.25)

    def test_archiving_keeps_records_and_refuses_to_hide_tracked_nonzero_money(self):
        self.prepare()
        result = self.page.evaluate("""async () => {
          const a=testAccount('nonzero',10),z=testAccount('zero',0);state.intelligence.accounts=[a,z];
          state.entries=[testFlow('closed-income','income',20,{accountId:z.id}),testFlow('closed-expense','expense',20,{accountId:z.id})];
          await v117ArchiveAccount(a.id);const refused=!a.archived;
          await v117ArchiveAccount(z.id);const closed=z.archived&&state.intelligence.accounts.length===2&&!state.intelligence.deleted.accounts[z.id]&&!v117SelectableAccounts().some(x=>x.id===z.id);
          const complete=v117AccountSummary().complete,blockedNew=!v117CheckAccountFields(testFlow('new','expense',1,{accountId:z.id})).ok;
          await v117ArchiveAccount(z.id,true);return {refused,closed,reopened:!z.archived,complete,blockedNew};
        }""")
        self.assertEqual(result, {'refused': True, 'closed': True, 'reopened': True, 'complete': True, 'blockedNew': True})

    def test_backup_extensions_merge_and_monotonic_record_dates_preserve_legacy_fields(self):
        self.prepare()
        result = self.page.evaluate("""() => {
          const a=testAccount('a'),b=testAccount('b');state.intelligence.accounts=[a,b];
          const base=JSON.parse(JSON.stringify(state)),cloud=JSON.parse(JSON.stringify(base)),local=JSON.parse(JSON.stringify(base));
          cloud.intelligence.accounts[0].ledger.openingBalance=101;cloud.intelligence.accounts[0].updated_at=v117RecordStamp(a);
          local.intelligence.accounts[1].ledger.openingBalance=102;local.intelligence.accounts[1].updated_at=v117RecordStamp(b);
          rememberCloudBase(base);const merged=reconcileCloudSnapshot(cloud,local,'fictional-account-test');
          const valid=validateBackup(JSON.parse(JSON.stringify(merged))),bad=JSON.parse(JSON.stringify(base));bad.intelligence.accounts[0].ledger.openingBalance='100';let rejected=false;
          try{validateBackup(bad)}catch{rejected=true}
          const old=JSON.parse(JSON.stringify(base));old.intelligence.accounts[0].ledger={futureShape:{opaque:'preserve'}};const oldKept=JSON.stringify(validateBackup(old).intelligence.accounts[0].ledger)===JSON.stringify(old.intelligence.accounts[0].ledger);
          const future='2030-01-01T00:00:00.000Z';return {openings:merged.intelligence.accounts.map(x=>x.ledger.openingBalance),futureFields:merged.intelligence.accounts.map(x=>x.futureField),valid:!!valid,rejected,oldKept,monotonic:v117RecordStamp({updated_at:future})>future,contains:verifiedCloudContains(merged,local)};
        }""")
        self.assertEqual(result['openings'], [101, 102])
        self.assertEqual(result['futureFields'], [{'keep': ['fictional', None, True]}] * 2)
        self.assertTrue(all(result[key] for key in ('valid', 'rejected', 'oldKept', 'monotonic', 'contains')))

    def test_account_cards_and_drafts_fit_phone_tablet_and_desktop_at_large_text(self):
        self.prepare()
        self.page.evaluate("""() => {
          const a=testAccount('layout',999999999999.99);a.name='Учебный очень длинный счёт для проверки отображения сумм и управления';state.intelligence.accounts=[a];
          v117RenderAccounts();v117OpenLedger(a.id);v117OpenReconcile(a.id);
        }""")
        for width in (320, 390, 768, 1280, 1920):
            self.page.set_viewport_size({'width': width, 'height': 900})
            for scale in (1, 2):
                if scale == 2:
                    self.page.evaluate("""() => {
                      window.layoutText=[...document.querySelectorAll('#accounts *')].map(el=>[el,el.style.fontSize,getComputedStyle(el).fontSize]);
                      for(const [el,,size] of layoutText)el.style.fontSize=(parseFloat(size)*2)+'px';
                    }""")
                overflow = self.page.evaluate("""() => [...document.querySelectorAll('#accounts .v117-account-card,#accounts .v117-account-metrics>div,#accounts .field,#accounts button,#accounts .v117-summary-grid>div')]
                  .filter(el=>el.getClientRects().length).filter(el=>el.getBoundingClientRect().right>innerWidth+1||el.getBoundingClientRect().left < -1)
                  .map(el=>({tag:el.tagName,id:el.id,text:el.textContent.slice(0,40)}))""")
                self.assertEqual(overflow, [], f'{width}px text scale {scale}: {overflow}')
                if scale == 2:
                    self.page.evaluate("for(const [el,size] of layoutText)el.style.fontSize=size")


class AccountLedgerSync(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        protocol.SyncProtocol.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        protocol.SyncProtocol.tearDownClass.__func__(cls)

    setUp = protocol.SyncProtocol.setUp
    tearDown = protocol.SyncProtocol.tearDown
    device = protocol.SyncProtocol.device
    start = protocol.SyncProtocol.start
    finish = protocol.SyncProtocol.finish
    wait_held = protocol.SyncProtocol.wait_held
    concurrent_push = protocol.SyncProtocol.concurrent_push
    assert_no_legacy_write = protocol.SyncProtocol.assert_no_legacy_write

    @staticmethod
    def account():
        return {'id': 'account:fictional', 'name': 'Учебная карта', 'amount': 90,
                'created_at': protocol.AT, 'updated_at': protocol.AT,
                'snapshotDate': '2026-10-21', 'snapshotRevision': 'fictional:revision',
                'snapshotVerification': {'amount': 90, 'date': '2026-10-21',
                    'revision': 'fictional:revision', 'verifiedAt': protocol.AT,
                    'accountUpdatedAt': protocol.AT},
                'ledger': {'version': 1, 'enabled': True, 'startDate': '2026-10-21',
                    'openingBalance': 100, 'kind': 'asset', 'includeInSpending': True,
                    'futureLedger': {'preserve': ['opaque', 7]}},
                'futureAccount': {'preserve': True}}

    def prepare_device(self, page):
        page.evaluate("""() => {
          document.getElementById('appRoot').classList.remove('auth-locked');
          document.getElementById('authGate').style.display='none';
          weatherCache.data={temperature_2m:10,weather_code:0};weatherCache.at=Date.now();
          renderAll=()=>v117RenderAccounts();window.confirm=()=>true;
        }""")

    def test_two_devices_create_one_correction_and_new_reader_receives_exact_audit(self):
        base=protocol.fixture();base['intelligence']['accounts']=[self.account()]
        self.backend.data=deepcopy(base)
        first,second=self.device(base),self.device(base)
        for page in (first,second):
            self.prepare_device(page)
            page.evaluate("""async () => {
              session=null;await v117AdjustAccount('account:fictional');
              session={access_token:'synthetic-protocol-token',user:{id:'fictional-user'}};
            }""")
        self.concurrent_push(first,second)
        rows=self.backend.data['entries']
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['id'],'account-adjustment:account%3Afictional:fictional%3Arevision')
        self.assertEqual((rows[0]['amount'],rows[0]['adjustmentDirection']),(10,-1))
        self.assertEqual(self.backend.data['intelligence']['accounts'],base['intelligence']['accounts'])
        reader=self.device();self.prepare_device(reader)
        self.assertTrue(reader.evaluate('syncFromCloud()'))
        self.assertEqual(reader.evaluate("v117AccountBalance('account:fictional').balance"),90)
        self.assertEqual(reader.evaluate('state.entries'),rows)
        self.assertEqual(self.backend.blocked,[])

    def test_concurrent_account_reconfiguration_retains_both_variants_and_queue(self):
        base=protocol.fixture();base['intelligence']['accounts']=[self.account()]
        self.backend.data=deepcopy(base);one,two=deepcopy(base),deepcopy(base)
        one['intelligence']['accounts'][0]['ledger']['openingBalance']=101
        two['intelligence']['accounts'][0]['ledger']['openingBalance']=102
        one['intelligence']['accounts'][0]['updated_at']=protocol.LATER
        two['intelligence']['accounts'][0]['updated_at']=protocol.LATEST
        first,second=self.device(one,True),self.device(two,True)
        for page in (first,second): self.prepare_device(page)
        self.backend.hold_gets=2;self.start(first);self.start(second);self.wait_held(2);self.backend.release()
        results=[self.finish(first),self.finish(second)]
        self.assertEqual(sorted(results),[False,True])
        refused=(first,second)[results.index(False)]
        self.assertIsNotNone(refused.evaluate('(key)=>localStorage.getItem(key)',protocol.PENDING))
        self.assertEqual(refused.evaluate('reconcileCloudSnapshot.conflicts'),['intelligence_accounts:account:fictional'])
        self.assertEqual(self.backend.revision,1)
        self.assertEqual(self.backend.data['intelligence']['accounts'][0]['futureAccount'],{'preserve':True})
        self.assert_no_legacy_write()


if __name__ == '__main__':
    unittest.main()
