"""Cross-feature budget invariants; fictional data, no session and blocked network."""
import unittest

import test_local_data_safety as harness


class HumanBudgetIntegration(unittest.TestCase):
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
          session=null;stopCloudSync();localStorage.clear();state=blankState();
          // The isolated family has no mortgage; actual recurring/calendar APIs remain live.
          loanScheduleData=()=>[];
          const day=today(),stamp=new Date(Date.now()-1000).toISOString(),later=new Date().toISOString();
          window.__qaAccount=(id,amount,include=true,kind='asset')=>({id,name:'Учебный '+id,
            amount,snapshotDate:day,snapshotRevision:'qa-rev-'+id,created_at:stamp,updated_at:stamp,
            ledger:{version:1,enabled:true,startDate:day,openingBalance:amount,kind,includeInSpending:include},
            snapshotVerification:{amount,date:day,revision:'qa-rev-'+id,verifiedAt:stamp,accountUpdatedAt:stamp}});
          window.__qaEntry=(id,amount,fields={})=>({id,date:day,type:'expense',amount,
            category:'Продукты',who:'Общее',beneficiary:'Общее',accountId:'asset',
            created_at:later,updated_at:later,...fields});
          window.__qaReset=()=>{
            state=blankState();state.intelligence.accounts=[__qaAccount('asset',80000)];
            state.intelligence.recurring=[
              {id:'bill1',name:'Учебный платёж',amount:5000,day:1,category:'ЖКХ',who:'Общее',updated_at:stamp},
              {id:'bill2',name:'Другой учебный платёж',amount:25000,day:1,category:'ЖКХ',who:'Общее',updated_at:stamp}];
            state.intelligence.budgets=[{id:'qa-plan',kind:V118_MONTH_KIND,groupVersion:3,amount:0,
              month:day.slice(0,7),updated_at:stamp,periodPlan:{confirmed:true,
                fromDate:day,untilDate:day,everydayAmount:20000}}];
            state.goals=[{id:'qa-goal',name:'Учебная цель',target:10000,saved:0,monthly:0,
              reserve:{enabled:true,accountId:'asset',amount:10000}}];
          };
          window.__qaSummary=()=>{const d=v118AvailableData();return {amount:d.amount,estimate:d.estimate,
            cash:d.cash,bills:d.obligations,everyday:d.futurePlan,reserves:d.reserves,
            complete:d.complete,warnings:d.warnings,accountComplete:d.accounts.complete}};
          telegramNotify=async()=>false;__qaReset();
        }""")

    def test_planned_payment_food_and_own_transfer_preserve_unallocated_cash(self):
        self.prepare()
        result = self.page.evaluate("""() => {
          const initial=__qaSummary();
          state.entries.push(__qaEntry('qa-bill-payment',5000,
            {recurringId:'bill1',recurringPeriod:month()}));const bill=__qaSummary();
          state.entries.push(__qaEntry('qa-food',2000));const food=__qaSummary();
          state.intelligence.accounts.push(__qaAccount('second',0));
          state.entries.push(__qaEntry('qa-own-transfer',3000,
            {type:'transfer',accountId:undefined,fromAccountId:'asset',toAccountId:'second'}));
          return {initial,bill,food,transfer:__qaSummary(),own:v117AccountSummary().ownTotal};
        }""")
        self.assertEqual(result['initial']['cash'], 80000)
        self.assertEqual(result['initial']['bills'], 30000)
        self.assertEqual(result['initial']['everyday'], 20000)
        self.assertEqual(result['initial']['reserves'], 10000)
        for stage in ['initial', 'bill', 'food', 'transfer']:
            self.assertTrue(result[stage]['complete'], stage)
            self.assertEqual(result[stage]['amount'], 20000, stage)
        self.assertEqual(result['bill']['cash'], 75000)
        self.assertEqual(result['bill']['bills'], 25000)
        self.assertEqual(result['food']['cash'], 73000)
        self.assertEqual(result['food']['everyday'], 18000)
        self.assertEqual(result['own'], 73000)

    def test_repayment_is_cash_outflow_without_another_expense(self):
        self.prepare()
        result = self.page.evaluate("""() => {
          state.entries.push(__qaEntry('qa-repayment',5000,{type:'transfer',accountId:undefined,
            fromAccountId:'asset',debtRepayment:true}));
          return {summary:__qaSummary(),expense:sum(expenses(month()))};
        }""")
        self.assertEqual(result['summary']['cash'], 75000)
        self.assertEqual(result['summary']['amount'], 15000)
        self.assertTrue(result['summary']['complete'])
        self.assertEqual(result['expense'], 0)

    def test_protected_account_reserve_is_excluded_exactly_once(self):
        self.prepare()
        result = self.page.evaluate("""() => {
          state.intelligence.accounts=[__qaAccount('asset',70000),__qaAccount('protected',10000,false)];
          state.goals[0].reserve.accountId='protected';return __qaSummary();
        }""")
        self.assertEqual(result['cash'], 70000)
        self.assertEqual(result['reserves'], 0)
        self.assertEqual(result['amount'], 20000)
        self.assertTrue(result['complete'])

    def test_unassigned_stale_malformed_and_fractional_sources_disable_authoritative_amount(self):
        self.prepare()
        result = self.page.evaluate("""() => {
          const outcomes={};
          state.entries.push(__qaEntry('qa-unassigned',20,{accountId:undefined}));
          outcomes.unassigned=__qaSummary();
          __qaReset();state.intelligence.accounts[0].snapshotDate='2020-01-01';outcomes.stale=__qaSummary();
          __qaReset();state.intelligence.accounts[0].ledger.openingBalance='80000';outcomes.malformed=__qaSummary();
          __qaReset();state.entries.push(__qaEntry('qa-negative',-1000));outcomes.negative=__qaSummary();
          __qaReset();state.entries.push(__qaEntry('qa-tiny1',0.001),__qaEntry('qa-tiny2',0.009));
          outcomes.cancelledFractions=__qaSummary();return outcomes;
        }""")
        for name, summary in result.items():
            self.assertFalse(summary['complete'], name)
            self.assertIsNone(summary['amount'], name)
            self.assertTrue(summary['warnings'], name)
        self.assertEqual(result['negative']['cash'], 80000)

    def test_malformed_calendar_obligation_disables_authoritative_amount(self):
        self.prepare()
        result = self.page.evaluate("""() => {
          state.intelligence.recurring[0].amount=-5000;return __qaSummary();
        }""")
        self.assertFalse(result['complete'])
        self.assertIsNone(result['amount'])
        self.assertTrue(result['warnings'])

    def test_credit_funded_food_does_not_release_cash_plan(self):
        self.prepare()
        result = self.page.evaluate("""() => {
          state.intelligence.accounts.push(__qaAccount('credit',0,false,'debt'));
          state.entries.push(__qaEntry('qa-credit-food',2000,{accountId:'credit'}));
          return {summary:__qaSummary(),debt:v117AccountSummary().debtTotal};
        }""")
        summary = result['summary']
        self.assertEqual(summary['cash'], 80000)
        self.assertEqual(summary['everyday'], 20000)
        self.assertEqual(result['debt'], 2000)
        self.assertFalse(summary['complete'])
        self.assertIsNone(summary['amount'])
        self.assertTrue(summary['warnings'])

    def test_merged_duplicate_seasonal_payment_requires_review(self):
        self.prepare()
        result = self.page.evaluate("""() => {
          state.goals=[];
          const reserve=id=>({id,kind:V118_RESERVE_KIND,groupVersion:3,amount:5000,
            name:'Учебный '+id,target:5000,saved:5000,dueDate:today(),accountId:'asset',
            paidEntryId:'qa-same-payment',updated_at:new Date().toISOString()});
          state.intelligence.budgets.push(reserve('qa-season1'),reserve('qa-season2'));
          state.entries.push(__qaEntry('qa-same-payment',5000));return __qaSummary();
        }""")
        self.assertEqual(result['cash'], 75000)
        self.assertFalse(result['complete'])
        self.assertIsNone(result['amount'])
        self.assertTrue(result['warnings'])

    def test_financial_reads_and_renders_leave_state_and_storage_unchanged(self):
        self.prepare()
        before = self.snapshot()
        self.page.evaluate("""() => {
          for(let n=0;n<2;n++){
            v117AccountSummary();v118AvailableData();v119GoalReserveData();
            v117RenderAccounts();v118RenderPlanning();renderGoals();renderChores();
            v119InitOperations();renderHome();
          }
        }""")
        self.assertEqual(self.snapshot(), before)

    def test_viewer_cannot_mutate_new_cross_feature_flows(self):
        self.prepare()
        result = self.page.evaluate("""async () => {
          document.getElementById('appRoot').classList.remove('auth-locked');
          window.__FINANCE_BRIDGE__={active:true,role:'viewer'};
          const before=JSON.stringify(state),storage=JSON.stringify({...localStorage});
          let saves=0;saveAll=async()=>{saves++;return false};
          const calls=[['addEntry',[]],['saveEdit',[]],['v119SaveSplit',[]],['v119SaveCSV',[]],
            ['v119UndoDelete',[]],['v117SaveSnapshot',[]],['v117SaveLedger',[]],['v84SaveAccount',[]],
            ['v118SaveMonth',[]],['v118SaveReserve',[]],['addGoal',[]],['addChore',[]],
            ['completeChore',['unknown']],['v84ConfirmRecurring',['bill1',month()]]];
          const unchanged={};for(const [name,args]of calls){await window[name](...args);unchanged[name]=before===JSON.stringify(state)};
          return {unchanged,saves,storage:storage===JSON.stringify({...localStorage})};
        }""")
        self.assertTrue(all(result['unchanged'].values()), result['unchanged'])
        self.assertEqual(result['saves'], 0)
        self.assertTrue(result['storage'])


if __name__ == '__main__':
    unittest.main()
