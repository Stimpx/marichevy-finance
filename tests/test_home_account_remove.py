"""Removing a duplicate Home account hides it without deleting financial history.

Run: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests python -m unittest test_home_account_remove
All records are synthetic and every external request is blocked.
"""
import os
import shutil
import unittest

from playwright.sync_api import sync_playwright

import test_home_account_bank as fixture


class HomeAccountRemove(unittest.TestCase):
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
        fixture.HomeAccountBank.setUp(self)
        self.remove_dialogs = []
        self.page.on('dialog', lambda dialog: self.remove_dialogs.append(dialog.message.replace('\u00a0', ' ')))
        self.page.wait_for_function("typeof v180RemoveHomeAccount==='function'")
        self.page.evaluate('''() => {
          window.removeReset=()=>{
            state=blankState();v89StorageFailed=false;saveAll=async()=>true;
            const first=bankTestAccount('first','Повторный счёт',1000.10),
              second=bankTestAccount('second','Основной счёт',2000.20);
            first.ledger.currentBalanceAnchor={version:1,amount:1000.10,date:'2026-11-06',
              recordedAt:'2026-11-06T12:00:00.000Z',existingSameDayEntryIds:[],snapshotRevision:'anchor-first'};
            state.intelligence.accounts=[first,second];
            state.entries=[bankTestEntry('purchase','expense',25.05,{accountId:'first',date:'2026-11-07'}),
              bankTestEntry('salary','income',50.15,{accountId:'second',date:'2026-11-07'})];
            go('home');renderAll();
          };
          removeReset();window.removeOriginalEntries=JSON.stringify(state.entries);
          window.removeOriginalLedger=JSON.stringify(v117AccountRecord('first').ledger);
          window.removeRead=()=>({total:v150HomeBankData().total,text:readBankText(),
            active:v150HomeBankData().items.map(item=>item.id),
            archived:v117AccountRecords(true).filter(account=>account.archived).map(account=>account.id),
            count:v117AccountRecords(true).length,unchanged:JSON.stringify(state.entries)===removeOriginalEntries});
        }''')

    def tearDown(self):
        fixture.HomeAccountBank.tearDown(self)

    def evaluate(self, code):
        return self.page.evaluate('async () => {' + code + '}')

    def test_real_home_buttons_remove_two_accounts_to_zero_and_restore_nonzero_accounts_with_history(self):
        self.assertEqual(self.evaluate('return removeRead().total;'), 3025.40)
        self.page.locator('#v180AccountRemove-first').click()
        self.page.wait_for_function("!v180AccountRemoveBusy&&v117AccountRecord('first').archived===true")
        first = self.evaluate('return removeRead();')
        self.assertEqual((first['total'], first['active'], first['archived']), (2050.35, ['second'], ['first']))
        self.assertEqual(first['count'], 2)
        self.assertTrue(first['unchanged'])
        self.assertIn('Повторный счёт', self.remove_dialogs[0])
        self.assertIn('975,05', self.remove_dialogs[0])
        self.assertTrue(self.page.locator('#v180HomeSingleRemove').is_visible())
        self.page.locator('#v180HomeSingleRemove').click()
        self.page.wait_for_function("!v180AccountRemoveBusy&&v117AccountRecord('second').archived===true")
        empty = self.evaluate('return removeRead();')
        self.assertIsNone(empty['total'])
        self.assertEqual(empty['active'], [])
        self.assertEqual(set(empty['archived']), {'first', 'second'})
        self.assertEqual(empty['count'], 2)
        self.assertTrue(empty['unchanged'])
        restored = self.evaluate('''
          await v117ArchiveAccount('first',true);await v117ArchiveAccount('second',true);renderHome();
          return {...removeRead(),ledgerSame:JSON.stringify(v117AccountRecord('first').ledger)===removeOriginalLedger,
            tombstones:Object.keys(state.intelligence.deleted?.accounts||{})};
        ''')
        self.assertEqual(restored['total'], 3025.40)
        self.assertEqual(set(restored['active']), {'first', 'second'})
        self.assertEqual(restored['archived'], [])
        self.assertTrue(restored['ledgerSame'])
        self.assertTrue(restored['unchanged'])
        self.assertEqual(restored['tombstones'], [])

    def test_cancel_viewer_and_changes_during_confirmation_cannot_remove_or_save_an_account(self):
        result = self.evaluate('''
          let saves=0,confirms=0;saveAll=async()=>{saves++;return true};
          const before=JSON.stringify(state);window.confirm=()=>{confirms++;return false};
          const cancelled=await v180RemoveHomeAccount('first'),cancelSame=JSON.stringify(state)===before;
          window.__FINANCE_BRIDGE__={active:true,role:'viewer'};
          window.confirm=()=>{confirms++;return true};renderHome();
          const disabled=document.getElementById('v180AccountRemove-first').disabled,
            viewer=await v180RemoveHomeAccount('first'),viewerConfirms=confirms;
          window.__FINANCE_BRIDGE__=null;
          window.confirm=()=>{const account=v117AccountRecord('first');account.name='Изменён параллельно';
            account.updated_at='2099-01-01T12:00:00.000Z';return true};
          const stale=await v180RemoveHomeAccount('first'),staleArchived=!!v117AccountRecord('first').archived;
          window.confirm=()=>{state.entries.push(bankTestEntry('arrived-while-confirming','expense',3,
            {accountId:'first',date:'2026-11-07'}));return true};
          const changedBalance=await v180RemoveHomeAccount('first');
          window.confirm=()=>{state.settings.preferences.unassignedExpenseAccountId='second';
            state.settings.preferences.unassignedExpenseUpdatedAt='2099-02-01T12:00:00.000Z';return true};
          const changedDefault=await v180RemoveHomeAccount('first');
          const household=CONFIG.household;window.confirm=()=>{authEpoch++;CONFIG.household='other-family';
            state=blankState();state.intelligence.accounts=[bankTestAccount('first','Новая семья',9000)];return true};
          const changedScope=await v180RemoveHomeAccount('first');
          const newFamily={name:v117AccountRecord('first').name,archived:!!v117AccountRecord('first').archived};
          CONFIG.household=household;return {cancelled,cancelSame,viewer,disabled,viewerConfirms,
            stale,staleArchived,changedBalance,changedDefault,changedScope,newFamily,saves};
        ''')
        self.assertFalse(result['cancelled'])
        self.assertTrue(result['cancelSame'])
        self.assertFalse(result['viewer'])
        self.assertTrue(result['disabled'])
        self.assertEqual(result['viewerConfirms'], 1)
        self.assertFalse(result['stale'])
        self.assertFalse(result['staleArchived'])
        self.assertFalse(result['changedBalance'])
        self.assertFalse(result['changedDefault'])
        self.assertFalse(result['changedScope'])
        self.assertEqual(result['newFamily'], {'name': 'Новая семья', 'archived': False})
        self.assertEqual(result['saves'], 0)

    def test_failed_storage_rolls_back_only_owned_account_and_shared_preference_changes(self):
        result = self.evaluate('''
          const original=JSON.stringify(v117AccountRecord('first'));
          window.confirm=()=>true;saveAll=async()=>{const other=v117AccountRecord('second');
            other.name='Название с другого устройства';other.updated_at='2099-01-01T12:00:00.000Z';
            state.settings.preferences.unrelatedPreference='Сохранить параллельную настройку';
            state.settings.updated_at='2099-01-01T12:00:00.000Z';v89StorageFailed=true;return false};
          const failed=await v180RemoveHomeAccount('first');
          const rollback={same:JSON.stringify(v117AccountRecord('first'))===original,
            other:v117AccountRecord('second').name,default:state.settings.preferences.unassignedExpenseAccountId??null,
            configured:Object.hasOwn(state.settings.preferences,'unassignedExpenseAccountId'),
            unrelated:state.settings.preferences.unrelatedPreference,unchanged:removeRead().unchanged};
          saveAll=async()=>{const own=v117AccountRecord('first');own.name='Параллельная правка этого счёта';
            own.updated_at='2099-02-01T12:00:00.000Z';state.settings.preferences.unassignedExpenseAccountId='second';
            state.settings.preferences.unassignedExpenseUpdatedAt='2099-02-01T12:00:00.000Z';return false};
          const concurrent=await v180RemoveHomeAccount('first');
          return {failed,rollback,concurrent,latest:{name:v117AccountRecord('first').name,
            archived:v117AccountRecord('first').archived,default:state.settings.preferences.unassignedExpenseAccountId}};
        ''')
        self.assertFalse(result['failed'])
        self.assertEqual(result['rollback'], {'same': True, 'other': 'Название с другого устройства',
                         'default': None, 'configured': False,
                         'unrelated': 'Сохранить параллельную настройку', 'unchanged': True})
        self.assertFalse(result['concurrent'])
        self.assertEqual(result['latest'], {'name': 'Параллельная правка этого счёта', 'archived': True,
                                         'default': 'second'})

    def test_queued_local_save_and_successful_cloud_ack_preserve_soft_removal_after_reload(self):
        result = self.evaluate('''
          window.confirm=()=>true;v89StorageFailed=false;
          saveAll=async()=>{localStorage.setItem(KEYS.state,JSON.stringify(state));return false};
          const queued=await v180RemoveHomeAccount('first'),persisted=normalize(JSON.parse(localStorage.getItem(KEYS.state)));
          const local={archived:persisted.intelligence.accounts.find(a=>a.id==='first').archived,
            entryIds:persisted.entries.map(e=>e.id)};
          saveAll=async()=>{state=normalize(JSON.parse(JSON.stringify(state)));return true};
          const acknowledged=await v180RemoveHomeAccount('second');renderHome();
          return {queued,local,acknowledged,...removeRead()};
        ''')
        self.assertTrue(result['queued'])
        self.assertEqual(result['local'], {'archived': True, 'entryIds': ['purchase', 'salary']})
        self.assertTrue(result['acknowledged'])
        self.assertEqual(set(result['archived']), {'first', 'second'})
        self.assertEqual(result['count'], 2)
        self.assertIsNone(result['total'])
        self.assertTrue(result['unchanged'])

    def test_ambiguous_or_selected_default_never_redirects_unassigned_flows_when_an_account_is_removed(self):
        result = self.evaluate('''
          state.entries=[bankTestEntry('unassigned-expense','expense',100,{date:'2026-11-07'}),
            bankTestEntry('unassigned-income','income',20,{date:'2026-11-07'})];
          const entries=JSON.stringify(state.entries);window.confirm=()=>true;
          const before=v150HomeBankData().total;await v180RemoveHomeAccount('first');
          const ambiguous={before,after:v150HomeBankData().total,
            preference:state.settings.preferences.unassignedExpenseAccountId,shared:v157SharedExpenseAccount().id};
          removeReset();state.entries=JSON.parse(entries);state.settings.preferences.unassignedExpenseAccountId='first';
          const selectedBefore=v150HomeBankData().total;await v180RemoveHomeAccount('first');
          const removed={total:v150HomeBankData().total,preference:state.settings.preferences.unassignedExpenseAccountId,
            shared:v157SharedExpenseAccount().id};
          await v117ArchiveAccount('first',true);const restored={total:v150HomeBankData().total,
            preference:state.settings.preferences.unassignedExpenseAccountId,shared:v157SharedExpenseAccount().id};
          await v180RemoveHomeAccount('first');state.settings.preferences.unassignedExpenseAccountId='second';
          await v117ArchiveAccount('first',true);
          return {ambiguous,selectedBefore,removed,restored,chosenOther:state.settings.preferences.unassignedExpenseAccountId,
            unchanged:JSON.stringify(state.entries)===entries};
        ''')
        self.assertEqual(result['ambiguous'], {'before': 3000.30, 'after': 2000.20, 'preference': '', 'shared': ''})
        self.assertEqual(result['selectedBefore'], 2920.30)
        self.assertEqual(result['removed'], {'total': 2000.20, 'preference': 'first', 'shared': ''})
        self.assertEqual(result['restored'], {'total': 2920.30, 'preference': 'first', 'shared': 'first'})
        self.assertEqual(result['chosenOther'], 'second')
        self.assertTrue(result['unchanged'])

    def test_failed_save_completion_after_family_switch_does_not_modify_new_accounts_or_preferences(self):
        result = self.evaluate('''
          window.confirm=()=>true;let finish;v89StorageFailed=true;
          saveAll=()=>new Promise(resolve=>{finish=resolve});
          const pending=v180RemoveHomeAccount('first'),during=v117AccountRecord('first').archived;
          const household=CONFIG.household;CONFIG.household='another-family';authEpoch++;
          state=blankState();state.intelligence.accounts=[bankTestAccount('first','Новый счёт',9000)];
          state.settings.preferences.unassignedExpenseAccountId='first';
          state.settings.preferences.unassignedExpenseUpdatedAt='2099-01-01T12:00:00.000Z';
          const original=JSON.stringify(state);finish(false);const ok=await pending;
          const untouched=JSON.stringify(state)===original;CONFIG.household=household;
          return {during,ok,untouched,name:v117AccountRecord('first').name,
            archived:!!v117AccountRecord('first').archived,preference:state.settings.preferences.unassignedExpenseAccountId};
        ''')
        self.assertTrue(result['during'])
        self.assertFalse(result['ok'])
        self.assertTrue(result['untouched'])
        self.assertEqual((result['name'], result['archived'], result['preference']), ('Новый счёт', False, 'first'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
