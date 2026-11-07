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
 def test_placeholder_is_protected_and_all_active_recipients_can_be_removed(self):
  r=self.evaluate('''const before=JSON.stringify(state),names=v99BeneficiaryChoices().filter(name=>name!=='Не указано');return {can:names.map(name=>[name,v134CanRemoveDirection(name)]),placeholder:await v134RemoveDirection('Не указано'),unchanged:JSON.stringify(state)===before};''')
  self.assertFalse(r['placeholder']);self.assertTrue(r['unchanged']);self.assertTrue(all(can for _,can in r['can']));self.assertIn(['Общее',True],r['can'])
 def test_legacy_only_custom_name_is_removable_and_remains_reportable(self):
  r=self.evaluate('''state.settings.preferences.expenseDirections=['Ремонт'];const before=v99BeneficiaryChoices().includes('Дача');await v134RemoveDirection('Дача');const normalized=normalize(JSON.parse(JSON.stringify(state)));state=normalized;return {before,active:v99BeneficiaryChoices(),report:v86TargetTotals(state.entries).find(([name])=>name==='Дача'),unchanged:JSON.stringify(state.entries)===originalEntries};''')
  self.assertTrue(r['before']);self.assertNotIn('Дача',r['active']);self.assertEqual(r['report'],['Дача',150.5]);self.assertTrue(r['unchanged'])
 def test_readonly_or_locked_access_does_not_remove(self):
  r=self.evaluate('''const before=JSON.stringify(state);window.__FINANCE_BRIDGE__={active:true,role:'viewer'};const viewer=await v134RemoveDirection('Дача'),builtinViewer=await v134RemoveDirection('Сергей');window.__FINANCE_BRIDGE__=null;document.getElementById('appRoot').classList.add('auth-locked');const locked=await v134RemoveDirection('Дача'),builtinLocked=await v134RemoveDirection('Сергей');return {viewer,builtinViewer,locked,builtinLocked,unchanged:JSON.stringify(state)===before};''')
  self.assertFalse(r['viewer']);self.assertFalse(r['builtinViewer']);self.assertFalse(r['locked']);self.assertFalse(r['builtinLocked']);self.assertTrue(r['unchanged'])
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
  self.assertTrue(editor.get_by_role('heading',name='Варианты списка',exact=True).is_visible())
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
 def test_home_manager_deletes_historical_choice_and_lists_all_recipients(self):
  self.page.evaluate("go('home')")
  if self.page.locator('#v73OverviewToggle').get_attribute('aria-expanded')!='true':self.page.locator('#v73OverviewToggle').click()
  self.page.locator("#v99HomeDirections button[onclick=\"v99OpenDirectionEditor('home')\"]").click()
  editor=self.page.locator('#v99DirectionEditorHome')
  expected=self.evaluate("return v99BeneficiaryChoices().filter(v134CanRemoveDirection).length;")
  self.assertEqual(editor.locator('[data-v136-remove-direction]').count(),expected)
  self.assertEqual(editor.get_by_role('button',name='Удалить Общее',exact=True).count(),1)
  editor.get_by_role('button',name='Удалить Дача',exact=True).click()
  self.page.wait_for_function("v134IsArchivedDirection('Дача') && !v99BeneficiaryChoices().includes('Дача')")
  r=self.evaluate("return {report:v86TargetTotals(state.entries).find(([name])=>name==='Дача'),unchanged:JSON.stringify(state.entries)===originalEntries};")
  self.assertEqual(r['report'],['Дача',150.5]);self.assertTrue(r['unchanged'])

 def test_manage_button_archives_builtin_preserving_reload_history_and_edit(self):
  self.evaluate("""state.entries.push({...state.entries[0],id:'synthetic-sergey',amount:200,beneficiary:'Сергей',who:'Сергей'});originalEntries=JSON.stringify(state.entries);v81FillDetails('e','Продукты','','Дача');v90Paint();""")
  self.assertEqual(self.page.locator('[data-v133-remove="Сергей"]').count(),0)
  self.page.get_by_role('button',name='Изменить список',exact=True).click()
  editor=self.page.locator('#v99DirectionEditorEntry')
  self.assertTrue(editor.get_by_role('button',name='Удалить Сергей',exact=True).is_visible())
  editor.get_by_role('button',name='Удалить Сергей',exact=True).click()
  self.page.wait_for_function("v134IsArchivedDirection('Сергей') && !v99BeneficiaryChoices().includes('Сергей')")
  r=self.evaluate("""const report=v86TargetTotals(state.entries).find(([name])=>name==='Сергей');openEdit('synthetic-sergey');return {report,selected:document.getElementById('xBeneficiary').value,unchanged:JSON.stringify(state.entries)===originalEntries};""")
  self.assertEqual(r['report'],['Сергей',200]);self.assertEqual(r['selected'],'Сергей');self.assertTrue(r['unchanged'])
  self.page.reload(wait_until='domcontentloaded');self.page.wait_for_function("typeof v134RemoveDirection==='function'")
  r=self.evaluate("return {active:v99BeneficiaryChoices(),archived:v134ArchivedDirections(),record:state.entries.find(e=>e.id==='synthetic-sergey')};")
  self.assertNotIn('Сергей',r['active']);self.assertIn('Сергей',r['archived']);self.assertEqual(r['record']['beneficiary'],'Сергей');self.assertEqual(r['record']['amount'],200);self.assertEqual(r['record']['unknown'],{'kept':True})

 def test_archived_builtin_is_not_restored_by_repeat_favorite_or_legacy_choose(self):
  r=self.evaluate("""state.entries[0].beneficiary='Общее';originalEntries=JSON.stringify(state.entries);await v134RemoveDirection('Общее');const repeated=v97RepeatEntry('synthetic-custom'),repeatWho=document.getElementById('eBeneficiary').value;state.intelligence.favorites=[{id:'builtin-favorite',name:'Общий расход',type:'expense',amount:44,category:'Продукты',beneficiary:'Общее',who:'Общее',store:'Synthetic shop',created_at:'2026-10-10T12:00:00.000Z',updated_at:'2026-10-10T12:00:00.000Z'}];const favorite=v97OpenFavorite('builtin-favorite'),legacy=v99ChooseEntryDirection('shared');return {repeated,repeatWho,favorite,legacy,selected:document.getElementById('eBeneficiary').value,active:v99BeneficiaryChoices(),options:[...document.getElementById('eBeneficiary').options].map(o=>o.value),unchanged:JSON.stringify(state.entries)===originalEntries};""")
  self.assertTrue(r['repeated']);self.assertEqual(r['repeatWho'],'Не указано');self.assertTrue(r['favorite']);self.assertFalse(r['legacy']);self.assertEqual(r['selected'],'Не указано');self.assertNotIn('Общее',r['active']);self.assertNotIn('Общее',r['options']);self.assertTrue(r['unchanged'])

 def test_restoring_builtin_uses_canonical_name_without_consuming_custom_slots(self):
  r=self.evaluate("""state.settings.preferences.expenseDirections=Array.from({length:32},(_,i)=>'Вариант '+i);await v134RemoveDirection('Сергей');v99OpenDirectionEditor('entry');document.querySelector('#v99DirectionEditorEntry input').value='сергей';const restored=await v99SubmitDirectionEditor('entry');return {restored,active:v99BeneficiaryChoices(),archived:v134ArchivedDirections(),custom:v99CustomDirections(),raw:state.settings.preferences.expenseDirections,unchanged:JSON.stringify(state.entries)===originalEntries};""")
  self.assertTrue(r['restored']);self.assertIn('Сергей',r['active']);self.assertNotIn('сергей',r['active']);self.assertNotIn('Сергей',r['archived']);self.assertEqual(len(r['custom']),32);self.assertNotIn('Сергей',r['raw']);self.assertTrue(r['unchanged'])

if __name__=='__main__':unittest.main(verbosity=2)
