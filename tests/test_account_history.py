"""Read-only account movements preserve anchored money and archived provenance.

Run: python -m unittest discover -s tests -p test_account_history.py
Requires Playwright/Chromium. All network requests are blocked.
"""
import unittest

import test_home_account_bank as bank_base


class AccountHistory(unittest.TestCase):
    setUpClass = classmethod(bank_base.HomeAccountBank.setUpClass.__func__)
    tearDownClass = classmethod(bank_base.HomeAccountBank.tearDownClass.__func__)
    setUp = bank_base.HomeAccountBank.setUp
    tearDown = bank_base.HomeAccountBank.tearDown
    evaluate = bank_base.HomeAccountBank.evaluate

    def test_movements_match_ledger_and_history_cannot_write(self):
        result = self.evaluate('''
          state.intelligence.accounts=[bankTestAccount('main','Карта',1000),bankTestAccount('save','Накопления',2000)];
          state.settings.preferences.unassignedExpenseAccountId='main';
          state.entries=[
            bankTestEntry('income','income',50,{accountId:'main'}),
            bankTestEntry('expense','expense',20,{accountId:'main'}),
            bankTestEntry('move-out','transfer',100,{fromAccountId:'main',toAccountId:'save'}),
            bankTestEntry('cash-in','cash',30,{fromAccountId:'save',toAccountId:'main'}),
            bankTestEntry('adjust','transfer',25,{accountId:'main',balanceAdjustment:true,adjustmentDirection:1,reconciliationRevision:'test-revision',unassignedExpenseVersion:1,unassignedIncomeVersion:1}),
            bankTestEntry('shared-in','income',40),bankTestEntry('shared-out','expense',10)];
          const stateBefore=JSON.stringify(state),diskBefore=JSON.stringify(localStorage),bankBefore=v150HomeBankData().total;let writes=0;saveAll=async()=>{writes++;return true};
          const opened=v181OpenAccountHistory('main'),data=v181AccountHistoryData('main'),content=document.getElementById('v181AccountHistoryContent');
          return {opened,balance:data.balance,ledger:v117AccountBalance('main').balance,
            incoming:data.incoming,outgoing:data.outgoing,flows:data.rows.filter(row=>row.kind==='entry').map(row=>[row.id,row.effect]),
            unchanged:JSON.stringify(state)===stateBefore,diskUnchanged:JSON.stringify(localStorage)===diskBefore,bankUnchanged:bankBefore===v150HomeBankData().total,writes,
            editors:content.querySelectorAll('button,input,select,textarea,form,[data-record-action],[data-action]').length,
            closeButtons:document.querySelectorAll('#v181AccountHistoryModal button').length};
        ''')
        self.assertTrue(result['opened'])
        self.assertEqual(result['balance'], 1015)
        self.assertEqual(result['balance'], result['ledger'])
        self.assertEqual(result['incoming'], 145)
        self.assertEqual(result['outgoing'], 130)
        self.assertEqual(dict(result['flows']), {'income': 50, 'expense': -20,
            'move-out': -100, 'cash-in': 30, 'adjust': 25, 'shared-in': 40, 'shared-out': -10})
        self.assertTrue(result['unchanged'])
        self.assertTrue(result['diskUnchanged'])
        self.assertTrue(result['bankUnchanged'])
        self.assertEqual(result['writes'], 0)
        self.assertEqual(result['editors'], 0)
        self.assertEqual(result['closeButtons'], 1)

    def test_saved_balance_points_do_not_replay_old_purchases_or_become_income(self):
        result = self.evaluate('''
          const account=bankTestAccount('main','Карта',1000);
          const previous={version:1,amount:700,date:'2026-11-03',recordedAt:'2026-11-03T12:00:00.000Z',existingSameDayEntryIds:[]};
          account.ledger.currentBalanceAnchors=[previous];
          account.ledger.currentBalanceAnchor={version:1,amount:500,date:'2026-11-05',recordedAt:'2026-11-05T12:00:00.000Z',existingSameDayEntryIds:['old-same-day']};
          state.intelligence.accounts=[account];state.entries=[
            bankTestEntry('old','expense',100,{accountId:'main',date:'2026-11-04'}),
            bankTestEntry('old-same-day','expense',80,{accountId:'main',date:'2026-11-05'}),
            bankTestEntry('new','income',50,{accountId:'main',date:'2026-11-06'})];
          const data=v181AccountHistoryData('main');return {balance:data.balance,ledger:v117AccountBalance('main').balance,
            incoming:data.incoming,outgoing:data.outgoing,base:data.base,anchors:data.rows.filter(row=>row.kind==='anchor').map(row=>row.amount),
            old:data.rows.find(row=>row.id==='old'),oldSameDay:data.rows.find(row=>row.id==='old-same-day')};
        ''')
        self.assertEqual(result['balance'], 550)
        self.assertEqual(result['balance'], result['ledger'])
        self.assertEqual(result['base'], 500)
        self.assertEqual(result['incoming'], 50)
        self.assertEqual(result['outgoing'], 0)
        self.assertEqual(result['anchors'], [500, 700])
        self.assertEqual(result['old']['effect'], -100)
        self.assertFalse(result['old']['included'])
        self.assertIn('Уже включено', result['old']['note'])
        self.assertFalse(result['oldSameDay']['included'])

    def test_debt_account_history_matches_negative_ledger_without_credit_limit_income(self):
        result = self.evaluate('''
          const debt=bankTestAccount('credit','Кредитная карта',-1000);
          debt.ledger={...debt.ledger,kind:'debt',creditLimit:50000,includeInSpending:false};
          state.intelligence.accounts=[debt,bankTestAccount('main','Карта',2000)];
          state.entries=[bankTestEntry('credit-purchase','expense',200,{accountId:'credit'}),
            bankTestEntry('credit-payment','transfer',300,{fromAccountId:'main',toAccountId:'credit'})];
          go('accounts');const button=document.querySelector('[data-v117-account-action="history"][data-v117-account-id="credit"]');button.click();
          const data=v181AccountHistoryData('credit');return {opened:document.getElementById('v181AccountHistoryModal').classList.contains('open'),
            balance:data.balance,ledger:v117AccountBalance('credit').balance,incoming:data.incoming,outgoing:data.outgoing,
            initial:data.rows.find(row=>row.kind==='opening').amount,limitShown:data.rows.some(row=>row.amount===50000)};
        ''')
        self.assertTrue(result['opened'])
        self.assertEqual(result['balance'], -900)
        self.assertEqual(result['balance'], result['ledger'])
        self.assertEqual(result['incoming'], 300)
        self.assertEqual(result['outgoing'], 200)
        self.assertEqual(result['initial'], -1000)
        self.assertFalse(result['limitShown'])

    def test_first_current_balance_is_a_point_not_a_fictional_correction(self):
        result = self.evaluate('''
          const account=bankTestAccount('main','Карта',1000);account.ledger.startDate=today();
          account.ledger.currentBalanceAnchor={version:1,amount:1000,date:today(),recordedAt:'2026-11-09T12:00:00.000Z',existingSameDayEntryIds:['already-in-balance']};
          state.intelligence.accounts=[account];state.entries=[bankTestEntry('already-in-balance','income',500,{date:today()})];
          const data=v181AccountHistoryData('main');return {balance:data.balance,incoming:data.incoming,outgoing:data.outgoing,point:data.rows.find(row=>row.kind==='anchor')};
        ''')
        self.assertEqual(result['balance'], 1000)
        self.assertEqual(result['incoming'], 0)
        self.assertEqual(result['outgoing'], 0)
        self.assertNotIn('change', result['point'])

    def test_deleted_and_other_account_rows_are_not_shown_and_future_is_not_spent(self):
        result = self.evaluate('''
          state.intelligence.accounts=[bankTestAccount('main','Карта',1000),bankTestAccount('other','Другой',1000)];
          state.settings.preferences.unassignedExpenseAccountId='';state.entries=[
            bankTestEntry('deleted','expense',100,{accountId:'main'}),
            bankTestEntry('other','income',500,{accountId:'other'}),
            bankTestEntry('future','expense',200,{accountId:'main',date:'2026-12-01'})];
          state.deletedEntries={deleted:'2026-11-08T12:00:00.000Z'};
          const data=v181AccountHistoryData('main');return {balance:data.balance,incoming:data.incoming,outgoing:data.outgoing,rows:data.rows.filter(row=>row.kind==='entry')};
        ''')
        self.assertEqual(result['balance'], 1000)
        self.assertEqual(result['incoming'], 0)
        self.assertEqual(result['outgoing'], 0)
        self.assertEqual(len(result['rows']), 1)
        self.assertEqual(result['rows'][0]['id'], 'future')
        self.assertTrue(result['rows'][0]['future'])
        self.assertFalse(result['rows'][0]['included'])

    def test_archived_implicit_history_keeps_frozen_ids_after_default_changes(self):
        result = self.evaluate('''
          const archived=bankTestAccount('closed','Прежний счёт',1000,{archived:true,
            homeRemovedAt:'2026-11-06T12:00:00.000Z',homeRemovedImplicitEntryIds:['old-in','old-out']});
          state.intelligence.accounts=[archived,bankTestAccount('new','Новый счёт',2000)];state.settings.preferences.unassignedExpenseAccountId='new';
          state.entries=[bankTestEntry('old-in','income',100),bankTestEntry('old-out','expense',30),
            bankTestEntry('later-backdated','expense',900,{created_at:'2026-11-09T12:00:00.000Z'})];
          const before=JSON.stringify(state),data=v181AccountHistoryData('closed'),opened=v181OpenAccountHistory('closed');
          return {balance:data.balance,incoming:data.incoming,outgoing:data.outgoing,rows:data.rows.filter(row=>row.kind==='entry').map(row=>row.id),opened,unchanged:before===JSON.stringify(state),title:document.getElementById('v181AccountHistoryTitle').textContent};
        ''')
        self.assertTrue(result['opened'])
        self.assertEqual(result['balance'], 1070)
        self.assertEqual(result['incoming'], 100)
        self.assertEqual(result['outgoing'], 30)
        self.assertCountEqual(result['rows'], ['old-in', 'old-out'])
        self.assertTrue(result['unchanged'])
        self.assertIn('архив', result['title'])

    def test_viewer_can_read_but_locked_or_changed_scope_closes_popup(self):
        result = self.evaluate('''
          state.intelligence.accounts=[bankTestAccount('main','Карта',1000)];
          window.__FINANCE_BRIDGE__={active:true,role:'viewer'};
          const viewerOpened=v181OpenAccountHistory('main');authEpoch++;v181RenderAccountHistory();
          const epochClosed=!document.getElementById('v181AccountHistoryModal').classList.contains('open');
          v181OpenAccountHistory('main');session={user:{id:'different-user'}};v181RenderAccountHistory();
          const userClosed=!document.getElementById('v181AccountHistoryModal').classList.contains('open');
          session=null;showGate();const locked=v181OpenAccountHistory('main');
          return {viewerOpened,epochClosed,userClosed,locked,content:document.getElementById('v181AccountHistoryContent').textContent};
        ''')
        self.assertTrue(result['viewerOpened'])
        self.assertTrue(result['epochClosed'])
        self.assertTrue(result['userClosed'])
        self.assertFalse(result['locked'])
        self.assertEqual(result['content'], '')

    def test_archived_points_do_not_invent_deltas_after_shared_default_changes(self):
        result = self.evaluate('''
          const archived=bankTestAccount('closed','Прежний счёт',1000,{archived:true,
            homeRemovedAt:'2026-11-06T12:00:00.000Z',homeRemovedImplicitEntryIds:['old-in','old-out']});
          archived.ledger.currentBalanceAnchors=[{version:1,amount:1200,date:'2026-11-02',recordedAt:'2026-11-02T12:00:00.000Z',existingSameDayEntryIds:[]}];
          archived.ledger.currentBalanceAnchor={version:1,amount:1000,date:'2026-11-04',recordedAt:'2026-11-04T12:00:00.000Z',existingSameDayEntryIds:[]};
          state.intelligence.accounts=[archived,bankTestAccount('new','Новый счёт',2000)];
          state.entries=[bankTestEntry('old-in','income',100),bankTestEntry('old-out','expense',30),
            bankTestEntry('before-point','expense',50,{date:'2026-11-03'})];
          const read=()=>{v181OpenAccountHistory('closed');const data=v181AccountHistoryData('closed');return {balance:data.balance,
            points:data.rows.filter(row=>row.kind==='anchor').map(row=>({amount:row.amount,inventedChange:Object.hasOwn(row,'change')})),
            inventedHint:document.getElementById('v181AccountHistoryContent').textContent.includes('Уточнение к расчётному остатку')};};
          state.settings.preferences.unassignedExpenseAccountId='closed';const before=read();
          state.settings.preferences.unassignedExpenseAccountId='new';const after=read();
          return {before,after};
        ''')
        self.assertEqual(result['before'], result['after'])
        self.assertEqual(result['after']['balance'], 1070)
        self.assertEqual(result['after']['points'], [
            {'amount': 1000, 'inventedChange': False},
            {'amount': 1200, 'inventedChange': False}])
        self.assertFalse(result['after']['inventedHint'])

    def test_scope_change_and_account_removal_hide_content_on_refresh(self):
        result = self.evaluate('''
          state.intelligence.accounts=[bankTestAccount('main','Карта',1000)];v181OpenAccountHistory('main');
          state.intelligence.accounts=[];v181RenderAccountHistory();
          return {open:document.getElementById('v181AccountHistoryModal').classList.contains('open'),context:v181AccountHistoryContext,content:document.getElementById('v181AccountHistoryContent').textContent};
        ''')
        self.assertFalse(result['open'])
        self.assertIsNone(result['context'])
        self.assertEqual(result['content'], '')

    def test_escaped_account_and_entry_text_never_becomes_controls(self):
        result = self.evaluate('''
          state.intelligence.accounts=[bankTestAccount('main','<img src=x onerror=alert(1)>',1000)];
          state.entries=[bankTestEntry('row','expense',5,{accountId:'main',store:'<button onclick=saveAll()>Edit</button>',comment:'<script>saveAll()</script>'})];
          v181OpenAccountHistory('main');const modal=document.getElementById('v181AccountHistoryModal');
          return {controls:modal.querySelectorAll('button').length,unsafe:modal.querySelectorAll('img,script').length,text:modal.textContent};
        ''')
        self.assertEqual(result['controls'], 1)
        self.assertEqual(result['unsafe'], 0)
        self.assertIn('<button onclick=saveAll()>Edit</button>', result['text'])

    def test_escape_navigation_backdrop_and_focus_use_dialog_manager(self):
        self.evaluate('''state.intelligence.accounts=[bankTestAccount('main','Карта',1000)];renderHome();
          const opener=document.createElement('button');opener.id='history-test-opener';opener.textContent='История';opener.onclick=()=>v181OpenAccountHistory('main');document.getElementById('home').append(opener);''')
        self.page.locator('#history-test-opener').click()
        self.assertEqual(self.page.locator('#v181AccountHistoryModal').get_attribute('aria-hidden'), 'false')
        self.assertEqual(self.page.evaluate('document.activeElement.id'), 'v181AccountHistoryClose')
        self.page.keyboard.press('Tab')
        self.assertEqual(self.page.evaluate('document.activeElement.id'), 'v181AccountHistoryClose')
        self.page.keyboard.press('Escape')
        self.assertEqual(self.page.locator('#v181AccountHistoryModal').get_attribute('aria-hidden'), 'true')
        self.assertEqual(self.page.evaluate('document.activeElement.id'), 'history-test-opener')
        self.evaluate("v181OpenAccountHistory('main');go('history')")
        self.assertEqual(self.page.locator('#v181AccountHistoryModal').get_attribute('aria-hidden'), 'true')
        self.assertEqual(self.evaluate('return v113DialogStack.length;'), 0)

    def test_account_screen_history_stays_enabled_for_viewer_and_archive(self):
        result = self.evaluate('''
          state.intelligence.accounts=[bankTestAccount('main','Карта',1000),bankTestAccount('old','Архивный',500,{archived:true})];window.__FINANCE_BRIDGE__={active:true,role:'viewer'};
          go('accounts');v117RenderAccounts();const buttons=[...document.querySelectorAll('#accounts [data-v117-account-action="history"]')];
          return {count:buttons.length,enabled:buttons.every(button=>!button.disabled),writesDisabled:[...document.querySelectorAll('#accounts [data-v117-account-action]:not([data-v117-account-action="history"])')].every(button=>button.disabled)};
        ''')
        self.assertEqual(result['count'], 2)
        self.assertTrue(result['enabled'])
        self.assertTrue(result['writesDisabled'])

    def test_mobile_modal_contains_long_names_and_large_amounts(self):
        self.evaluate('''state.intelligence.accounts=[bankTestAccount('main','Очень длинное название семейного счёта с накоплениями на поездку',999999999999.99)];state.entries=[bankTestEntry('long','expense',999999999.99,{accountId:'main',comment:'Длинный комментарий '.repeat(15)})];v181OpenAccountHistory('main');''')
        for width, height in [(320, 700), (390, 844), (760, 420), (1440, 1000)]:
            with self.subTest(width=width):
                self.page.set_viewport_size({'width': width, 'height': height})
                result = self.evaluate('''const modal=document.querySelector('#v181AccountHistoryModal .modal'),content=document.getElementById('v181AccountHistoryContent'),box=modal.getBoundingClientRect();return {overflow:content.scrollWidth>content.clientWidth+1,left:box.left,right:box.right,window:innerWidth,bottom:box.bottom,height:innerHeight};''')
                self.assertFalse(result['overflow'])
                self.assertGreaterEqual(result['left'], 0)
                self.assertLessEqual(result['right'], result['window'] + 1)
                self.assertLessEqual(result['bottom'], result['height'] + 1)


if __name__ == '__main__':
    unittest.main()
