"""Historical Split payments: offline browser regressions with synthetic entries.

Run: python -m unittest discover -s tests -p test_installment_history.py
Requires Playwright and Chromium (system or Playwright-managed).
Set CHROMIUM_EXECUTABLE to override the browser executable.
All outbound requests are blocked; no account is authenticated.
"""
from pathlib import Path
import hashlib,json,os,shutil,unittest
from playwright.sync_api import sync_playwright

SOURCE=Path(__file__).resolve().parents[1]/'index.html'
HTML=SOURCE.read_text()
BASE='http://127.0.0.1:9887/'

class PastPaymentRegression(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.p=sync_playwright().start()
  executable=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium') or shutil.which('chromium-browser')
  cls.browser=cls.p.chromium.launch(headless=True,**({'executable_path':executable} if executable else {}))
 @classmethod
 def tearDownClass(cls):
  cls.browser.close();cls.p.stop()
 def setUp(self):
  self.context=self.browser.new_context(viewport={'width':1280,'height':1000},timezone_id='Europe/Moscow',service_workers='block')
  self.context.route('**/*',lambda r:r.fulfill(status=200,content_type='text/html',body=HTML) if r.request.url==BASE else r.abort())
  self.page=self.context.new_page();self.page.goto(BASE,wait_until='domcontentloaded');self.page.wait_for_function("typeof v127OpenPastPayment==='function'")
  self.page.evaluate('''() => {
   session=null;localStorage.clear();state=blankState();localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=null;
   window.clone=x=>JSON.parse(JSON.stringify(x));
   const plan=clone(FAMILY_DOCUMENT_PLANS[0]);plan.title='Synthetic remainder';plan.created_at='2026-10-31T12:00:00.000Z';plan.updated_at=plan.created_at;
   const expense={id:'synthetic-oct',type:'expense',category:'Кредит',amount:4608,date:'2026-10-10',who:'Общее',store:'Synthetic Split',comment:'Existing October payment',pay:'Карта',accountId:'synthetic-account',customUnknown:{kept:true},created_at:'2026-10-10T12:00:00.000Z',updated_at:'2026-10-10T12:00:00.000Z'};
   state.installments=[plan];state.entries=[expense];window.originalFuture=clone(plan.parts);window.originalExpense=clone(expense);showApp();go('loans');
   window.openPast=()=>v127OpenPastPayment(state.installments[0].id,'synthetic-oct');
   window.planRemaining=()=>state.installments[0].parts.reduce((sum,p)=>sum+p.amount-installmentAllocated(state.installments[0],p),0);
  }''')
 def tearDown(self):self.context.close()
 def evaluate(self,js):return self.page.evaluate('async () => {'+js+'}')
 def test_october_payment_preserves_expense_future_remainder_and_month(self):
  r=self.evaluate('''openPast();await v127ApplyPastPayment();const i=state.installments[0],part=i.parts.find(p=>p.historicalPayment);return {entriesUnchanged:cloudJSONEqual(state.entries[0],originalExpense),futureUnchanged:cloudJSONEqual(i.parts.filter(p=>!p.historicalPayment),originalFuture),remaining:planRemaining(),paid:installmentAllocated(i,part),amount:i.amount,parts:i.parts.length,date:part.date,count:state.entries.length,group:v78Obligations('2026-10').groups.find(g=>g.title===i.title),calendar:v86CalendarEvents('2026-10').filter(e=>e.installmentId===i.id)};''')
  self.assertTrue(r['entriesUnchanged']);self.assertTrue(r['futureUnchanged']);self.assertEqual(r['remaining'],32255);self.assertEqual(r['paid'],4608);self.assertEqual(r['amount'],36863);self.assertEqual(r['parts'],8);self.assertEqual(r['date'],'2026-10-10');self.assertEqual(r['count'],1)
  self.assertEqual((r['group']['planned'],r['group']['paid']),(4608,4608));self.assertEqual(len(r['calendar']),1);self.assertTrue(r['calendar'][0]['paid']);self.assertEqual(r['calendar'][0]['allocated'],4608)
 def test_repeated_apply_and_reopen_do_not_duplicate(self):
  r=self.evaluate('''openPast();await v127ApplyPastPayment();await v127ApplyPastPayment();openPast();await v127ApplyPastPayment();return {parts:state.installments[0].parts.length,count:state.entries.length,remaining:planRemaining(),amount:state.installments[0].amount};''')
  self.assertEqual(r,{'parts':8,'count':1,'remaining':32255,'amount':36863})
 def test_repeated_older_payments_preserve_future_and_order(self):
  r=self.evaluate('''openPast();await v127ApplyPastPayment();state.entries.push({...clone(originalExpense),id:'synthetic-sep',date:'2026-09-10',amount:1234.56});v127OpenPastPayment(state.installments[0].id,'synthetic-sep');await v127ApplyPastPayment();const i=state.installments[0];return {parts:i.parts.length,amount:i.amount,remaining:planRemaining(),dates:i.parts.slice(0,2).map(p=>p.date),future:cloudJSONEqual(i.parts.filter(p=>!p.historicalPayment),originalFuture),entryCount:state.entries.length};''')
  self.assertEqual(r,{'parts':9,'amount':38097.56,'remaining':32255,'dates':['2026-09-10','2026-10-10'],'future':True,'entryCount':2})
 def test_invalid_future_and_already_claimed_candidates_rejected(self):
  r=self.evaluate('''const e=state.entries[0],i=state.installments[0];const variants={future:{date:'2099-10-10'},invalidDate:{date:'2026-02-30'},zero:{amount:0},negative:{amount:-1},nan:{amount:NaN},large:{amount:100000001},income:{type:'income'},otherCategory:{category:'Продукты'},metadata:{installmentId:'other'},metadataPart:{installmentPartId:'other'},mortgageFlag:{mortgagePayment:true},mortgageType:{obligationType:'mortgage'},mortgageAllocation:{mortgageAllocation:{kind:'regular',dueDate:'2026-10-10'}},bankDescription:{store:'Ипотека УралСиб'}};const result=Object.fromEntries(Object.entries(variants).map(([name,change])=>[name,v127PastPlanAllowed(i,{...e,...change})]));i.links[i.parts[0].id]=e.id;result.alreadyClaimed=v127PastEntryAllowed(e);return result;''')
  self.assertFalse(any(r.values()),r)
 def test_same_day_or_after_first_scheduled_date_rejected(self):
  r=self.evaluate('''const i=state.installments[0],e=state.entries[0];return ['2026-11-10','2026-11-11'].map(date=>v127PastPlanAllowed(i,{...e,date}));''')
  self.assertEqual(r,[False,False])
 def test_read_only_bridge_blocks_open_and_apply(self):
  r=self.evaluate('''window.__FINANCE_BRIDGE__={active:true,role:'viewer'};openPast();const deniedOpen=v127PastPaymentContext===null;window.__FINANCE_BRIDGE__=null;openPast();window.__FINANCE_BRIDGE__={active:true,role:'viewer'};await v127ApplyPastPayment();return {deniedOpen,parts:state.installments[0].parts.length};''')
  self.assertEqual(r,{'deniedOpen':True,'parts':7})
 def test_stale_auth_context_rejected(self):
  r=self.evaluate('''openPast();authEpoch++;await v127ApplyPastPayment();return {parts:state.installments[0].parts.length,count:state.entries.length};''')
  self.assertEqual(r,{'parts':7,'count':1})
 def test_stale_plan_rejected(self):
  r=self.evaluate('''openPast();state.installments[0].provider='Concurrent change';await v127ApplyPastPayment();return {parts:state.installments[0].parts.length,error:document.getElementById('v127PastError').textContent};''')
  self.assertEqual(r['parts'],7);self.assertIn('изменился',r['error'])
 def test_stale_expense_rejected(self):
  r=self.evaluate('''openPast();state.entries[0].comment='Concurrent change';await v127ApplyPastPayment();return {parts:state.installments[0].parts.length,error:document.getElementById('v127PastError').textContent};''')
  self.assertEqual(r['parts'],7);self.assertIn('изменился',r['error'])
 def test_entry_claimed_between_preview_and_apply_rejected(self):
  r=self.evaluate('''openPast();state.installments.push({...clone(state.installments[0]),id:'other-plan',links:{other:'synthetic-oct'}});await v127ApplyPastPayment();return state.installments[0].parts.length;''')
  self.assertEqual(r,7)
 def test_plan_with_inconsistent_total_rejected(self):
  r=self.evaluate('''state.installments[0].amount=32000;return v127PastPlanAllowed(state.installments[0],state.entries[0]);''');self.assertFalse(r)
 def test_normalization_and_local_reload_preserve_link(self):
  self.evaluate('''openPast();await v127ApplyPastPayment();validateBackup(state);const parsed=normalize(JSON.parse(localStorage.getItem(KEYS.state)));if(parsed.installments[0].parts.length!==8)throw new Error('Missing persisted part');''')
  self.page.reload(wait_until='domcontentloaded');self.page.wait_for_function("typeof v127OpenPastPayment==='function'")
  r=self.evaluate('''const data=normalize(JSON.parse(localStorage.getItem(KEYS.state))),i=data.installments[0];return {amount:i.amount,link:i.links['past:synthetic-oct'],date:i.parts.find(p=>p.historicalPayment).date,count:data.entries.length};''')
  self.assertEqual(r,{'amount':36863,'link':'synthetic-oct','date':'2026-10-10','count':1})
 def test_future_plan_stamp_is_advanced_and_old_merge_retains_new_part(self):
  r=self.evaluate('''state.installments[0].updated_at='2099-01-01T00:00:00.000Z';const old=clone(state);openPast();await v127ApplyPastPayment();const stamp=state.installments[0].updated_at,merged=mergeStates(old,state);return {advanced:stamp>'2099-01-01T00:00:00.000Z',parts:merged.installments[0].parts.length,amount:merged.installments[0].amount};''')
  self.assertEqual(r,{'advanced':True,'parts':8,'amount':36863})
 def test_undo_preserves_expense_and_future_parts(self):
  r=self.evaluate('''openPast();await v127ApplyPastPayment();await v127RemovePastPayment(state.installments[0].id,'past:synthetic-oct');const i=state.installments[0];return {amount:i.amount,remaining:planRemaining(),parts:i.parts.length,links:i.links,entryUnchanged:cloudJSONEqual(state.entries[0],originalExpense),futureUnchanged:cloudJSONEqual(i.parts,originalFuture),count:state.entries.length,entryAvailable:v127PastEntryAllowed(state.entries[0])};''')
  self.assertEqual(r,{'amount':32255,'remaining':32255,'parts':7,'links':{},'entryUnchanged':True,'futureUnchanged':True,'count':1,'entryAvailable':True})
 def test_repeated_undo_is_noop(self):
  r=self.evaluate('''openPast();await v127ApplyPastPayment();const id=state.installments[0].id;await v127RemovePastPayment(id,'past:synthetic-oct');const before=clone(state);await v127RemovePastPayment(id,'past:synthetic-oct');return cloudJSONEqual(before,state);''')
  self.assertTrue(r)
 def test_ordinary_part_cannot_be_removed(self):
  r=self.evaluate('''const before=clone(state),i=state.installments[0];await v127RemovePastPayment(i.id,i.parts[0].id);return cloudJSONEqual(before,state);''')
  self.assertTrue(r)
 def test_reader_cannot_remove_historical_part(self):
  r=self.evaluate('''openPast();await v127ApplyPastPayment();const before=clone(state);window.__FINANCE_BRIDGE__={active:true,role:'viewer'};await v127RemovePastPayment(state.installments[0].id,'past:synthetic-oct');return cloudJSONEqual(before,state);''')
  self.assertTrue(r)
 def test_add_undo_readd_once(self):
  r=self.evaluate('''openPast();await v127ApplyPastPayment();await v127RemovePastPayment(state.installments[0].id,'past:synthetic-oct');openPast();await v127ApplyPastPayment();const i=state.installments[0];return {parts:i.parts.length,amount:i.amount,remaining:planRemaining(),count:state.entries.length,paid:i.parts.filter(p=>p.historicalPayment).map(p=>installmentAllocated(i,p))};''')
  self.assertEqual(r,{'parts':8,'amount':36863,'remaining':32255,'count':1,'paid':[4608]})
 def test_cleanup_deleted_entry_historical_part(self):
  r=self.evaluate('''openPast();await v127ApplyPastPayment();state.entries=[];await v127RemovePastPayment(state.installments[0].id,'past:synthetic-oct');return {parts:state.installments[0].parts.length,amount:state.installments[0].amount,remaining:planRemaining(),links:state.installments[0].links};''')
  self.assertEqual(r,{'parts':7,'amount':32255,'remaining':32255,'links':{}})
 def test_orphan_historical_payment_cannot_create_new_expense(self):
  r=self.evaluate('''openPast();await v127ApplyPastPayment();state.entries=[];renderInstallments();window.prompt=()=>{throw new Error('Unexpected spending prompt')};const i=state.installments[0],part=i.parts.find(p=>p.historicalPayment),row=document.querySelector('.v77-part');await v77PayPart(i.id,part.id);return {count:state.entries.length,noPay:!row.querySelector('[data-v77-pay]'),cleanup:!!row.querySelector('[data-v127-unlink]')};''')
  self.assertEqual(r,{'count':0,'noPay':True,'cleanup':True})
 def test_undo_survives_merge_with_older_linked_backup(self):
  r=self.evaluate('''openPast();await v127ApplyPastPayment();const linked=clone(state);await v127RemovePastPayment(state.installments[0].id,'past:synthetic-oct');const clean=clone(state);return [[linked,clean],[clean,linked]].map(sources=>{state=mergeStates(...sources);return {parts:state.installments[0].parts.length,amount:state.installments[0].amount,links:state.installments[0].links,available:v127PastEntryAllowed(state.entries[0])}});''')
  self.assertEqual(r,[{'parts':7,'amount':32255,'links':{},'available':True}]*2)
 def test_undo_recovery_preserves_ordinary_link_union(self):
  r=self.evaluate('''openPast();await v127ApplyPastPayment();const linked=clone(state),futureId=linked.installments[0].parts.find(p=>!p.historicalPayment).id;linked.installments[0].links[futureId]='synthetic-other';linked.installments[0].links['ordinary-reference']='synthetic-legacy';await v127RemovePastPayment(state.installments[0].id,'past:synthetic-oct');const clean=clone(state);return [[linked,clean],[clean,linked]].map(sources=>{state=mergeStates(...sources);return {futureLink:state.installments[0].links[futureId],legacyLink:state.installments[0].links['ordinary-reference'],pastLink:state.installments[0].links['past:synthetic-oct']||null,parts:state.installments[0].parts.length}});''')
  self.assertEqual(r,[{'futureLink':'synthetic-other','legacyLink':'synthetic-legacy','pastLink':None,'parts':7}]*2)
 def test_document_plan_import_does_not_replace_extended_schedule(self):
  r=self.evaluate('''openPast();await v127ApplyPastPayment();const before=clone(state.installments[0]);session={access_token:'synthetic-offline-token'};v126MarkDocumentPlansReady(authEpoch,CONFIG.household);const imported=v126ApplyDocumentPlans({persist:false});session=null;return {count:state.installments.length,unchanged:cloudJSONEqual(before,state.installments[0]),added:imported.added,remaining:planRemaining()};''')
  self.assertEqual(r,{'count':1,'unchanged':True,'added':[],'remaining':32255})

if __name__=='__main__':
 print('SOURCE SHA256',hashlib.sha256(HTML.encode()).hexdigest(),flush=True)
 unittest.main(verbosity=2)
