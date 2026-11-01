"""Everyday entry, split receipts and reviewed CSV; fictional data, all remote I/O blocked."""
import json
import unittest

import test_local_data_safety as harness


class HumanOperations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.LocalDataSafety.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        harness.LocalDataSafety.tearDownClass.__func__(cls)

    setUp = harness.LocalDataSafety.setUp
    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open
    snapshot = harness.LocalDataSafety.snapshot

    def prepare(self):
        self.open()
        self.page.evaluate("""() => {
          stopCloudSync();session=null;localStorage.clear();state=blankState();
          localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=undefined;
          const d=today(),stamp=new Date().toISOString();
          const account=(id,name,balance,kind='asset')=>({id,name,amount:balance,
            snapshotDate:d,created_at:stamp,updated_at:stamp,
            ledger:{version:1,enabled:true,startDate:d,openingBalance:balance,kind,includeInSpending:true}});
          state.intelligence.accounts=[account('bank','Учебная карта',1000),account('cash','Учебные наличные',100),account('debt','Учебный долг',0,'debt')];
          state.entries=[{id:'legacy',type:'expense',date:d,amount:17.251,category:'Прочее',
            who:'Вымышленный человек',store:'Старая запись',comment:'Сохранить',
            foreign:{raw:'unknown-field',list:[1,2]},created_at:stamp,updated_at:stamp}];
          window.legacySnapshot=JSON.stringify(state.entries[0]);
          telegramNotify=async()=>false;showApp();renderAll();go('today');clearEntry(true);
          window.actualSaveAll=saveAll;window.operationSaves=0;
          saveAll=async(...args)=>{window.operationSaves++;return await window.actualSaveAll(...args)};
        }""")

    def draft(self, amount='12,50', kind='expense', account='bank'):
        self.page.evaluate("""([amount,kind,account])=>{
          document.getElementById('eType').value=kind;updateEntryForm();
          document.getElementById('eAmount').value=amount;
          document.getElementById('eDate').value=today();
          document.getElementById('eCategory').value='Прочее';
          document.getElementById('eStore').value='Учебный магазин';
          document.getElementById('eComment').value='Тест';
          document.getElementById('eAccountId').value=account;
        }""", [amount, kind, account])

    def csv(self, text):
        self.page.evaluate("text=>{v119SetCSV(text,'fiction.csv');document.getElementById('v119CSVDefaultAccount').value='bank';v119CSVPreview()}", text)

    def assert_legacy(self):
        self.assertTrue(self.page.evaluate("JSON.stringify(state.entries.find(e=>e.id==='legacy'))===window.legacySnapshot"))

    def test_explicit_account_save_and_own_transfer_keep_correct_totals(self):
        self.prepare()
        self.draft()
        self.page.locator('#v90Save').click()
        self.page.wait_for_function('!v90Saving')
        self.assertEqual(self.page.evaluate('state.entries.length'), 2)
        self.assertEqual(self.page.evaluate('state.entries[1].accountId'), 'bank')
        self.assertEqual(self.page.evaluate("v117AccountBalance('bank').balance"), 987.5)
        self.assertEqual(self.page.evaluate('operationSaves'), 1)
        self.assertEqual(self.page.evaluate('v119DefaultAccount()'), 'bank')
        self.draft('50', 'transfer', '')
        self.page.evaluate("document.getElementById('eFromAccountId').value='bank';document.getElementById('eToAccountId').value='cash'")
        self.page.evaluate('addEntry()')
        self.assertEqual(self.page.evaluate("v117AccountBalance('bank').balance"), 937.5)
        self.assertEqual(self.page.evaluate("v117AccountBalance('cash').balance"), 150)
        self.assertEqual(self.page.evaluate("state.entries.filter(e=>e.type==='expense').length"), 2)
        self.assert_legacy()

    def test_new_invalid_account_and_disabled_account_do_not_write(self):
        self.prepare(); self.draft()
        self.page.evaluate("state.intelligence.accounts[0].ledger.enabled=false")
        before=self.page.evaluate('JSON.stringify(state)')
        self.page.evaluate('addEntry()')
        self.assertEqual(self.page.evaluate('JSON.stringify(state)'), before)
        self.assertEqual(self.page.evaluate('operationSaves'), 0)
        self.assertTrue(self.page.locator('#eAccountError').is_visible())

    def test_comment_edit_preserves_historical_unknown_account_and_blocks_stale_editor(self):
        self.prepare()
        self.page.evaluate("state.entries[0].accountId='retired-account';openEdit('legacy');document.getElementById('xComment').value='Новый комментарий'")
        self.page.evaluate('saveEdit()')
        self.assertEqual(self.page.evaluate('state.entries[0].accountId'), 'retired-account')
        self.assertEqual(self.page.evaluate('state.entries[0].foreign.raw'), 'unknown-field')
        self.assertEqual(self.page.evaluate('state.entries[0].comment'), 'Новый комментарий')
        self.assertEqual(self.page.evaluate('state.entries[0].amount'), 17.251)
        self.assertFalse(self.page.evaluate("Object.hasOwn(state.entries[0],'beneficiary')"))
        self.page.evaluate("openEdit('legacy');document.getElementById('xComment').value='Устаревший черновик';state.entries[0]={...state.entries[0],amount:99,comment:'Другой участник',updated_at:v117RecordStamp(state.entries[0])}")
        before=self.page.evaluate('JSON.stringify(state)'); saves=self.page.evaluate('operationSaves')
        self.page.evaluate('saveEdit()')
        self.assertEqual(self.page.evaluate('JSON.stringify(state)'), before)
        self.assertEqual(self.page.evaluate('operationSaves'), saves)
        self.assertEqual(self.page.locator('#xComment').input_value(), 'Устаревший черновик')
        self.assertTrue(self.page.locator('#v119EditConflict').is_visible())

    def test_adjustment_account_and_scope_change_are_guarded(self):
        self.prepare()
        self.page.evaluate("""()=>{state.entries.push({id:'adjust',type:'transfer',balanceAdjustment:true,accountId:'bank',adjustmentDirection:1,amount:5,date:today(),category:'Корректировка',comment:'',created_at:v117RecordStamp(),updated_at:v117RecordStamp()});openEdit('adjust');document.getElementById('xAccountId').value='cash'}""")
        before=self.page.evaluate('JSON.stringify(state)')
        self.page.evaluate('saveEdit()')
        self.assertEqual(self.page.evaluate('JSON.stringify(state)'), before)
        self.page.evaluate("openEdit('legacy');document.getElementById('xComment').value='Wrong scope';authEpoch++")
        before=self.page.evaluate('JSON.stringify(state)')
        self.page.evaluate('saveEdit()')
        self.assertEqual(self.page.evaluate('JSON.stringify(state)'), before)

    def test_split_exact_cents_without_parent_and_no_write_on_mismatch(self):
        self.prepare(); self.draft('0,30')
        self.page.evaluate("v119StartSplit();const rows=document.querySelectorAll('#v119SplitRows .v119-split-amount');rows[0].value='0,10';rows[1].value='0,19'")
        before=self.page.evaluate('JSON.stringify(state)')
        self.page.evaluate('v119SaveSplit()')
        self.assertEqual(self.page.evaluate('JSON.stringify(state)'), before)
        self.page.evaluate("document.querySelectorAll('#v119SplitRows .v119-split-amount')[1].value='0,20';v119SaveSplit()")
        self.page.wait_for_function('!v119Busy')
        parts=self.page.evaluate("state.entries.filter(e=>e.splitGroupId)")
        self.assertEqual(len(parts), 2)
        self.assertEqual({e['splitGroupId'] for e in parts}, {parts[0]['splitGroupId']})
        self.assertEqual([e['amount'] for e in parts], [.1,.2])
        self.assertTrue(all(e['splitSourceTotal']==.3 and e['accountId']=='bank' for e in parts))
        self.assertEqual(self.page.evaluate('state.entries.length'), 3)
        self.assertEqual(self.page.evaluate('operationSaves'), 1)
        self.assert_legacy()

    def test_split_prevents_whole_receipt_save_and_preserves_new_draft_during_commit(self):
        self.prepare(); self.draft('3')
        self.page.evaluate("v119StartSplit();const rows=document.querySelectorAll('#v119SplitRows .v119-split-amount');rows[0].value='1';rows[1].value='2';addEntry()")
        self.assertEqual(self.page.evaluate('state.entries.length'),1)
        self.page.evaluate("""()=>{saveAll=()=>new Promise(resolve=>window.finishReceipt=resolve);v119SaveSplit();document.getElementById('eAmount').value='77';document.getElementById('eComment').value='Следующий черновик';addEntry()}""")
        self.assertEqual(self.page.evaluate('state.entries.length'),3)
        self.page.evaluate('v89StorageFailed=false;finishReceipt(false)')
        self.page.wait_for_function('!v119Busy')
        self.assertEqual(self.page.locator('#eAmount').input_value(),'77')
        self.assertEqual(self.page.locator('#eComment').input_value(),'Следующий черновик')
        self.assertTrue(self.page.evaluate('v119Split===null'))

    def test_split_retry_after_local_failure_never_adds_duplicates(self):
        self.prepare(); self.draft('3')
        self.page.evaluate("""()=>{v119StartSplit();const rows=document.querySelectorAll('#v119SplitRows .v119-split-amount');rows[0].value='1';rows[1].value='2';saveAll=async()=>{operationSaves++;v89StorageFailed=true;return false}}""")
        self.page.evaluate('v119SaveSplit()')
        self.assertEqual(self.page.evaluate('state.entries.length'), 3)
        self.page.evaluate('v119SaveSplit()')
        self.assertEqual(self.page.evaluate('state.entries.length'), 3)
        self.page.evaluate('saveAll=async()=>{operationSaves++;v89StorageFailed=false;return false};v119SaveSplit()')
        self.assertEqual(self.page.evaluate('state.entries.length'), 3)
        self.assertTrue(self.page.evaluate('v119Split===null'))

    def test_split_undo_is_atomic_and_changed_part_blocks_whole_undo(self):
        self.prepare(); self.draft('3')
        self.page.evaluate("v119StartSplit();const rows=document.querySelectorAll('#v119SplitRows .v119-split-amount');rows[0].value='1';rows[1].value='2';v119SaveSplit()")
        ids=self.page.evaluate('v119Undo.records.map(e=>e.id)')
        self.page.evaluate('v119UndoDelete()')
        self.assertEqual(self.page.evaluate('state.entries.length'),1)
        self.assertTrue(self.page.evaluate('ids=>ids.every(id=>!!state.deletedEntries[id])',ids))
        self.assert_legacy()
        self.draft('3')
        self.page.evaluate("v119StartSplit();const rows=document.querySelectorAll('#v119SplitRows .v119-split-amount');rows[0].value='1';rows[1].value='2';v119SaveSplit()")
        self.page.evaluate("state.entries.find(e=>e.splitPart===2).comment='Другой участник изменил часть'")
        before=self.page.evaluate('JSON.stringify(state)')
        self.page.evaluate('v119UndoDelete()')
        self.assertEqual(self.page.evaluate('JSON.stringify(state)'),before)

    def test_pending_batch_blocks_second_save_and_undo_retries_without_second_restore(self):
        self.prepare(); self.draft('3')
        self.page.evaluate("""()=>{v119StartSplit();const rows=document.querySelectorAll('#v119SplitRows .v119-split-amount');rows[0].value='1';rows[1].value='2';saveAll=()=>{operationSaves++;return new Promise(resolve=>window.finishBatch=resolve)};v119SaveSplit();v119SaveSplit()}""")
        self.assertEqual(self.page.evaluate('state.entries.length'),3)
        self.assertEqual(self.page.evaluate('operationSaves'),1)
        self.page.evaluate('v89StorageFailed=false;finishBatch(false)')
        self.page.wait_for_function('!v119Busy')
        self.page.evaluate('saveAll=actualSaveAll;deleteEntry("legacy")')
        self.page.evaluate('saveAll=async()=>{v89StorageFailed=true;return false};v119UndoDelete()')
        self.assertEqual(self.page.evaluate("state.entries.filter(e=>e.id==='legacy').length"),1)
        self.page.evaluate('saveAll=async()=>{v89StorageFailed=false;return false};v119UndoDelete()')
        self.assertEqual(self.page.evaluate("state.entries.filter(e=>e.id==='legacy').length"),1)
        self.assertTrue(self.page.evaluate('v119Undo===null'))

    def test_single_entry_failed_retry_keeps_same_id_and_changed_draft(self):
        self.prepare(); self.draft('5')
        self.page.evaluate('saveAll=async()=>{operationSaves++;v89StorageFailed=true;return false};addEntry()')
        identifier=self.page.evaluate('state.entries[1].id')
        self.page.evaluate('addEntry()')
        self.assertEqual(self.page.evaluate('state.entries.length'), 2)
        self.page.evaluate("document.getElementById('eAmount').value='6';document.getElementById('eAccountId').value='cash';addEntry()")
        self.assertEqual(self.page.evaluate('state.entries.length'), 2)
        self.assertEqual(self.page.evaluate('v119DefaultAccount()'), 'bank')
        self.page.evaluate('saveAll=async()=>{v89StorageFailed=false;return false};v119RetryEntry()')
        self.assertEqual(self.page.evaluate('state.entries[1].id'), identifier)
        self.assertEqual(self.page.locator('#eAmount').input_value(), '6')
        self.assertFalse(self.page.locator('#v119EntryRetry').is_visible())

    def test_failed_whole_entry_cannot_be_saved_again_as_split_parts(self):
        self.prepare(); self.draft('3')
        self.page.evaluate('saveAll=async()=>{v89StorageFailed=true;return false};addEntry()')
        self.page.evaluate('v119StartSplit()')
        self.assertTrue(self.page.evaluate('v119Split===null'))
        self.assertEqual(self.page.evaluate('state.entries.length'),2)
        self.assertEqual(self.page.evaluate("sum(state.entries.filter(e=>e.id!=='legacy'))"),3)
        self.assertIn('уже добавлена',self.page.locator('#v119ToolsStatus').text_content())

    def test_csv_quoted_russian_money_preview_then_explicit_confirm(self):
        self.prepare()
        text='Дата;Сумма;Описание\r\n01.11.2026;"-1 234,50 ₽";"Магазин; с \"\"кавычками\"\"\nвторая строка"\r\n2026-11-01;+20,10;"=HYPERLINK(""example"")"'
        self.csv(text)
        self.assertEqual(self.page.evaluate('state.entries.length'), 1)
        self.assertEqual(self.page.evaluate('v119CSV.preview[0].draft.amount'), 1234.5)
        self.assertIn('Магазин; с "кавычками"\nвторая строка',self.page.evaluate('v119CSV.preview[0].draft.store'))
        self.assertEqual(self.page.locator('#v119CSVRows script').count(), 0)
        self.page.evaluate('v119SaveCSV()')
        self.assertEqual(self.page.evaluate('state.entries.length'), 3)
        self.assertEqual(self.page.evaluate('operationSaves'), 1)
        self.assertEqual(self.page.evaluate('state.entries[2].type'), 'income')
        self.assertEqual(self.page.evaluate('state.entries[2].store'), '=HYPERLINK("example")')
        self.assert_legacy()

    def test_csv_rejects_ambiguous_dates_subcents_zero_and_invalid_quotes(self):
        self.prepare()
        self.csv('Дата;Сумма;Описание\n01/02/2026;-2;A\n01.11.2026;-0,001;B\n01.11.2026;0;C\n01.11.2026;-2,01;D')
        self.assertEqual(self.page.evaluate('v119CSV.preview.map(x=>!!x.error)'), [True,True,True,False])
        self.page.evaluate('v119SaveCSV()')
        self.assertEqual(self.page.evaluate('state.entries.length'), 2)
        self.assertEqual(self.page.evaluate('state.entries[1].amount'), 2.01)
        self.assertTrue(self.page.evaluate("(()=>{try{v119ParseCSV('a;b\\n\"bad;b');return false}catch(e){return true}})()"))

    def test_csv_duplicate_candidates_repeat_import_and_late_duplicate(self):
        self.prepare(); text='Дата;Сумма;Описание\n01.11.2026;-3,10;Учебный магазин'
        self.csv(text); self.page.evaluate('v119SaveCSV()'); self.csv(text)
        self.assertTrue(self.page.evaluate('v119CSV.preview[0].duplicate'))
        self.assertFalse(self.page.evaluate('v119CSV.preview[0].selected'))
        self.page.evaluate('v119CSV.preview[0].selected=true;v119SaveCSV()')
        self.assertEqual(self.page.evaluate('state.entries.length'), 2)
        self.page.evaluate("v119CSV.preview[0].selected=true;document.getElementById('v119CSVDuplicates').checked=true;v119SaveCSV()")
        self.assertEqual(self.page.evaluate('state.entries.length'), 3)
        self.csv('Дата;Сумма;Описание\n01.11.2026;-4;Поздний дубль')
        self.page.evaluate("state.entries.push({id:'late',...v119CSV.preview[0].draft});v119SaveCSV()")
        self.assertEqual(self.page.evaluate('state.entries.length'), 4)
        self.assertFalse(self.page.evaluate('v119CSV.preview[0].selected'))

    def test_csv_ambiguous_transfer_and_debt_need_review_without_double_expense(self):
        self.prepare(); self.csv('Дата;Сумма;Описание\n01.11.2026;-25;Перевод между своими счетами\n01.11.2026;-15;Погашение покупки')
        self.assertEqual(self.page.evaluate('v119CSV.preview.map(x=>x.selected)'), [False,False])
        self.page.evaluate("v119CSV.preview[0].selected=true;v119SaveCSV()")
        self.assertEqual(self.page.evaluate('state.entries.length'),1)
        self.page.evaluate("""()=>{const [a,b]=v119CSV.preview;a.draft={...a.draft,type:'transfer',fromAccountId:'bank',toAccountId:'cash'};a.reviewed=true;b.selected=true;b.reviewed=true;b.draft={...b.draft,type:'transfer',debtRepayment:true,fromAccountId:'bank',toAccountId:'debt'};v119SaveCSV()}""")
        self.assertEqual(self.page.evaluate('state.entries.length'),3)
        self.assertEqual(self.page.evaluate("state.entries.filter(e=>e.type==='expense').length"),1)
        self.assertEqual(self.page.evaluate("v117AccountBalance('bank').balance"),960)
        self.assertEqual(self.page.evaluate("v117AccountBalance('cash').balance"),125)
        self.assertEqual(self.page.evaluate("v117AccountBalance('debt').balance"),15)

    def test_csv_manual_transfer_type_requires_visible_review_confirmation(self):
        self.prepare(); self.csv('Дата;Сумма;Описание\n01.11.2026;-2;Обычная строка')
        self.page.evaluate("document.getElementById('v119OperationTools').open=true")
        self.page.locator('#v119CSVRows select[data-field="type"]').select_option('transfer',force=True)
        self.assertTrue(self.page.evaluate('v119CSV.preview[0].needsReview'))
        self.assertEqual(self.page.locator('#v119CSVRows .v119-reviewed').count(),1)
        self.page.evaluate("v119CSV.preview[0].draft.fromAccountId='bank';v119CSV.preview[0].draft.toAccountId='cash';v119SaveCSV()")
        self.assertEqual(self.page.evaluate('state.entries.length'),1)
        self.page.locator('#v119CSVRows .v119-reviewed').check(force=True)
        self.page.evaluate('v119SaveCSV()')
        self.assertEqual(self.page.evaluate('state.entries.length'),2)

    def test_stage_role_and_household_changes_block_commit(self):
        self.prepare(); self.csv('Дата;Сумма;Описание\n01.11.2026;-4;Учебная операция')
        before=self.page.evaluate('JSON.stringify(state)')
        self.page.evaluate("window.__FINANCE_BRIDGE__={active:true,role:'viewer'};v119SaveCSV()")
        self.assertEqual(self.page.evaluate('JSON.stringify(state)'), before)
        self.page.evaluate("window.__FINANCE_BRIDGE__=undefined;authEpoch++;v119SaveCSV()")
        self.assertEqual(self.page.evaluate('JSON.stringify(state)'), before)
        self.assertEqual(self.page.evaluate('operationSaves'),0)

    def test_real_utf8_csv_file_read_is_preview_only_and_html_is_inert(self):
        self.prepare()
        self.page.evaluate("document.getElementById('v119OperationTools').open=true")
        text='Дата;Сумма;Описание\n01.11.2026;-0,01;"<img src=x onerror=alert(1)>;товар"'
        self.page.locator('#v119CSVFile').set_input_files({'name':'fiction.csv','mimeType':'text/csv','buffer':text.encode('utf-8')})
        self.page.wait_for_function('v119CSV?.raw?.length===2')
        self.assertEqual(self.page.evaluate('state.entries.length'),1)
        self.page.evaluate("document.getElementById('v119CSVDefaultAccount').value='bank';v119CSVPreview()")
        self.assertEqual(self.page.locator('#v119CSVRows img').count(),0)
        self.assertIn('<img src=x',self.page.locator('#v119CSVRows').inner_text())
        self.page.evaluate('v119CancelCSV()')
        self.assertEqual(self.page.evaluate('state.entries.length'),1)
        self.assertEqual(self.page.evaluate('operationSaves'),0)

    def test_late_async_file_read_cannot_cross_auth_epoch(self):
        self.prepare()
        self.page.evaluate("""()=>{const bytes=new TextEncoder().encode('Дата;Сумма;Описание\\n01.11.2026;-1;Тест');const file={name:'fiction.csv',size:bytes.length,arrayBuffer:()=>new Promise(resolve=>window.finishFile=()=>resolve(bytes.buffer))};v119ReadCSV(file);authEpoch++;v119ResetOperations();finishFile()}""")
        self.page.wait_for_function("document.getElementById('v119CSVFile').value===''")
        self.assertTrue(self.page.evaluate('v119CSV===null'))
        self.assertEqual(self.page.evaluate('state.entries.length'),1)

    def test_undo_exact_record_and_changed_tombstone_guard(self):
        self.prepare()
        self.page.evaluate("deleteEntry('legacy')")
        self.assertEqual(self.page.evaluate('state.entries.length'),0)
        tomb=self.page.evaluate('state.deletedEntries.legacy')
        self.page.evaluate('v119UndoDelete()')
        restored=self.page.evaluate('state.entries[0]')
        self.assertEqual(restored['foreign'], {'raw':'unknown-field','list':[1,2]})
        self.assertEqual(restored['amount'],17.251)
        self.assertGreater(restored['updated_at'],tomb)
        self.page.evaluate("deleteEntry('legacy');state.deletedEntries.legacy=v117RecordStamp(state.deletedEntries.legacy)")
        before=self.page.evaluate('JSON.stringify(state)')
        self.page.evaluate('v119UndoDelete()')
        self.assertEqual(self.page.evaluate('JSON.stringify(state)'),before)

    def test_confirm_boundary_rechecks_scope_and_record_before_delete_or_payment(self):
        self.prepare()
        before=self.page.evaluate('JSON.stringify(state)')
        self.page.evaluate("window.confirm=()=>{authEpoch++;return true};deleteEntry('legacy')")
        self.assertEqual(self.page.evaluate('JSON.stringify(state)'),before)
        self.page.evaluate("window.confirm=()=>{state.entries[0].comment='Новое облачное значение';return true};deleteEntry('legacy')")
        self.assertEqual(self.page.evaluate('state.entries.length'),1)
        self.assertEqual(self.page.evaluate('state.entries[0].comment'),'Новое облачное значение')
        self.page.evaluate("""()=>{state.installments=[{id:'plan',title:'Тест',kind:'split',amount:10,accountingMode:'payments',parts:[{id:'p',date:today(),amount:10}],links:{}}];window.confirm=()=>{authEpoch++;return true};v77PayPart('plan','p')}""")
        self.assertEqual(self.page.evaluate('state.entries.length'),1)
        self.assertEqual(self.page.evaluate('operationSaves'),0)

    def test_installment_and_recurring_payment_keep_links_and_source(self):
        self.prepare()
        self.page.evaluate("""()=>{const stamp=v117RecordStamp();state.installments=[{id:'plan',title:'Учебная покупка',kind:'split',provider:'Учебный сервис',amount:10,accountingMode:'purchase',parts:[{id:'p1',date:today(),amount:10}],links:{},created_at:stamp,updated_at:stamp}];state.intelligence.recurring=[{id:'r1',name:'Учебная подписка',amount:5,category:'Прочее',day:1,who:'Общее',created_at:stamp,updated_at:stamp}];renderAll();v119RefreshPaymentAccounts();document.getElementById('v119LoanAccount').value='bank';document.getElementById('v119RecurringAccount').value='cash';v77PayPart('plan','p1')}""")
        self.page.evaluate("v84ConfirmRecurring('r1',today().slice(0,7))")
        self.assertEqual(self.page.evaluate('state.entries.length'),3)
        self.assertEqual(self.page.evaluate('state.entries[1].fromAccountId'),'bank')
        self.assertEqual(self.page.evaluate('state.entries[1].debtRepayment'),True)
        self.assertEqual(self.page.evaluate('state.installments[0].links.p1'),'installment:plan:p1')
        self.assertEqual(self.page.evaluate('state.entries[2].accountId'),'cash')
        self.page.evaluate("v77PayPart('plan','p1');v84ConfirmRecurring('r1',today().slice(0,7))")
        self.assertEqual(self.page.evaluate('state.entries.length'),3)
        self.assertEqual(self.page.evaluate("v117AccountBalance('bank').balance"),990)
        self.assertEqual(self.page.evaluate("v117AccountBalance('cash').balance"),95)

    def test_mobile_and_large_text_tools_bound_and_csv_paginated(self):
        self.prepare(); self.page.set_viewport_size({'width':320,'height':740})
        self.draft('3')
        self.page.evaluate("document.documentElement.style.fontSize='200%';document.getElementById('v119OperationTools').open=true;v119StartSplit()")
        bounds=self.page.evaluate("""()=>[...document.querySelectorAll('#v119SplitPanel input,#v119SplitPanel button,#v119SplitPanel .v107-select-trigger')].filter(e=>e.getBoundingClientRect().width).map(e=>({x:e.getBoundingClientRect().x,right:e.getBoundingClientRect().right,text:e.textContent}))""")
        self.assertTrue(all(e['x']>=-1 and e['right']<=321 for e in bounds),bounds)
        text='Дата;Сумма;Описание\n'+'\n'.join(f'01.11.2026;-{i+1};Строка {i}' for i in range(25))
        self.csv(text)
        self.assertEqual(self.page.locator('#v119CSVRows .v119-csv-row').count(),20)
        self.page.evaluate('v119CSV.page=1;v119RenderCSVRows()')
        self.assertEqual(self.page.locator('#v119CSVRows .v119-csv-row').count(),5)
        self.assertEqual(self.page.evaluate('state.entries.length'),1)


if __name__ == '__main__':
    unittest.main()
