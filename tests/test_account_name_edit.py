"""Renaming an account never edits its money, anchors, snapshots or operations.

Run: PYTHONPATH=tests python -m unittest test_account_name_edit
Browser requests and all account data are isolated synthetic fixtures.
"""
import unittest

import test_home_account_bank as bank_base


class AccountNameEdit(unittest.TestCase):
    setUpClass = classmethod(bank_base.HomeAccountBank.setUpClass.__func__)
    tearDownClass = classmethod(bank_base.HomeAccountBank.tearDownClass.__func__)
    setUp = bank_base.HomeAccountBank.setUp
    tearDown = bank_base.HomeAccountBank.tearDown
    evaluate = bank_base.HomeAccountBank.evaluate

    def seed(self, multiple=False):
        self.evaluate('''
          saveAll=async()=>true;state.entries=[];
          state.intelligence.accounts=[bankTestAccount('main','Общий счёт',1000)];
          state.settings.preferences.unassignedExpenseAccountId='main';
          if(''' + str(multiple).lower() + ''')state.intelligence.accounts.push(bankTestAccount('savings','Накопления',2000));
          renderAll();
        ''')

    def test_real_single_account_pencil_renames_without_reentering_or_resetting_balance(self):
        self.seed()
        result = self.evaluate('''
          v150OpenHomeAccount('main');bankTestFill('Общий счёт',800000);await v150SaveHomeAccount();
          state.entries.push(bankTestEntry('new-expense','expense',100,{date:today()}));renderAll();
          const before=JSON.parse(JSON.stringify(v117AccountRecord('main'))),
            entries=JSON.stringify(state.entries),prefs=JSON.stringify(state.settings.preferences),total=v150HomeBankData().total;
          window.renameBefore={before,entries,prefs,total};
          return {total,trust:v117SnapshotTrusted(before),buttonVisible:document.getElementById('v173HomeSingleRename').getClientRects().length>0};
        ''')
        self.assertEqual(result['total'], 799900)
        self.assertTrue(result['trust'])
        self.assertTrue(result['buttonVisible'])
        self.page.click('#v173HomeSingleRename')
        self.assertEqual(self.page.locator('#v173AccountName').input_value(), 'Общий счёт')
        self.assertEqual(self.page.locator('#v150HomeAccountModal').get_attribute('aria-hidden'), 'true')
        self.page.fill('#v173AccountName', '  <img src=x onerror=window.renameXss=1>  ')
        self.page.click('#v173AccountRenameSave')
        result = self.evaluate('''
          const after=v117AccountRecord('main'),before=renameBefore.before,
            clean=row=>{const next=JSON.parse(JSON.stringify(row));delete next.name;delete next.updated_at;
              delete next.snapshotVerification.accountUpdatedAt;return JSON.stringify(next)};
          return {name:after.name,total:v150HomeBankData().total,trust:v117SnapshotTrusted(after),
            moneyUnchanged:clean(after)===clean(before),entries:JSON.stringify(state.entries)===renameBefore.entries,
            prefs:JSON.stringify(state.settings.preferences)===renameBefore.prefs,
            stamp:after.updated_at!==before.updated_at,verifiedStamp:after.snapshotVerification.accountUpdatedAt===after.updated_at,
            snapshotRevision:after.snapshotRevision===before.snapshotRevision,
            label:document.getElementById('v169HomeSingleName').textContent,
            noHtml:!document.getElementById('v169HomeSingleName').querySelector('img')&&!window.renameXss,
            closed:document.getElementById('v173RenameAccountModal').getAttribute('aria-hidden'),
            focus:document.activeElement.id,
            picker:[...document.querySelectorAll('#eAccountId option')].find(option=>option.value==='main')?.textContent};
        ''')
        self.assertEqual(result['name'], '<img src=x onerror=window.renameXss=1>')
        self.assertEqual(result['label'], result['name'])
        self.assertEqual(result['picker'], result['name'])
        self.assertEqual(result['total'], 799900)
        for key in ['trust', 'moneyUnchanged', 'entries', 'prefs', 'stamp', 'verifiedStamp',
                    'snapshotRevision', 'noHtml']:
            self.assertTrue(result[key], key)
        self.assertEqual(result['closed'], 'true')
        self.assertEqual(result['focus'], 'v173HomeSingleRename')

    def test_validation_duplicate_names_stale_account_and_permissions_never_write(self):
        self.seed(multiple=True)
        result = self.evaluate('''
          let writes=0;saveAll=async()=>{writes++;return true};
          const original=JSON.stringify(state.intelligence.accounts);v173OpenAccountRename('main');
          const attempt=async value=>{document.getElementById('v173AccountName').value=value;
            const ok=await v173SaveAccountRename();return {ok,error:document.getElementById('v173AccountNameError').textContent}};
          const duplicate=await attempt('  НАКОПЛЕНИЯ  '),blank=await attempt('   '),long=await attempt('a'.repeat(66));
          document.getElementById('v173AccountName').value='Новый счёт';
          const current=v117AccountRecord('main');current.ledger.openingBalance=1500;v117TouchAccount(current);
          const changed=JSON.stringify(current),stale=await v173SaveAccountRename();
          v173CloseAccountRename();v99CanWriteDirections=()=>false;renderAll();
          return {duplicate,blank,long,writes,stale,sameConcurrent:JSON.stringify(v117AccountRecord('main'))===changed,
            denied:v173OpenAccountRename('main')===false,
            buttonsDisabled:[...document.querySelectorAll('#v150HomeAccounts .v173-account-rename')].every(button=>button.disabled)};
        ''')
        self.assertFalse(result['duplicate']['ok'])
        self.assertIn('уже есть', result['duplicate']['error'])
        self.assertFalse(result['blank']['ok'])
        self.assertFalse(result['long']['ok'])
        self.assertEqual(result['writes'], 0)
        self.assertFalse(result['stale'])
        self.assertTrue(result['sameConcurrent'])
        self.assertTrue(result['denied'])
        self.assertTrue(result['buttonsDisabled'])

    def test_failed_storage_rolls_back_own_write_and_preserves_concurrent_account_or_settings(self):
        self.seed()
        result = self.evaluate('''
          const original=JSON.stringify(v117AccountRecord('main'));v173OpenAccountRename('main');
          document.getElementById('v173AccountName').value='Переименованный';
          let release;saveAll=()=>new Promise(resolve=>release=resolve);v89StorageFailed=true;
          const pending=v173SaveAccountRename();state.settings.preferences.payday=25;release(false);
          const first=await pending,rollback={ok:first,account:JSON.stringify(v117AccountRecord('main'))===original,
            payday:state.settings.preferences.payday,error:document.getElementById('v173AccountNameError').textContent,
            enabled:!document.getElementById('v173AccountRenameSave').disabled};
          v173CloseAccountRename();v173OpenAccountRename('main');document.getElementById('v173AccountName').value='Ожидающее имя';
          const secondPending=v173SaveAccountRename(),concurrent=v117AccountRecord('main');
          concurrent.name='Имя с другого устройства';concurrent.ledger.openingBalance=777;v117TouchAccount(concurrent);
          const latest=JSON.stringify(concurrent);release(false);const second=await secondPending;
          return {rollback,concurrent:{ok:second,preserved:JSON.stringify(v117AccountRecord('main'))===latest,
            name:v117AccountRecord('main').name,balance:v150HomeBankData().total},
            unlocked:!v173AccountRenameBusy&&!v117AccountsBusy};
        ''')
        self.assertFalse(result['rollback']['ok'])
        self.assertTrue(result['rollback']['account'])
        self.assertEqual(result['rollback']['payday'], 25)
        self.assertIn('Не удалось сохранить название', result['rollback']['error'])
        self.assertTrue(result['rollback']['enabled'])
        self.assertFalse(result['concurrent']['ok'])
        self.assertTrue(result['concurrent']['preserved'])
        self.assertEqual(result['concurrent']['name'], 'Имя с другого устройства')
        self.assertEqual(result['concurrent']['balance'], 777)
        self.assertTrue(result['unlocked'])

    def test_local_queue_untrusted_snapshot_scope_change_and_closed_accounts_keep_their_contracts(self):
        self.seed()
        result = self.evaluate('''
          const account=v117AccountRecord('main');delete account.ledger;
          account.snapshotVerification.accountUpdatedAt='old-untrusted-stamp';
          const snapshot=JSON.stringify(account.snapshotVerification);saveAll=async()=>false;v89StorageFailed=false;
          v173OpenAccountRename('main');document.getElementById('v173AccountName').value='Ручной остаток';
          const local=await v173SaveAccountRename(),manual={ok:local,name:v117AccountRecord('main').name,
            trust:v117SnapshotTrusted(v117AccountRecord('main')),snapshot:JSON.stringify(v117AccountRecord('main').snapshotVerification)===snapshot,
            ledger:v117AccountRecord('main').ledger,amount:v117AccountRecord('main').amount};
          v173OpenAccountRename('main');document.getElementById('v173AccountName').value='Не переносить в другую семью';
          authEpoch++;const scopeRejected=await v173SaveAccountRename();v173CloseAccountRename();
          const closed=v117AccountRecord('main');closed.archived=true;
          const closedRejected=v173OpenAccountRename('main')===false;closed.archived=false;
          v173OpenAccountRename('main');document.getElementById('v173AccountName').value='Удалённый';
          state.intelligence.deleted.accounts.main=new Date(Date.now()+1000).toISOString();
          const deletedRejected=await v173SaveAccountRename();
          return {manual,scopeRejected,closedRejected,deletedRejected,
            originalName:state.intelligence.accounts[0].name};
        ''')
        self.assertTrue(result['manual']['ok'])
        self.assertEqual(result['manual']['name'], 'Ручной остаток')
        self.assertFalse(result['manual']['trust'])
        self.assertTrue(result['manual']['snapshot'])
        self.assertIsNone(result['manual']['ledger'])
        self.assertEqual(result['manual']['amount'], 1000)
        self.assertFalse(result['scopeRejected'])
        self.assertTrue(result['closedRejected'])
        self.assertFalse(result['deletedRejected'])
        self.assertEqual(result['originalName'], 'Ручной остаток')

    def test_multi_account_pencils_keyboard_cancel_navigation_and_responsive_geometry(self):
        self.seed(multiple=True)
        original = self.evaluate('return JSON.stringify(state.intelligence.accounts);')
        self.page.click('#v173AccountRename-savings')
        self.assertEqual(self.page.locator('#v173AccountName').input_value(), 'Накопления')
        self.assertEqual(self.page.evaluate('document.activeElement.id'), 'v173AccountName')
        self.page.keyboard.press('Shift+Tab')
        self.assertEqual(self.page.locator('#v173RenameAccountModal button:focus').inner_text(), 'Отмена')
        self.page.keyboard.press('Tab')
        self.assertEqual(self.page.evaluate('document.activeElement.id'), 'v173AccountName')
        self.page.keyboard.press('Escape')
        self.assertEqual(self.page.evaluate('document.activeElement.id'), 'v173AccountRename-savings')
        self.assertEqual(self.evaluate('return JSON.stringify(state.intelligence.accounts);'), original)
        self.page.click('#v173AccountRename-savings')
        self.evaluate("go('analytics');")
        self.assertEqual(self.page.locator('#v173RenameAccountModal').get_attribute('aria-hidden'), 'true')
        self.assertTrue(self.evaluate('return v173AccountRenameDraft===null;'))
        for width in [320, 375, 430, 700, 1024, 1440, 1920]:
            self.page.set_viewport_size({'width': width, 'height': 1000})
            result = self.evaluate('''
              go('home');const account=v117AccountRecord('main');account.name='ДлинноеНазвание'.repeat(4);renderAll();
              v173OpenAccountRename('main');
              const nodes=[document.querySelector('#v173RenameAccountModal .modal'),
                ...document.querySelectorAll('#v150HomeAccounts .v150-home-account,#v150HomeAccounts .v173-account-name')];
              const result={page:document.documentElement.scrollWidth<=innerWidth+1,
                overflow:nodes.some(node=>node.scrollWidth>node.clientWidth+1),
                controls:[...document.querySelectorAll('#v150HomeAccounts .v173-account-rename')].map(button=>({
                  width:button.getBoundingClientRect().width,height:button.getBoundingClientRect().height,
                  label:button.getAttribute('aria-label')}))};v173CloseAccountRename();return result;
            ''')
            with self.subTest(width=width):
                self.assertTrue(result['page'])
                self.assertFalse(result['overflow'])
                self.assertEqual(len(result['controls']), 2)
                for button in result['controls']:
                    self.assertGreaterEqual(button['width'], 44 if width <= 700 else 32)
                    self.assertGreaterEqual(button['height'], 44 if width <= 700 else 32)
                    self.assertIn('Переименовать', button['label'])


if __name__ == '__main__':
    unittest.main()
