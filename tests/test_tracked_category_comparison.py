"""Tracked categories compare eligible calendar months without changing money."""
import unittest

import test_tracked_categories as tracked_base


class TrackedCategoryComparison(unittest.TestCase):
    setUpClass = classmethod(tracked_base.TrackedCategories.setUpClass.__func__)
    tearDownClass = classmethod(tracked_base.TrackedCategories.tearDownClass.__func__)
    tearDown = tracked_base.TrackedCategories.tearDown
    evaluate = tracked_base.TrackedCategories.evaluate

    def setUp(self):
        tracked_base.TrackedCategories.setUp(self)
        self.evaluate('''
          state.settings.preferences.trackedExpenseCategories=
            ['Подписки','Подарки','Рестораны и кафе','Продукты','Дом','Одежда'];
          const e=(id,amount,category,date='2026-11-05',extra={})=>
            trackedEntry(id,amount,category,'Общее',{date,...extra});
          state.entries=[e('sub-cent',.10,'Подписки'),e('sub-main',99.90,'Подписки и онлайн-сервисы'),
            e('prior-sub-first',50,'Подписки и сервисы','2026-10-01'),
            e('prior-sub-last',150,'Подписки','2026-10-31'),
            e('not-previous',9000,'Подписки','2026-09-30'),e('future',8000,'Подписки','2026-12-01'),
            e('gift',150,'Подарки'),e('prior-gift',100,'Подарки','2026-10-15'),
            e('cafe',50,'Кафе и доставка'),e('prior-food',20,'Продукты','2026-10-01'),
            e('home',10,'Дом'),e('prior-home',10,'Дом и быт','2026-10-01'),
            e('invalid-prior',10000,'Подписки','2026-10-32'),
            e('invalid-current',10000,'Подписки','2026-11-31'),
            e('negative-prior',-500,'Подписки','2026-10-05'),
            e('adjustment',500,'Подписки','2026-10-05',{balanceAdjustment:true}),
            e('income',500,'Подписки','2026-10-05',{type:'income'}),
            e('deleted',500,'Подписки','2026-10-05')];
          state.deletedEntries={deleted:'2026-11-06T10:00:00.000Z'};renderAll();
          window.comparisonRead=()=>[...document.querySelectorAll('#v175TrackedCards [data-v175-category]')]
            .map(card=>{const comparison=card.querySelector('.v182-month-comparison');return {
              key:card.dataset.v175Category,amount:card.querySelector('.v175-tracked-amount').textContent.replace(/\\s/g,' '),
              comparison:comparison?{tone:comparison.dataset.tone,previous:comparison.dataset.previousMonth,
                text:comparison.textContent.replace(/\\s/g,' '),
                color:getComputedStyle(comparison.querySelector('.v182-comparison-change')).color}:null};});
        ''')

    def test_canonical_live_expenses_use_the_whole_previous_calendar_month_and_exact_deltas(self):
        data = self.evaluate('''
          const before=JSON.stringify(state);renderHome();renderHome();
          const rows=v175TrackedSpending('2026-11'),cards=comparisonRead();
          trackedCard('Подписки').querySelector('.v182-comparison-change').click();
          return {rows,cards,unchanged:JSON.stringify(state)===before,drill:trackedDrill()};
        ''')
        rows = {row['key']: row for row in data['rows']}
        expected = {
            'Подписки': (100, 200, -100, -50, 'good'),
            'Подарки': (150, 100, 50, 50, 'bad'),
            'Рестораны и кафе': (50, 0, 50, None, 'bad'),
            'Продукты': (0, 20, -20, -100, 'good'),
            'Дом': (10, 10, 0, 0, 'neutral'),
            'Одежда': (0, 0, 0, 0, 'neutral'),
        }
        for key, values in expected.items():
            row = rows[key]
            self.assertEqual(row['previousMonth'], '2026-10')
            self.assertEqual((row['amount'], row['previousAmount'], row['comparison']['delta'],
                              row['comparison']['percent'], row['comparison']['tone']), values)
        cards = {card['key']: card for card in data['cards']}
        self.assertEqual(cards['Подписки']['amount'], '100,00 ₽')
        self.assertIn('−50%', cards['Подписки']['comparison']['text'])
        self.assertIn('−100,00 ₽', cards['Подписки']['comparison']['text'])
        self.assertIn('октябрь 2026', cards['Подписки']['comparison']['text'])
        self.assertIn('0 ₽', cards['Рестораны и кафе']['comparison']['text'])
        self.assertNotIn('%', cards['Рестораны и кафе']['comparison']['text'])
        self.assertNotEqual(cards['Подписки']['comparison']['color'], cards['Подарки']['comparison']['color'])
        self.assertNotEqual(cards['Подарки']['comparison']['color'], cards['Дом']['comparison']['color'])
        self.assertTrue(data['unchanged'])
        self.assertEqual((data['drill']['scope'], data['drill']['key'], data['drill']['total']),
                         ('month', 'Подписки', '100,00 ₽'))
        self.assertEqual(set(data['drill']['ids']), {'sub-cent', 'sub-main'})

    def test_january_compares_to_previous_december_and_all_time_hides_the_comparison(self):
        data = self.evaluate('''
          state.entries=[trackedEntry('jan',25,'Подписки','Общее',{date:'2027-01-05'}),
            trackedEntry('dec',100,'Подписки и онлайн-сервисы','Общее',{date:'2026-12-31'}),
            trackedEntry('nov',400,'Подписки','Общее',{date:'2026-11-05'})];
          refreshHistoryPeriods();document.getElementById('homeMonth').value='2027-01';renderHome();
          const january={row:v175TrackedSpending()[0],card:comparisonRead()[0]};
          document.getElementById('homeMonth').value='all';renderHome();
          const all={rows:v175TrackedSpending(),cards:comparisonRead(),
            count:document.querySelectorAll('#v175TrackedCards .v182-month-comparison').length};
          document.getElementById('homeMonth').value='2027-01';renderHome();
          return {january,all,returned:comparisonRead()[0]};
        ''')
        self.assertEqual((data['january']['row']['previousMonth'], data['january']['row']['previousAmount']),
                         ('2026-12', 100))
        self.assertEqual((data['january']['row']['comparison']['delta'], data['january']['row']['comparison']['percent']),
                         (-75, -75))
        self.assertIn('декабрь 2026', data['january']['card']['comparison']['text'])
        self.assertEqual(data['all']['rows'][0]['amount'], 525)
        self.assertEqual(data['all']['count'], 0)
        self.assertTrue(all(row['comparison'] is None and row['previousAmount'] is None
                            for row in data['all']['rows']))
        self.assertEqual(data['returned']['comparison']['previous'], '2026-12')

    def test_comparison_updates_after_real_edit_and_delete_without_changing_tracking_preferences(self):
        data = self.evaluate('''
          const preferences=JSON.stringify(state.settings.preferences);
          trackedCard('Подарки').querySelector('[data-v175-open]').click();
          v96EditFromDrill('gift');document.getElementById('xAmount').value='50';await saveEdit();
          const edited={row:v175TrackedSpending().find(row=>row.key==='Подарки'),drill:trackedDrill()};
          v84CloseDrill();await deleteEntry('prior-gift');
          return {edited,after:v175TrackedSpending().find(row=>row.key==='Подарки'),cards:comparisonRead(),
            samePreferences:JSON.stringify(state.settings.preferences)===preferences};
        ''')
        self.assertEqual((data['edited']['row']['amount'], data['edited']['row']['comparison']['delta'],
                          data['edited']['row']['comparison']['tone']), (50, -50, 'good'))
        self.assertEqual((data['edited']['drill']['scope'], data['edited']['drill']['total']), ('month', '50,00 ₽'))
        self.assertEqual((data['after']['previousAmount'], data['after']['comparison']['percent'],
                          data['after']['comparison']['tone']), (0, None, 'bad'))
        self.assertTrue(data['samePreferences'])

    def test_compact_comparisons_and_actions_fit_small_and_large_screens(self):
        self.evaluate('''
          state.entries=[trackedEntry('large',1234567890.12,'Подписки'),
            trackedEntry('large-prior',.01,'Подписки','Общее',{date:'2026-10-31'})];
          v97SetHomeOverview(false);for(let parent=document.getElementById('v99HomeSlices').parentElement;parent;parent=parent.parentElement)
            if(parent.tagName==='DETAILS')parent.open=true;renderHome();
        ''')
        for width in [320, 360, 390, 430, 560, 768, 1024, 1440]:
            self.page.set_viewport_size({'width': width, 'height': 1000})
            data = self.evaluate('''
              const root=document.getElementById('v99HomeSlices');
              return {page:document.documentElement.scrollWidth<=innerWidth+1,
                overflow:[...root.querySelectorAll('.v175-tracked-card,.v175-tracked-card-head,.v175-tracked-money,.v182-month-comparison')]
                  .filter(node=>node.getClientRects().length).some(node=>node.scrollWidth>node.clientWidth+1),
                invalid:/NaN|Infinity|undefined/.test(root.textContent),
                buttons:root.querySelectorAll('[data-v175-open]').length,
                compact:[...root.querySelectorAll('.v182-comparison-change,.v182-comparison-period')]
                  .every(node=>parseFloat(getComputedStyle(node).fontSize)>=11&&parseFloat(getComputedStyle(node).fontSize)<=12)};
            ''')
            with self.subTest(width=width):
                self.assertTrue(data['page'])
                self.assertFalse(data['overflow'])
                self.assertFalse(data['invalid'])
                self.assertTrue(data['compact'])
                self.assertEqual(data['buttons'], 6)


if __name__ == '__main__':
    unittest.main()
