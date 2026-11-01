"""Dialog keyboard regressions with fictional local rows; all external requests blocked."""
import re
import unittest

import test_analytics_edit as analytics
import test_category_review as review
import test_local_data_safety as harness


class DialogKeyboard(unittest.TestCase):
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
    prepare = analytics.AnalyticsEdit.prepare
    open_drill = analytics.AnalyticsEdit.open_drill
    edit_first = analytics.AnalyticsEdit.edit_first

    def history_edit(self):
        self.prepare()
        self.page.evaluate("go('history');clearHistoryMonth()")
        row = self.page.locator('#historyBody tr').filter(has_text='Fictional first')
        opener = row.get_by_role('button', name='Редактировать операцию', exact=True)
        opener.click()
        self.assertTrue(self.page.locator('#editModal').is_visible())
        return opener

    def assert_in_editor(self):
        self.assertTrue(self.page.evaluate("editModal.contains(document.activeElement)"))

    def test_history_edit_tab_enter_never_activates_background_delete(self):
        self.history_edit()
        confirmations = []
        self.page.on('dialog', lambda dialog: confirmations.append(dialog.message))
        self.assertEqual(self.page.evaluate('document.activeElement.id'), 'xAmount')
        self.page.keyboard.press('Tab')
        self.assert_in_editor()
        self.page.keyboard.press('Enter')
        self.assertEqual(confirmations, [])
        self.assertEqual(self.snapshot(), self.before)
        self.assertTrue(self.page.locator('#editModal').is_visible())

    def test_editor_tab_wraps_visible_custom_selects_in_both_directions(self):
        self.history_edit()
        first = self.page.locator('#editModal button[role="combobox"]').first
        last = self.page.locator('#editModal').get_by_role('button', name='Отмена', exact=True)
        first.focus(); self.page.keyboard.press('Shift+Tab')
        self.assertTrue(last.evaluate('(node)=>node===document.activeElement'))
        self.page.keyboard.press('Tab')
        self.assertTrue(first.evaluate('(node)=>node===document.activeElement'))
        for _ in range(25):
            self.page.keyboard.press('Tab')
            self.assert_in_editor()

    def test_escape_discards_draft_and_returns_to_exact_history_opener(self):
        opener = self.history_edit()
        self.page.locator('#xAmount').fill('999,99')
        self.page.locator('#xComment').fill('Unsaved keyboard draft')
        self.page.keyboard.press('Escape')
        self.assertFalse(self.page.locator('#editModal').is_visible())
        self.assertTrue(opener.evaluate('(node)=>node===document.activeElement'))
        self.assertFalse(self.page.locator('#appRoot').evaluate('(node)=>node.inert'))
        self.assertEqual(self.snapshot(), self.before)

    def test_history_save_returns_to_equivalent_live_record_button_after_render(self):
        opener = self.history_edit()
        self.page.locator('#xComment').fill('Explicit local edit')
        self.page.locator('#editModal').get_by_role('button', name='Сохранить', exact=True).click()
        self.assertFalse(self.page.locator('#editModal').is_visible())
        self.assertTrue(opener.evaluate('(node)=>node===document.activeElement'))
        self.assertEqual(self.page.evaluate('document.activeElement.dataset.id'), self.first_id)

    def test_background_is_inert_and_cannot_receive_focus_or_synthetic_activation(self):
        self.history_edit()
        self.assertTrue(self.page.locator('#appRoot').evaluate('(node)=>node.inert'))
        self.page.evaluate("""() => {
          const button=[...document.querySelectorAll('#historyBody [data-action="delete"]')]
            .find(node=>node.dataset.id==='fictional-first');
          button.focus();button.click();
        }""")
        self.assert_in_editor()
        self.assertEqual(self.snapshot(), self.before)

    def test_nested_drill_edit_escape_restores_row_then_original_chart_button(self):
        self.prepare()
        chart = self.page.locator('#aCats').get_by_role('button').filter(has_text=self.group)
        chart.click()
        self.edit_first()
        self.page.keyboard.press('Escape')
        self.assertTrue(self.page.locator('#v84DrillModal').is_visible())
        self.assertFalse(self.page.locator('#editModal').is_visible())
        self.assertEqual(self.page.evaluate('document.activeElement.dataset.recordAction'), 'drill-entry-edit')
        self.assertIn(self.first_id, self.page.evaluate('document.activeElement.dataset.recordArgs'))
        self.page.keyboard.press('Escape')
        self.assertFalse(self.page.locator('#v84DrillModal').is_visible())
        self.assertTrue(chart.evaluate('(node)=>node===document.activeElement'))
        self.assertEqual(self.snapshot(), self.before)

    def test_drill_tab_wraps_and_escape_returns_focus(self):
        self.prepare(); self.open_drill()
        close = self.page.locator('#v84DrillModal .v84-close')
        last = self.page.locator('#v84DrillModal [data-record-action="drill-entry-delete"]').last
        close.focus(); self.page.keyboard.press('Shift+Tab')
        self.assertTrue(last.evaluate('(node)=>node===document.activeElement'))
        self.page.keyboard.press('Tab')
        self.assertTrue(close.evaluate('(node)=>node===document.activeElement'))
        self.page.keyboard.press('Escape')
        self.assertFalse(self.page.locator('#v84DrillModal').is_visible())
        self.assertTrue(self.page.evaluate("document.getElementById('analytics').contains(document.activeElement)"))
        self.assertEqual(self.snapshot(), self.before)

    def test_nested_drill_save_ack_preserves_live_edit_or_filter_focus(self):
        for focus_filter in [False, True]:
            with self.subTest(focus_filter=focus_filter):
                self.prepare(); self.open_drill(); self.edit_first()
                self.page.evaluate("""() => {
                  const original=saveAll;
                  saveAll=()=>{const pending=original();return new Promise(resolve=>{
                    window.__releaseDialogSave=async()=>resolve(await pending);
                  })};
                }""")
                self.page.locator('#xComment').fill('Explicit nested save')
                self.page.locator('#editModal').get_by_role('button', name='Сохранить', exact=True).click()
                self.assertEqual(self.page.evaluate('document.activeElement.dataset.recordAction'), 'drill-entry-edit')
                self.assertIn(self.first_id, self.page.evaluate('document.activeElement.dataset.recordArgs'))
                if focus_filter:
                    self.page.locator('#v84DrillBody button[data-v84-sub]').filter(has_text='Сергей').click()
                self.page.evaluate('__releaseDialogSave()')
                self.page.wait_for_function("document.getElementById('v96DrillSaveStatus').textContent.length>0")
                if focus_filter:
                    self.assertEqual(self.page.evaluate('document.activeElement.dataset.v84Sub'), 'Сергей')
                else:
                    self.assertEqual(self.page.evaluate('document.activeElement.dataset.recordAction'), 'drill-entry-edit')
                    self.assertIn(self.first_id, self.page.evaluate('document.activeElement.dataset.recordArgs'))

    def test_select_escape_closes_child_before_editor(self):
        self.history_edit()
        trigger = self.page.locator('#xCat').locator('..').get_by_role('combobox')
        trigger.focus(); self.page.keyboard.press('Enter')
        self.assertEqual(trigger.get_attribute('aria-expanded'), 'true')
        self.page.keyboard.press('Escape')
        self.assertEqual(trigger.get_attribute('aria-expanded'), 'false')
        self.assertTrue(self.page.locator('#editModal').is_visible())
        self.assertTrue(trigger.evaluate('(node)=>node===document.activeElement'))
        self.page.keyboard.press('Escape')
        self.assertFalse(self.page.locator('#editModal').is_visible())
        self.assertEqual(self.snapshot(), self.before)

    def test_calendar_portal_escape_and_tab_return_to_editor_without_changes(self):
        self.history_edit()
        field = self.page.locator('#xDate')
        original = field.input_value()
        field.focus(); field.press('Alt+ArrowDown')
        panel = self.page.locator('#v108CalendarPanel')
        self.assertTrue(panel.is_visible())
        self.assertTrue(panel.evaluate('(node)=>node.contains(document.activeElement)'))
        self.page.keyboard.press('ArrowRight'); self.page.keyboard.press('Escape')
        self.assertFalse(panel.is_visible())
        self.assertTrue(self.page.locator('#editModal').is_visible())
        self.assertEqual(self.page.evaluate('document.activeElement.id'), 'xDate')
        self.assertEqual(field.input_value(), original)
        field.press('Alt+ArrowDown')
        panel.get_by_role('button', name='Закрыть календарь', exact=True).focus()
        self.page.keyboard.press('Tab')
        self.assertFalse(panel.is_visible()); self.assert_in_editor()
        self.page.locator('#xComment').focus()
        self.page.keyboard.press('Escape')
        self.assertFalse(self.page.locator('#editModal').is_visible())
        self.assertEqual(self.snapshot(), self.before)

    def test_merchant_escape_closes_suggestions_before_editor(self):
        self.history_edit()
        self.page.locator('#xStore').fill('Само')
        self.assertTrue(self.page.locator('#xStoreSuggestions').is_visible())
        self.page.keyboard.press('Escape')
        self.assertFalse(self.page.locator('#xStoreSuggestions').is_visible())
        self.assertTrue(self.page.locator('#editModal').is_visible())
        self.page.keyboard.press('Escape')
        self.assertFalse(self.page.locator('#editModal').is_visible())
        self.assertEqual(self.snapshot(), self.before)

    def test_native_calculator_escape_and_apply_keep_parent_editor_open(self):
        self.history_edit()
        tools = self.page.locator('#editModal .v96-amount-tools')
        tools.get_by_role('button', name='Калькулятор', exact=True).click()
        self.assertEqual(self.page.evaluate('document.activeElement.id'), 'v96CalcExpression')
        self.page.keyboard.press('Escape')
        self.assertFalse(self.page.locator('#v96Calculator').is_visible())
        self.assertTrue(self.page.locator('#editModal').is_visible())
        self.assertEqual(self.page.evaluate('document.activeElement.id'), 'xAmount')
        tools.get_by_role('button', name='Калькулятор', exact=True).click()
        self.page.locator('#v96CalcExpression').fill('100 + 25,50')
        self.page.locator('#v96CalcApply').click()
        self.assertEqual(self.page.locator('#xAmount').input_value(), '125,50')
        self.assertTrue(self.page.locator('#editModal').is_visible())
        self.page.keyboard.press('Escape')
        self.assertEqual(self.snapshot(), self.before)

    def test_navigation_and_logout_close_overlays_without_hidden_focus(self):
        self.history_edit()
        self.page.locator('#xDate').click()
        self.page.evaluate("go('settings')")
        self.assertFalse(self.page.locator('#editModal').is_visible())
        self.assertFalse(self.page.locator('#v108CalendarPanel').is_visible())
        self.assertFalse(self.page.locator('#appRoot').evaluate('(node)=>node.inert'))
        self.assertTrue(self.page.evaluate("document.getElementById('settings').contains(document.activeElement)"))
        self.page.evaluate("go('history');clearHistoryMonth()")
        self.page.locator('#historyBody tr').filter(has_text='Fictional first').get_by_role('button', name='Редактировать операцию', exact=True).click()
        self.page.evaluate('logout()')
        self.assertFalse(self.page.locator('#editModal').is_visible())
        self.assertFalse(self.page.locator('#v84DrillModal').is_visible())
        self.assertFalse(self.page.locator('#authModal').is_visible())
        self.assertFalse(self.page.locator('#appRoot').evaluate('(node)=>node.inert'))
        self.assertFalse(self.page.evaluate("!!document.activeElement.closest('#appRoot,#editModal,#v84DrillModal,#authModal')"))

    def test_auth_dialog_named_labels_tab_escape_and_restore(self):
        self.prepare()
        self.page.locator('#v104GlobalCalculator').focus()
        self.page.evaluate('openAuth()')
        self.assertTrue(self.page.get_by_role('dialog', name='Вход в семейный банк').is_visible())
        self.assertEqual(self.page.evaluate('document.activeElement.id'), 'loginEmail')
        self.page.keyboard.press('Shift+Tab')
        self.assertEqual(self.page.locator('#authModal').get_by_role('button', name='Закрыть', exact=True).evaluate('(node)=>node===document.activeElement'), True)
        self.page.keyboard.press('Escape')
        self.assertFalse(self.page.locator('#authModal').is_visible())
        self.assertEqual(self.page.evaluate('document.activeElement.id'), 'v104GlobalCalculator')
        self.assertEqual(self.snapshot(), self.before)

    def test_category_review_uses_same_dialog_lifecycle_and_restores_review_row(self):
        review.CategoryReview.prepare(self)
        self.page.evaluate('v98OpenCategoryReview()')
        row = self.page.locator('#v98ReviewRows [data-v98-review-id="digital"]')
        opener = row.get_by_role('button', name='Проверить запись', exact=True)
        opener.click()
        self.assertTrue(self.page.get_by_role('dialog', name='Изменить только категорию').is_visible())
        self.assert_in_editor()
        self.page.keyboard.press('Escape')
        self.assertFalse(self.page.locator('#editModal').is_visible())
        self.assertTrue(opener.evaluate('(node)=>node===document.activeElement'))
        self.assertEqual(self.snapshot(), self.before)

    def test_category_review_no_change_save_restores_row_and_changed_save_focuses_context(self):
        review.CategoryReview.prepare(self)
        self.page.evaluate('v98OpenCategoryReview()')
        row = self.page.locator('#v98ReviewRows [data-v98-review-id="digital"]')
        opener = row.get_by_role('button', name='Проверить запись', exact=True)
        opener.click()
        self.page.locator('#editModal').get_by_role('button', name='Сохранить', exact=True).click()
        self.assertFalse(self.page.locator('#editModal').is_visible())
        self.assertTrue(opener.evaluate('(node)=>node===document.activeElement'))
        self.assertEqual(self.snapshot(), self.before)
        opener.click()
        self.page.locator('#xCat').select_option('Подписки')
        self.page.locator('#editModal').get_by_role('button', name='Сохранить', exact=True).click()
        self.assertFalse(self.page.locator('#editModal').is_visible())
        self.assertEqual(row.count(), 0)
        self.assertTrue(self.page.evaluate("document.getElementById('categoryReview').contains(document.activeElement)"))
        self.assertEqual(self.page.evaluate('document.activeElement.tagName'), 'H2')

    def test_editor_labels_are_associated_with_their_preserved_controls(self):
        self.history_edit()
        for field in ['xType', 'xAmount', 'xCat', 'xWho', 'xStore', 'xDate', 'xComment']:
            self.assertTrue(self.page.locator('#'+field).evaluate('(node)=>node.labels.length>0'))


if __name__ == '__main__':
    unittest.main()
