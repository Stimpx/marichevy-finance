"""Fictional planning, earmark and stale-draft regressions; all external requests blocked."""
import unittest
import test_local_data_safety as harness


class HumanPlanning(unittest.TestCase):
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
        return self.page.evaluate('''async () => {
          session=null;stopCloudSync();localStorage.clear();state=blankState();showApp();
          today=()=> '2026-11-01';month=()=> '2026-11';loanScheduleData=()=>[];
          window.confirm=()=>true;
          const stamp='2026-11-01T00:00:00.000Z',later='2026-11-01T00:00:01.000Z';
          const account=(id,amount,include=true,kind='asset')=>({id,name:'Fictional '+id,
            amount,snapshotDate:today(),snapshotRevision:'rev-'+id,created_at:stamp,updated_at:stamp,
            ledger:{version:1,enabled:true,startDate:today(),openingBalance:amount,kind,includeInSpending:include},
            snapshotVerification:{amount,date:today(),revision:'rev-'+id,verifiedAt:stamp,accountUpdatedAt:stamp}});
          const entry=(id,amount,fields={})=>({id,date:today(),type:'expense',amount,
            category:'Продукты',who:'Общее',beneficiary:'Общее',accountId:'cash',
            created_at:later,updated_at:later,...fields});
          const monthPlan=(period=month(),fields={})=>({id:'v118-month:'+period,kind:V118_MONTH_KIND,
            groupVersion:3,amount:0,month:period,expectedIncome:100000,groups:{},
            updated_at:stamp,created_at:stamp,periodPlan:{confirmed:true,
            fromDate:today(),untilDate:'2026-11-10',everydayAmount:20000},...fields});
          const reserve=(id='season',fields={})=>({id,kind:V118_RESERVE_KIND,groupVersion:3,
            name:'Fictional annual purchase',amount:10000,target:10000,saved:10000,
            accountId:'cash',dueDate:'2027-01-10',updated_at:stamp,created_at:stamp,...fields});
          const reset=()=>{state=blankState();state.intelligence.accounts=[account('cash',80000)];
            state.intelligence.recurring=[{id:'bill',name:'Fictional payment',amount:30000,
              day:2,category:'ЖКХ',who:'Общее',updated_at:stamp}];
            state.intelligence.budgets=[monthPlan()];state.goals=[{id:'goal',name:'Fictional goal',
              target:10000,saved:0,monthly:0,reserve:{enabled:true,accountId:'cash',amount:10000}}];
            v118ClearPlanningDrafts();document.getElementById('v118PlanMonth').value=month();};
          const snapshot=()=>({state:JSON.stringify(state),primary:localStorage.getItem(KEYS.state),
            pending:localStorage.getItem(KEYS.pending)});
          const concise=()=>{const d=v118AvailableData();return {amount:d.amount,estimate:d.estimate,
            cash:d.cash,obligations:d.obligations,everyday:d.futurePlan,reserves:d.reserves,
            complete:d.complete,warnings:d.warnings,boundary:d.boundary,components:d.components}};
          reset();
        '''+code+'\n}')

    def test_available_and_real_payment_and_food_invariants_keep_kopecks(self):
        r=self.evaluate('''
          const baseline=concise();
          state.entries.push(entry('bill-part',5000,{recurringId:'bill',recurringPeriod:month()}));
          const paid=concise();state.entries.push(entry('food',2000));const food=concise();
          state.intelligence.accounts.push(account('other',0));
          state.entries.push(entry('own-transfer',123.45,{type:'transfer',accountId:undefined,
            fromAccountId:'cash',toAccountId:'other'}));const transfer=concise();
          state.entries.push(entry('food-cents',0.31));const cents=concise();
          return {baseline,paid,food,transfer,cents};
        ''')
        for key in r:
            self.assertTrue(r[key]['complete'], (key,r[key]))
            self.assertEqual(r[key]['amount'],20000)
        self.assertEqual(r['baseline']['cash'],80000)
        self.assertEqual(r['baseline']['obligations'],30000)
        self.assertEqual(r['paid']['cash'],75000)
        self.assertEqual(r['paid']['obligations'],25000)
        self.assertEqual(r['food']['everyday'],18000)
        self.assertEqual(r['cents']['everyday'],17999.69)

    def test_partial_recurring_linked_installment_is_counted_once(self):
        r=self.evaluate('''
          const bill=state.intelligence.recurring[0];bill.installmentId='loan';bill.installmentPartId='part';
          state.installments=[{id:'loan',kind:'personal',title:'Fictional loan',accountingMode:'payments',
            parts:[{id:'part',date:'2026-11-02',amount:30000}],links:{part:'part-payment'}}];
          state.entries=[entry('part-payment',5000,{installmentId:'loan',installmentPartId:'part',
            recurringId:'bill',recurringPeriod:month()})];
          return {d:concise(),events:v86Forecast('2026-11-10').events.map(e=>e.kind)};
        ''')
        self.assertEqual(r['d']['amount'],20000)
        self.assertEqual(r['d']['obligations'],25000)
        self.assertEqual(r['events'],['installment'])

    def test_explicit_goal_and_seasonal_earmarks_do_not_double_protected_cash(self):
        r=self.evaluate('''
          state.goals[0].reserve.enabled=false;state.goals[0].saved=9999;
          const inferred=concise();state.intelligence.budgets.push(reserve());const seasonal=concise();
          state.intelligence.accounts[0]=account('cash',70000);
          state.intelligence.accounts.push(account('safe',10000,false));
          state.intelligence.budgets.find(r=>r.id==='season').accountId='safe';const protectedCash=concise();
          state.intelligence.budgets.find(r=>r.id==='season').dueDate='2026-11-05';const dueProtected=concise();
          return {inferred,seasonal,protectedCash,dueProtected};
        ''')
        self.assertEqual(r['inferred']['reserves'],0)
        self.assertEqual(r['inferred']['amount'],30000)
        for key in ['seasonal','protectedCash','dueProtected']:
            self.assertTrue(r[key]['complete'],r[key])
            self.assertEqual(r[key]['amount'],20000)
        self.assertEqual(r['dueProtected']['obligations'],30000)

    def test_known_future_payment_uses_earmark_once_and_explicit_payment_does_not_create_entry(self):
        r=self.evaluate('''
          state.goals=[];state.intelligence.budgets.push(reserve('season',{dueDate:'2026-11-05',target:15000,amount:15000,saved:10000}));
          const before=concise();state.entries.push(entry('actual-purchase',15000));
          const row=state.intelligence.budgets.find(r=>r.id==='season');v118RenderReserves();
          document.getElementById('v118Pay_season').value='actual-purchase';const count=state.entries.length;
          await v118LinkReservePayment('season');const paid=concise(),linkedCount=state.entries.length;
          state.entries[0].amount=5000;const partial=concise();state.entries=[];const removed=concise();
          return {before,paid,partial,removed,count,linkedCount,entryId:row.paidEntryId,
            event:v118ReserveEvents(month())[0]};
        ''')
        self.assertEqual(r['before']['amount'],15000)
        self.assertEqual(r['before']['obligations'],35000)
        self.assertEqual(r['before']['reserves'],10000)
        self.assertEqual(r['count'],r['linkedCount'])
        self.assertEqual(r['paid']['amount'],15000)
        self.assertEqual(r['paid']['reserves'],0)
        self.assertEqual(r['partial']['amount'],15000)
        self.assertFalse(r['removed']['complete'])
        self.assertEqual(r['event']['allocated'],0)
        self.assertFalse(r['event']['paid'])

    def test_duplicate_cross_device_seasonal_payment_and_invalid_schedule_are_not_authoritative(self):
        r=self.evaluate('''
          state.goals=[];state.entries=[entry('same',5000)];
          state.intelligence.budgets.push(reserve('a',{amount:5000,target:5000,saved:5000,
            dueDate:today(),paidEntryId:'same'}),reserve('b',{amount:5000,target:5000,
            saved:5000,dueDate:today(),paidEntryId:'same'}));const duplicate=concise();
          reset();state.intelligence.recurring[0].amount=-5000;const negative=concise();
          reset();state.intelligence.recurring[0].amount=1.001;const fractional=concise();
          reset();state.installments=[{id:'bad',title:'Fictional bad date',parts:[{id:'p',date:'2026-11-31',amount:100}],links:{}}];
          const invalidDate=concise();return {duplicate,negative,fractional,invalidDate};
        ''')
        for key in r:
            self.assertFalse(r[key]['complete'], (key,r[key]))
            self.assertIsNone(r[key]['amount'])
            self.assertTrue(r[key]['warnings'])
        self.assertIn('несколькими', ' '.join(r['duplicate']['warnings']))

    def test_credit_purchases_do_not_release_cash_budget_and_no_false_debt_reserve_warning(self):
        r=self.evaluate('''
          state.intelligence.accounts.push(account('credit',0,false,'debt'));const before=concise();
          state.entries.push(entry('debt-food',2000,{accountId:'credit'}));const credit=concise();
          return {before,credit};
        ''')
        self.assertTrue(r['before']['complete'],r['before'])
        self.assertFalse(r['credit']['complete'])
        self.assertIsNone(r['credit']['amount'])
        self.assertEqual(r['credit']['estimate'],20000)
        self.assertEqual(r['credit']['everyday'],20000)
        self.assertNotIn('Резервы на счёте',' '.join(r['credit']['warnings']))
        self.assertIn('заёмными',' '.join(r['credit']['warnings']))

    def test_missing_period_cash_or_malformed_inputs_show_incomplete_and_crossmonth_explicit_period_works(self):
        r=self.evaluate('''
          delete v118PlanFor().periodPlan;const noPeriod=concise();
          reset();state.intelligence.accounts=[];const noAccounts=concise();
          reset();v118PlanFor().periodPlan.untilDate='2026-12-03';
          state.intelligence.recurring[0].day=2;const crossmonth=concise();
          reset();v118PlanFor().periodPlan.untilDate='2026-11-31';const invalid=concise();
          return {noPeriod,noAccounts,crossmonth,invalid};
        ''')
        for key in ['noPeriod','noAccounts','invalid']:
            self.assertFalse(r[key]['complete'])
            self.assertIsNone(r[key]['amount'])
        self.assertTrue(r['crossmonth']['complete'],r['crossmonth'])
        self.assertEqual(r['crossmonth']['boundary'],'2026-12-03')
        self.assertEqual(r['crossmonth']['obligations'],60000)
        self.assertEqual(r['crossmonth']['everyday'],20000)

    def test_month_save_preserves_unknown_fields_and_history_in_one_budget_record(self):
        r=self.evaluate('''
          state.entries=[entry('old-history',0.31,{date:'2026-10-01',who:'Fictional legacy',unknown:{a:1}})];
          state.intelligence.budgets[0].unknownPlanField={keep:true};
          state.intelligence.budgets.push({id:'old-limit',group:'Fictional legacy limit',amount:321,unknown:{b:2}});
          const history=JSON.stringify(state.entries),limit=JSON.stringify(state.intelligence.budgets[1]);
          v118RenderPlanning();document.getElementById('v118Income').value='123456,78';
          document.getElementById('v118MonthForm').dataset.dirty='true';await v118SaveMonth();
          return {history,sameHistory:history===JSON.stringify(state.entries),limit,
            sameLimit:limit===JSON.stringify(state.intelligence.budgets.find(r=>r.id==='old-limit')),
            plans:state.intelligence.budgets.filter(r=>r.kind===V118_MONTH_KIND),
            pending:JSON.parse(localStorage.getItem(KEYS.pending)).intelligence.budgets};
        ''')
        self.assertTrue(r['sameHistory'])
        self.assertTrue(r['sameLimit'])
        self.assertEqual(len(r['plans']),1)
        self.assertEqual(r['plans'][0]['expectedIncome'],123456.78)
        self.assertEqual(r['plans'][0]['unknownPlanField'],{'keep':True})
        self.assertEqual(r['plans'][0],next(x for x in r['pending'] if x['id']==r['plans'][0]['id']))

    def test_copy_preview_and_apply_are_readonly_until_explicit_save_and_preserve_source(self):
        r=self.evaluate('''
          state.intelligence.budgets.push(monthPlan('2026-10',{expectedIncome:123456.78,
            unknownHistorical:{keep:true},periodPlan:{old:true}}));
          v118RenderPlanning();const before=snapshot(),source=JSON.stringify(v118PlanFor('2026-10'));
          v118PreviewPrevious();const preview=snapshot();v118ApplyCopyPreview();const apply=snapshot();
          const income=document.getElementById('v118Income').value;
          await v118SaveMonth();return {before,preview,apply,income,source,
            sourceAfter:JSON.stringify(v118PlanFor('2026-10')),target:v118PlanFor()};
        ''')
        self.assertEqual(r['before'],r['preview'])
        self.assertEqual(r['before'],r['apply'])
        self.assertEqual(r['income'],'123456.78')
        self.assertEqual(r['source'],r['sourceAfter'])
        self.assertEqual(r['target']['expectedIncome'],123456.78)
        self.assertTrue(r['target']['periodPlan']['confirmed'])
        self.assertNotIn('old',r['target']['periodPlan'])

    def test_dirty_month_cas_rejects_remote_update_without_writing_or_losing_fields(self):
        r=self.evaluate('''
          v118RenderPlanning();document.getElementById('v118Income').value='54321,09';
          document.getElementById('v118MonthForm').dataset.dirty='true';
          v118PlanFor().expectedIncome=77777;v118PlanFor().updated_at=later;v118RenderPlanning();
          const before=snapshot();await v118SaveMonth();return {before,after:snapshot(),
            field:document.getElementById('v118Income').value,error:document.getElementById('v118PlanError').textContent};
        ''')
        self.assertEqual(r['before'],r['after'])
        self.assertEqual(r['field'],'54321,09')
        self.assertIn('другом устройстве',r['error'])

    def test_reserve_cas_rejects_remote_update_and_copy_rechecks_both_source_and_target(self):
        r=self.evaluate('''
          state.intelligence.budgets.push(reserve());v118OpenReserve('season');
          document.getElementById('v118ReserveName').value='My unsaved reserve';
          state.intelligence.budgets.find(r=>r.id==='season').saved=9000;
          const before=snapshot();await v118SaveReserve();const after=snapshot();
          const reserveError=document.getElementById('v118ReserveError').textContent;
          state.intelligence.budgets.push(monthPlan('2026-10'));v118RenderPlanning();
          v118PreviewPrevious();document.getElementById('v118Income').value='33333';
          v118PlanFor('2026-10').expectedIncome=55555;v118ApplyCopyPreview();
          const sourceError=document.getElementById('v118CopyPreview').textContent;
          v118PreviewPrevious();v118PlanFor().expectedIncome=66666;v118ApplyCopyPreview();
          return {before,after,reserveError,sourceError,targetError:document.getElementById('v118CopyPreview').textContent,
            field:document.getElementById('v118Income').value};
        ''')
        self.assertEqual(r['before'],r['after'])
        self.assertIn('другом устройстве',r['reserveError'])
        self.assertIn('изменился',r['sourceError'])
        self.assertIn('изменился',r['targetError'])
        self.assertEqual(r['field'],'33333')

    def test_auth_epoch_during_await_does_not_clear_new_draft_or_toast_in_new_household(self):
        r=self.evaluate('''
          v118RenderPlanning();document.getElementById('v118Income').value='12345';
          document.getElementById('v118MonthForm').dataset.dirty='true';
          const notices=[],originalToast=toast;toast=(message)=>notices.push(message);
          let release;saveAll=()=>new Promise(resolve=>release=resolve);
          const pending=v118SaveMonth();authEpoch++;v118ClearPlanningDrafts();
          state=blankState();state.intelligence.budgets=[monthPlan(undefined,{expectedIncome:99999})];
          v118RenderPlanning();document.getElementById('v118Income').value='88888';
          document.getElementById('v118MonthForm').dataset.dirty='true';
          release(true);await pending;toast=originalToast;
          return {field:document.getElementById('v118Income').value,
            dirty:document.getElementById('v118MonthForm').dataset.dirty,notices,
            income:v118PlanFor().expectedIncome,busy:v118Saving};
        ''')
        self.assertEqual(r['field'],'88888')
        self.assertEqual(r['dirty'],'true')
        self.assertEqual(r['income'],99999)
        self.assertFalse(r['busy'])
        self.assertEqual(r['notices'],[])

    def test_same_scope_new_input_during_save_keeps_new_draft_and_rebases_loaded_version(self):
        r=self.evaluate('''
          v118RenderPlanning();document.getElementById('v118Income').value='12345';
          document.getElementById('v118MonthForm').dataset.dirty='true';
          let release;saveAll=()=>new Promise(resolve=>release=resolve);
          const pending=v118SaveMonth();document.getElementById('v118Income').value='54321';
          release(true);await pending;const first={income:v118PlanFor().expectedIncome,
            field:document.getElementById('v118Income').value,dirty:document.getElementById('v118MonthForm').dataset.dirty};
          saveAll=()=>Promise.resolve(true);await v118SaveMonth();return {first,second:v118PlanFor().expectedIncome};
        ''')
        self.assertEqual(r['first'],{'income':12345,'field':'54321','dirty':'true'})
        self.assertEqual(r['second'],54321)

    def test_viewer_recovery_and_gate_block_writes_and_rendering_is_read_only(self):
        r=self.evaluate('''
          const before=snapshot();v118RenderPlanning();v118AvailableData();v118MonthlyData(month());
          const render=snapshot();v118OpenReserve();document.getElementById('v118ReserveName').value='Fictional';
          document.getElementById('v118ReserveTarget').value='5000';
          window.__FINANCE_BRIDGE__={active:true,role:'viewer'};await v118SaveMonth();await v118SaveReserve();
          const viewer=snapshot();delete window.__FINANCE_BRIDGE__;localRecoveryBlocked=true;
          await v118SaveMonth();await v118SaveReserve();const recovery=snapshot();localRecoveryBlocked=false;
          v118ClearPlanningDrafts();return {before,render,viewer,recovery,
            dirty:document.getElementById('v118MonthForm').dataset.dirty,
            hidden:document.getElementById('v118ReserveForm').hidden,copy:v118CopyDraft,baseline:v118MonthSnapshot};
        ''')
        for key in ['render','viewer','recovery']:
            self.assertEqual(r['before'],r[key])
        self.assertEqual(r['dirty'],'false')
        self.assertTrue(r['hidden'])
        self.assertIsNone(r['copy'])
        self.assertIsNone(r['baseline'])

    def test_confirmation_scope_switch_cannot_move_old_reserve_into_new_household(self):
        r=self.evaluate('''
          state.intelligence.budgets.push(reserve('season',{paidEntryId:'paid'}));
          let newSnapshot;window.confirm=()=>{authEpoch++;v118ClearPlanningDrafts();
            state=blankState();newSnapshot=snapshot();return true};
          await v118UnlinkReservePayment('season');const unlink=snapshot();
          reset();state.intelligence.budgets.push(reserve());
          window.confirm=()=>{authEpoch++;v118ClearPlanningDrafts();
            state=blankState();newSnapshot=snapshot();return true};
          await v118RemoveReserve('season');return {newSnapshot,unlink,remove:snapshot()};
        ''')
        self.assertEqual(r['newSnapshot'],r['unlink'])
        self.assertEqual(r['newSnapshot'],r['remove'])

    def test_calendar_badges_show_scheduled_day_for_distinct_dates_in_same_month(self):
        r=self.evaluate('''
          state.intelligence.recurring=[
            {id:'early',name:'Fictional early bill',amount:100,day:2},
            {id:'late',name:'Fictional late bill',amount:200,day:30}];
          const before=JSON.stringify(state);v118MountPlanning();
          document.getElementById('v86CalendarMonth').innerHTML='<option value="2026-11">November 2026</option>';
          document.getElementById('v86CalendarMonth').value='2026-11';v86SetFilter('all');
          return {before,after:JSON.stringify(state),
            badges:[...document.querySelectorAll('#v86CalendarList .v86-calendar-date strong')].map(n=>n.textContent),
            dates:v86CalendarEvents('2026-11').map(e=>e.date)};
        ''')
        self.assertEqual(r['badges'],['2','30'])
        self.assertEqual(r['dates'],['2026-11-02','2026-11-30'])
        self.assertEqual(r['before'],r['after'])

    def test_future_dated_linked_payment_cannot_release_current_cash(self):
        r=self.evaluate('''
          state.entries=[entry('future-paid',30000,{date:'2026-11-02',recurringId:'bill',recurringPeriod:month()})];
          const d=concise();state.intelligence.budgets.push(reserve('season',{target:30000,amount:30000}));
          return {d,candidates:v118PaymentCandidates(state.intelligence.budgets.at(-1)).map(e=>e.id)};
        ''')
        self.assertEqual(r['d']['cash'],80000)
        self.assertFalse(r['d']['complete'])
        self.assertIsNone(r['d']['amount'])
        self.assertIn('будущей даты',' '.join(r['d']['warnings']))
        self.assertEqual(r['candidates'],[])

    def test_new_budget_metadata_survives_normalize_and_atomic_record_merge(self):
        r=self.evaluate('''
          const group=EXPENSE_GROUPS[0],id=v98GroupId(group);
          state.intelligence.budgets[0].groups={[id]:{amount:100.31,flexible:true,unknown:{keep:1}}};
          state.intelligence.budgets[0].unknown={preserved:true};
          state.intelligence.budgets.push(reserve('season',{saved:1234.56,unknown:{keep:2}}));
          const original=JSON.parse(JSON.stringify(state)),restored=normalize(JSON.parse(JSON.stringify(state)));
          const remote=JSON.parse(JSON.stringify(state));remote.intelligence.budgets[0].groups[id].amount=222.22;
          remote.intelligence.budgets[0].expectedIncome=33333.33;remote.intelligence.budgets[0].updated_at=later;
          const merged=mergeStates(original,remote),plan=merged.intelligence.budgets.find(r=>r.kind===V118_MONTH_KIND);
          return {original:original.intelligence.budgets,restored:restored.intelligence.budgets,
            plan,group:id,reserve:merged.intelligence.budgets.find(r=>r.kind===V118_RESERVE_KIND)};
        ''')
        self.assertEqual(r['original'],r['restored'])
        self.assertEqual(r['plan']['groups'][r['group']]['amount'],222.22)
        self.assertEqual(r['plan']['expectedIncome'],33333.33)
        self.assertEqual(r['plan']['unknown'],{'preserved':True})
        self.assertEqual(r['reserve']['saved'],1234.56)
        self.assertEqual(r['reserve']['unknown'],{'keep':2})


if __name__=='__main__':
    unittest.main()
