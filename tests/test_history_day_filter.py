"""Exact-day history filtering and home recent alignment; fictional local data only."""
import unittest

import test_local_data_safety as harness


class HistoryDayFilter(unittest.TestCase):
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
          session=null;stopCloudSync();localStorage.clear();state=blankState();
          const make=(id,date,amount,type,category,beneficiary,store,comment='',hour='12')=>({
            id,date,amount,type,category,beneficiary,who:beneficiary,store,comment,
            created_at:date+'T'+hour+':00:00Z',updated_at:date+'T'+hour+':00:00Z',
            unknownExtension:{preserve:[true,null,{id}]}});
          state.entries=[
            make('daily-a','2026-10-30',19.25,'expense','Продукты','Сергей','Fictional Bakery','Daily alpha','12'),
            make('daily-b','2026-10-30',12.75,'expense','Дом','Виктория','Fictional Home','Daily beta','13'),
            make('daily-c','2026-10-31',5,'expense','Продукты','Сергей','Fictional Bakery','Another day'),
            make('daily-d','2026-11-01',100,'income','Зарплата','Сергей','Fictional Employer'),
            make('daily-e','2026-09-20',7,'expense','Продукты','Сергей','Fictional old shop'),
            make('daily-f','2026-10-30',70,'income','Зарплата','Сергей','Fictional income','Daily income','14')
          ];
          showApp();renderAll();go('history');resetHistoryFilters();
        }""")
        self.before = self.snapshot()

    def row_ids(self):
        return self.page.locator('#historyBody .v76-entry-row button[data-action="edit"]').evaluate_all(
            'buttons=>buttons.map(button=>button.dataset.id)')

    def test_exact_day_updates_month_and_composes_with_search_type_person_and_category(self):
        self.prepare()
        self.page.locator('#fDay').fill('2026-10-30')
        self.assertEqual(self.page.locator('#fMonth').input_value(), '2026-10')
        self.assertEqual(set(self.row_ids()), {'daily-a','daily-b','daily-f'})
        self.assertIn('3 операции', self.page.locator('#historyCount').inner_text())
        self.page.locator('#fType').select_option('expense')
        self.assertEqual(set(self.row_ids()), {'daily-a','daily-b'})
        group=self.page.evaluate("expenseEntryGroup(state.entries.find(entry=>entry.id==='daily-a'))")
        self.page.locator('#fGroup').select_option(group)
        self.assertEqual(self.row_ids(), ['daily-a'])
        self.page.locator('#fWho').select_option(label='Сергей')
        self.page.locator('#fCat').select_option('Продукты')
        self.page.locator('#fSearch').fill('bakery')
        self.assertEqual(self.row_ids(), ['daily-a'])
        self.page.locator('#fSearch').fill('no such fictional shop')
        self.assertEqual(self.row_ids(), [])
        self.assertIn('0 операций', self.page.locator('#historyCount').inner_text())
        self.assertEqual(self.snapshot(), self.before)

    def test_month_change_clears_day_and_all_dates_clears_both_without_losing_other_filters(self):
        self.prepare()
        self.page.locator('#fDay').fill('2026-10-30')
        self.page.locator('#fMonth').fill('2026-11')
        self.assertEqual(self.page.locator('#fDay').input_value(), '')
        self.assertEqual(self.row_ids(), ['daily-d'])
        self.page.locator('#fType').select_option('expense')
        self.page.get_by_role('button', name='Все даты', exact=True).click()
        self.assertEqual(self.page.locator('#fMonth').input_value(), '')
        self.assertEqual(self.page.locator('#fDay').input_value(), '')
        self.assertEqual(self.page.locator('#fType').input_value(), 'expense')
        self.assertEqual(set(self.row_ids()), {'daily-a','daily-b','daily-c','daily-e'})
        self.assertEqual(self.snapshot(), self.before)

    def test_old_day_empty_day_and_reset_filters_keep_all_history(self):
        self.prepare()
        self.page.locator('#fDay').fill('2026-09-20')
        self.assertEqual(self.page.locator('#fMonth').input_value(), '2026-09')
        self.assertEqual(self.row_ids(), ['daily-e'])
        self.page.locator('#fDay').fill('2026-10-29')
        self.assertEqual(self.row_ids(), [])
        self.page.locator('#fDay').fill('')
        self.assertEqual(set(self.row_ids()), {'daily-a','daily-b','daily-c','daily-f'})
        self.page.locator('#fDay').fill('2026-10-30')
        self.page.locator('#fSearch').fill('Daily')
        self.page.get_by_role('button', name='Сбросить фильтры', exact=True).click()
        self.assertEqual(self.page.locator('#fMonth').input_value(), '')
        self.assertEqual(self.page.locator('#fDay').input_value(), '')
        self.assertEqual(self.page.locator('#fSearch').input_value(), '')
        self.assertEqual(set(self.row_ids()), {'daily-a','daily-b','daily-c','daily-d','daily-e','daily-f'})
        self.assertEqual(self.snapshot(), self.before)

    def test_recent_amount_and_actions_share_vertical_row_centre_with_long_comments(self):
        self.prepare()
        self.page.evaluate("""() => {
          state.entries[3].comment='Fictional long comment. '.repeat(25);
          state.entries[2].comment='Short comment';
          go('home');document.getElementById('home').classList.add('v73-focus');renderHome();
        }""")
        before = self.snapshot()
        for width in (1280,1536,1920):
            with self.subTest(width=width):
                self.page.set_viewport_size({'width':width,'height':1000})
                rows=self.page.evaluate("""() => {
                  const rect=el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,right:r.right,bottom:r.bottom}};
                  return [...document.querySelectorAll('#recent .v96-recent-row')].map(row=>{
                    const amount=row.querySelector('.v96-recent-amount'),range=document.createRange();range.selectNodeContents(amount);
                    const r=range.getBoundingClientRect();
                    return {row:rect(row),amount:{y:r.y,h:r.height},actions:rect(row.querySelector('.v96-recent-actions')),
                      buttons:[...row.querySelectorAll('button')].map(rect)};
                  });
                }""")
                self.assertEqual(len(rows), 3)
                centre=lambda r:r['y']+r['h']/2
                for row in rows:
                    self.assertLessEqual(abs(centre(row['amount'])-centre(row['row'])),2)
                    self.assertLessEqual(abs(centre(row['actions'])-centre(row['row'])),2)
                    for button in row['buttons']:
                        self.assertGreaterEqual(button['h'],44)
                        self.assertGreaterEqual(button['x'],row['row']['x'])
                        self.assertLessEqual(button['right'],row['row']['right']+1)
        self.page.set_viewport_size({'width':390,'height':844})
        self.assertEqual(self.page.locator('#recent .v96-recent-amount').first.evaluate('el=>getComputedStyle(el).gridRowStart'),'auto')
        self.assertEqual(self.snapshot(), before)

    def test_calendar_day_and_month_selection_updates_filters_and_custom_select_text(self):
        self.prepare()
        self.assertTrue(self.page.evaluate("typeof window.v108RefreshCalendars==='function'"))
        self.page.locator('#fDay').fill('2026-10-30')
        self.page.locator('#fDay').click()
        panel=self.page.locator('#v108CalendarPanel')
        self.assertTrue(panel.is_visible())
        panel.locator('button[data-date="2026-10-31"]').click()
        self.assertEqual(self.page.locator('#fDay').input_value(),'2026-10-31')
        self.assertEqual(self.page.locator('#fMonth').input_value(),'2026-10')
        self.assertEqual(self.row_ids(),['daily-c'])
        self.page.locator('#fMonth').click()
        panel.locator('button[data-month="11"]').click()
        self.assertEqual(self.page.locator('#fMonth').input_value(),'2026-11')
        self.assertEqual(self.page.locator('#fDay').input_value(),'')
        self.assertEqual(self.row_ids(),['daily-d'])
        type_picker=self.page.locator('#fType').locator('..').get_by_role('combobox')
        type_picker.click()
        self.page.get_by_role('option',name='Доходы',exact=True).click()
        self.assertIn('Доходы',type_picker.inner_text())
        self.page.get_by_role('button',name='Все даты',exact=True).click()
        self.assertEqual(self.page.locator('#fMonth').input_value(),'')
        self.assertEqual(self.page.locator('#fDay').input_value(),'')
        self.assertEqual(set(self.row_ids()),{'daily-d','daily-f'})
        self.assertIn('Доходы',type_picker.inner_text())
        self.page.locator('#fMonth').click()
        self.assertEqual(panel.locator('[role="gridcell"][aria-selected="true"]').count(),0)
        panel.get_by_role('button',name='Закрыть календарь',exact=True).click()
        self.page.get_by_role('button',name='Сбросить фильтры',exact=True).click()
        self.page.wait_for_function("document.querySelector('#fType + button, #fType ~ button').textContent.includes('Все операции')")
        self.assertIn('Все операции',type_picker.inner_text())
        self.assertEqual(set(self.row_ids()),{'daily-a','daily-b','daily-c','daily-d','daily-e','daily-f'})
        self.assertEqual(self.snapshot(),self.before)


if __name__ == '__main__':
    unittest.main()
