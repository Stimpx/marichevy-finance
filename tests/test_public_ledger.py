"""Public full-ledger integration with two users/families in real iframes.

All Auth/RPC responses are deterministic in-page fixtures. No hosted project is
contacted and no personal browser storage is read.
"""
import importlib.util
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from build_public_client import transform_public

H1 = '11111111-1111-4111-8111-111111111111'
H2 = '22222222-2222-4222-8222-222222222222'
U1 = '33333333-3333-4333-8333-333333333333'
U2 = '44444444-4444-4444-8444-444444444444'

HARNESS = '''<!doctype html><html><head><script src="/ledger.js"></script></head>
<body><div id="mount"></div><script>
const H1=''' + json.dumps(H1) + ''', H2=''' + json.dumps(H2) + ''', U1=''' + json.dumps(U1) + ''', U2=''' + json.dumps(U2) + ''';
const households={}; const rows={}; const calls=[]; let handle, currentUser=U1, paused=false, revoked=false, blockedWrites=false, holdCAS=false, held=[];
for(const [id,name] of [[H1,'Первая семья'],[H2,'Вторая семья']]) {
 households[id]={id,name,timezone:'UTC',role:'owner',settings:{people:[{id:'person-1',name:'Читатель'}],categories:[{id:'cat-1',name:'Еда'}]}};
 rows[id]={household_id:id,data:{entries:[],settings:{}},sync_revision:0,sync_protocol:2};
}
async function request(path,body) {
 calls.push({path,body:JSON.parse(JSON.stringify(body)),user:currentUser});
 if(revoked)throw Object.assign(new Error('permission denied'),{status:403});
 const id=body.p_household_id;
 if(path.endsWith('finance_get_household'))return JSON.parse(JSON.stringify(households[id]));
 if(path.endsWith('finance_read_state')) {
  const result=JSON.parse(JSON.stringify([rows[id]]));
  if(paused)return await new Promise(resolve=>held.push(()=>resolve(result)));
  return result;
 }
 if(path.endsWith('finance_state_cas')) {
  if(blockedWrites)throw Object.assign(new Error('offline'),{status:503});
  if(households[id].role==='viewer')throw Object.assign(new Error('viewer'),{status:403});
  if(body.p_expected_revision!==rows[id].sync_revision)return {status:'conflict',protocol:2,revision:rows[id].sync_revision,data:rows[id].data};
  rows[id].data=JSON.parse(JSON.stringify(body.p_data)); rows[id].sync_revision++;
  const ack={status:'written',protocol:2,revision:rows[id].sync_revision,data:JSON.parse(JSON.stringify(rows[id].data)),request_id:body.p_request_id};
  if(holdCAS)return await new Promise(resolve=>held.push(()=>resolve(ack)));
  return ack;
 }
 throw new Error('Unexpected RPC '+path);
}
function mountFamily(house=H1,user=U1) {
 handle?.unmount(); currentUser=user;
 handle=FinanceLedger.mount(document.getElementById('mount'),{
 config:{supabaseUrl:'https://backend.example.invalid',publishableKey:'sb_publishable_unit'},
 session:{access_token:'unit-user-token',user:{id:user,user_metadata:{name:'Участник'}}},household:households[house],request,
 refresh:async()=>({access_token:'unit-refreshed',user:{id:user}}),onAccessLost:()=>window.lost=true
 }); return handle.ready.then(()=>true);
}
function release(){const list=held;held=[];paused=false;holdCAS=false;for(const done of list)done();}
</script></body></html>'''


class PublicTemplate(unittest.TestCase):
    def test_full_ui_is_depersonalized_without_seeded_records(self):
        source = (ROOT / 'index.html').read_text()
        template = transform_public(source)
        from build_bundle import detach_merchant_catalog
        personal_text, catalogue = detach_merchant_catalog(template)
        self.assertEqual(catalogue, detach_merchant_catalog(source)[1])
        self.assertEqual(template, (ROOT / 'public/ledger-template.html').read_text())
        original = set(re.findall(r'(?:async )?function (\w+)\(', source))
        delivered = set(re.findall(r'(?:async )?function (\w+)\(', template))
        self.assertEqual(original, delivered)
        for marker in ['gmail.com','Сергей','Виктория','Алиса','Майя','Алексей','Елена','София','Илья','Демобанк','1985-11-27','9946-WZ3/00067','supabase.co','offline-demo','__FINANCE_STORAGE__','__FINANCE_CONFIG__']:
            self.assertNotIn(marker, personal_text)
        self.assertIn('const FAMILY_BIRTHS=[];', template)
        self.assertIn('const FAMILY_WEDDING=null;', template)
        self.assertIn('const BANK_LOAN_SCHEDULE=[];', template)
        self.assertIn('let state=blankState();', template)
        self.assertNotIn('window.fetch=()=>Promise.reject', template)
        self.assertNotIn('boot().catch', template)
        self.assertIn('data-finance-runtime', template)


