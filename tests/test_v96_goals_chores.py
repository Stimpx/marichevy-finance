"""Goals, explicit earmarks and safe chore undo; fictional data, blocked network."""
import os
from pathlib import Path
import unittest

import test_local_data_safety as harness


class GoalsChores(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.LocalDataSafety.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        harness.LocalDataSafety.tearDownClass.__func__(cls)

    setUp = harness.LocalDataSafety.setUp
    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open

    def prepare(self, tab='goals'):
        self.open()
        self.page.evaluate("""tab=>{
          session=null;stopCloudSync();state=blankState();localStorage.clear();
          window.__notifications=[];telegramNotify=(...args)=>{__notifications.push(args);return Promise.resolve(false)};
          window.confirm=()=>true;delete window.__FINANCE_BRIDGE__;
          document.getElementById('appRoot').classList.remove('auth-locked');
          window.testStamp=new Date(Date.now()-120000).toISOString();window.testShift=(value,days)=>{const d=new Date(value+'T12:00:00Z');d.setUTCDate(d.getUTCDate()+days);return d.toISOString().slice(0,10)};
          window.testAccount=(id,opening=100,spending=true)=>({id,name:'Учебный счёт '+id,
            amount:opening,snapshotDate:today(),snapshotRevision:'fictional-'+id,
            created_at:testStamp,updated_at:testStamp,future:{preserve:['fictional',null]},
            ledger:{version:1,enabled:true,startDate:today(),openingBalance:opening,kind:'asset',includeInSpending:spending},
            snapshotVerification:{amount:opening,date:today(),revision:'fictional-'+id,verifiedAt:testStamp,accountUpdatedAt:testStamp}});
          window.testGoal=(id='goal')=>({id,name:'Учебная цель',target:100,saved:0,monthly:5,
            updated_at:testStamp,created_at:testStamp,future:{preserve:['fictional',null]}});
          window.testChore=(id='chore',recurrence='weekly')=>({id,title:'Учебное домашнее дело',
            assignee:'Учебный участник',dueDate:today(),recurrence,lastDone:'',created_at:testStamp,
            updated_at:testStamp,future:{preserve:['fictional',null]}});
          showApp();renderAll();go(tab);window.__writes=0;const original=saveAll;
          saveAll=(...args)=>{__writes++;return original(...args)};
        }""", tab)

    def test_list_first_collapsed_create_and_exact_money(self):
        self.prepare()
        self.assertFalse(self.page.locator('#v119GoalCreate').evaluate('(e)=>e.open'))
        self.assertTrue(self.page.evaluate("document.getElementById('goalsList').compareDocumentPosition(document.getElementById('v119GoalCreate')) & Node.DOCUMENT_POSITION_FOLLOWING"))
        self.page.get_by_role('button', name='Новая цель', exact=True).click()
        self.page.locator('#goalName').fill('Учебный отпуск')
        self.page.locator('#goalTarget').fill('1 250,50')
        self.page.locator('#goalSaved').fill('0,10')
        self.page.locator('#goalMonthly').fill('25,05')
        self.page.locator('#v119GoalDeadline').fill('2027-02-01')
        self.page.locator('#v119GoalPriority').select_option('high')
        self.page.locator('#v119GoalSubmit').click()
        goal = self.page.evaluate('state.goals[0]')
        self.assertEqual([goal[k] for k in ('target', 'saved', 'monthly', 'deadline', 'priority')], [1250.50, .10, 25.05, '2027-02-01', 'high'])
        self.assertEqual(self.page.evaluate('__writes'), 1)
        self.assertFalse(self.page.locator('#v119GoalCreate').evaluate('(e)=>e.open'))

    def test_edit_preserves_legacy_subcents_and_unknown_fields(self):
        self.prepare()
        result = self.page.evaluate("""async()=>{
          const g={...testGoal(),target:'100.001',saved:17.251,monthly:'5.001',deposits:[{amount:17.251,date:today(),future:{keep:true}}]};state.goals=[g];
          const original=JSON.parse(JSON.stringify(g));v119EditGoal(g.id);document.getElementById('goalName').value='Изменённая учебная цель';
          await addGoal();return {g,original,readonly:document.getElementById('goalSaved').readOnly,writes:__writes};
        }""")
        expected = result['original']; expected.update(name='Изменённая учебная цель', updated_at=result['g']['updated_at'])
        self.assertEqual(result['g'], expected)
        self.assertEqual(result['writes'], 1)

    def test_stale_edit_and_changed_tombstone_keep_draft_without_write(self):
        self.prepare()
        result = self.page.evaluate("""async()=>{
          const g=testGoal();state.goals=[g];v119EditGoal(g.id);document.getElementById('goalName').value='Несохранённый черновик';
          g.monthly=25;g.updated_at=v119Stamp(g);await addGoal();const changed=JSON.stringify(g);
          v119EditGoal(g.id);document.getElementById('goalName').value='Второй черновик';state.deletedGoals[g.id]=v119Stamp(g);await addGoal();
          return {same:changed===JSON.stringify(g),name:g.name,draft:document.getElementById('goalName').value,error:document.getElementById('v119GoalError').textContent,writes:__writes};
        }""")
        self.assertTrue(result['same']); self.assertEqual(result['draft'], 'Второй черновик')
        self.assertIn('изменилась', result['error']); self.assertEqual(result['writes'], 0)

    def test_reserve_uses_real_account_capacity_separate_from_manual_saved(self):
        self.prepare()
        result = self.page.evaluate("""()=>{
          state.intelligence.accounts=[testAccount('own',100),testAccount('protected',500,false)];
          state.goals=[{...testGoal('a'),saved:99,reserve:{enabled:true,accountId:'own',amount:30}},
            {...testGoal('b'),saved:88,reserve:{enabled:true,accountId:'protected',amount:40}}];
          const before=JSON.stringify(state),summary=v119GoalReserveData(),entries=JSON.stringify(state.entries);
          const capacity=v119ReserveValidation('new',{enabled:true,accountId:'own',amount:71},100),okay=v119ReserveValidation('new',{enabled:true,accountId:'own',amount:70},100);
          const raw=JSON.parse(JSON.stringify(state));raw.goals[0].reserve.amount=-1;let bad=false;try{validateBackup(raw)}catch{bad=true}
          return {summary,capacity,okay,unchanged:before===JSON.stringify(state),entries,bad};
        }""")
        self.assertEqual(result['summary']['total'], 30)
        self.assertEqual([x['included'] for x in result['summary']['items']], [True, False])
        self.assertTrue(result['summary']['complete']); self.assertTrue(result['capacity']); self.assertEqual(result['okay'], '')
        self.assertTrue(result['unchanged'] and result['bad']); self.assertEqual(result['entries'], '[]')

    def test_reserve_rechecks_seasonal_and_stale_account_and_target(self):
        self.prepare()
        result = self.page.evaluate("""async()=>{
          const a=testAccount('a',100),g={...testGoal(),accountId:'a',reserve:{enabled:true,accountId:'a',amount:30}};state.intelligence.accounts=[a];state.goals=[g];
          const old=v118ReserveTotalForAccount;v118ReserveTotalForAccount=()=>60;
          const over=v119ReserveValidation('new',{enabled:true,accountId:'a',amount:11},100);v118ReserveTotalForAccount=old;
          v119EditGoal(g.id);document.getElementById('goalTarget').value='20';await addGoal();const targetKept=g.target;
          a.snapshotVerification=null;const stale=v119ReserveValidation(g.id,g.reserve,100);
          return {over,stale,targetKept,writes:__writes};
        }""")
        self.assertTrue(result['over'] and result['stale']); self.assertEqual(result['targetKept'], 100); self.assertEqual(result['writes'], 0)

    def test_deposit_optional_reserve_and_exact_undo_preserve_history(self):
        self.prepare()
        result = self.page.evaluate("""async()=>{
          state.intelligence.accounts=[testAccount('a',100)];const g={...testGoal(),saved:.10,reserve:{enabled:true,accountId:'a',amount:1,lastEventId:'manual'}};state.goals=[g];renderGoals();
          document.getElementById('deposit_goal').value='0,20';await addGoalDeposit(g.id);const manual={saved:g.saved,reserve:g.reserve.amount};
          document.getElementById('deposit_goal').value='0,30';document.getElementById('reserve_deposit_goal').checked=true;await addGoalDeposit(g.id);const funded={saved:g.saved,reserve:g.reserve.amount};
          const original=JSON.stringify(g.deposits[1]);await v119UndoGoalDeposit(g.id,1,original);const after=JSON.stringify(g);await v119UndoGoalDeposit(g.id,1,original);
          return {manual,funded,g,duplicateNoChange:after===JSON.stringify(g),entries:state.entries,writes:__writes,valid:!!validateBackup(JSON.parse(JSON.stringify(state)))};
        }""")
        self.assertEqual(result['manual'], {'saved': .30, 'reserve': 1})
        self.assertEqual(result['funded'], {'saved': .60, 'reserve': 1.30})
        self.assertEqual((result['g']['saved'], result['g']['reserve']['amount']), (.30, 1))
        self.assertEqual(len(result['g']['deposits']), 2); self.assertTrue(result['g']['deposits'][1]['undone_at'])
        self.assertTrue(result['duplicateNoChange'] and result['valid']); self.assertEqual(result['entries'], []); self.assertEqual(result['writes'], 3)

    def test_undo_legacy_idless_and_conflicting_reserve_does_not_partially_mutate(self):
        self.prepare()
        result = self.page.evaluate("""async()=>{
          const g={...testGoal(),saved:17.251,deposits:[{amount:17.251,date:today(),future:{keep:true}}]};state.goals=[g];
          await v119UndoGoalDeposit(g.id,0,JSON.stringify(g.deposits[0]));const legacy={saved:g.saved,deposit:JSON.parse(JSON.stringify(g.deposits[0]))};
          g.saved=1;g.reserve={enabled:true,accountId:'a',amount:2,lastEventId:'later'};g.deposits.push({id:'changed',amount:1,date:today(),reserveChange:{accountId:'a',before:1,after:2,previousEventId:'manual'}});
          const before=JSON.stringify(g),writes=__writes;await v119UndoGoalDeposit(g.id,1,JSON.stringify(g.deposits[1]));return {legacy,unchanged:before===JSON.stringify(g),noWrite:writes===__writes};
        }""")
        self.assertEqual(result['legacy']['saved'], 0); self.assertTrue(result['legacy']['deposit']['id']); self.assertTrue(result['legacy']['deposit']['undone_at'])
        self.assertEqual(result['legacy']['deposit']['future'], {'keep': True}); self.assertTrue(result['unchanged'] and result['noWrite'])

    def test_archive_releases_only_after_confirmation_and_restores_matching_tombstone(self):
        self.prepare()
        result = self.page.evaluate("""async()=>{
          const g={...testGoal(),saved:100,reserve:{enabled:true,accountId:'a',amount:20}};state.goals=[g];window.confirm=()=>false;
          await v119ArchiveGoal(g.id);const cancelled=state.goals.length===1&&g.reserve.enabled;
          window.confirm=()=>true;await v119ArchiveGoal(g.id);const packet=v119ArchivePacket('goals',g.id),snapshot=JSON.stringify(packet.record),stamp=state.deletedGoals[g.id];
          const outside=state.goals.length===0&&!packet.record.reserve.enabled;await v119ArchiveGoal(g.id,true);const restored=state.goals[0];
          const roundtrip=normalize(validateBackup(JSON.parse(JSON.stringify(state))));
          return {cancelled,outside,restored,stamp,immutable:snapshot===JSON.stringify(v119ArchivePacket('goals',g.id).record),packetStatus:v119ArchivePacket('goals',g.id).status,roundtrip,writes:__writes};
        }""")
        self.assertTrue(result['cancelled'] and result['outside'] and result['immutable'])
        self.assertFalse(result['restored']['reserve']['enabled']); self.assertGreater(result['restored']['updated_at'], result['stamp'])
        self.assertEqual(result['restored']['future'], {'preserve': ['fictional', None]}); self.assertEqual(result['packetStatus'], 'restored'); self.assertEqual(result['writes'], 2)
        self.assertEqual(len(result['roundtrip']['goals']), 1)

    def test_archive_restore_rejects_changed_tombstone_and_confirm_race(self):
        self.prepare()
        result = self.page.evaluate("""async()=>{
          const g={...testGoal(),reserve:{enabled:true,accountId:'a',amount:20}};state.goals=[g];
          window.confirm=()=>{g.name='Параллельное изменение';return true};await v119ArchiveGoal(g.id);const race=state.goals.length===1&&__writes===0;
          window.confirm=()=>true;await v119ArchiveGoal(g.id);state.deletedGoals[g.id]=v119Stamp(state.deletedGoals[g.id]);const before=JSON.stringify(state),writes=__writes;await v119ArchiveGoal(g.id,true);
          return {race,unchanged:before===JSON.stringify(state),noWrite:writes===__writes};
        }""")
        self.assertTrue(all(result.values()), result)

    def test_chores_today_includes_overdue_and_edit_keeps_unknown_fields(self):
        self.prepare('chores')
        result = self.page.evaluate("""async()=>{
          const overdue={...testChore('overdue'),dueDate:testShift(today(),-1)},future={...testChore('future'),dueDate:testShift(today(),2)};state.chores=[overdue,testChore('now'),future];setChoreFilter('today');
          const visible=document.getElementById('choresList').querySelectorAll('article').length;
          v119EditChore(overdue.id);document.getElementById('choreTitle').value='Перенесённое учебное дело';document.getElementById('choreDue').value=testShift(today(),3);await addChore();
          return {visible,row:overdue,writes:__writes,collapsed:!document.getElementById('v119ChoreCreate').open};
        }""")
        self.assertEqual(result['visible'], 2); self.assertEqual(result['row']['assignee'], 'Учебный участник'); self.assertEqual(result['row']['future'], {'preserve': ['fictional', None]})
        self.assertEqual(result['writes'], 1); self.assertTrue(result['collapsed'])

    def test_recurring_completion_undo_and_later_reschedule_guard(self):
        self.prepare('chores')
        result = self.page.evaluate("""async()=>{
          const c=testChore();state.chores=[c];const before={dueDate:c.dueDate,lastDone:c.lastDone};await Promise.all([completeChore(c.id),completeChore(c.id)]);const advanced=c.dueDate>before.dueDate,event=c.completions[0];
          await v119UndoChore(c.id,event.id,JSON.stringify(event));const restored=c.dueDate===before.dueDate&&c.lastDone===before.lastDone&&!!event.undone_at;
          await completeChore(c.id);const later=c.completions.at(-1);c.dueDate=testShift(c.dueDate,2);const snap=JSON.stringify(c),writes=__writes;await v119UndoChore(c.id,later.id,JSON.stringify(later));
          return {advanced,restored,count:c.completions.length,unchanged:snap===JSON.stringify(c),noWrite:writes===__writes,future:c.future,valid:!!validateBackup(JSON.parse(JSON.stringify(state)))};
        }""")
        self.assertTrue(all(result[k] for k in ('advanced', 'restored', 'unchanged', 'noWrite', 'valid'))); self.assertEqual(result['count'], 2)
        self.assertEqual(result['future'], {'preserve': ['fictional', None]})

    def test_oneoff_completion_is_outside_reminder_rows_and_undo_keeps_archive_copy(self):
        self.prepare('chores')
        result = self.page.evaluate("""async()=>{
          const c=testChore('one','once');state.chores=[c];await completeChore(c.id);const packet=v119ArchivePacket('chores',c.id),snap=JSON.stringify(packet.record),event=packet.record.completions[0],stamp=state.deletedChores[c.id];
          const inactive=!state.chores.length&&!choresDue().length;setChoreFilter('completed');const displayed=document.querySelectorAll('#choresList article').length;
          await v119UndoChore(c.id,event.id,JSON.stringify(event));return {inactive,displayed,row:state.chores[0],stamp,immutable:snap===JSON.stringify(v119ArchivePacket('chores',c.id).record),status:v119ArchivePacket('chores',c.id).status,valid:!!validateBackup(JSON.parse(JSON.stringify(state)))};
        }""")
        self.assertTrue(result['inactive'] and result['immutable'] and result['valid']); self.assertEqual(result['displayed'], 1)
        self.assertEqual(result['status'], 'restored'); self.assertFalse(result['row'].get('archivedAt')); self.assertGreater(result['row']['updated_at'], result['stamp'])
        self.assertTrue(result['row']['completions'][0]['undone_at'])

    def test_viewer_epoch_and_stale_chore_editor_do_not_write(self):
        self.prepare('chores')
        result = self.page.evaluate("""async()=>{
          const g=testGoal(),c=testChore();state.goals=[g];state.chores=[c];window.__FINANCE_BRIDGE__={active:true,role:'viewer'};
          await completeChore(c.id);await v119ArchiveGoal(g.id);await deleteGoal(g.id);const denied=__writes===0;
          delete window.__FINANCE_BRIDGE__;v119EditChore(c.id);document.getElementById('choreTitle').value='Несохранённый черновик';c.assignee='Изменённый участник';await addChore();const stale=__writes===0&&c.title==='Учебное домашнее дело';
          v119EditGoal(g.id);document.getElementById('goalName').value='Другой сеанс';authEpoch++;await addGoal();const epoch=__writes===0&&g.name==='Учебная цель';
          return {denied,stale,epoch};
        }""")
        self.assertTrue(all(result.values()), result)

    def test_notifications_do_not_cross_session_during_pending_save(self):
        self.prepare()
        result = self.page.evaluate("""async()=>{
          state.goals=[testGoal()];renderGoals();document.getElementById('deposit_goal').value='1';
          saveAll=()=>new Promise(resolve=>window.finishSave=resolve);const saving=addGoalDeposit('goal');authEpoch++;finishSave(true);await saving;
          v119NewChore();document.getElementById('choreTitle').value='Новое учебное дело';const task=addChore();authEpoch++;finishSave(true);await task;
          return {notifications:__notifications.length,goals:state.goals[0].saved,chores:state.chores.length};
        }""")
        self.assertEqual(result, {'notifications': 0, 'goals': 1, 'chores': 1})

    def test_archive_cas_conflict_and_backup_reject_malformed_audit(self):
        self.prepare()
        result = self.page.evaluate("""async()=>{
          state.goals=[testGoal()];const base=JSON.parse(JSON.stringify(state));rememberCloudBase(base);await v119ArchiveGoal('goal');const local=JSON.parse(JSON.stringify(state)),remote=JSON.parse(JSON.stringify(base));remote.goals[0].name='Удалённое параллельное изменение';remote.goals[0].updated_at=v119Stamp(remote.goals[0]);let conflict=false;
          try{conflict=reconcileCloudSnapshot(remote,local,'fictional archive collision')===null&&reconcileCloudSnapshot.conflicts.includes('goals:goal')}catch{conflict=true}
          const bad=JSON.parse(JSON.stringify(local));bad.settings.preferences.humanArchive.goals.goal.record.reserve={enabled:true,accountId:'a',amount:'30'};let rejected=false;try{validateBackup(bad)}catch{rejected=true}
          const future=JSON.parse(JSON.stringify(local));future.settings.preferences.humanArchive.goals.opaque={format:'future-archive',opaque:{preserve:true}};
          return {conflict,rejected,preserved:!!validateBackup(future).settings.preferences.humanArchive.goals.opaque.opaque.preserve};
        }""")
        self.assertTrue(all(result.values()), result)

    def test_open_create_forms_reflow_with_large_text_and_cancel_without_writes(self):
        self.prepare()
        for width in (320, 390, 1280):
            self.page.set_viewport_size({'width': width, 'height': 900})
            for tab, action, root in (('goals', 'v119NewGoal', 'v119GoalCreate'), ('chores', 'v119NewChore', 'v119ChoreCreate')):
                with self.subTest(width=width, tab=tab):
                    self.page.evaluate("""({tab,action,root})=>{
                      document.querySelectorAll('[data-form-test-font]').forEach(el=>el.style.fontSize=el.dataset.formTestFont);
                      go(tab);window[action]();const form=document.getElementById(root),nodes=[form,...form.querySelectorAll('*')];
                      const sizes=nodes.map(el=>parseFloat(getComputedStyle(el).fontSize));nodes.forEach((el,i)=>{el.dataset.formTestFont=sizes[i]+'px';el.style.fontSize=sizes[i]*2+'px'});
                    }""", {'tab': tab, 'action': action, 'root': root})
                    failures = self.page.locator('#'+root).evaluate("""root=>[...root.querySelectorAll('label,input,select,button,.hint')].filter(el=>{const r=el.getBoundingClientRect();return r.width&&r.height&&(r.right>innerWidth+1||r.left< -1||el.tagName!=='INPUT'&&el.tagName!=='SELECT'&&el.scrollWidth>el.clientWidth+2)}).map(el=>({tag:el.tagName,text:el.textContent,client:el.clientWidth,scroll:el.scrollWidth}))""")
                    self.assertEqual(failures, [])
                    self.assertEqual(self.page.evaluate('__writes'), 0)
                    if width == 390:
                        Path('/tmp/v96-goals-chores').mkdir(exist_ok=True)
                        self.page.screenshot(path=f'/tmp/v96-goals-chores/{tab}-form-390-text200.png', full_page=True)
                    self.page.evaluate('v119ClearEditors()')

    def test_responsive_goals_and_chores_buttons_and_long_history_reflow(self):
        self.prepare()
        self.page.evaluate("""()=>{state.goals=[{...testGoal(),name:'Учебная цель с очень длинным названием для проверки переносов',target:999999999,saved:123456789,monthly:123456,
          deposits:[{id:'long',date:today(),who:'Очень длинное имя учебного участника',amount:123456789}]}];state.chores=[{...testChore(),title:'Длинное учебное домашнее дело с удобными действиями и переносом',assignee:'Очень длинное имя учебного участника'}];renderAll()}""")
        shot_dir = Path(os.environ.get('V96_GOALS_SHOTS', '/tmp/v96-goals-chores'))
        shot_dir.mkdir(parents=True, exist_ok=True)
        for width in (320, 390, 1280):
            self.page.set_viewport_size({'width': width, 'height': 900})
            for tab in ('goals', 'chores'):
                for factor in (1, 2):
                    with self.subTest(width=width, tab=tab, factor=factor):
                        self.page.evaluate("""({tab,factor})=>{document.querySelectorAll('[data-text-test-original]').forEach(el=>{el.style.fontSize=el.dataset.textTestOriginal});go(tab);const root=document.getElementById(tab),nodes=[root,...root.querySelectorAll('*')];const sizes=nodes.map(el=>parseFloat(getComputedStyle(el).fontSize));nodes.forEach((el,i)=>{el.dataset.textTestOriginal=sizes[i]+'px';el.style.fontSize=sizes[i]*factor+'px'});root.querySelectorAll('details:not(.v119-create)').forEach(el=>el.open=true)}""", {'tab': tab, 'factor': factor})
                        overflow = self.page.evaluate("""tab=>{const root=document.getElementById(tab);return [...root.querySelectorAll('button,input,h3,.v78-goal-history-row,.chore-assignee,.v119-reserve-note')].filter(el=>{const r=el.getBoundingClientRect();return r.width&&r.height&&(r.right>innerWidth+1||r.left< -1||el.scrollWidth>el.clientWidth+2)}).map(el=>({tag:el.tagName,cls:el.className,text:el.textContent.slice(0,70),client:el.clientWidth,scroll:el.scrollWidth}))}""", tab)
                        self.assertEqual(overflow, [])
                        if factor == 2:
                            self.page.screenshot(path=str(shot_dir / f'{tab}-{width}-text200.png'), full_page=True)


if __name__ == '__main__':
    unittest.main()
