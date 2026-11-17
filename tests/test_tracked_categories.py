"""Tracked Home categories change family preferences, never the expense history.

Run: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests python -m unittest test_tracked_categories
Every browser record is synthetic and external requests are blocked.
"""
from pathlib import Path
import os
import shutil
import unittest

from playwright.sync_api import sync_playwright


HTML = (Path(__file__).resolve().parents[1] / 'index.html').read_text()
BASE = 'http://127.0.0.1:9863/'


class TrackedCategories(unittest.TestCase):
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
        self.context = self.browser.new_context(
            viewport={'width': 1440, 'height': 1100},
            timezone_id='Europe/Moscow', service_workers='block')
        self.context.route('**/*', lambda route: route.fulfill(
            status=200, content_type='text/html', body=HTML)
            if route.request.url == BASE else route.abort())
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.on('dialog', lambda dialog: dialog.accept())
        self.page.goto(BASE, wait_until='domcontentloaded')
        self.page.wait_for_function("typeof v175TrackedSpending==='function'")
        self.page.evaluate('''() => {
          session=null;localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=null;
          localStorage.clear();state=blankState();saveAll=async()=>true;
          today=()=> '2026-11-17';month=()=> '2026-11';
          window.trackedEntry=(id,amount,category,beneficiary='Общее',fields={})=>({id,type:'expense',
            date:'2026-11-05',amount,category,beneficiary,who:'Общее',store:'Тестовый магазин',
            comment:'Ручная заметка',pay:'Карта',created_at:'2026-11-05T10:00:00.000Z',
            updated_at:'2026-11-05T10:00:00.000Z',...fields});
          window.unsafeTrackedLabel='Своя <img src=x onerror="window.unsafeTracker=1">';
          state.entries=[trackedEntry('sub-a',100.10,'Подписки','Сергей',{store:'Netflix'}),
            trackedEntry('sub-b',10.20,'Подписки и онлайн-сервисы','Виктория',{store:'Netlify'}),
            trackedEntry('gift-a',20.25,'Подарки','Алиса'),trackedEntry('gift-b',30.15,'Подарки'),
            trackedEntry('oct-sub',200.10,'Подписки','Сергей',{date:'2026-10-05'}),
            trackedEntry('oct-gift',100.25,'Подарки','Алиса',{date:'2026-10-05'}),
            trackedEntry('cafe-v',40.17,'Рестораны и кафе','Виктория'),
            trackedEntry('cafe-s',18.95,'Кафе и доставка','Сергей'),
            trackedEntry('cafe-shared',22.90,'  КАФЕ   И ДОСТАВКА  '),
            trackedEntry('custom',5.05,unsafeTrackedLabel),
            trackedEntry('not-expense',99999,'Подписки','Сергей',{type:'income'}),
            trackedEntry('transfer',88888,'Подписки','Сергей',{type:'transfer'}),
            trackedEntry('deleted',1000,'Подписки')];
          state.deletedEntries={deleted:'2026-11-06T10:00:00.000Z'};
          showApp();go('home');document.getElementById('homeMonth').value='2026-11';renderAll();
          window.trackedOriginalEntries=JSON.stringify(state.entries);
          window.trackedOriginalAccounts=JSON.stringify(state.intelligence.accounts);
          window.trackedCard=key=>[...document.querySelectorAll('#v175TrackedCards [data-v175-category]')]
            .find(card=>card.dataset.v175Category===key);
          window.readTrackedCards=()=>[...document.querySelectorAll('#v175TrackedCards [data-v175-category]')]
            .map(card=>({key:card.dataset.v175Category,text:card.textContent.replaceAll('\\u00a0',' '),
              amount:card.querySelector('.v175-tracked-amount').textContent.replaceAll('\\u00a0',' ')}));
          window.trackedFinancesUnchanged=()=>JSON.stringify(state.entries)===trackedOriginalEntries&&
            JSON.stringify(state.intelligence.accounts)===trackedOriginalAccounts;
          window.trackedDrill=()=>({scope:v96DrillContext.scope,key:v96DrillContext.key,
            total:document.getElementById('v96DrillTotal').textContent.replaceAll('\\u00a0',' '),
            ids:[...document.querySelectorAll('#v84DrillEntries [data-v141-operation-id]')]
              .map(row=>row.dataset.v141OperationId),
            participants:[...document.querySelectorAll('#v84DrillBody [data-v84-sub]')]
              .map(button=>button.dataset.v84Sub)});
        }''')

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def evaluate(self, code):
        return self.page.evaluate('async () => {' + code + '}')

    def test_default_cards_combine_aliases_and_retain_subscriptions_and_gifts_without_writing_preferences(self):
        data = self.evaluate('''
          const settings=JSON.stringify(state.settings);renderHome();renderHome();
          return {keys:v175TrackedCategoryKeys(),rows:v175TrackedSpending('2026-11'),
            cards:readTrackedCards(),settingsSame:JSON.stringify(state.settings)===settings,
            unchanged:trackedFinancesUnchanged(),heading:document.getElementById('v99HomeSlices').textContent};
        ''')
        self.assertEqual(data['keys'], ['Подписки', 'Подарки'])
        self.assertEqual([(row['key'], row['amount'], row['count']) for row in data['rows']],
                         [('Подписки', 110.30, 2), ('Подарки', 50.40, 2)])
        self.assertEqual([card['amount'] for card in data['cards']], ['110,30 ₽', '50,40 ₽'])
        self.assertIn('Отслеживаемые категории', data['heading'])
        self.assertTrue(data['settingsSame'])
        self.assertTrue(data['unchanged'])

    def test_explicit_empty_add_alias_or_historical_custom_and_remove_only_changes_tracking_list(self):
        data = self.evaluate('''
          state.settings.preferences.trackedExpenseCategories=[];renderHome();
          const empty={keys:v175TrackedCategoryKeys(),cards:readTrackedCards(),
            text:document.getElementById('v99HomeSlices').textContent};
          v175OpenTrackedEditor();const catalog=v175TrackedCatalog(),custom=catalog.find(row=>row.label===unsafeTrackedLabel);
          const added=await v175AddTrackedCategory('Рестораны и кафе');
          v175OpenTrackedEditor();const duplicate=await v175AddTrackedCategory('Кафе и доставка');
          v175OpenTrackedEditor();const customAdded=await v175AddTrackedCategory(custom.key);
          const withCustom={keys:v175TrackedCategoryKeys(),cards:readTrackedCards(),
            unsafe:!!document.querySelector('#v99HomeSlices img,#v99HomeSlices script'),executed:window.unsafeTracker||0};
          v175OpenTrackedEditor();const removed=await v175RemoveTrackedCategory('Рестораны и кафе');
          v175OpenTrackedEditor();await v175RemoveTrackedCategory(custom.key);renderHome();
          return {empty,added,duplicate,customAdded,custom,withCustom,removed,final:v175TrackedCategoryKeys(),
            cards:readTrackedCards(),unchanged:trackedFinancesUnchanged(),categoryStillAvailable:
              v175TrackedCatalog().some(row=>row.key==='Рестораны и кафе')};
        ''')
        self.assertEqual(data['empty']['keys'], [])
        self.assertEqual(data['empty']['cards'], [])
        self.assertIn('Добавить категорию', data['empty']['text'])
        self.assertTrue(data['added'])
        self.assertFalse(data['duplicate'])
        self.assertTrue(data['customAdded'])
        self.assertEqual(data['withCustom']['keys'], ['Рестораны и кафе', data['custom']['key']])
        self.assertEqual([card['amount'] for card in data['withCustom']['cards']], ['82,02 ₽', '5,05 ₽'])
        self.assertIn('<img src=x', data['withCustom']['cards'][1]['text'])
        self.assertFalse(data['withCustom']['unsafe'])
        self.assertEqual(data['withCustom']['executed'], 0)
        self.assertTrue(data['removed'])
        self.assertEqual(data['final'], [])
        self.assertEqual(data['cards'], [])
        self.assertTrue(data['categoryStillAvailable'])
        self.assertTrue(data['unchanged'])

    def test_saved_configuration_survives_normalization_profile_change_and_older_unrelated_settings_merge(self):
        data = self.evaluate('''
          const old=JSON.parse(JSON.stringify(state));
          saveAll=async()=>{localStorage.setItem(KEYS.state,JSON.stringify(state));
            state=normalize(JSON.parse(JSON.stringify(state)));return true};
          v175OpenTrackedEditor();await v175RemoveTrackedCategory('Подписки');
          v175OpenTrackedEditor();const acknowledged=await v175AddTrackedCategory('Рестораны и кафе');
          const nextAcknowledged=await v175AddTrackedCategory('Продукты');
          const persisted=normalize(JSON.parse(localStorage.getItem(KEYS.state)));
          validateBackup(persisted);state=persisted;currentProfile=()=>({id:'other-user',name:'Другой участник'});renderHome();
          const afterReload=v175TrackedCategoryKeys();
          old.settings.preferences.unrelatedPreference='Сохранить';old.settings.updated_at='2099-01-01T10:00:00.000Z';
          state=mergeStates(state,old);renderHome();
          const rejected=[{trackedExpenseCategories:'Подписки'},{trackedExpenseCategories:[42]},
            {trackedExpenseCategoriesUpdatedAt:'не дата'}].map(change=>{
            const invalid=JSON.parse(JSON.stringify(persisted));Object.assign(invalid.settings.preferences,change);
            try{validateBackup(invalid);return false}catch{return true}
          });
          return {afterReload,afterMerge:v175TrackedCategoryKeys(),acknowledged,nextAcknowledged,stored:
            persisted.settings.preferences.trackedExpenseCategories,
            stamp:persisted.settings.preferences.trackedExpenseCategoriesUpdatedAt,
            unrelated:state.settings.preferences.unrelatedPreference,
            liveEntries:v117LiveEntries(),originalLive:JSON.parse(trackedOriginalEntries).filter(e=>e.id!=='deleted'),
            accountsUnchanged:JSON.stringify(state.intelligence.accounts)===trackedOriginalAccounts,rejected};
        ''')
        expected = ['Подарки', 'Рестораны и кафе', 'Продукты']
        self.assertTrue(data['acknowledged'])
        self.assertTrue(data['nextAcknowledged'])
        self.assertEqual(data['afterReload'], expected)
        self.assertEqual(data['afterMerge'], expected)
        self.assertEqual(data['stored'], expected)
        self.assertTrue(data['stamp'])
        self.assertEqual(data['unrelated'], 'Сохранить')
        self.assertEqual(data['rejected'], [True, True, True])
        self.assertEqual(sorted(data['liveEntries'], key=lambda row: row['id']),
                         sorted(data['originalLive'], key=lambda row: row['id']))
        self.assertTrue(data['accountsUnchanged'])
        offsets = self.evaluate('''
          const earlier=JSON.parse(JSON.stringify(state)),later=JSON.parse(JSON.stringify(state));
          earlier.settings.preferences.trackedExpenseCategories=['Подарки'];
          earlier.settings.preferences.trackedExpenseCategoriesUpdatedAt='2026-11-17T00:00:00+03:00';
          later.settings.preferences.trackedExpenseCategories=['Продукты'];
          later.settings.preferences.trackedExpenseCategoriesUpdatedAt='2026-11-16T22:00:00.000Z';
          validateBackup(earlier);validateBackup(later);
          return [[earlier,later],[later,earlier]].map(pair=>{
            const merged=mergeStates(...pair);return merged.settings.preferences.trackedExpenseCategories;
          });
        ''')
        self.assertEqual(offsets, [['Продукты'], ['Продукты']])

    def test_selected_month_and_all_time_cards_open_same_category_and_refresh_after_edit_or_delete(self):
        self.evaluate('''
          v175OpenTrackedEditor();await v175AddTrackedCategory('Рестораны и кафе');v97SetHomeOverview(false);
          for(let parent=document.getElementById('v99HomeSlices').parentElement;parent;parent=parent.parentElement)
            if(parent.tagName==='DETAILS')parent.open=true;
        ''')
        self.page.locator('#v175TrackedCards [data-v175-open="Рестораны и кафе"]').click()
        monthly = self.evaluate('return trackedDrill();')
        self.assertEqual((monthly['scope'], monthly['key'], monthly['total']),
                         ('month', 'Рестораны и кафе', '82,02 ₽'))
        self.assertEqual(set(monthly['ids']), {'cafe-v', 'cafe-s', 'cafe-shared'})
        self.assertTrue({'Виктория', 'Сергей', 'Общее'}.issubset(set(monthly['participants'])))
        data = self.evaluate('''
          v84CloseDrill();const select=document.getElementById('homeMonth');select.value='all';
          select.dispatchEvent(new Event('change',{bubbles:true}));
          const all=v175TrackedSpending('all');trackedCard('Подписки').querySelector('[data-v175-open]').click();
          const opened=trackedDrill();v96EditFromDrill('sub-a');document.getElementById('xAmount').value='120.25';
          await saveEdit();const edited={drill:trackedDrill(),rows:v175TrackedSpending('all')};
          v96DeleteFromDrill('oct-sub');await new Promise(requestAnimationFrame);
          return {all,opened,edited,deleted:{drill:trackedDrill(),rows:v175TrackedSpending('all')},
            selected:document.getElementById('homeMonth').value,count:state.entries.length};
        ''')
        all_rows = {row['key']: row for row in data['all']}
        self.assertEqual(all_rows['Подписки']['amount'], 310.40)
        self.assertEqual(all_rows['Подарки']['amount'], 150.65)
        self.assertEqual((data['opened']['scope'], data['opened']['total']), ('all', '310,40 ₽'))
        self.assertEqual(set(data['opened']['ids']), {'sub-a', 'sub-b', 'oct-sub'})
        self.assertEqual((data['edited']['drill']['scope'], data['edited']['drill']['total']), ('all', '330,55 ₽'))
        self.assertEqual((data['deleted']['drill']['scope'], data['deleted']['drill']['total']), ('all', '130,45 ₽'))
        self.assertEqual(data['selected'], 'all')
        self.assertEqual(data['count'], 12)

    def test_read_only_stale_auth_or_concurrent_tracking_change_cannot_overwrite_preferences(self):
        data = self.evaluate('''
          const before=JSON.stringify(state.settings.preferences);window.__FINANCE_BRIDGE__={active:true,role:'viewer'};
          v175OpenTrackedEditor();const viewer=await v175AddTrackedCategory('Рестораны и кафе');
          const viewerUnchanged=JSON.stringify(state.settings.preferences)===before;window.__FINANCE_BRIDGE__=null;
          v175OpenTrackedEditor();authEpoch++;const stale=await v175AddTrackedCategory('Рестораны и кафе');
          const staleUnchanged=JSON.stringify(state.settings.preferences)===before;
          document.getElementById('v175TrackedEditor').open=false;v175ToggleTrackedEditor();
          v175OpenTrackedEditor();state.settings.preferences.trackedExpenseCategories=['Продукты'];
          state.settings.preferences.trackedExpenseCategoriesUpdatedAt='2099-01-01T10:00:00.000Z';
          const concurrent=await v175AddTrackedCategory('Рестораны и кафе');
          return {viewer,viewerUnchanged,stale,staleUnchanged,concurrent,keys:v175TrackedCategoryKeys(),
            unchanged:trackedFinancesUnchanged()};
        ''')
        self.assertFalse(data['viewer'])
        self.assertTrue(data['viewerUnchanged'])
        self.assertFalse(data['stale'])
        self.assertTrue(data['staleUnchanged'])
        self.assertFalse(data['concurrent'])
        self.assertEqual(data['keys'], ['Продукты'])
        self.assertTrue(data['unchanged'])

    def test_failed_save_restores_own_preference_without_losing_unrelated_updates_or_touching_new_family(self):
        data = self.evaluate('''
          v175OpenTrackedEditor();saveAll=async()=>{
            state.settings.preferences.unrelatedPreference='Изменено параллельно';
            state.settings.updated_at='2099-01-01T10:00:00.000Z';v89StorageFailed=true;return false};
          const failed=await v175AddTrackedCategory('Рестораны и кафе');
          const rollback={keys:v175TrackedCategoryKeys(),unrelated:state.settings.preferences.unrelatedPreference,
            hasExplicit:Object.hasOwn(state.settings.preferences,'trackedExpenseCategories')};
          v89StorageFailed=false;v175OpenTrackedEditor();let releaseAuth;
          saveAll=()=>new Promise(resolve=>{releaseAuth=resolve});
          const sameOwnerPending=v175AddTrackedCategory('Рестораны и кафе');authEpoch++;
          v89StorageFailed=true;releaseAuth(false);const expired=await sameOwnerPending;
          const afterExpired=v175TrackedCategoryKeys();
          document.getElementById('v175TrackedEditor').open=false;v175ToggleTrackedEditor();
          v89StorageFailed=false;v175OpenTrackedEditor();let release;
          saveAll=()=>new Promise(resolve=>{release=resolve});const pending=v175AddTrackedCategory('Рестораны и кафе');
          const oldFamily=CONFIG.household;CONFIG.household='different-synthetic-family';authEpoch++;
          state=blankState();state.settings.preferences.trackedExpenseCategories=['Продукты'];
          state.settings.preferences.trackedExpenseCategoriesUpdatedAt='2099-02-01T10:00:00.000Z';
          release(false);const stale=await pending;const newFamily=v175TrackedCategoryKeys();CONFIG.household=oldFamily;
          return {failed,rollback,expired,afterExpired,stale,newFamily};
        ''')
        self.assertFalse(data['failed'])
        self.assertEqual(data['rollback'], {'keys': ['Подписки', 'Подарки'],
                                         'unrelated': 'Изменено параллельно', 'hasExplicit': False})
        self.assertFalse(data['expired'])
        self.assertEqual(data['afterExpired'], ['Подписки', 'Подарки'])
        self.assertFalse(data['stale'])
        self.assertEqual(data['newFamily'], ['Продукты'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
