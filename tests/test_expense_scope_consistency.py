"""Consistent car scope and distinct credit sources; synthetic browser rows only."""
import argparse
from pathlib import Path
import unittest

import test_local_data_safety as harness


class ExpenseScopeConsistency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.LocalDataSafety.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        harness.LocalDataSafety.tearDownClass.__func__(cls)

    setUp = harness.LocalDataSafety.setUp
    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open

    def prepare(self):
        self.open()
        self.page.evaluate("""() => {
            session=null;state=blankState();localStorage.clear();showApp();
            window.__scopeEntry=(id,amount,category,fields={})=>({id,type:'expense',
                date:today(),amount,category,who:'Сергей',beneficiary:'Общее',
                store:'Fictional shop',comment:'Fictional transaction',...fields});
        }""")

    def seed_car(self):
        self.prepare()
        self.page.evaluate("""() => {
            const mk=window.__scopeEntry;
            state.entries=[
                mk('fictional-to',11.25,'ТО'),mk('fictional-fuel',17.50,'Бензин'),
                mk('fictional-modern-fuel',23.75,'Авто и транспорт',{subcategory:'Бензин'}),
                mk('fictional-modern-general',31,'Авто и транспорт'),
                mk('fictional-modern-unknown',37.25,'Авто и транспорт',{subcategory:'Неизвестное старое уточнение'}),
                mk('fictional-legacy-car',41.50,'Автомобиль'),
                mk('fictional-legacy-taxi',43.75,'Такси'),
                mk('fictional-modern-taxi',47,'Авто и транспорт',{subcategory:'Такси'}),
                mk('fictional-modern-transit',53.25,'Авто и транспорт',{subcategory:'Общественный транспорт'}),
                mk('fictional-property-insurance',59.50,'Страховка'),
                mk('fictional-property-tax',61.75,'Налог'),
                mk('fictional-car-insurance-hint',67,'Страховка',{comment:'ОСАГО на машину'}),
                mk('fictional-car-insurance',71.25,'Автострахование'),
                mk('fictional-car-tax-hint',73.50,'Налог',{comment:'Транспортный налог'}),
                mk('fictional-car-tax',79.75,'Транспортный налог'),
                mk('fictional-food',83,'Продукты'),
                mk('fictional-prior-month',97.50,'Авто и транспорт',{date:previousMonthKey(month())+'-10'}),
                mk('fictional-prior-year',101.75,'Бензин',{date:(Number(month().slice(0,4))-1)+'-01-15'}),
                mk('fictional-transfer',107,'Авто и транспорт',{type:'transfer'}),
                mk('fictional-income',109,'Бензин',{type:'income'})
            ];
            window.__scopeOriginal=JSON.stringify(state.entries);
            window.__scopeCarIds=['fictional-to','fictional-fuel','fictional-modern-fuel',
                'fictional-modern-general','fictional-modern-unknown','fictional-legacy-car',
                'fictional-car-insurance-hint','fictional-car-insurance',
                'fictional-car-tax-hint','fictional-car-tax'];
            window.__scopeCarTotal=state.entries.filter(e=>window.__scopeCarIds.includes(e.id)).reduce((n,e)=>n+e.amount,0);
            document.getElementById('homeMonth').value=month();
            document.getElementById('analyticsMonth').value=month();
            document.getElementById('carMonth').value=month();
            renderHome();renderCar();v81SetFocus('auto');
        }""")

    def test_car_month_category_group_special_article_and_auto_focus_agree(self):
        self.seed_car()
        result=self.page.evaluate("""() => {
            const tile=document.querySelector('#v99HomeDirectionTiles [data-v99-direction="car"]');
            const grouped=groupedExpenseEntries(expenses(month()))
                .filter(e=>e.category==='Автомобиль').reduce((n,e)=>n+e.amount,0);
            const expectedYear=state.entries.filter(e=>e.type==='expense'&&
                (window.__scopeCarIds.includes(e.id)||e.id==='fictional-prior-month')&&e.date.startsWith(month().slice(0,4)))
                .reduce((n,e)=>n+e.amount,0);
            const expectedIds=[...window.__scopeCarIds].sort();
            const monthTotal=sum(expenses(month()));
            const recipients=v86TargetTotals(expenses(month())).reduce((n,[,amount])=>n+amount,0);
            tile.click();
            const tileDrillIds=[...document.querySelectorAll('#v84DrillEntries [data-record-action="drill-entry-edit"]')]
                .map(button=>JSON.parse(button.dataset.recordArgs)[0]).sort();
            return {expected:money(window.__scopeCarTotal),car:carMonthTotal.textContent,
                tile:tile.querySelector('strong')?.textContent,expectedTile:money2(window.__scopeCarTotal),
                expectedIds,tileDrillIds,drillMode:v96DrillContext.mode,drillMonth:v96DrillContext.month,
                total:document.getElementById('v99HomeExpenseTotal').textContent,expectedTotal:money2(monthTotal),
                recipients,monthTotal,
                analytics:document.querySelector('#v81LifeSummary strong')?.textContent,
                grouped:money(grouped),year:carYearTotal.textContent,expectedYear:money(expectedYear),
                unchanged:window.__scopeOriginal===JSON.stringify(state.entries)};
        }""")
        for view in ('car','analytics','grouped'):
            self.assertEqual(result[view],result['expected'],view)
        self.assertEqual(result['tile'],result['expectedTile'])
        self.assertEqual(result['tileDrillIds'],result['expectedIds'])
        self.assertEqual(result['drillMode'],'direction')
        self.assertEqual(result['drillMonth'],self.page.evaluate('month()'))
        # The car tile is another cut of existing rows, never another family expense.
        self.assertEqual(result['total'],result['expectedTotal'])
        self.assertEqual(result['recipients'],result['monthTotal'])
        self.assertEqual(result['year'],result['expectedYear'])
        self.assertTrue(result['unchanged'])

    def test_car_filter_drill_and_budget_share_scope_without_changing_recipients(self):
        self.seed_car()
        result=self.page.evaluate("""() => {
            resetHistoryFilters();fMonth.value=month();fGroup.value='Автомобиль';renderHistory();
            const history=[...document.querySelectorAll('#historyBody button[data-action="edit"]')].map(b=>b.dataset.id).sort();
            const expected=[...window.__scopeCarIds].sort();
            const budget=v84SpendGroup(month(),'Автомобиль');
            v84Drill('group','Автомобиль','home');
            const drill=document.getElementById('v84DrillEntries').textContent;
            const cars=state.entries.filter(e=>window.__scopeCarIds.includes(e.id));
            const recipients=Object.fromEntries(v86TargetTotals(expenses(month())));
            return {history,expected,budget,total:window.__scopeCarTotal,
                drillHasGeneric:drill.includes('Неизвестное старое уточнение'),
                drillHasTaxi:drill.includes('Такси'),
                recipientsGeneral:recipients['Общее'],allExpenses:sum(expenses(month())),
                sourceUntouched:window.__scopeOriginal===JSON.stringify(state.entries),
                targetsUntouched:cars.every(e=>e.who==='Сергей'&&e.beneficiary==='Общее')};
        }""")
        self.assertEqual(result['history'],result['expected'])
        self.assertEqual(result['budget'],result['total'])
        self.assertTrue(result['drillHasGeneric'])
        self.assertFalse(result['drillHasTaxi'])
        self.assertEqual(result['recipientsGeneral'],result['allExpenses'])
        self.assertTrue(result['sourceUntouched'])
        self.assertTrue(result['targetsUntouched'])

    def test_unclassified_car_stays_visible_and_taxi_stays_transport(self):
        self.seed_car()
        result=self.page.evaluate("""() => {
            const byId=Object.fromEntries(state.entries.map(e=>[e.id,e]));
            const transportIds=['fictional-legacy-taxi','fictional-modern-taxi','fictional-modern-transit'];
            const grouped=Object.fromEntries(groupedExpenseEntries(expenses(month())).map(e=>[e.id,e.category]));
            return {general:carCategory(byId['fictional-modern-general']),
                unknown:carCategory(byId['fictional-modern-unknown']),legacy:carCategory(byId['fictional-legacy-car']),
                transportExcluded:transportIds.every(id=>carCategory(byId[id])===''),
                transportGrouped:transportIds.every(id=>grouped[id]==='Передвижение'),
                unrelatedExcluded:['fictional-property-insurance','fictional-property-tax','fictional-food'].every(id=>carCategory(byId[id])===''),
                unspecifiedVisible:carCategories.textContent.includes('Без уточнения'),
                categoriesUnchanged:window.__scopeOriginal===JSON.stringify(state.entries)};
        }""")
        for key in ('general','unknown','legacy'):
            self.assertEqual(result[key],'Без уточнения')
        for key in ('transportExcluded','transportGrouped','unrelatedExcluded','unspecifiedVisible','categoriesUnchanged'):
            self.assertTrue(result[key],key)

    def test_unlinked_split_expense_is_not_mortgage_payment(self):
        self.prepare()
        result=self.page.evaluate("""() => {
            const payment=window.__scopeEntry('fictional-split-payment',235.75,'Кредит',
                {store:'Яндекс Сплит',comment:'Fictional purchase payment'});
            state.entries=[payment];const before=JSON.stringify(payment);renderLoans();
            const o=v78Obligations(month());
            const card=loanActualTotal.closest('.card');
            return {mortgage:v78BankExpense(payment),actual:o.mortgageActual,paid:o.mortgagePaid,
                unresolved:loanActualTotal.textContent,expected:money(235.75),
                noBankFigures:!card.querySelector('#v77LoanNext,#v77LoanRest,#loanNextPayment,#loanBalanceNow'),
                unchanged:before===JSON.stringify(state.entries[0])};
        }""")
        self.assertFalse(result['mortgage'])
        self.assertEqual(result['actual'],0)
        self.assertEqual(result['paid'],0)
        self.assertEqual(result['unresolved'],result['expected'])
        self.assertTrue(result['noBankFigures'])
        self.assertTrue(result['unchanged'])

    def test_recognized_mortgage_is_not_unassigned_credit(self):
        self.prepare()
        result=self.page.evaluate("""() => {
            state.entries=[window.__scopeEntry('fictional-split',235.75,'Кредит',{store:'Яндекс Сплит'}),
                window.__scopeEntry('fictional-mortgage',87.65,'Кредит',{mortgagePayment:true})];
            renderLoans();return {unresolved:loanActualTotal.textContent,expected:money(235.75),
                mortgageActual:v78Obligations(month()).mortgageActual};
        }""")
        self.assertEqual(result['unresolved'],result['expected'])
        self.assertEqual(result['mortgageActual'],87.65)

    def test_split_paid_from_bank_named_card_is_not_inferred_as_mortgage(self):
        self.prepare()
        result=self.page.evaluate("""() => {
            const payment=window.__scopeEntry('fictional-bank-card-split',321.45,'Кредит',
                {store:'УралСиб карта',comment:'Яндекс Сплит · Fictional purchase'});
            state.entries=[payment];const before=JSON.stringify(state.entries);renderLoans();
            return {inferred:v78BankExpense(payment),actual:v78Obligations(month()).mortgageActual,
                unresolved:loanActualTotal.textContent,expected:money(321.45),count:state.entries.length,
                rawUnchanged:before===JSON.stringify(state.entries),
                explicitMarker:v78BankExpense({...payment,mortgagePayment:true}),
                explicitObligation:v78BankExpense({...payment,obligationType:'mortgage'})};
        }""")
        self.assertEqual(result,{'inferred':False,'actual':0,'unresolved':result['expected'],
            'expected':result['expected'],'count':1,'rawUnchanged':True,
            'explicitMarker':True,'explicitObligation':True})

    def test_later_split_plan_links_existing_expense_without_second_expense(self):
        self.prepare()
        part=self.page.evaluate("""() => {
            const existing=window.__scopeEntry('fictional-existing-split',235.75,'Кредит',
                {store:'Яндекс Сплит',futureField:{keep:true}});
            state.entries=[existing];window.__scopePayment=JSON.stringify(existing);
            v77Kind.value='split';v77KindChanged();v77Purchase.value='Fictional purchase';
            v77PurchaseSum.value='943';v77PartCount.value='4';v77FirstDate.value=today();
            v77Period.value='fortnight';v77CreateInstallment();go('loans');
            const plan=state.installments[0],part=plan.parts[0];
            document.querySelector('[data-v77-match]').closest('details').open=true;
            return {plan:plan.id,part:part.id,count:state.entries.length};
        }""")
        self.assertEqual(part['count'],1)
        self.page.locator('button[data-v77-match][data-v77-part="'+part['part']+'"]').click()
        self.page.locator('button[data-v77-entry="fictional-existing-split"]').click()
        result=self.page.evaluate("""() => {
            const plan=state.installments[0],part=plan.parts[0];
            return {count:state.entries.length,total:sum(expenses()),linked:plan.links[part.id],
                paid:installmentPaid(plan,part),allocated:installmentAllocated(plan,part),
                unchanged:window.__scopePayment===JSON.stringify(state.entries[0]),
                mortgage:v78Obligations(month()).mortgageActual,
                unresolved:loanActualTotal.textContent,zero:money(0)};
        }""")
        self.assertEqual(result,{'count':1,'total':235.75,'linked':'fictional-existing-split',
            'paid':True,'allocated':235.75,'unchanged':True,'mortgage':0,
            'unresolved':result['zero'],'zero':result['zero']})


if __name__=='__main__':
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--html',type=Path)
    args,remaining=parser.parse_known_args()
    if args.html:
        harness.HTML=args.html.resolve()
    unittest.main(argv=[__file__,*remaining])