@unittest.skipUnless(importlib.util.find_spec('playwright'), 'playwright required')
class PublicLedgerBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/':
                    body, mime = HARNESS.encode(), 'text/html; charset=utf-8'
                elif self.path.split('?',1)[0] in ['/ledger.js','/ledger-template.html']:
                    body = (ROOT / 'public' / self.path.lstrip('/').split('?',1)[0]).read_bytes()
                    mime = 'text/javascript' if self.path.endswith('.js') else 'text/html; charset=utf-8'
                else:
                    self.send_error(404); return
                self.send_response(200); self.send_header('Content-Type',mime)
                self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
            def log_message(self,*_): pass
        cls.server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever,daemon=True); cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}/'
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.pw.stop(); cls.server.shutdown(); cls.server.server_close()

    def setUp(self):
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror',lambda error:self.errors.append(str(error)))
        self.page.goto(self.base)

    def tearDown(self): self.context.close()

    def mount(self,house=H1,user=U1):
        self.page.evaluate('([h,u])=>mountFamily(h,u)',[house,user])
        self.page.wait_for_function('handle.iframe && !handle.iframe.contentDocument.getElementById("appRoot").classList.contains("auth-locked")')
        return self.page.frames[-1]

    def add(self,frame,amount='12,34'):
        frame.evaluate('''amount=>{go('today');document.getElementById('eAmount').value=amount;document.getElementById('eCategory').value='Еда';document.getElementById('eBeneficiary').value='Читатель';return addEntry()}''',amount)

    def test_blank_full_ui_actual_sum_calculator_and_catalog_ids(self):
        frame=self.mount()
        self.assertEqual(frame.evaluate('state.entries.length'),0)
        self.assertEqual(frame.evaluate('state.settings.loans.loan1'),0)
        self.assertEqual(frame.evaluate('getBirthdayRows().length'),0)
        self.assertEqual(frame.evaluate('v97FavoriteRows().length'),0)
        self.add(frame)
        self.add(frame,'0,66')
        self.assertEqual(frame.evaluate('sum(state.entries)'),13)
        self.assertEqual(frame.evaluate('state.entries[0].category_id'),'cat-1')
        self.assertEqual(frame.evaluate('state.entries[0].person_id'),'person-1')
        self.assertEqual(self.page.evaluate('rows[H1].data.entries.length'),2)
        frame.evaluate("v96OpenCalculator('eAmount')")
        self.assertTrue(frame.locator('#v96Calculator').is_visible())
        self.assertEqual(self.errors,[])

    def test_configured_legacy_category_keeps_budget_and_analytics_group_consistent(self):
        self.page.evaluate("households[H1].settings.categories[0].name='Продукты'")
        frame=self.mount()
        frame.evaluate("()=>{go('today');document.getElementById('eAmount').value='12,34';document.getElementById('eCategory').value='Продукты';return addEntry()}")
        self.assertEqual(frame.evaluate('EXPENSE_GROUPS[0].title'),frame.evaluate('expenseEntryGroup(state.entries[0])'))
        frame.evaluate("()=>{document.getElementById('v84BudgetAmount').value='20';v84AddBudget()}")
        self.assertEqual(frame.evaluate('v84SpendGroup(month(),state.intelligence.budgets[0].group)'),12.34)

    def test_user_and_family_cache_pending_and_late_read_are_isolated(self):
        frame=self.mount()
        self.page.evaluate('blockedWrites=true')
        self.add(frame)
        prefix1=self.page.evaluate('handle.namespace')
        pending1=self.page.evaluate('(key)=>localStorage.getItem(key+"pending_v10")',prefix1)
        self.assertIn('12.34',pending1)
        self.page.evaluate('()=>{paused=true;void handle.iframe.contentWindow.syncFromCloud()}')
        self.page.wait_for_function('held.length>0')
        frame2=self.mount(H2,U1)
        self.assertEqual(frame2.evaluate('state.entries.length'),0)
        prefix2=self.page.evaluate('handle.namespace'); self.assertNotEqual(prefix1,prefix2)
        self.page.evaluate('release()')
        self.page.wait_for_timeout(30)
        self.assertEqual(frame2.evaluate('state.entries.length'),0)
        self.assertEqual(self.page.evaluate('(key)=>localStorage.getItem(key+"pending_v10")',prefix1),pending1)
        frame3=self.mount(H1,U2)
        self.assertEqual(frame3.evaluate('state.entries.length'),0)
        self.assertNotEqual(self.page.evaluate('handle.namespace'),prefix1)
        frame4=self.mount(H1,U1)
        self.assertEqual(frame4.evaluate('state.entries.length'),1)
        self.assertEqual(self.page.evaluate('(key)=>localStorage.getItem(key+"pending_v10")',prefix1),pending1)

    def test_viewer_guards_export_calculator_and_access_loss_preserve_queue(self):
        self.page.evaluate("rows[H1].data.entries=[{id:'visible-cloud-entry',type:'expense',date:new Date().toISOString().slice(0,10),amount:42,category:'Еда',who:'Читатель',store:'Облачная операция'}]")
        self.page.evaluate("households[H1].role='viewer'")
        frame=self.mount()
        frame.wait_for_function('state.entries.length===1')
        self.assertIn('Облачная операция',frame.locator('#todayList').inner_text())
        self.assertTrue(frame.locator('#v90Save').is_disabled())
        frame.evaluate("document.getElementById('eAmount').value='11';addEntry()")
        self.assertEqual(frame.evaluate('state.entries.length'),1)
        self.assertEqual(self.page.evaluate('calls.filter(x=>x.path.endsWith("finance_state_cas")).length'),0)
        frame.evaluate("v96OpenCalculator('eAmount')")
        self.assertTrue(frame.locator('#v96Calculator').is_visible())
        with self.page.expect_download() as item: frame.evaluate('exportData()')
        self.assertTrue(item.value.suggested_filename.endswith('.json'))
        prefix=self.page.evaluate('handle.namespace')
        self.page.evaluate('(key)=>localStorage.setItem(key+"pending_v10","retained raw queue")',prefix)
        self.page.evaluate('revoked=true; handle.iframe.contentWindow.syncFromCloud()')
        self.page.wait_for_function('window.lost===true')
        self.assertTrue(self.page.evaluate('handle.iframe.hidden'))
        self.assertEqual(self.page.evaluate('(key)=>localStorage.getItem(key+"pending_v10")',prefix),'retained raw queue')

    def test_hostile_family_names_are_text_and_parent_owns_refresh(self):
        self.page.evaluate("households[H1].name='</script><img src=x onerror=parent.pwned=1>'")
        frame=self.mount()
        self.assertIn('</script>', frame.locator('.brand-heading').inner_text())
        self.assertFalse(self.page.evaluate('Boolean(window.pwned)'))
        self.assertTrue(frame.evaluate('refreshSession()'))
        self.assertEqual(frame.evaluate('session.access_token'),'unit-refreshed')
        self.assertFalse(self.page.evaluate('Object.keys(localStorage).some(k=>k.endsWith("session_v10"))'))

    def test_empty_metadata_has_no_inherited_categories_and_denied_boot_reads_no_cache(self):
        self.page.evaluate('households[H1].settings={people:[],categories:[]}')
        frame=self.mount()
        self.assertEqual(frame.evaluate('V90_CATEGORIES.length'),0)
        self.assertEqual(frame.locator('#v90Quick button').count(),0)
        self.assertIn('настройках семьи',frame.locator('#saveMsg').inner_text())
        prefix=self.page.evaluate('handle.namespace')
        self.page.evaluate('(key)=>localStorage.setItem(key+"state_v10","private cache must stay unread")',prefix)
        self.page.evaluate('handle.unmount();revoked=true;window.lost=false;mountFamily().catch(()=>{})')
        self.page.wait_for_function('window.lost===true')
        self.assertIsNone(self.page.evaluate('handle.iframe'))
        self.assertEqual(self.page.evaluate('(key)=>localStorage.getItem(key+"state_v10")',prefix),'private cache must stay unread')

    def test_late_write_ack_and_downgraded_dynamic_controls_preserve_finances(self):
        frame=self.mount()
        self.page.evaluate('holdCAS=true')
        frame.evaluate("()=>{go('today');document.getElementById('eAmount').value='10';document.getElementById('eCategory').value='Еда';void addEntry()}")
        self.page.wait_for_function('held.length===1')
        prefix=self.page.evaluate('handle.namespace')
        pending=self.page.evaluate('(key)=>localStorage.getItem(key+"pending_v10")',prefix)
        other=self.mount(H2,U1)
        self.page.evaluate('release()')
        self.page.wait_for_timeout(30)
        self.assertEqual(other.evaluate('state.entries.length'),0)
        self.assertEqual(self.page.evaluate('(key)=>localStorage.getItem(key+"pending_v10")',prefix),pending)
        self.assertTrue(self.page.evaluate('calls.filter(x=>x.path.endsWith("finance_state_cas")).every(x=>x.body.p_household_id===H1)'))
        frame=self.mount(H1,U1)
        frame.evaluate("()=>{state.intelligence.recurring.push({id:'recurring-test',name:'Тест',category:'Еда',amount:10,day:1});v84LinkRecurring('recurring-test',month())}")
        self.assertEqual(frame.locator('[data-v84-link]').count(),1)
        self.page.evaluate("households[H1].role='viewer'")
        frame.evaluate('window.__FINANCE_BRIDGE__.membership()')
        frame.evaluate("()=>{const button=document.querySelector('[data-v84-link]');button.disabled=false;button.click()}")
        self.assertFalse(frame.evaluate('Boolean(state.entries[0].recurringId)'))
        before=frame.evaluate('JSON.stringify(state.entries)')
        frame.evaluate("v78ToggleMortgage(state.entries[0].id)")
        self.assertEqual(frame.evaluate('JSON.stringify(state.entries)'),before)

    def test_category_rename_keeps_historical_labels_and_id(self):
        frame=self.mount(); self.add(frame)
        self.page.evaluate("households[H1].settings.categories[0].name='Питание'")
        frame=self.mount()
        self.assertEqual(frame.evaluate('state.entries[0].category'),'Еда')
        self.assertEqual(frame.evaluate('state.entries[0].category_id'),'cat-1')
        self.assertEqual(frame.evaluate('V90_CATEGORIES[0][0]'),'Питание')
        frame.evaluate("()=>{go('today');document.getElementById('eAmount').value='5';document.getElementById('eCategory').value='Питание';return addEntry()}")
        self.assertEqual(frame.evaluate('state.entries.map(row=>[row.category,row.category_id])'),[['Еда','cat-1'],['Питание','cat-1']])
        self.assertIn('Еда',frame.locator('#fCat').inner_text())
        self.page.evaluate("households[H1].settings.people[0].name='Новое имя'")
        frame=self.mount()
        frame.evaluate("()=>{state.entries[0].type='income';state.entries[0].who='Читатель';delete state.entries[0].beneficiary;openEdit(state.entries[0].id)}")
        self.assertEqual(frame.locator('#xWho').input_value(),'Читатель')

    def test_regaining_edit_rights_restores_unsent_queue_after_viewer_refresh(self):
        frame=self.mount()
        self.page.evaluate('blockedWrites=true')
        self.add(frame,'19,25')
        prefix=self.page.evaluate('handle.namespace')
        pending=self.page.evaluate('(key)=>localStorage.getItem(key+"pending_v10")',prefix)
        self.page.evaluate("households[H1].role='viewer'")
        frame.evaluate('window.__FINANCE_BRIDGE__.membership()')
        frame.evaluate('syncFromCloud()')
        self.assertEqual(frame.evaluate('state.entries.length'),0)
        self.assertEqual(self.page.evaluate('(key)=>localStorage.getItem(key+"pending_v10")',prefix),pending)
        self.page.evaluate("households[H1].role='editor';blockedWrites=false")
        frame.evaluate('window.__FINANCE_BRIDGE__.membership()')
        self.assertEqual(frame.evaluate('state.entries[0].amount'),19.25)
        frame.evaluate('syncFromCloud()')
        self.assertEqual(self.page.evaluate('rows[H1].data.entries[0].amount'),19.25)
        self.assertIsNone(self.page.evaluate('(key)=>localStorage.getItem(key+"pending_v10")',prefix))

    def test_delayed_import_and_backup_stop_after_unmount_preserving_personal_storage(self):
        self.page.evaluate("localStorage.setItem('marichevy_state_v10','existing personal bytes')")
        frame=self.mount(); self.add(frame)
        prefix=self.page.evaluate('handle.namespace')
        before=self.page.evaluate('(prefix)=>Object.fromEntries(Object.entries(localStorage).filter(([key])=>key.startsWith(prefix)))',prefix)
        frame.evaluate("""()=>{
          const input=document.getElementById('importFile');
          Object.defineProperty(input,'files',{value:[{size:100,text:()=>new Promise(resolve=>parent.finishImport=resolve)}]});
          input.dispatchEvent(new Event('change',{bubbles:true}));
          let first=true;crypto.subtle.digest=()=>first?(first=false,new Promise(resolve=>parent.finishDigest=()=>resolve(new ArrayBuffer(32)))):Promise.resolve(new ArrayBuffer(32));
          void exportDeviceBackup();
        }""")
        self.page.wait_for_function('Boolean(window.finishImport && window.finishDigest)')
        self.page.evaluate("handle.unmount();finishImport(JSON.stringify({entries:[],settings:{}}));finishDigest()")
        self.page.wait_for_timeout(30)
        after=self.page.evaluate('(prefix)=>Object.fromEntries(Object.entries(localStorage).filter(([key])=>key.startsWith(prefix)))',prefix)
        self.assertEqual(before,after)
        self.assertEqual(self.page.evaluate("localStorage.getItem('marichevy_state_v10')"),'existing personal bytes')

    def test_device_download_preserves_catalog_metadata_hash_and_exact_pending_bytes(self):
        self.page.evaluate("""()=>{
          households[H1].timezone='Europe/Paris';
          households[H1].settings.people.push({id:'person-archived',name:'Архивный участник',archived:true,email:'must-not-export@example.invalid'});
          households[H1].settings.categories.push({id:'cat-archived',name:'Архивная категория',archived:true,role:'must-not-export'});
          households[H1].settings.people.push('Участник старого формата');
          households[H1].settings.categories.push('Категория старого формата');
          households[H1].email='must-not-export@example.invalid';households[H1].invites=['must-not-export-token'];
        }""")
        frame=self.mount();self.page.evaluate('blockedWrites=true');self.add(frame)
        prefix=self.page.evaluate('handle.namespace')
        pending=self.page.evaluate('(key)=>localStorage.getItem(key+"pending_v10")',prefix)
        with self.page.expect_download() as item: frame.evaluate('exportDeviceBackup()')
        capture=json.loads(Path(item.value.path()).read_text())
        metadata=capture['household_metadata']
        self.assertEqual(set(metadata),{'household_id','name','timezone','people','categories'})
        self.assertEqual(metadata['household_id'],H1)
        self.assertEqual(metadata['name'],'Первая семья')
        self.assertEqual(metadata['timezone'],'Europe/Paris')
        self.assertEqual(metadata['people'][1],{'id':'person-archived','name':'Архивный участник','archived':True})
        self.assertEqual(metadata['categories'][1],{'id':'cat-archived','name':'Архивная категория','archived':True})
        self.assertEqual(metadata['people'][2],'Участник старого формата')
        self.assertEqual(metadata['categories'][2],'Категория старого формата')
        metadata_raw=json.dumps(metadata,ensure_ascii=False,separators=(',',':'))
        self.assertEqual(capture['household_metadata_sha256_utf8'],hashlib.sha256(metadata_raw.encode()).hexdigest())
        self.assertEqual(next(row['raw'] for row in capture['records'] if row['key']==prefix+'pending_v10'),pending)
        self.assertEqual(self.page.evaluate('(key)=>localStorage.getItem(key+"pending_v10")',prefix),pending)
        body=json.dumps(capture,ensure_ascii=False)
        for marker in ['unit-user-token','refresh_token','access_token','must-not-export','session_v10']:
            self.assertNotIn(marker,body)
        self.assertFalse(capture['session_included'])
        with self.page.expect_download() as item: frame.evaluate('exportData()')
        ordinary=json.loads(Path(item.value.path()).read_text())
        self.assertNotIn('household_metadata',ordinary)
        self.assertEqual(ordinary['entries'][0]['amount'],12.34)

    def test_metadata_change_during_device_hashing_blocks_capture_without_writes(self):
        frame=self.mount();self.page.evaluate('blockedWrites=true');self.add(frame)
        prefix=self.page.evaluate('handle.namespace')
        pending=self.page.evaluate('(key)=>localStorage.getItem(key+"pending_v10")',prefix)
        frame.evaluate("""()=>{
          const original=crypto.subtle.digest.bind(crypto.subtle);let first=true;
          crypto.subtle.digest=(...args)=>first?(first=false,new Promise(resolve=>parent.finishMetadataHash=()=>original(...args).then(resolve))):original(...args);
          parent.captureResult=null;void exportDeviceBackup().then(result=>parent.captureResult=result);
        }""")
        self.page.wait_for_function('Boolean(window.finishMetadataHash)')
        self.page.evaluate("households[H1].name='Изменённая семья'")
        frame.evaluate('window.__FINANCE_BRIDGE__.membership()')
        self.page.evaluate('finishMetadataHash()')
        self.page.wait_for_function('Boolean(window.captureResult)')
        self.assertEqual(self.page.evaluate('captureResult'),{'outcome':'blocked','reason':'metadata-changed-during-capture'})
        self.assertEqual(self.page.evaluate('(key)=>localStorage.getItem(key+"pending_v10")',prefix),pending)
        self.assertTrue(frame.locator('#deviceBackupDownload').is_hidden())

    def test_category_review_updates_configured_id_and_preserves_financial_fields(self):
        self.page.evaluate("""()=>{
          households[H1].settings.categories.push({id:'cat-subscription',name:'Подписки'},{id:'cat-work',name:'Работа'});
        }""")
        frame=self.mount()
        frame.evaluate("""()=>{
          state.entries=[{id:'review-service',type:'expense',date:today(),amount:12.34,
            category:'Еда',category_id:'cat-1',who:null,store:'OpenAI',comment:'Подписка ChatGPT',
            futureField:{keep:[true,null,7]}}];
          renderAll();go('analytics');v98OpenCategoryReview();
        }""")
        before=frame.evaluate('JSON.parse(JSON.stringify(state.entries[0]))')
        frame.locator('#v98ReviewRows button').click()
        frame.locator('#v98CategoryEditIntro button').filter(has_text='Подписки').click()
        frame.locator('#editModal').get_by_role('button',name='Сохранить',exact=True).click()
        self.page.wait_for_function('rows[H1].data.entries?.[0]?.category_id==="cat-subscription"')
        stored=self.page.evaluate('rows[H1].data.entries[0]')
        self.assertEqual(stored['category'],'Подписки')
        self.assertEqual(stored['category_id'],'cat-subscription')
        for key in ('amount','date','who','store','comment','futureField'):
            self.assertEqual(stored[key],before[key])
        self.assertEqual(self.page.evaluate('rows[H1].data.entries.length'),1)
        self.assertEqual(frame.evaluate("v98BudgetScope({groupVersion:2,groupId:'subscriptions',group:'Подписки и сервисы'}).supported"),True)

    def test_viewer_can_read_review_but_never_apply_category(self):
        self.page.evaluate("households[H1].role='viewer';households[H1].settings.categories.push({id:'cat-subscription',name:'Подписки'})")
        frame=self.mount()
        frame.evaluate("""()=>{
          state.entries=[{id:'viewer-review',type:'expense',date:today(),amount:12.34,
            category:'Еда',who:'Читатель',store:'OpenAI',comment:'ChatGPT'}];
          renderAll();go('analytics');v98OpenCategoryReview();
        }""")
        before=frame.evaluate('JSON.stringify(state)')
        self.assertTrue(frame.locator('#categoryReview').is_visible())
        self.assertTrue(frame.locator('#v98ReviewRows button').is_disabled())
        frame.evaluate("v98OpenReviewEntry('viewer-review');v98SaveCategoryReview()")
        self.assertEqual(frame.evaluate('JSON.stringify(state)'),before)
        self.assertFalse(frame.locator('#editModal').is_visible())
        self.assertEqual(self.page.evaluate("calls.filter(call=>call.path.endsWith('finance_state_cas')).length"),0)


if __name__=='__main__': unittest.main()
