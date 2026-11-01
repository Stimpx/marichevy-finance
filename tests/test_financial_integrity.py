"""PR3 financial regressions, synthetic browser state and blocked external requests only."""
import argparse
from pathlib import Path
import unittest

import test_local_data_safety as harness


class FinancialIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.LocalDataSafety.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        harness.LocalDataSafety.tearDownClass.__func__(cls)

    setUp = harness.LocalDataSafety.setUp
    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open

    def evaluate(self, code, *, isolated_forecast=False):
        self.open()
        if isolated_forecast:
            # These fixtures exercise only fictional installment/recurring plans.
            # Keep a past day within one period and exclude the unrelated embedded
            # bank schedule, so month rollover cannot change their expected scope.
            code="""today=()=> '2026-10-21';month=()=> '2026-10';
                loanScheduleData=()=>[];state.settings.preferences.payday=0;"""+code
        return self.page.evaluate('''async () => {
            session=null;state=blankState();localStorage.clear();
            window.confirm=()=>true;window.prompt=()=> '1';
            const mk=(id,amount,fields={})=>({id,type:'expense',date:today(),amount,
                category:'Прочее',who:'Общее',store:'Fictional shop',...fields});
            const makePlan=(amount=4608,date=today(),mode)=>({id:'fictional-plan',kind:'split',
                title:'Fictional purchase',provider:'Fictional provider',amount,
                parts:[{id:'fictional-part',date,amount}],links:{},...(mode?{accountingMode:mode}:{})});
        '''+code+'\n}')

    def test_partial_edited_link_allocates_actual_and_deletion_reopens_part(self):
        result = self.evaluate('''
            const plan=makePlan();state.installments=[plan];state.entries=[mk('linked',1)];plan.links['fictional-part']='linked';
            const p=plan.parts[0],ob=v78Obligations(month()),row=v78ObligationRows(ob).find(x=>x.kind==='installment');
            renderInstallments();const text=document.getElementById('v77InstallmentSummary').textContent;
            const before={paid:installmentPaid(plan,p),allocated:ob.groups[0].paid,remaining:ob.groups[0].planned-ob.groups[0].paid,row,upcoming:installmentUpcoming()[0]?.amount,text};
            state.entries=[];const after={paid:installmentPaid(plan,p),allocated:v78Obligations(month()).groups[0].paid};
            return {before,after};''')
        self.assertFalse(result['before']['paid'])
        self.assertEqual(result['before']['allocated'], 1)
        self.assertEqual(result['before']['remaining'], 4607)
        self.assertEqual(result['before']['upcoming'], 4607)
        self.assertEqual(result['before']['row']['allocated'], 1)
        self.assertTrue(result['before']['row']['partial'])
        self.assertFalse(result['after']['paid'])
        self.assertEqual(result['after']['allocated'], 0)

    def test_overpaid_link_caps_allocation_without_rewriting_history(self):
        result=self.evaluate('''const p=makePlan();state.installments=[p];state.entries=[mk('large',5000)];p.links['fictional-part']='large';return {amount:state.entries[0].amount,paid:v78Obligations(month()).groups[0].paid,complete:installmentPaid(p,p.parts[0])};''')
        self.assertEqual(result, {'amount':5000,'paid':4608,'complete':True})

    def test_confirm_past_part_records_today_and_keeps_due_date(self):
        result=self.evaluate('''const due=previousMonthKey(month())+'-10',p=makePlan(4608,due,'payments');state.installments=[p];v77PayPart(p.id,p.parts[0].id);return {date:state.entries[0].date,due:p.parts[0].date,metadata:state.entries[0].scheduledDate,today:today()};''')
        self.assertEqual(result['date'], result['today'])
        self.assertEqual(result['metadata'], result['due'])
        self.assertNotEqual(result['date'], result['due'])

    def test_explicit_booked_purchase_creates_debt_movement_only(self):
        result=self.evaluate('''state.entries=[mk('full-purchase',18432)];const p=makePlan(4608,today());state.installments=[p];window.prompt=()=> '2';v77PayPart(p.id,p.parts[0].id);const e=state.entries[1];return {spent:sum(expenses()),type:e.type,flag:e.debtRepayment,mode:p.accountingMode,paid:installmentPaid(p,p.parts[0]),original:state.entries[0].amount};''')
        self.assertEqual(result,{'spent':18432,'type':'transfer','flag':True,'mode':'purchase','paid':True,'original':18432})

    def test_payments_choice_preserves_equal_unlinked_historical_expense(self):
        result=self.evaluate('''const old=mk('fictional-existing-payment',4608,{beneficiary:'Сергей'});state.entries=[old];const p=makePlan();state.installments=[p];const before=JSON.stringify(old);window.prompt=()=> '1';v77PayPart(p.id,p.parts[0].id);return {oldUnchanged:before===JSON.stringify(state.entries[0]),spent:sum(expenses()),count:state.entries.length,mode:p.accountingMode,type:state.entries[1].type};''')
        self.assertEqual(result,{'oldUnchanged':True,'spent':9216,'count':2,'mode':'payments','type':'expense'})

    def test_cancel_mode_choice_leaves_plan_and_operations_unchanged(self):
        result=self.evaluate('''const p=makePlan();state.installments=[p];const before=JSON.stringify(state);window.prompt=()=>null;v77PayPart(p.id,p.parts[0].id);return {before,after:JSON.stringify(state)};''')
        self.assertEqual(result['before'],result['after'])

    def test_partial_confirmation_does_not_silently_replace_edited_history(self):
        result=self.evaluate('''const p=makePlan(4608,today(),'payments');state.installments=[p];state.entries=[mk('actual',1)];p.links['fictional-part']='actual';const before=JSON.stringify(state);v77PayPart(p.id,p.parts[0].id);return {before,after:JSON.stringify(state)};''')
        self.assertEqual(result['before'],result['after'])

    def test_overdue_forecast_includes_pending_current_recurring_and_old_partial(self):
        result=self.evaluate('''state.intelligence.accounts=[{id:'cash',amount:10000}];state.intelligence.recurring=[{id:'rent',name:'Fictional rent',amount:4000,day:1}];const p=makePlan(4608,previousMonthKey(month())+'-10');state.installments=[p];state.entries=[mk('partial',1)];p.links['fictional-part']='partial';const f=v86Forecast();return {regular:f.regular,mortgage:f.mortgage,overdue:f.overdue,estimate:f.estimate};''', isolated_forecast=True)
        self.assertEqual(result,{'regular':4000,'mortgage':4607,'overdue':8607,'estimate':1393})

    def test_explicit_installment_recurring_cross_link_deduplicates_same_part(self):
        result=self.evaluate('''state.intelligence.accounts=[{id:'cash',amount:10000}];const p=makePlan(4608,today());state.installments=[p];state.intelligence.recurring=[{id:'same-plan',name:'Fictional payment',amount:4608,day:Number(today().slice(8)),installmentId:p.id,installmentPartId:p.parts[0].id}];return {sum:v86Forecast().obligations,events:v86Forecast().events.filter(x=>x.kind!=='mortgage').length};''', isolated_forecast=True)
        self.assertEqual(result,{'sum':4608,'events':1})

    def test_equal_amounts_do_not_infer_duplicate(self):
        result=self.evaluate('''state.intelligence.accounts=[{id:'cash',amount:20000}];const p=makePlan();state.installments=[p];state.intelligence.recurring=[{id:'unrelated',name:'Different payment',amount:4608,day:Number(today().slice(8))}];return v86Forecast().obligations;''', isolated_forecast=True)
        self.assertEqual(result,9216)

    def test_transfer_only_month_is_not_advisor_expense_basis(self):
        result=self.evaluate('''state.entries=[mk('transfer',100,{type:'transfer',date:previousMonthKey(month())+'-10'}),mk('current',5000)];const d=v87AdvisorData();v87RenderAdvisor();return {months:d.months,spent:d.spent,provisional:d.provisional,status:document.getElementById('v87AdvisorStatus').textContent};''')
        self.assertEqual(result['spent'],5000)
        self.assertTrue(result['provisional'])
        self.assertEqual(len(result['months']),1)
        self.assertIn('Доходы не внесены',result['status'])

    def test_income_only_cannot_claim_zero_required_expenses(self):
        result=self.evaluate('''state.entries=[mk('income',100,{type:'income'})];const d=v87AdvisorData();v87RenderAdvisor();return {months:d.months,metrics:document.getElementById('v87AdvisorMetrics').textContent,status:document.getElementById('v87AdvisorStatus').textContent};''')
        self.assertEqual(result['months'],[])
        self.assertEqual(result['metrics'],'')
        self.assertIn('Недостаточно данных',result['status'])

    def test_report_destinations_separate_loans_and_car_but_history_keeps_saved_recipient(self):
        result=self.evaluate('''
            state.entries=[mk('alice',100,{who:'Сергей',beneficiary:'Алиса',category:'Вкусняшки'}),
                mk('legacy',200,{who:'Виктория'}),mk('credit',4608,{beneficiary:'Сергей',category:'Кредит'}),
                mk('car',300,{beneficiary:'Сергей',category:'Бензин'})];
            const before=JSON.stringify(state.entries);
            document.getElementById('fWho').value='Алиса';renderHistory();
            const alice=document.getElementById('historyCount').textContent;
            document.getElementById('fWho').value='Сергей';renderHistory();
            return {totals:Object.fromEntries(v86TargetTotals(expenses(month()))),alice,
                sergey:document.getElementById('historyCount').textContent,total:sum(expenses(month())),
                legacy:state.entries[1].who,unchanged:before===JSON.stringify(state.entries)};
        ''')
        self.assertEqual(result['totals']['Сергей'],0)
        self.assertEqual(result['totals']['Алиса'],100)
        self.assertEqual(result['totals']['Виктория'],200)
        self.assertEqual(result['totals']['Автомобиль'],300)
        self.assertEqual(result['totals']['Кредиты и рассрочки'],4608)
        self.assertEqual(sum(result['totals'].values()),result['total'])
        self.assertTrue(result['alice'].startswith('1 '), result)
        self.assertTrue(result['sergey'].startswith('2 '), result)
        self.assertEqual(result['legacy'],'Виктория')
        self.assertTrue(result['unchanged'])

    def test_exclusive_destinations_use_real_loan_links_and_keep_taxi_and_recurring_expenses_personal(self):
        result=self.evaluate('''
            const plan=makePlan();plan.links['fictional-part']='linked-car';state.installments=[plan];
            state.entries=[
                mk('food',10.01,{beneficiary:'Сергей',category:'Продукты'}),
                mk('fuel',11.02,{beneficiary:'Виктория',category:'Бензин'}),
                mk('credit',12.03,{beneficiary:'Сергей',category:'Кредит'}),
                mk('linked-car',13.04,{beneficiary:'Сергей',category:'Бензин'}),
                mk('installment',14.05,{beneficiary:'Алиса',category:'Продукты',installmentId:plan.id}),
                mk('mortgage',15.06,{beneficiary:'Общее',mortgagePayment:true}),
                mk('mortgage-type',16.07,{beneficiary:'Общее',obligationType:'mortgage'}),
                mk('taxi',17.08,{beneficiary:'Сергей',category:'Авто и транспорт',subcategory:'Такси'}),
                mk('transit',18.09,{beneficiary:'Сергей',category:'Авто и транспорт',subcategory:'Общественный транспорт'}),
                mk('recurring',19.10,{beneficiary:'Сергей',category:'Продукты',paymentKey:'recurring:test',
                    recurringId:'fictional-recurring',scheduledDate:today(),autoGenerated:true,accountingMode:'payments'}),
                mk('explicit-car',20.11,{beneficiary:'Автомобиль',category:'Продукты'}),
                mk('explicit-loan',21.12,{beneficiary:'Кредиты и рассрочки',category:'Бензин'}),
                mk('custom',22.13,{beneficiary:'constructor',category:'Продукты'}),
                mk('legacy-credit',23.14,{beneficiary:'Сергей',category:' кредит '}),
                mk('bank-description',24.15,{beneficiary:'Сергей',category:'Продукты',comment:'Fictional bank mortgage text'}),
                mk('transfer',900,{type:'transfer',category:'Кредит',debtRepayment:true,installmentId:plan.id}),
                mk('income',800,{type:'income',category:'Бензин'}),
                mk('old-credit',700,{category:'Кредит',date:previousMonthKey(month())+'-10'})
            ];
            const before=JSON.stringify(state),rows=expenses(month()),totals=v86TargetTotals(rows);
            return {ids:rows.map(e=>e.id),buckets:Object.fromEntries(rows.map(e=>[e.id,v94ExpenseBucket(e)])),
                targets:Object.fromEntries(rows.map(e=>[e.id,v86ExpenseTarget(e)])),
                totals:Object.fromEntries(totals),total:sum(rows),
                bucketTotal:sum(totals.map(([,amount])=>({amount}))),
                unchanged:before===JSON.stringify(state)};
        ''')
        expected={
            'food':'Сергей','fuel':'Автомобиль','credit':'Кредиты и рассрочки',
            'linked-car':'Кредиты и рассрочки','installment':'Кредиты и рассрочки',
            'mortgage':'Кредиты и рассрочки','mortgage-type':'Кредиты и рассрочки',
            'taxi':'Сергей','transit':'Сергей','recurring':'Сергей',
            'explicit-car':'Автомобиль','explicit-loan':'Кредиты и рассрочки',
            'custom':'constructor','legacy-credit':'Кредиты и рассрочки','bank-description':'Сергей',
        }
        self.assertEqual(result['buckets'],expected)
        self.assertEqual(set(result['ids']),set(expected))
        self.assertEqual(result['totals']['Кредиты и рассрочки'],114.51)
        self.assertEqual(result['totals']['Автомобиль'],31.13)
        self.assertEqual(result['totals']['Сергей'],88.43)
        self.assertEqual(result['totals']['constructor'],22.13)
        self.assertEqual(result['total'],256.20)
        self.assertEqual(result['bucketTotal'],result['total'])
        self.assertEqual(result['targets']['fuel'],'Виктория')
        self.assertEqual(result['targets']['linked-car'],'Сергей')
        self.assertEqual(result['targets']['installment'],'Алиса')
        self.assertTrue(result['unchanged'])

    def test_empty_destination_breakdown_includes_loans_and_car_at_zero(self):
        result=self.evaluate('''const before=JSON.stringify(state);return {
            totals:Object.fromEntries(v86TargetTotals([])),unchanged:before===JSON.stringify(state)};''')
        self.assertEqual(result['totals']['Кредиты и рассрочки'],0)
        self.assertEqual(result['totals']['Автомобиль'],0)
        self.assertEqual(sum(result['totals'].values()),0)
        self.assertTrue(result['unchanged'])

    def test_incomplete_installment_link_does_not_turn_missing_entry_id_into_a_loan(self):
        result=self.evaluate('''
            const plan=makePlan();plan.links['fictional-part']=undefined;state.installments=[plan];
            state.entries=[mk(undefined,.1,{beneficiary:'Сергей',category:'Продукты'}),
                mk('',.2,{beneficiary:'Сергей',category:'Продукты'})];
            const before=JSON.stringify(state),rows=expenses(month());
            return {buckets:rows.map(v94ExpenseBucket),totals:Object.fromEntries(v86TargetTotals(rows)),
                unchanged:before===JSON.stringify(state)};
        ''')
        self.assertEqual(result['buckets'],['Сергей','Сергей'])
        self.assertEqual(result['totals']['Сергей'],.3)
        self.assertEqual(result['totals']['Кредиты и рассрочки'],0)
        self.assertTrue(result['unchanged'])

    def test_partial_income_is_labeled_and_not_compared_to_required_plan(self):
        result=self.evaluate('''const previous=previousMonthKey(month()),older=previousMonthKey(previous);state.entries=[mk('expense-a',5000,{date:previous+'-10'}),mk('expense-b',7000,{date:older+'-10'}),mk('income-a',10000,{type:'income',date:previous+'-10'})];const d=v87AdvisorData();v87RenderAdvisor();return {spent:d.spent,income:d.income,required:d.required,hasIncome:d.hasIncome,partialIncome:d.partialIncome,status:document.getElementById('v87AdvisorStatus').textContent,guide:document.getElementById('v87AdvisorGuidance').textContent};''')
        self.assertEqual(result['spent'],6000)
        self.assertEqual(result['income'],5000)
        self.assertEqual(result['required'],6000)
        self.assertTrue(result['partialIncome'])
        self.assertFalse(result['hasIncome'])
        self.assertIn('не во все месяцы',result['status'])
        self.assertNotIn('должен вырасти',result['guide'])

    def test_early_model_summary_and_input_rows_agree_after_overpayment(self):
        result=self.evaluate('''addEarlyPaymentRow(5000000,'2026-10-21');addEarlyPaymentRow(10000,'2026-11-15');const sim=simulateEarlyPlan(getEarlyPayments(),'term'),before={balance:document.getElementById('earlyFirstBalance').textContent,total:document.getElementById('earlyFirstTotal').textContent,rows:[...document.querySelectorAll('.early-plan-total')].map(e=>e.textContent)};renderEarlyRepayment();return {before,expected:{balance:money2(sim.firstBalance),total:money2(sim.rows[0].total)},result:document.getElementById('earlyResult').textContent};''')
        self.assertEqual(result['before']['balance'],result['expected']['balance'])
        self.assertEqual(result['before']['total'],result['expected']['total'])
        self.assertIn('не использовано',result['before']['rows'][1])
        self.assertIn('Прочие начисления',result['result'])
        self.assertIn('Не использовано',result['result'])
        self.assertIn('21.10.2026',result['result'])

    def test_zero_early_scenario_exactly_preserves_pinned_bank_rows_and_charges(self):
        result=self.evaluate('''const pinned=JSON.stringify(BANK_LOAN_SCHEDULE),base=loanScheduleData(),sim=simulateEarlyPlan([{date:base[0].payDate,amount:0}],'term');return {unchanged:pinned===JSON.stringify(BANK_LOAN_SCHEDULE),rows:sim.rows,base,interest:sim.totalInterest};''')
        self.assertTrue(result['unchanged'])
        self.assertEqual(len(result['rows']),len(result['base']))
        for actual,expected in zip(result['rows'],result['base']):
            for a,b in [('body','body'),('total','payment'),('balance','balance'),('interest','interest')]:
                self.assertAlmostEqual(actual[a],expected[b],places=2,msg=str((actual,expected)))
            self.assertAlmostEqual(actual['body']+actual['interest']+actual['charges'],actual['total'],places=2)
        self.assertAlmostEqual(result['interest'],sum(row['interest'] for row in result['base']),places=2)

    def test_partial_and_full_early_repayment_have_consistent_rows(self):
        result=self.evaluate('''return ['term','payment'].flatMap(mode=>[50000,4500000,5000000].map(amount=>simulateEarlyPlan([{date:'2026-10-21',amount}],mode)));''')
        for amount,sim in zip((50000,4500000,5000000)*2, result):
            self.assertGreater(sim['totalInterest'],0)
            self.assertAlmostEqual(sim['totalInterest'],sum(row['interest'] for row in sim['rows']),places=2)
            self.assertLessEqual(sim['totalExtra'],4500000)
            self.assertAlmostEqual(sim['totalExtra']+sim['totalUnused'],amount,places=2)
            balance=4500000
            for row in sim['rows']:
                self.assertGreaterEqual(row['body'],0)
                self.assertLessEqual(row['body'],balance+.005)
                self.assertAlmostEqual(row['balance'],balance-row['body'],places=2)
                self.assertAlmostEqual(row['total'],row['body']+row['interest']+row.get('charges',0),places=2)
                balance=row['balance']
        self.assertEqual(result[-1]['firstBalance'],0)
        self.assertEqual(result[-1]['totalUnused'],500000)

    def test_early_extras_after_payoff_remain_explicitly_unused(self):
        result=self.evaluate('''return simulateEarlyPlan([{date:'2026-10-21',amount:5000000},{date:'2026-11-15',amount:10000}],'term');''')
        self.assertEqual(result.get('totalUnused'),510000)
        self.assertEqual(result['rows'][-1]['kind'],'unused')
        self.assertEqual(result['rows'][-1]['body'],0)


if __name__=='__main__':
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--html',type=Path)
    args,remaining=parser.parse_known_args()
    if args.html:
        harness.HTML=args.html.resolve()
    unittest.main(argv=[__file__,*remaining])
