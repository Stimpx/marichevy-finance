"""Documented Split schedule: fictional local state and stubbed cloud I/O only."""
import argparse
from pathlib import Path
import unittest

import test_local_data_safety as harness


class SplitDocuments(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.LocalDataSafety.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        harness.LocalDataSafety.tearDownClass.__func__(cls)

    setUp = harness.LocalDataSafety.setUp
    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open

    @staticmethod
    def setup_js(reset=True):
        return """
          session=null;stopCloudSync();
        """+("localStorage.clear();state=blankState();" if reset else "")+"""
          today=()=> '2026-11-02';month=()=> '2026-11';
          window.__FINANCE_BRIDGE__=undefined;
          window.__saveCalls=0;window.__readCalls=0;window.__casCalls=0;window.__casBodies=[];
          saveAll=async()=>{__saveCalls++;v89StorageFailed=false;return true};
          showApp();session={access_token:'fictional-token-only',user:{id:'fictional-user'}};
          window.__source=JSON.parse(JSON.stringify(FAMILY_DOCUMENT_PLANS[0]));
          window.__copy=()=>JSON.parse(JSON.stringify(__source));
          window.__ready=async(remoteOverride=null)=>{
            let cloud=JSON.parse(JSON.stringify(remoteOverride||state));let revision=1;
            fetchCloudState=async()=>{__readCalls++;cloudReadMeta={protocol:2,revision:1};return normalize(cloud)};
            ensureToken=async()=>true;
            api=async(path,options={})=>{
              if(path!=='/rest/v1/rpc/family_state_cas')throw Error('Unexpected synthetic API path');
              const body=JSON.parse(options.body);__casCalls++;__casBodies.push(body);
              cloud=JSON.parse(JSON.stringify(body.p_data));revision++;
              return {ok:true,json:async()=>({status:'written',protocol:2,revision,
                request_id:body.p_request_id,data:JSON.parse(JSON.stringify(cloud))})};
            };
            // A full, successful family read is required before automatic seed.
            await syncFromCloud();
          };
          window.__snapshot=()=>({plans:JSON.parse(JSON.stringify(state.installments)),
            entries:JSON.parse(JSON.stringify(state.entries)),saves:__saveCalls,
            retry:v126DocumentPlanRetry,ambiguous:v126DocumentPlanAmbiguous});
        """

    def evaluate(self, code):
        self.open()
        return self.page.evaluate('async()=>{'+self.setup_js()+code+'\n}')

    def test_new_plan_has_exact_documented_parts_and_preserves_expenses(self):
        result=self.evaluate("""
          state.entries=[{id:'fictional-existing',type:'expense',date:'2026-11-01',amount:17,
            category:'Прочее',who:'Учебный участник',store:'Fictional shop',extension:{keep:true}}];
          const before=JSON.stringify(state.entries);await __ready();
          await v126ApplyDocumentPlans();await Promise.resolve();
          const plan=state.installments[0];return {...__snapshot(),unchanged:before===JSON.stringify(state.entries),
            valid:validateBackup(state)===state,total:plan.parts.reduce((n,p)=>n+p.amount,0),
            paid:plan.parts.map(p=>installmentPaid(plan,p))};
        """)
        self.assertEqual(len(result['plans']),1)
        plan=result['plans'][0]
        self.assertEqual(plan['amount'],32255)
        self.assertEqual([p['amount'] for p in plan['parts']],[4608]*6+[4607])
        self.assertEqual([p['date'] for p in plan['parts']],['2026-11-10','2026-12-10','2027-01-10','2027-02-10','2027-03-10','2027-04-10','2027-05-10'])
        self.assertEqual(plan['links'],{})
        self.assertEqual(result['total'],32255)
        self.assertTrue(result['valid'])
        self.assertTrue(result['unchanged'])
        self.assertEqual(result['paid'],[False]*7)
        self.assertNotEqual(plan['amount'],200000)

    def test_second_call_does_not_duplicate_or_overwrite_edits(self):
        result=self.evaluate("""
          await __ready();await v126ApplyDocumentPlans();await Promise.resolve();
          state.installments[0].title='Своё название';state.installments[0].parts[0].amount=4600;
          const before=JSON.stringify(state.installments),saves=__saveCalls;
          for(let i=0;i<3;i++)await v126ApplyDocumentPlans();
          return {unchanged:before===JSON.stringify(state.installments),count:state.installments.length,
            extraSaves:__saveCalls-saves};
        """)
        self.assertEqual(result,{'unchanged':True,'count':1,'extraSaves':0})

    def test_actual_reload_keeps_one_plan_and_original_timestamps(self):
        before=self.evaluate("""
          await __ready();await v126ApplyDocumentPlans();await Promise.resolve();saveLocal();
          return JSON.stringify(state.installments);
        """)
        self.page.reload(wait_until='domcontentloaded')
        self.page.wait_for_function("typeof v126ApplyDocumentPlans==='function'")
        after=self.page.evaluate('async()=>{'+self.setup_js(reset=False)+"await __ready();await v126ApplyDocumentPlans();return JSON.stringify(state.installments)}")
        self.assertEqual(after,before)

    def test_existing_exact_timeline_with_other_id_is_not_duplicated(self):
        result=self.evaluate("""
          const plan=__copy();plan.id='existing-other-id';delete plan.source;
          plan.parts=plan.parts.map((p,i)=>({...p,id:'existing-part-'+i}));state.installments=[plan];
          const before=JSON.stringify(state.installments);await __ready();await v126ApplyDocumentPlans();
          return {unchanged:before===JSON.stringify(state.installments),count:state.installments.length};
        """)
        self.assertEqual(result,{'unchanged':True,'count':1})

    def test_existing_larger_plan_with_paid_past_part_is_not_duplicated(self):
        result=self.evaluate("""
          const plan=__copy();plan.id='existing-with-history';delete plan.source;
          plan.parts.unshift({id:'past-part',date:'2026-10-10',amount:4608});plan.amount+=4608;
          plan.links={'past-part':'past-payment'};state.installments=[plan];
          state.entries=[{id:'past-payment',type:'expense',date:'2026-10-10',amount:4608,category:'Кредит'}];
          state=normalize(state);const before=JSON.stringify(state);await __ready();await v126ApplyDocumentPlans();
          return {count:state.installments.length,upcoming:installmentUpcoming().length,
            unchanged:before===JSON.stringify(state)};
        """)
        self.assertEqual(result,{'count':1,'upcoming':7,'unchanged':True})

    def test_existing_source_fingerprint_preserves_changed_schedule(self):
        result=self.evaluate("""
          const plan=__copy();plan.id='existing-source-id';plan.parts[0].date='2026-11-11';
          state.installments=[plan];const before=JSON.stringify(state.installments);
          await __ready();await v126ApplyDocumentPlans();
          return {count:state.installments.length,unchanged:before===JSON.stringify(state.installments)};
        """)
        self.assertEqual(result,{'count':1,'unchanged':True})

    def test_deleted_plan_tombstone_prevents_resurrection(self):
        result=self.evaluate("""
          state.deletedInstallments[__source.id]='2026-11-02T10:00:00Z';await __ready();
          renderAll();await v126ApplyDocumentPlans();return {count:state.installments.length,saves:__saveCalls};
        """)
        self.assertEqual(result,{'count':0,'saves':0})

    def test_token_without_full_family_read_cannot_seed_blank_device(self):
        result=self.evaluate("""
          await v126ApplyDocumentPlans();return {count:state.installments.length,saves:__saveCalls};
        """)
        self.assertEqual(result,{'count':0,'saves':0})

    def test_anonymous_locked_and_viewer_contexts_cannot_add(self):
        for mode in ('anonymous','locked','viewer'):
            with self.subTest(mode=mode):
                result=self.evaluate("""
                  await __ready();state.installments=[];__saveCalls=0;
                """+{'anonymous':"session=null;",'locked':"document.getElementById('appRoot').classList.add('auth-locked');",'viewer':"window.__FINANCE_BRIDGE__={active:true,role:'viewer'};"}[mode]+"""
                  await v126ApplyDocumentPlans();return {count:state.installments.length,saves:__saveCalls};
                """)
                self.assertEqual(result,{'count':0,'saves':0})

    def test_partial_overlap_requires_review_and_keeps_existing_plan(self):
        result=self.evaluate("""
          const plan=__copy();plan.id='existing-partial';delete plan.source;plan.parts=plan.parts.slice(0,1);plan.amount=4608;
          state.installments=[plan];await __ready();await v126ApplyDocumentPlans();v126RenderDocumentPlanNotice();
          return {count:state.installments.length,id:state.installments[0].id,ambiguous:v126DocumentPlanAmbiguous.length,
            visible:!document.getElementById('v126DocumentPlanNotice').hidden};
        """)
        self.assertEqual(result,{'count':1,'id':'existing-partial','ambiguous':1,'visible':True})

    def test_unrelated_loan_with_same_dates_does_not_hide_split(self):
        result=self.evaluate("""
          const plan=__copy();plan.id='unrelated-loan';plan.kind='loan';plan.provider='Fictional unrelated lender';delete plan.source;
          state.installments=[plan];await __ready();await v126ApplyDocumentPlans();return state.installments.map(p=>p.id);
        """)
        self.assertEqual(len(result),2)
        self.assertIn('unrelated-loan',result)

    def test_november_obligations_add_exactly_one_4608_payment(self):
        result=self.evaluate("""
          const before=v78Obligations('2026-11').planned;await __ready();await v126ApplyDocumentPlans();
          const after=v78Obligations('2026-11');return {difference:Math.round((after.planned-before)*100)/100,
            groupCount:after.groups.length,first:installmentUpcoming()[0]};
        """)
        self.assertEqual(result['difference'],4608)
        self.assertEqual(result['groupCount'],1)
        self.assertEqual(result['first']['date'],'2026-11-10')
        self.assertEqual(result['first']['amount'],4608)

    def test_failed_save_retry_keeps_one_plan_and_no_fake_cash(self):
        result=self.evaluate("""
          saveAll=async()=>{__saveCalls++;v89StorageFailed=true;return false};
          v126MarkDocumentPlansReady(authEpoch,CONFIG.household);await v126ApplyDocumentPlans();await Promise.resolve();
          const first=__snapshot();saveAll=async()=>{__saveCalls++;v89StorageFailed=false;return true};
          await v126PersistDocumentPlans();await v126ApplyDocumentPlans();await Promise.resolve();
          return {first,after:__snapshot(),cash:sum(expenses())};
        """)
        self.assertEqual(len(result['first']['plans']),1)
        self.assertTrue(result['first']['retry'])
        self.assertEqual(len(result['after']['plans']),1)
        self.assertFalse(result['after']['retry'])
        self.assertEqual(result['after']['entries'],[])
        self.assertEqual(result['cash'],0)

    def test_initial_full_cloud_read_deduplicates_legacy_remote_id_before_any_cas(self):
        result=self.evaluate("""
          const plan=__copy();plan.id='remote-existing-other-id';delete plan.source;
          const remote=blankState();remote.installments=[plan];await __ready(remote);
          return {count:state.installments.length,id:state.installments[0].id,
            reads:__readCalls,cas:__casCalls,entries:state.entries.length};
        """)
        self.assertEqual(result['count'],1)
        self.assertEqual(result['id'],'remote-existing-other-id')
        self.assertGreaterEqual(result['reads'],1)
        self.assertEqual(result['cas'],0)
        self.assertEqual(result['entries'],0)

    def test_empty_full_cloud_read_adds_one_plan_through_normal_cas(self):
        result=self.evaluate("""
          await __ready();return {count:state.installments.length,cas:__casCalls,
            savedPlans:__casBodies[0]?.p_data.installments.length,
            savedEntries:__casBodies[0]?.p_data.entries,valid:validateBackup(state)===state};
        """)
        self.assertEqual(result,{'count':1,'cas':1,'savedPlans':1,'savedEntries':[],'valid':True})

    def test_two_independent_devices_merge_as_one_deterministic_plan(self):
        result=self.evaluate("""
          await __ready();await v126ApplyDocumentPlans({persist:false});
          const first=JSON.parse(JSON.stringify(state));state=blankState();
          await v126ApplyDocumentPlans({persist:false});const second=JSON.parse(JSON.stringify(state));
          const merged=mergeStates(first,second);
          return {first:first.installments[0].id,second:second.installments[0].id,
            merged:merged.installments.length,entries:merged.entries.length};
        """)
        self.assertEqual(result['first'],result['second'])
        self.assertEqual(result['merged'],1)
        self.assertEqual(result['entries'],0)


if __name__=='__main__':
    p=argparse.ArgumentParser(add_help=False);p.add_argument('--html',type=Path)
    args,rest=p.parse_known_args()
    if args.html:harness.HTML=args.html.resolve()
    unittest.main(argv=[__file__,*rest])
