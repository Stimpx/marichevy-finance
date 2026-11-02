"""Mortgage allocation forms: synthetic local expenses and blocked external I/O."""
import argparse
from pathlib import Path
import unittest
import test_local_data_safety as harness


class MortgageForms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):harness.LocalDataSafety.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):harness.LocalDataSafety.tearDownClass.__func__(cls)
    setUp=harness.LocalDataSafety.setUp
    tearDown=harness.LocalDataSafety.tearDown
    open=harness.LocalDataSafety.open

    def evaluate(self,code):
        self.open()
        return self.page.evaluate("""async () => {
          session=null;state=blankState();localStorage.clear();today=()=> '2026-11-02';month=()=> '2026-11';
          showApp();go('loans');
          window.__expense=(id,amount=10000)=>({id,type:'expense',date:'2026-11-02',amount,
            category:'Кредит',who:'Вымышленный участник',store:'Fictional mortgage payment',
            updated_at:'2026-11-02T00:00:00Z'});
          window.__openExtra=(id,included)=>{
            v125OpenMortgagePayment(id);v125MortgageKind.value='early';v125MortgageFill();
            v125MortgageBankIncluded.checked=included;v125MortgageChecked.checked=true;
          };
          window.__bank=async(balance,end='2040-07-31')=>{
            v125OpenMortgageBank();v125BankDate.value='2026-11-02';v125BankBalance.value=String(balance);
            v125BankEnd.value=end;v125BankChecked.checked=true;return v125SaveMortgageBank();
          };
        """+code+"\n}")

    def test_included_payment_extra_and_unlink_do_not_duplicate_expenses(self):
        result=self.evaluate("""
          const initial=v125MortgageProgress().balance;
          state.entries=[__expense('already-in-bank',40000),__expense('additional',10000)];
          __openExtra('already-in-bank',true);await v125SaveMortgagePayment();
          const included=v125MortgageProgress().balance;
          __openExtra('additional',false);await v125SaveMortgagePayment();
          const extra=v125MortgageProgress().balance;
          await v125UnlinkMortgage('additional');
          return {initial,included,extra,removed:v125MortgageProgress().balance,
            count:state.entries.length,cash:sum(expenses())};
        """)
        self.assertEqual(result['included'],result['initial'])
        self.assertAlmostEqual(result['extra'],result['initial']-10000,places=2)
        self.assertEqual(result['removed'],result['initial'])
        self.assertEqual((result['count'],result['cash']),(2,50000))

    def test_new_bank_checkpoint_then_resaving_same_payment_never_subtracts_it_twice(self):
        result=self.evaluate("""
          state.entries=[__expense('additional')];__openExtra('additional',false);
          await v125SaveMortgagePayment();const actual=v125MortgageProgress().balance;
          await __bank(actual);const afterBank=v125MortgageProgress().balance;
          v125OpenMortgagePayment('additional');const defaultIncluded=v125MortgageBankIncluded.checked;
          v125MortgageChecked.checked=true;await v125SaveMortgagePayment();
          return {actual,afterBank,defaultIncluded,afterResave:v125MortgageProgress().balance};
        """)
        self.assertEqual(result['afterBank'],result['actual'])
        self.assertTrue(result['defaultIncluded'])
        self.assertEqual(result['afterResave'],result['actual'])

    def test_authentication_context_change_rejects_open_payment_form(self):
        result=self.evaluate("""
          state.entries=[__expense('additional')];__openExtra('additional',false);
          const before=JSON.stringify(state);authEpoch++;
          return {saved:await v125SaveMortgagePayment(),unchanged:before===JSON.stringify(state)};
        """)
        self.assertEqual(result,{'saved':False,'unchanged':True})

    def test_viewer_cannot_write_bank_or_allocation_or_unlink(self):
        result=self.evaluate("""
          state.entries=[__expense('additional')];__openExtra('additional',false);
          await v125SaveMortgagePayment();v125OpenMortgagePayment('additional');v125OpenMortgageBank();
          window.__FINANCE_BRIDGE__={active:true,role:'viewer'};renderLoans();const before=JSON.stringify(state);
          const attempts=[await v125SaveMortgagePayment(),await v125SaveMortgageBank(),await v125UnlinkMortgage('additional')];
          return {attempts,unchanged:before===JSON.stringify(state)};
        """)
        self.assertEqual(result,{'attempts':[False,False,False],'unchanged':True})

    def test_same_day_checkpoint_versions_are_unique_and_backup_preserves_inclusion(self):
        result=self.evaluate("""
          state.entries=[__expense('additional')];__openExtra('additional',false);
          await v125SaveMortgagePayment();const actual=v125MortgageProgress().balance;
          await __bank(actual);const first=v125SnapshotKey(v125MortgageSnapshot());
          await __bank(actual);const second=v125SnapshotKey(v125MortgageSnapshot());
          const original=JSON.stringify(state),copy=JSON.parse(original);validateBackup(copy);state=normalize(copy);
          return {unique:first!==second,balance:v125MortgageProgress().balance,actual,
            states:!!state.settings.loans.mortgageSnapshot.includedEntryStates.additional,
            allocations:!!state.entries[0].mortgageAllocation};
        """)
        self.assertTrue(result['unique'])
        self.assertEqual(result['balance'],result['actual'])
        self.assertTrue(result['states'])
        self.assertTrue(result['allocations'])

    def test_concurrent_settings_change_rejects_bank_form_without_overwriting_it(self):
        result=self.evaluate("""
          v125OpenMortgageBank();v125BankDate.value='2026-11-02';v125BankBalance.value='4448197.19';
          v125BankEnd.value='2040-07-31';v125BankChecked.checked=true;
          state.settings.updated_at=v119MonotonicStamp(state.settings.updated_at);
          const before=JSON.stringify(state);return {saved:await v125SaveMortgageBank(),
            unchanged:before===JSON.stringify(state),message:v125MortgageMessage.textContent};
        """)
        self.assertFalse(result['saved'])
        self.assertTrue(result['unchanged'])
        self.assertIn('изменились',result['message'])

    def test_failed_local_storage_save_is_explicit_and_never_duplicates_cash_entry(self):
        result=self.evaluate("""
          state.entries=[__expense('additional')];__openExtra('additional',false);
          const original=Storage.prototype.setItem;
          Storage.prototype.setItem=function(k,v){if(k==='marichevy_state_v10'||k==='marichevy_pending_v10')
            throw new DOMException('Synthetic quota failure','QuotaExceededError');return original.call(this,k,v)};
          const saved=await v125SaveMortgagePayment();
          return {saved,failed:v89StorageFailed,message:v125MortgageMessage.textContent,
            messageVisible:!v125MortgageMessage.hidden,count:state.entries.length,cash:sum(expenses())};
        """)
        self.assertFalse(result['saved'])
        self.assertTrue(result['failed'])
        self.assertTrue(result['messageVisible'])
        self.assertIn('памяти',result['message'])
        self.assertEqual((result['count'],result['cash']),(1,10000))


if __name__=='__main__':
    parser=argparse.ArgumentParser(add_help=False);parser.add_argument('--html',type=Path)
    args,remaining=parser.parse_known_args()
    if args.html:harness.HTML=args.html.resolve()
    unittest.main(argv=[__file__,*remaining])
