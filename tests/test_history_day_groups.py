"""History day sections use the exact filtered rows and preserve operation actions.

Run: PYTHONPATH=tests python -m unittest test_history_day_groups
Synthetic browser fixtures only; all external requests are blocked.
"""
import unittest

import test_history_totals as fixtures


class HistoryDayGroups(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.HistoryTotals.setUpClass()

    @classmethod
    def tearDownClass(cls):
        fixtures.HistoryTotals.tearDownClass()

    def setUp(self):
        self.fixture = fixtures.HistoryTotals(
            'test_month_person_mixed_totals_keep_transfers_and_corrections_separate')
        self.fixture.setUp()
        self.page = self.fixture.page
        self.page.evaluate('''() => {
          window.readHistoryDays=()=>[...document.querySelectorAll('#historyBody [data-v164-day]')].map(group=>({
            date:group.dataset.v164Day,label:group.querySelector('h3').textContent,
            ids:[...group.querySelectorAll('[data-v141-operation-id]')].map(row=>row.dataset.v141OperationId),
            totals:Object.fromEntries([...group.querySelectorAll('[data-v164-day-total]')].map(total=>[total.dataset.v164DayTotal,total.querySelector('strong').textContent.replaceAll('\\u00a0',' ')]))
          }));
        }''')

    def tearDown(self):
        self.fixture.tearDown()

    def evaluate(self, code):
        return self.fixture.evaluate(code)

    def test_calendar_days_are_descending_and_same_day_rows_keep_existing_order(self):
        result = self.evaluate("historySet('fWho','');return {days:readHistoryDays(),all:historyRead(),unchanged:JSON.stringify(state.entries)===historyOriginalEntries};")
        self.assertEqual([row['date'] for row in result['days']],
                         ['2026-11-03', '2026-11-02', '2026-11-01'])
        self.assertEqual(result['days'][0]['ids'], ['income', 'move', 'cash', 'adjustment'])
        self.assertEqual(result['days'][1]['ids'], ['second', 'other-person'])
        self.assertEqual(result['days'][1]['totals'], {'expense': '450,20 ₽'})
        self.assertEqual(result['days'][0]['totals'], {'income': '1 000,25 ₽'})
        self.assertIn('ноября', result['days'][0]['label'])
        self.assertIn('2026', result['days'][0]['label'])
        self.assertTrue(result['unchanged'])
        self.assertEqual(result['all']['totals']['expense'], '550,30 ₽')

    def test_day_subtotals_follow_person_category_search_and_type_filters(self):
        result = self.evaluate('''
          historySet('fType','expense');const byPerson=readHistoryDays();
          historySet('fDay','2026-11-02');const byDay=readHistoryDays();
          historySet('fSearch','Магазин Б');historySet('fCat','Продукты');const searched=readHistoryDays();
          historySet('fSearch','Несуществующий магазин');return {byPerson,byDay,searched,empty:readHistoryDays(),emptyText:document.getElementById('historyBody').textContent};
        ''')
        self.assertEqual([day['date'] for day in result['byPerson']], ['2026-11-02', '2026-11-01'])
        self.assertEqual(result['byPerson'][0]['totals'], {'expense': '50,20 ₽'})
        self.assertEqual(len(result['byDay']), 1)
        self.assertEqual(result['searched'][0]['ids'], ['second'])
        self.assertEqual(result['searched'][0]['totals'], {'expense': '50,20 ₽'})
        self.assertEqual(result['empty'], [])
        self.assertIn('Операций не найдено', result['emptyText'])

    def test_all_time_adds_older_days_without_losing_other_filters(self):
        self.evaluate("historySet('fType','expense');historySet('fDay','2026-11-02');")
        self.page.locator('#v158HistoryAllTime').click()
        result = self.evaluate("return {days:readHistoryDays(),who:document.getElementById('fWho').value,type:document.getElementById('fType').value,total:historyRead().totals};")
        self.assertEqual([day['date'] for day in result['days']],
                         ['2026-11-02', '2026-11-01', '2026-10-01'])
        self.assertEqual(result['days'][-1]['totals'], {'expense': '200,30 ₽'})
        self.assertEqual((result['who'], result['type']), ('Сергей', 'expense'))
        self.assertEqual(result['total'], {'expense': '350,60 ₽'})

    def test_mixed_day_does_not_net_income_or_count_movements_as_expenses(self):
        result = self.evaluate('''
          state.entries.push({...state.entries[0],id:'same-day-spend',date:'2026-11-03',amount:10.10},
            {...state.entries[0],id:'expense-correction',date:'2026-11-03',amount:700,balanceAdjustment:true,adjustmentDirection:1});
          renderHistory();const mixed=readHistoryDays()[0];historySet('fType','transfer');return {mixed,movements:readHistoryDays()};
        ''')
        self.assertEqual(result['mixed']['totals'], {'expense': '10,10 ₽', 'income': '1 000,25 ₽'})
        self.assertEqual(result['movements'][0]['totals'], {})
        self.assertEqual(set(result['movements'][0]['ids']), {'move', 'adjustment'})

    def test_add_date_edit_delete_and_undo_rebuild_day_membership_and_sums(self):
        result = self.evaluate('''
          historySet('fType','expense');openEntry('expense');document.getElementById('eAmount').value='10.10';
          v90Choose('Продукты');v133ChooseRecipient('eBeneficiary','Сергей');await addEntry();
          const added=state.entries.at(-1);go('history');const afterAdd=readHistoryDays();
          openEdit(added.id);document.getElementById('xDate').value='2026-11-02';document.getElementById('xAmount').value='20.20';await saveEdit();go('history');const afterEdit=readHistoryDays();
          await deleteEntry(added.id);const afterDelete=readHistoryDays();await v119UndoDelete();go('history');
          return {afterAdd,afterEdit,afterDelete,afterUndo:readHistoryDays(),originalPreserved:JSON.stringify(state.entries.filter(e=>e.id!==added.id))===historyOriginalEntries};
        ''')
        self.assertEqual(result['afterAdd'][0]['date'], '2026-11-12')
        self.assertEqual(result['afterAdd'][0]['totals'], {'expense': '10,10 ₽'})
        self.assertEqual([day['date'] for day in result['afterEdit']], ['2026-11-02', '2026-11-01'])
        self.assertEqual(result['afterEdit'][0]['totals'], {'expense': '70,40 ₽'})
        self.assertEqual(result['afterDelete'][0]['totals'], {'expense': '50,20 ₽'})
        self.assertEqual(result['afterUndo'][0]['totals'], {'expense': '70,40 ₽'})
        self.assertTrue(result['originalPreserved'])

    def test_invalid_dates_use_one_named_group_without_crashing_or_inventing_dates(self):
        result = self.evaluate('''
          state.entries.push({...state.entries[0],id:'bad-date',date:'not-a-date',amount:1.25},
            {...state.entries[0],id:'missing-date',date:'',amount:2.50},
            {...state.entries[0],id:'impossible-date',date:'2026-02-30',amount:5});
          resetHistoryFilters();return {days:readHistoryDays(),unknownTimes:document.querySelectorAll('#historyBody [data-v164-day=""] .v164-history-day-head time').length};
        ''')
        self.assertEqual(result['days'][-1]['date'], '')
        self.assertEqual(result['days'][-1]['label'], 'Дата не указана')
        self.assertEqual(result['days'][-1]['totals'], {'expense': '8,75 ₽'})
        self.assertEqual(set(result['days'][-1]['ids']), {'bad-date', 'missing-date', 'impossible-date'})
        self.assertEqual(result['unknownTimes'], 0)

    def test_existing_operation_actions_and_row_dates_remain_usable(self):
        row = self.page.locator('#historyBody [data-v141-operation-id="first"]')
        self.assertEqual(row.locator('.v141-actions button').count(), 4)
        self.assertEqual(row.locator('time').get_attribute('datetime'), '2026-11-01')
        row.locator('[data-action="edit"]').click()
        self.assertTrue(self.page.locator('#editModal').evaluate("e=>e.classList.contains('open')"))
        self.assertEqual(self.page.locator('#xAmount').input_value(), '100.1')
        self.evaluate('closeEdit();')
        self.assertEqual(self.evaluate('return JSON.stringify(state.entries)===historyOriginalEntries;'), True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
