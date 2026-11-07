"""Custom recipient removal: preserve historical entries and edit values.

Run: python -m unittest discover -s tests -p test_custom_recipients.py
Requires Playwright and Chromium; CHROMIUM_EXECUTABLE may override the browser.
FINANCE_TEST_HTML may point to an offline preview; no outbound requests are allowed.
"""
from pathlib import Path
import json,os,shutil,unittest
from playwright.sync_api import sync_playwright

SOURCE=Path(os.environ.get('FINANCE_TEST_HTML',str(Path(__file__).resolve().parents[1]/'index.html')))
HTML=SOURCE.read_text();BASE='http://127.0.0.1:9898/'
class CustomRecipients(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.p=sync_playwright().start();executable=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium') or shutil.which('chromium-browser')
  cls.browser=cls.p.chromium.launch(headless=True,**({'executable_path':executable} if executable else {}))
 @classmethod
 def tearDownClass(cls):cls.browser.close();cls.p.stop()
 def setUp(self):
  self.context=self.browser.new_context(viewport={'width':1280,'height':1000},timezone_id='Europe/Moscow',service_workers='block')
  self.context.route('**/*',lambda r:r.fulfill(status=200,content_type='text/html',body=HTML) if r.request.url==BASE else r.abort())
  self.page=self.context.new_page();self.page.on('dialog',lambda d:d.accept());self.page.goto(BASE,wait_until='domcontentloaded');self.page.wait_for_function("typeof v134RemoveDirection==='function'")
  self.page.evaluate('''() => {session=null;state=blankState();localStorage.clear();localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=null;state.settings.preferences.expenseDirections=['Дача','Ремонт'];state.entries=[{id:'synthetic-custom',type:'expense',date:'2026-10-10',amount:150.5,category:'Продукты',beneficiary:'Дача',who:'Общее',store:'Synthetic shop',comment:'Synthetic history',accountId:'synthetic-account',unknown:{kept:true}}];window.originalEntries=JSON.stringify(state.entries);showApp();go('today');clearEntry();document.getElementById('eAmount').value='321,50';document.getElementById('eCategory').value='Продукты';document.getElementById('eComment').value='Synthetic draft';v81FillDetails('e','Продукты','','Дача');v90Paint();window.recipientRefreshCount=0;const previous=typeof v133RenderRecipients==='function'?v133RenderRecipients:null;window.v133RenderRecipients=(...args)=>{window.recipientRefreshCount++;return previous?.(...args)};}''')
 def tearDown(self):self.context.close()
 def evaluate(self,code):return self.page.evaluate('async () => {'+code+'}')
 def test_remove_only_updates_settings_and_current_recipient(self):
  r=self.evaluate('''const ok=await v134RemoveDirection('Дача');return {ok,active:v99BeneficiaryChoices(),custom:v99CustomDirections(),archived:v134ArchivedDirections(),selected:document.getElementById('eBeneficiary').value,amount:document.getElementById('eAmount').value,comment:document.getElementById('eComment').value,category:document.getElementById('eCategory').value,entriesSame:JSON.stringify(state.entries)===originalEntries,chipsRefreshed:recipientRefreshCount>0};''')
  self.assertTrue(r['ok']);self.assertNotIn('Дача',r['active']);self.assertEqual(r['custom'],['Ремонт']);self.assertIn('Дача',r['archived']);self.assertEqual(r['selected'],'Не указано');self.assertEqual(r['amount'],'321,50');self.assertEqual(r['comment'],'Synthetic draft');self.assertEqual(r['category'],'Продукты');self.assertTrue(r['entriesSame']);self.assertTrue(r['chipsRefreshed'])
 def test_removed_historical_recipient_does_not_return_after_reload(self):
  self.evaluate("await v134RemoveDirection('Дача');validateBackup(state);")
  self.page.reload(wait_until='domcontentloaded');self.page.wait_for_function("typeof v134RemoveDirection==='function'")
  r=self.evaluate("return {active:v99BeneficiaryChoices(),archived:v134ArchivedDirections(),entry:state.entries[0]};")
  self.assertNotIn('Дача',r['active']);self.assertIn('Дача',r['archived']);self.assertEqual(r['entry']['beneficiary'],'Дача');self.assertEqual(r['entry']['amount'],150.5);self.assertEqual(r['entry']['unknown'],{'kept':True})
 def test_historical_reports_and_existing_edit_value_preserved(self):
  r=self.evaluate('''await v134RemoveDirection('Дача');const report=v86TargetTotals(state.entries).find(([name])=>name==='Дача');openEdit('synthetic-custom');return {report,selected:document.getElementById('xBeneficiary').value,option:[...document.getElementById('xBeneficiary').options].some(o=>o.value==='Дача'),entriesSame:JSON.stringify(state.entries)===originalEntries};''')
  self.assertEqual(r['report'],['Дача',150.5]);self.assertEqual(r['selected'],'Дача');self.assertTrue(r['option']);self.assertTrue(r['entriesSame'])
 def test_readding_restores_canonical_choice_and_history(self):
  r=self.evaluate('''await v134RemoveDirection('Дача');v99OpenDirectionEditor('entry');document.querySelector('#v99DirectionEditorEntry input').value='дача';const ok=await v99SubmitDirectionEditor('entry');return {ok,active:v99BeneficiaryChoices(),custom:v99CustomDirections(),archived:v134ArchivedDirections(),entriesSame:JSON.stringify(state.entries)===originalEntries};''')
  self.assertTrue(r['ok']);self.assertIn('Дача',r['active']);self.assertIn('Дача',r['custom']);self.assertNotIn('дача',r['active']);self.assertNotIn('Дача',r['archived']);self.assertTrue(r['entriesSame'])
 def test_builtin_recipients_are_protected(self):
  r=self.evaluate('''const before=JSON.stringify(state),names=['Не указано','Общее',...PEOPLE,'Автомобиль','Кредиты и рассрочки','Оба ребёнка','Все питомцы'];const results=[];for(const name of names)results.push([name,v134CanRemoveDirection(name),await v134RemoveDirection(name)]);return {results,unchanged:JSON.stringify(state)===before};''')
  self.assertTrue(r['unchanged']);self.assertTrue(all(not can and not removed for _,can,removed in r['results']))
 def test_legacy_only_custom_name_is_removable_and_remains_reportable(self):
  r=self.evaluate('''state.settings.preferences.expenseDirections=['Ремонт'];const before=v99BeneficiaryChoices().includes('Дача');await v134RemoveDirection('Дача');const normalized=normalize(JSON.parse(JSON.stringify(state)));state=normalized;return {before,active:v99BeneficiaryChoices(),report:v86TargetTotals(state.entries).find(([name])=>name==='Дача'),unchanged:JSON.stringify(state.entries)===originalEntries};''')
  self.assertTrue(r['before']);self.assertNotIn('Дача',r['active']);self.assertEqual(r['report'],['Дача',150.5]);self.assertTrue(r['unchanged'])
 def test_readonly_or_locked_access_does_not_remove(self):
  r=self.evaluate('''const before=JSON.stringify(state);window.__FINANCE_BRIDGE__={active:true,role:'viewer'};const viewer=await v134RemoveDirection('Дача');window.__FINANCE_BRIDGE__=null;document.getElementById('appRoot').classList.add('auth-locked');const locked=await v134RemoveDirection('Дача');return {viewer,locked,unchanged:JSON.stringify(state)===before};''')
  self.assertFalse(r['viewer']);self.assertFalse(r['locked']);self.assertTrue(r['unchanged'])
 def test_storage_failure_is_retryable_without_restoring_choice(self):
  r=self.evaluate('''const original=saveAll;saveAll=async()=>{v89StorageFailed=true;return false};const failed=await v134RemoveDirection('Дача');const notice=!document.getElementById('v134DirectionRemovalNotice').hidden;saveAll=original;const retried=await v134RetryDirectionRemoval();return {failed,notice,retried,archived:v134IsArchivedDirection('Дача'),choice:v99BeneficiaryChoices().includes('Дача'),entriesSame:JSON.stringify(state.entries)===originalEntries,persisted:JSON.parse(localStorage.getItem(KEYS.state)).settings.preferences.archivedExpenseDirections};''')
  self.assertFalse(r['failed']);self.assertTrue(r['notice']);self.assertTrue(r['retried']);self.assertTrue(r['archived']);self.assertFalse(r['choice']);self.assertTrue(r['entriesSame']);self.assertIn('Дача',r['persisted'])
 def test_archived_name_in_older_raw_list_does_not_block_new_choice(self):
  r=self.evaluate("""state.settings.preferences.archivedExpenseDirections=['Дача'];v99OpenDirectionEditor('entry');document.querySelector('#v99DirectionEditorEntry input').value='Двор';const ok=await v99SubmitDirectionEditor('entry');return {ok,custom:v99CustomDirections(),active:v99BeneficiaryChoices(),archived:v134ArchivedDirections(),entriesSame:JSON.stringify(state.entries)===originalEntries};""")
  self.assertTrue(r['ok']);self.assertEqual(r['custom'],['Ремонт','Двор']);self.assertNotIn('Дача',r['active']);self.assertIn('Дача',r['archived']);self.assertTrue(r['entriesSame'])
 def test_repeating_old_operation_does_not_restore_archived_new_choice(self):
  r=self.evaluate("""await v134RemoveDirection('Дача');const ok=v97RepeatEntry('synthetic-custom');return {ok,selected:document.getElementById('eBeneficiary').value,options:[...document.getElementById('eBeneficiary').options].map(o=>o.value),amount:parseMoneyInput(document.getElementById('eAmount').value),entriesSame:JSON.stringify(state.entries)===originalEntries};""")
  self.assertTrue(r['ok']);self.assertEqual(r['selected'],'Не указано');self.assertNotIn('Дача',r['options']);self.assertEqual(r['amount'],150.5);self.assertTrue(r['entriesSame'])
 def test_favorite_old_recipient_is_not_reintroduced_to_new_choice(self):
  r=self.evaluate("""await v134RemoveDirection('Дача');state.intelligence.favorites=[{id:'synthetic-favorite',name:'Synthetic favorite',type:'expense',amount:44,category:'Продукты',beneficiary:'Дача',who:'Общее',store:'Synthetic shop',created_at:'2026-10-10T12:00:00.000Z',updated_at:'2026-10-10T12:00:00.000Z'}];const ok=v97OpenFavorite('synthetic-favorite');return {ok,selected:document.getElementById('eBeneficiary').value,options:[...document.getElementById('eBeneficiary').options].map(o=>o.value),amount:parseMoneyInput(document.getElementById('eAmount').value),favoriteTarget:state.intelligence.favorites[0].beneficiary,entriesSame:JSON.stringify(state.entries)===originalEntries};""")
  self.assertTrue(r['ok']);self.assertEqual(r['selected'],'Не указано');self.assertNotIn('Дача',r['options']);self.assertEqual(r['amount'],44);self.assertEqual(r['favoriteTarget'],'Дача');self.assertTrue(r['entriesSame'])
 def test_invalid_settings_are_not_overwritten(self):
  r=self.evaluate('''state.settings.preferences.archivedExpenseDirections='invalid';const before=JSON.stringify(state);const result=await v134RemoveDirection('Дача');return {result,unchanged:JSON.stringify(state)===before};''')
  self.assertFalse(r['result']);self.assertTrue(r['unchanged'])
 def test_manager_can_delete_typo_and_create_corrected_choice_from_buttons(self):
  self.page.locator('#v111AddDirection').click()
  editor=self.page.locator('#v99DirectionEditorEntry')
  editor.locator('input').fill('Дачаа')
  editor.get_by_role('button',name='Создать направление',exact=True).click()
  self.page.wait_for_function("v99CustomDirections().includes('Дачаа') && document.getElementById('v99DirectionEditorEntry').hidden")
  self.page.locator('#v111AddDirection').click()
  self.assertTrue(editor.get_by_role('heading',name='Мои варианты',exact=True).is_visible())
  editor.get_by_role('button',name='Удалить Дачаа',exact=True).click()
  self.page.wait_for_function("v134IsArchivedDirection('Дачаа') && !v99CustomDirections().includes('Дачаа')")
  self.assertEqual(editor.get_by_role('button',name='Удалить Дачаа',exact=True).count(),0)
  self.assertEqual(self.page.locator('[data-v133-recipient="Дачаа"]').count(),0)
  self.assertIn('Прошлые операции сохранены',editor.locator('[role="status"]').inner_text())
  editor.locator('input').fill('Гараж')
  editor.get_by_role('button',name='Создать направление',exact=True).click()
  self.page.wait_for_function("v99CustomDirections().includes('Гараж') && document.getElementById('v99DirectionEditorEntry').hidden")
  self.assertTrue(self.evaluate('return JSON.stringify(state.entries)===originalEntries;'))
  self.page.reload(wait_until='domcontentloaded');self.page.wait_for_function("typeof v134RemoveDirection==='function'")
  r=self.evaluate("return {active:v99BeneficiaryChoices(),archived:v134ArchivedDirections()};")
  self.assertIn('Гараж',r['active']);self.assertNotIn('Дачаа',r['active']);self.assertIn('Дачаа',r['archived'])
 def test_home_manager_deletes_historical_choice_and_only_lists_custom_names(self):
  self.page.evaluate("go('home')")
  if self.page.locator('#v73OverviewToggle').get_attribute('aria-expanded')!='true':self.page.locator('#v73OverviewToggle').click()
  self.page.locator("#v99HomeDirections button[onclick=\"v99OpenDirectionEditor('home')\"]").click()
  editor=self.page.locator('#v99DirectionEditorHome')
  self.assertEqual(editor.locator('[data-v136-remove-direction]').count(),2)
  self.assertEqual(editor.get_by_role('button',name='Удалить Общее',exact=True).count(),0)
  editor.get_by_role('button',name='Удалить Дача',exact=True).click()
  self.page.wait_for_function("v134IsArchivedDirection('Дача') && !v99BeneficiaryChoices().includes('Дача')")
  r=self.evaluate("return {report:v86TargetTotals(state.entries).find(([name])=>name==='Дача'),unchanged:JSON.stringify(state.entries)===originalEntries};")
  self.assertEqual(r['report'],['Дача',150.5]);self.assertTrue(r['unchanged'])

if __name__=='__main__':unittest.main(verbosity=2)
