"""Mortgage progress regressions: fictional local state; external requests blocked."""
import argparse
from pathlib import Path
import unittest

import test_local_data_safety as harness


class MortgageProgress(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.LocalDataSafety.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        harness.LocalDataSafety.tearDownClass.__func__(cls)

    setUp = harness.LocalDataSafety.setUp
    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open

    def evaluate(self, code):
        self.open()
        return self.page.evaluate("""async () => {
            session=null;localStorage.clear();state=blankState();
            today=()=> '2026-11-05';month=()=> '2026-11';
            // A completely fictional 1,000 RUB loan; no production reads.
            window.__bankRows=[
              {n:1,payDate:'2026-11-02',periodEnd:'2026-11-02',payment:100,body:50,interest:50,balance:950},
              {n:2,payDate:'2026-11-30',periodEnd:'2026-11-30',payment:100,body:60,interest:40,balance:890},
              {n:3,payDate:'2026-12-31',periodEnd:'2026-12-31',payment:900,body:890,interest:10,balance:0}
            ];
            v125BankScheduleData=()=>window.__bankRows.map(r=>({...r}));
            window.__payment=(id,date,amount,principal,extraPrincipal=0,kind='regular')=>({
              id,type:'expense',date,amount,category:'Кредит',who:'Вымышленный участник',
              store:'Fictional mortgage bank',comment:'Synthetic mortgage payment',mortgagePayment:true,
              mortgageAllocation:{version:1,kind,date,amount,principal,interest:amount-principal,
                charges:0,extraPrincipal,...(kind==='regular'?{dueDate:'2026-11-02'}:{})}
            });
            window.__regular=()=>__payment('regular','2026-11-02',100,50);
            window.__early=(id='early',date='2026-11-02',amount=200)=>
              __payment(id,date,amount,amount,amount,'early');
            window.__snapshot=(date='2026-11-02',balance=800)=>{
              state.settings.loans.mortgageSnapshot={version:1,date,balance,endDate:'2026-12-15'};
            };
        """+code+"\n}")

    def test_allocation_supports_regular_early_and_mixed_without_mutating_expenses(self):
        result=self.evaluate("""
            const records=[__regular(),__early(),__payment('mixed','2026-11-02',300,250,200)];
            const before=JSON.stringify(records);
            return {valid:records.map(e=>!!v125MortgageRecord(e)),unchanged:before===JSON.stringify(records)};
        """)
        self.assertEqual(result,{'valid':[True,True,True],'unchanged':True})

    def test_fingerprint_rejects_edited_amount_and_date(self):
        result=self.evaluate("""
            const a=__early(),b=__early();a.amount=250;b.date='2026-11-03';
            return [v125MortgageRecord(a)===null,v125MortgageRecord(b)===null];
        """)
        self.assertEqual(result,[True,True])

    def test_non_expense_and_invalid_numeric_allocation_are_not_principal(self):
        result=self.evaluate("""
            const income=__early();income.type='income';
            const cases=[income];
            for(const [key,value]of [['principal',-1],['principal',NaN],['interest',Infinity],
                ['charges',-1],['extraPrincipal',201],['principal',199]]){
              const e=__early();e.mortgageAllocation[key]=value;cases.push(e);
            }
            return cases.map(e=>v125MortgageRecord(e)===null);
        """)
        self.assertTrue(all(result),result)

    def test_date_alone_never_marks_bank_rows_paid_or_reduces_actual_balance(self):
        result=self.evaluate("""
            const before=JSON.stringify(state),balances=[];
            for(const date of ['2026-11-01','2026-11-05','2027-01-10']){
              today=()=>date;balances.push(v125MortgageProgress().balance);
            }
            return {balances,unchanged:JSON.stringify(state)===before};
        """)
        self.assertEqual(result,{'balances':[1000,1000,1000],'unchanged':True})

    def test_unconfirmed_due_row_prevents_an_authoritative_projected_term(self):
        result=self.evaluate("""
            const p=v125MortgageProgress();
            return {balance:p.balance,missing:p.missing.length,projection:p.projection};
        """)
        self.assertEqual(result['balance'],1000)
        self.assertGreater(result['missing'],0)
        self.assertIsNone(result['projection'])

    def test_actual_regular_payment_reduces_principal_not_whole_cash_payment(self):
        result=self.evaluate("""
            state.entries=[__regular()];const before=JSON.stringify(state.entries),p=v125MortgageProgress();
            return {balance:p.balance,count:state.entries.length,cash:sum(expenses()),
              missing:p.missing.length,unchanged:before===JSON.stringify(state.entries)};
        """)
        self.assertEqual(result,{'balance':950,'count':1,'cash':100,'missing':0,'unchanged':True})

    def test_multiple_variable_extras_recompute_and_leave_cash_history_unchanged(self):
        result=self.evaluate("""
            state.entries=[__regular(),__early(),__early('second','2026-11-04',70)];
            const before=JSON.stringify(state.entries),p=v125MortgageProgress();
            return {balance:p.balance,count:state.entries.length,cash:sum(expenses()),
              unchanged:before===JSON.stringify(state.entries)};
        """)
        self.assertEqual(result,{'balance':680,'count':3,'cash':370,'unchanged':True})

    def test_editing_or_deleting_after_anchor_invalidates_only_that_allocation(self):
        result=self.evaluate("""
            state.entries=[__regular(),__early()];const original=v125MortgageProgress().balance;
            state.entries[1].amount=250;const editedAmount=v125MortgageProgress().balance;
            state.entries[1]=__early();state.entries[1].date='2026-11-03';
            const editedDate=v125MortgageProgress().balance;
            state.entries.pop();const deleted=v125MortgageProgress().balance;
            return {original,editedAmount,editedDate,deleted};
        """)
        self.assertEqual(result,{'original':750,'editedAmount':950,'editedDate':950,'deleted':950})

    def test_unclassified_credit_expense_does_not_guess_principal(self):
        result=self.evaluate("""
            const unclassified=__early();delete unclassified.mortgageAllocation;
            state.entries=[__regular(),unclassified];
            return {balance:v125MortgageProgress().balance,cash:sum(expenses()),count:state.entries.length};
        """)
        self.assertEqual(result,{'balance':950,'cash':300,'count':2})

    def test_future_actual_record_is_not_applied_before_its_date(self):
        result=self.evaluate("""
            state.entries=[__regular(),__early('future','2026-11-10',200)];
            return {balance:v125MortgageProgress().balance,count:state.entries.length};
        """)
        self.assertEqual(result,{'balance':950,'count':2})

    def test_bank_snapshot_includes_all_payments_through_its_date_once(self):
        result=self.evaluate("""
            state.entries=[__regular(),__early()];__snapshot();
            const before=JSON.stringify(state.entries),p=v125MortgageProgress();
            return {balance:p.balance,missing:p.missing.length,
              unchanged:before===JSON.stringify(state.entries),count:state.entries.length};
        """)
        self.assertEqual(result,{'balance':800,'missing':0,'unchanged':True,'count':2})

    def test_backfill_or_delete_before_bank_snapshot_does_not_reapply_or_revert_it(self):
        result=self.evaluate("""
            __snapshot();const initial=v125MortgageProgress().balance;
            state.entries=[__regular(),__early(),__early('backfill','2026-11-01',30)];
            const backfilled=v125MortgageProgress().balance;
            state.entries=[];const deleted=v125MortgageProgress().balance;
            return {initial,backfilled,deleted};
        """)
        self.assertEqual(result,{'initial':800,'backfilled':800,'deleted':800})

    def test_post_snapshot_payment_and_deletion_recompute_from_confirmed_balance(self):
        result=self.evaluate("""
            __snapshot();state.entries=[__early('after','2026-11-03',50)];
            const paid=v125MortgageProgress().balance;
            state.entries=[];return {paid,deleted:v125MortgageProgress().balance};
        """)
        self.assertEqual(result,{'paid':750,'deleted':800})

    def test_mixed_payment_applies_total_principal_and_covers_only_regular_cash(self):
        result=self.evaluate("""
            state.entries=[__payment('mixed','2026-11-02',300,250,200)];
            const before=JSON.stringify(state.entries),p=v125MortgageProgress(),ob=v78Obligations('2026-11');
            return {balance:p.balance,ordinary:ob.mortgagePaid,
              unchanged:before===JSON.stringify(state.entries),cash:sum(expenses())};
        """)
        self.assertEqual(result,{'balance':750,'ordinary':100,'unchanged':True,'cash':300})

    def test_early_principal_never_pays_a_later_ordinary_due(self):
        result=self.evaluate("""
            state.entries=[__regular(),__early()];
            const ob=v78Obligations('2026-11'),rows=v78ObligationRows(ob),
              later=rows.find(r=>r.kind==='mortgage'&&r.date==='2026-11-30');
            return {ordinary:ob.mortgagePaid,early:state.entries[1].amount,
              laterPaid:later?.paid,laterAllocated:later?.allocated};
        """)
        self.assertEqual(result,{'ordinary':100,'early':200,'laterPaid':False,'laterAllocated':0})

    def test_recomputation_never_changes_the_embedded_bank_baseline(self):
        result=self.evaluate("""
            state.entries=[__regular(),__early()];const before=JSON.stringify(__bankRows);
            v125MortgageProgress();loanScheduleData();v78Obligations('2026-11');
            return {unchanged:before===JSON.stringify(__bankRows),rows:__bankRows.length};
        """)
        self.assertEqual(result,{'unchanged':True,'rows':3})

    def test_future_bank_checkpoint_cannot_replace_todays_actual_balance(self):
        result=self.evaluate("""
            __snapshot('2026-12-01',800);
            return {balance:v125MortgageProgress().balance};
        """)
        self.assertEqual(result['balance'],1000)

    def test_payment_before_contract_cannot_reduce_the_loan(self):
        result=self.evaluate("""
            const e=__early('before-contract','2026-09-01',200);
            state.entries=[e];return {record:v125MortgageRecord(e),balance:v125MortgageProgress().balance};
        """)
        self.assertIsNone(result['record'])
        self.assertEqual(result['balance'],1000)

    def test_early_interest_already_paid_is_not_charged_again_as_future_interest(self):
        result=self.evaluate("""
            const e=__early('paid-interest','2026-11-05',200);
            state.entries=[__regular(),e];
            const principalOnly=v125MortgageProgress();
            e.amount=201;e.mortgageAllocation.amount=201;e.mortgageAllocation.interest=1;
            const paidInterest=v125MortgageProgress();
            return {balance:paidInterest.balance,safe:paidInterest.projection===null||
              paidInterest.projection.totalInterest<=principalOnly.projection.totalInterest-1+.005};
        """)
        self.assertEqual(result['balance'],750)
        self.assertTrue(result['safe'],'Paid interest must be consumed or the projection withheld')


    def test_future_draft_does_not_count_previously_recorded_early_cash_again(self):
        result=self.evaluate("""
            state.entries=[__regular(),__early('paid','2026-11-03',200)];
            const before=JSON.stringify(state),s=v125Scenario([{date:'2026-11-04',amount:50}],'term');
            return {extra:s.totalExtra,first:s.firstBalance,dates:s.rows.filter(r=>r.kind==='extra').map(r=>r.date),unchanged:before===JSON.stringify(state)};
        """)
        self.assertEqual(result,{'extra':50,'first':700,'dates':['2026-11-04'],'unchanged':True})

    def test_paid_principal_alone_cannot_claim_full_interest_settlement(self):
        result=self.evaluate("""
            state.entries=[__regular(),__early('close','2026-11-04',950)];
            const p=v125MortgageProgress();return {balance:p.balance,projection:p.projection,warnings:p.warnings};
        """)
        self.assertEqual(result['balance'],0)
        self.assertIsNone(result['projection'])
        self.assertTrue(result['warnings'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--html',type=Path)
    args,remaining=parser.parse_known_args()
    if args.html:
        harness.HTML=args.html.resolve()
    unittest.main(argv=[__file__,*remaining])
