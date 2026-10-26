"""Versioned expense groups and legacy budget scopes; fictional data, blocked network."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import test_local_data_safety as harness
import test_sync_protocol as protocol


class ExpenseGroups(unittest.TestCase):
    @classmethod
    def setUpClass(cls):harness.LocalDataSafety.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):harness.LocalDataSafety.tearDownClass.__func__(cls)
    setUp=harness.LocalDataSafety.setUp
    tearDown=harness.LocalDataSafety.tearDown
    open=harness.LocalDataSafety.open
    import_data=harness.LocalDataSafety.import_data
    snapshot=harness.LocalDataSafety.snapshot

    def prepare(self):
        self.open()
        self.page.evaluate("""()=>{
          session=null;stopCloudSync();localStorage.clear();state=blankState();
          const row=(id,category,amount,type='expense')=>({id,type,date:today(),amount,
            category,who:'Учебный участник',beneficiary:'Общее',store:'Фиктивный магазин',
            comment:'Только тестовая запись',future:{keep:[true,null,id]}});
          state.entries=[row('subscriptions','Подписки',0.10),row('leisure','Развлечения',0.20),
            row('work','Работа',0.30),row('other','Прочее',0.40),row('food','Продукты',1.05),
            row('unknown','Прежняя неизвестная категория',0.06),
            row('transfer','Подписки',99,'transfer'),row('income','Подписки',100,'income')];
          state.settings.preferences.futureSetting={keep:true};
          state.intelligence.budgets=[{id:'legacy-leisure',group:'Досуг и привычки',amount:0.30,
            futureBudget:{keep:true},created_at:'2025-01-01T00:00:00Z',updated_at:'2025-01-01T00:00:00Z'},
            {id:'legacy-other',group:'Прочее',amount:0.76,updated_at:'2025-01-01T00:00:00Z'}];
          state.intelligence.deleted.budgets={'fictional-deleted':'2025-01-01T00:00:00Z'};
          weatherCache.data={temperature_2m:10,weather_code:0};weatherCache.at=Date.now();
          showApp();renderAll();go('analytics');
        }""")

    def test_current_groups_separate_services_work_and_keep_total_records_and_links(self):
        self.prepare();before=self.snapshot()
        result=self.page.evaluate("""()=>({groups:EXPENSE_GROUPS.map(group=>[group.id,group.title]),
          totals:Object.fromEntries(EXPENSE_GROUPS.map(group=>[group.title,v84SpendGroup(month(),group.title)])),
          total:sum(expenses(month())),unknown:expenseGroup('constructor'),
          colors:['Подписки и сервисы','Работа'].map(v84GroupColor)})""")
        self.assertEqual(len(result['groups']),10)
        self.assertEqual(len({row[0] for row in result['groups']}),10)
        self.assertEqual(result['totals']['Подписки и сервисы'],0.10)
        self.assertEqual(result['totals']['Работа'],0.30)
        self.assertEqual(result['totals']['Досуг и привычки'],0.20)
        self.assertEqual(result['totals']['Прочее'],0.46)
        self.assertEqual(round(sum(result['totals'].values()),2),result['total'])
        self.assertEqual(result['total'],2.11);self.assertEqual(result['unknown'],'Прочее')
        self.assertEqual(len(set(result['colors'])),2)
        self.assertEqual(self.snapshot(),before)

    def test_legacy_budgets_keep_original_scope_and_cents_without_render_migration(self):
        self.prepare();before=self.snapshot()
        result=self.page.evaluate("""()=>({spent:state.intelligence.budgets.map(b=>v84BudgetSpent(month(),b)),
          text:v84BudgetList.textContent,report:v84ReportText()})""")
        self.assertEqual(result['spent'],[0.30,0.76])
        self.assertIn('Сохранённый состав · включая «Подписки»',result['text'])
        self.assertIn('Сохранённый состав · включая «Работа»',result['text'])
        self.assertNotIn('лимит превышен',result['text']);self.assertNotIn('· превышено',result['report'])
        self.page.evaluate("state.entries.push({...state.entries[0],id:'extra-kopeck',amount:0.01});v84RenderBudgets()")
        self.assertIn('лимит превышен',self.page.locator('[data-budget-id="legacy-leisure"]').inner_text())
        self.assertEqual(json.loads(before['state'])['intelligence']['budgets'],self.page.evaluate('state.intelligence.budgets'))
        self.assertEqual(self.snapshot()['storage'],before['storage'])

    def test_new_budget_uses_stable_id_version_and_never_updates_same_title_legacy(self):
        self.prepare();before=self.page.evaluate('JSON.parse(JSON.stringify(state))')
        self.page.locator('#v84BudgetGroup').select_option('Досуг и привычки')
        self.page.locator('#v84BudgetAmount').fill('0.50')
        self.page.evaluate('v84AddBudget()')
        self.page.wait_for_function('state.intelligence.budgets.length===3')
        budgets=self.page.evaluate('state.intelligence.budgets')
        self.assertEqual(budgets[:2],before['intelligence']['budgets'])
        fresh=budgets[-1];self.assertEqual((fresh['groupId'],fresh['groupVersion']),('leisure',2))
        self.assertEqual(fresh['group'],'Досуг и привычки')
        self.assertEqual(self.page.evaluate('v84BudgetSpent(month(),state.intelligence.budgets.at(-1))'),0.20)
        self.page.evaluate("state.intelligence.budgets.at(-1).futureMetadata={preserve:true}")
        self.page.locator('#v84BudgetAmount').fill('0.60');self.page.evaluate('v84AddBudget()')
        self.assertEqual(self.page.evaluate('state.intelligence.budgets.length'),3)
        self.assertEqual(self.page.evaluate('state.intelligence.budgets.at(-1).futureMetadata'),{'preserve':True})
        self.assertEqual(self.page.evaluate('state.intelligence.budgets.at(-1).amount'),0.60)
        self.assertEqual(self.page.evaluate('state.entries'),before['entries'])
        self.assertEqual(self.page.evaluate('state.intelligence.deleted.budgets'),before['intelligence']['deleted']['budgets'])

    def test_new_service_budget_updates_current_scope_and_survives_device_backup(self):
        self.prepare();self.page.locator('#v84BudgetGroup').select_option('Подписки и сервисы')
        self.page.locator('#v84BudgetAmount').fill('12.34');self.page.evaluate('v84AddBudget()')
        self.page.wait_for_function("!!localStorage.getItem(KEYS.pending)")
        saved=self.page.evaluate('state.intelligence.budgets.at(-1)')
        self.assertEqual((saved['groupId'],saved['groupVersion']),('subscriptions',2))
        self.page.evaluate("go('settings')")
        with self.page.expect_download() as result:
            self.page.get_by_role('button',name='↓ Полная копия устройства',exact=True).click()
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'fictional-capture.json';result.value.save_as(target)
            capture=json.loads(target.read_text())
        memory=json.loads(capture['memory_state_json'])['intelligence']['budgets'][-1]
        pending=json.loads(next(row['raw'] for row in capture['records'] if row['key']==harness.PENDING))['intelligence']['budgets'][-1]
        self.assertEqual(memory,saved);self.assertEqual(pending,saved)

    def test_unknown_scope_has_no_guessed_zero_percentage_or_overspend_verdict(self):
        self.prepare()
        self.page.evaluate("""()=>{state.intelligence.budgets=[
          {id:'unknown-v1',group:'Учебный неизвестный состав',amount:0.01,futureField:7},
          {id:'unknown-v3',group:'Учебный будущий состав',groupId:'subscriptions',groupVersion:99,amount:0.01},
          {id:'missing-id',group:'Подписки и сервисы',groupId:'missing',groupVersion:2,amount:0.01}];v84RenderBudgets()}""")
        before=self.snapshot()
        self.assertEqual(self.page.evaluate('state.intelligence.budgets.map(b=>v84BudgetSpent(month(),b))'),[None,None,None])
        text=self.page.locator('#v84BudgetList').inner_text()
        self.assertEqual(text.count('Состав лимита не распознан'),3)
        self.assertNotIn('%',text);self.assertNotIn('0 ₽',text);self.assertNotIn('превышен',text)
        self.assertEqual(self.page.locator('#v84BudgetList .v84-progress').count(),0)
        self.assertIn('Учебный будущий состав',self.page.evaluate('v84ReportText()'))
        self.assertEqual(self.snapshot(),before)

    def test_idless_public_custom_group_fallback_and_legacy_scope_are_compatible(self):
        self.prepare()
        result=self.page.evaluate("""()=>{EXPENSE_GROUPS.push({title:'Учебная группа',values:['Учебная категория']});
          EXPENSE_GROUP_NAME['Учебная категория']='Учебная группа';
          state.entries.push({...state.entries[0],id:'custom',category:'Учебная категория',amount:0.07});
          v84InitLists();return {id:v98GroupId(EXPENSE_GROUPS.at(-1)),
            old:v84BudgetSpent(month(),{group:'Учебная группа'}),
            current:v84BudgetSpent(month(),{group:'Учебная группа',groupId:v98GroupId(EXPENSE_GROUPS.at(-1)),groupVersion:2}),
            option:[...v84BudgetGroup.options].at(-1).textContent}}""")
        self.assertTrue(result['id'].startswith('custom:'))
        self.assertEqual(result['old'],0.07);self.assertEqual(result['current'],0.07)
        self.assertEqual(result['option'],'Учебная группа')
        self.assertEqual(self.page.evaluate("EXPENSE_GROUPS.at(-1).id='family-custom-id';v84BudgetSpent(month(),{group:'Учебная группа'})"),0.07)

    def test_history_and_analytics_drill_use_new_groups_without_editing_expenses(self):
        self.prepare();before=self.snapshot()
        self.page.evaluate("go('history');fMonth.value=month();fGroup.value='Подписки и сервисы';renderHistory()")
        self.assertEqual(self.page.locator('#historyBody .v76-entry-row').count(),1)
        self.assertIn('0,10',self.page.locator('#historyBody').inner_text())
        self.page.evaluate("go('analytics');v84Drill('group','Работа','analytics')")
        self.assertEqual(self.page.locator('#v84DrillEntries .v85-drill-entry').count(),1)
        self.assertIn('0,30',self.page.locator('#v84DrillEntries').inner_text())
        self.assertEqual(self.snapshot(),before)

    def test_normalize_validate_and_actual_import_preserve_scope_metadata_and_extensions(self):
        self.prepare();fixture=protocol.fixture()
        budget={'id':'new-import','group':'Подписки и сервисы','groupId':'subscriptions','groupVersion':2,
                'amount':12.34,'updated_at':protocol.AT,'futureField':{'keep':[None,True]}}
        fixture['intelligence']['budgets']=[budget]
        result=self.page.evaluate("""raw=>({validated:parseLocalState(JSON.stringify(raw)).intelligence.budgets[0],
          normalized:normalize(raw).intelligence.budgets[0]})""",fixture)
        self.assertEqual(result['validated'],budget);self.assertEqual(result['normalized'],budget)
        self.import_data(fixture)
        self.assertEqual(self.page.evaluate('state.intelligence.budgets[0]'),budget)
        pending=self.page.evaluate('JSON.parse(localStorage.getItem(KEYS.pending))')
        self.assertEqual(pending['intelligence']['budgets'][0],budget)

    def test_existing_recurring_subscription_allocation_and_link_candidates_stay_intact(self):
        self.prepare()
        result=self.page.evaluate("""()=>{const rec={id:'legacy-recurring',name:'Фиктивная старая подписка',
          category:'Досуг и привычки',amount:0.30,day:1};state.intelligence.recurring=[rec];
          state.entries.push({...state.entries[0],id:'linked-payment',amount:0.30,recurringId:rec.id,recurringPeriod:month()});
          const before=JSON.stringify(state);v84RenderAll();return {unchanged:before===JSON.stringify(state),
            confirmed:v84RecurringConfirmed(rec,month()),allocated:v84RecurringAllocated(rec,month()),
            event:v86CalendarEvents(month()).find(row=>row.recurringId===rec.id)}}""")
        self.assertTrue(result['unchanged']);self.assertTrue(result['confirmed'])
        self.assertEqual(result['allocated'],0.30);self.assertTrue(result['event']['paid'])
        self.page.evaluate("state.entries=state.entries.filter(e=>e.id!=='linked-payment');go('analytics');v84LinkRecurring('legacy-recurring',month())")
        # The existing unlinked work payment has exactly30kopecks; group split cannot hide it.
        self.assertIn('0,30',self.page.locator('#v84DrillBody').inner_text())
        self.assertEqual(self.page.locator('#v84DrillBody [data-v84-link="work"]').count(),1)


class ExpenseGroupSync(unittest.TestCase):
    @classmethod
    def setUpClass(cls):protocol.SyncProtocol.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):protocol.SyncProtocol.tearDownClass.__func__(cls)
    setUp=protocol.SyncProtocol.setUp
    tearDown=protocol.SyncProtocol.tearDown
    device=protocol.SyncProtocol.device
    start=protocol.SyncProtocol.start
    finish=protocol.SyncProtocol.finish
    wait_held=protocol.SyncProtocol.wait_held
    concurrent_push=protocol.SyncProtocol.concurrent_push
    assert_no_legacy_write=protocol.SyncProtocol.assert_no_legacy_write

    def test_cas_conflict_preserves_legacy_budget_new_group_versions_and_unknown_fields(self):
        base=protocol.fixture();legacy={'id':'legacy','group':'Досуг и привычки','amount':10,
            'updated_at':protocol.AT,'futureField':{'keep':True}}
        base['intelligence']['budgets']=[legacy];base['entries']=[protocol.entry('unchanged',category='Подписки',amount=0.10)]
        self.backend.data=deepcopy(base);a=deepcopy(base);b=deepcopy(base)
        one={'id':'current-subscriptions','group':'Подписки и сервисы','groupId':'subscriptions','groupVersion':2,'amount':12.34,'updated_at':protocol.LATER,'futureField':7}
        two={'id':'current-work','group':'Работа','groupId':'work','groupVersion':2,'amount':56.78,'updated_at':protocol.LATER}
        a['intelligence']['budgets'].append(one);b['intelligence']['budgets'].append(two)
        first,second=self.device(a,True),self.device(b,True)
        for page in (first,second):
            page.evaluate("weatherCache.data={temperature_2m:10,weather_code:0};weatherCache.at=Date.now()")
        self.concurrent_push(first,second)
        saved={row['id']:row for row in self.backend.data['intelligence']['budgets']}
        self.assertEqual(saved,{'legacy':legacy,one['id']:one,two['id']:two})
        self.assertEqual(self.backend.data['entries'],base['entries'])
        reader=self.device()
        reader.evaluate("weatherCache.data={temperature_2m:10,weather_code:0};weatherCache.at=Date.now()")
        self.assertTrue(reader.evaluate('syncFromCloud()'))
        received={row['id']:row for row in reader.evaluate('state.intelligence.budgets')}
        self.assertEqual(received,saved)
        self.assertEqual(self.backend.blocked,[])


if __name__=='__main__':unittest.main()
