"""Income edits preserve recorded recipients; fictional rows and blocked external traffic."""
import unittest

import test_local_data_safety as harness


class IncomeEdit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.LocalDataSafety.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        harness.LocalDataSafety.tearDownClass.__func__(cls)

    setUp=harness.LocalDataSafety.setUp
    tearDown=harness.LocalDataSafety.tearDown
    open=harness.LocalDataSafety.open
    snapshot=harness.LocalDataSafety.snapshot

    def prepare(self,recipient='Учебный прежний получатель',kind='income',missing_recipient=False):
        self.open()
        self.before=self.page.evaluate("""value => {
          session=null;stopCloudSync();localStorage.clear();state=blankState();
          state.entries=[{id:'fictional-edit-income',type:value.kind,date:today(),amount:123.45,
            category:value.kind==='income'?'Доход':'Продукты',who:value.recipient,
            store:'Учебный источник',comment:'Исходный комментарий',pay:'Исторический способ оплаты',
            futureField:{preserve:[true,null,'unchanged']},created_at:'2025-01-02T03:04:05Z'},
            {id:'fictional-unrelated',type:'income',date:today(),amount:9.87,
             category:'Доход',who:'Виктория',store:'Другой учебный источник',futureField:{keep:7}}];
          if(value.kind==='expense')Object.assign(state.entries[0],{
            subcategory:'Прежнее уточнение',beneficiary:'Учебная получательница'});
          if(value.missingRecipient)delete state.entries[0].who;
          state=normalize(state);showApp();renderAll();go('history');openEdit(state.entries[0].id);
          return JSON.parse(JSON.stringify(state.entries));
        }""",{'recipient':recipient,'kind':kind,'missingRecipient':missing_recipient})

    def save_comment(self):
        self.page.locator('#xComment').fill('Только исправленный комментарий')
        self.page.locator('#editModal').get_by_role('button',name='Сохранить',exact=True).click()
        self.page.wait_for_function('!document.getElementById("editModal").classList.contains("open")')
        return self.page.evaluate('state.entries')

    def assert_only_comment_changed(self,rows):
        self.assertEqual(rows[1],self.before[1])
        expected={**self.before[0],'comment':'Только исправленный комментарий'}
        updated={**rows[0]};self.assertIsInstance(updated.pop('updated_at'),str)
        self.assertEqual(updated,expected)

    def test_unknown_income_recipient_survives_comment_only_edit(self):
        self.prepare()
        self.assertEqual(self.page.locator('#xWho').input_value(),self.before[0]['who'])
        self.assert_only_comment_changed(self.save_comment())

    def test_explicit_empty_income_recipient_stays_unspecified(self):
        self.prepare('')
        self.assertEqual(self.page.locator('#xWho').input_value(),'')
        self.assertEqual(self.page.locator('#xWho option:checked').inner_text(),'Не указано')
        rows=self.save_comment();self.assert_only_comment_changed(rows)
        self.assertEqual(rows[0]['who'],'')
        self.assertIn('Не указано',self.page.locator('#incomeList').inner_text())

    def test_missing_income_recipient_field_is_not_added_by_comment_edit(self):
        self.prepare(missing_recipient=True)
        self.assertNotIn('who',self.before[0])
        self.assertEqual(self.page.locator('#xWho').input_value(),'')
        rows=self.save_comment();self.assert_only_comment_changed(rows)
        self.assertNotIn('who',rows[0])

    def test_null_income_recipient_is_not_replaced_by_empty_string(self):
        self.prepare(None)
        self.assertIsNone(self.before[0]['who'])
        self.assertEqual(self.page.locator('#xWho').input_value(),'')
        rows=self.save_comment();self.assert_only_comment_changed(rows)
        self.assertIsNone(rows[0]['who'])

    def test_selecting_recipient_for_missing_or_null_income_is_an_explicit_change(self):
        for missing in [True,False]:
            with self.subTest(missing=missing):
                self.prepare(None,missing_recipient=missing)
                self.page.locator('#xWho').select_option('Виктория')
                rows=self.save_comment();self.assertEqual(rows[0]['who'],'Виктория')
                self.before[0]['who']='Виктория';self.assert_only_comment_changed(rows)

    def test_historical_recipient_exact_text_is_safe_and_not_trimmed(self):
        recipient='  Учебный <img src=x onerror="window.__incomeInjected=true"> & "получатель"  '
        self.prepare(recipient)
        self.assertEqual(self.page.locator('#xWho').input_value(),recipient)
        self.assertEqual(self.page.locator('#xWho img').count(),0)
        self.assertFalse(self.page.evaluate('Boolean(window.__incomeInjected)'))
        self.assert_only_comment_changed(self.save_comment())
        self.assertFalse(self.page.evaluate('Boolean(window.__incomeInjected)'))

    def test_explicit_recipient_selection_changes_only_requested_income_fields(self):
        self.prepare()
        self.page.locator('#xWho').select_option('Виктория')
        rows=self.save_comment()
        self.assertEqual(rows[0]['who'],'Виктория')
        self.before[0]['who']='Виктория'
        self.assert_only_comment_changed(rows)

    def test_income_comment_preserves_legacy_hidden_allocation_fields(self):
        self.prepare()
        self.page.evaluate("""() => {
          Object.assign(state.entries[0],{subcategory:'Прежняя скрытая детализация',beneficiary:'Учебная прежняя получательница'});
          openEdit(state.entries[0].id);
        }""")
        self.before=self.page.evaluate('JSON.parse(JSON.stringify(state.entries))')
        self.assertFalse(self.page.locator('#xBeneficiary').is_visible())
        self.assert_only_comment_changed(self.save_comment())

    def test_explicit_expense_to_income_retype_clears_expense_allocation_fields(self):
        self.prepare(kind='expense')
        self.page.locator('#xType').select_option('income')
        self.page.locator('#xWho').select_option('Виктория')
        rows=self.save_comment()
        self.assertEqual(rows[0]['type'],'income');self.assertEqual(rows[0]['who'],'Виктория')
        self.assertNotIn('subcategory',rows[0]);self.assertNotIn('beneficiary',rows[0])
        self.assertEqual(rows[0]['futureField'],self.before[0]['futureField'])
        self.assertEqual(rows[1],self.before[1])

    def test_blank_edit_date_keeps_every_record_and_storage_copy_unchanged(self):
        self.prepare(kind='expense')
        self.page.evaluate('saveLocal();savePendingLocal();rememberCloudBase(normalize(state))')
        before=self.snapshot();total=self.page.evaluate('sum(expenses(month()))')
        self.page.locator('#xDate').fill('');self.page.locator('#xAmount').fill('999,99')
        self.page.locator('#xComment').fill('Не сохранять эти изменения')
        self.page.locator('#editModal').get_by_role('button',name='Сохранить',exact=True).click()
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.page.evaluate('sum(expenses(month()))'),total)
        self.assertTrue(self.page.locator('#editModal').is_visible())
        self.assertTrue(self.page.locator('#xDateError').is_visible())
        self.assertIn('дат',self.page.locator('#xDateError').inner_text().lower())
        self.assertEqual(self.page.locator('#xDate').get_attribute('aria-invalid'),'true')
        self.assertEqual(self.page.evaluate('document.activeElement.id'),'xDate')

    def test_invalid_programmatic_edit_dates_never_roll_over_or_mutate_history(self):
        self.prepare(kind='expense')
        self.page.evaluate('saveLocal();savePendingLocal();rememberCloudBase(normalize(state))')
        before=self.snapshot();total=self.page.evaluate('sum(expenses(month()))')
        for invalid in ['2025-02-29','2026-02-30','2026-13-01','not-a-date']:
            with self.subTest(date=invalid):
                # Native date controls sanitize impossible values to empty; a text
                # override verifies the save guard itself rejects rollover dates.
                self.page.evaluate("""value=>{const date=document.getElementById('xDate');date.type='text';date.value=value}""",invalid)
                self.page.locator('#editModal').get_by_role('button',name='Сохранить',exact=True).click()
                self.assertEqual(self.snapshot(),before)
                self.assertEqual(self.page.evaluate('sum(expenses(month()))'),total)
                self.assertTrue(self.page.locator('#editModal').is_visible())
                self.assertTrue(self.page.locator('#xDateError').is_visible())
                self.assertEqual(self.page.evaluate('document.activeElement.id'),'xDate')

    def test_valid_leap_day_and_explicit_date_change_save_without_altering_other_fields(self):
        self.prepare(kind='expense')
        for valid in ['2024-02-29','2026-03-01']:
            with self.subTest(date=valid):
                self.page.locator('#xDate').fill(valid)
                rows=self.save_comment()
                self.before[0]['date']=valid
                if 'updated_at' in self.before[0]:self.before[0].pop('updated_at')
                self.assert_only_comment_changed(rows)
                self.assertEqual(self.page.evaluate('m=>sum(expenses(m))',valid[:7]),123.45)
                saved=self.page.evaluate('JSON.parse(localStorage.getItem(KEYS.pending)).entries')
                self.assertEqual(saved,rows)
                self.page.evaluate('openEdit(state.entries[0].id)')

    def test_expense_comment_edit_preserves_recipient_allocation_and_metadata(self):
        self.prepare('Учебный прежний участник',kind='expense')
        self.assertFalse(self.page.locator('#v86EditWhoField').is_visible())
        rows=self.save_comment();self.assert_only_comment_changed(rows)
        self.assertEqual(rows[0]['beneficiary'],'Учебная получательница')


if __name__=='__main__':
    unittest.main()
