"""Read-only expense cuts have distinct visible context; fictional local records only."""
import os
from pathlib import Path
import unittest

from playwright.sync_api import expect

import test_local_data_safety as harness


class FinancialPresentation(unittest.TestCase):
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

    def prepare(self, width=1280):
        self.page.set_viewport_size({'width': width, 'height': 844})
        self.open()
        self.page.evaluate("""() => {
          session=null;stopCloudSync();localStorage.clear();state=blankState();
          telegramNotify=()=>Promise.resolve(false);
          const mk=(id,amount,category,extra={})=>({id,type:'expense',date:'2026-10-20',
            amount,category,who:'Сергей',beneficiary:'Сергей',store:'Учебный '+id,
            comment:'Только вымышленные данные',futureField:{keep:[true,null]},...extra});
          state.entries=[mk('fictional-food',100,'Продукты'),
            mk('fictional-fuel',300,'Бензин'),mk('fictional-credit',200,'Кредит'),
            mk('fictional-old-fraction',17.251,'Прочее',{date:'2026-09-19',who:'Виктория',beneficiary:''}),
            mk('fictional-income',2000,'Доход',{type:'income'}),
            mk('fictional-transfer',40,'Движение денег',{type:'transfer'})];
          state.futureField={keep:['fictional',false]};
          v84Data().accounts=[{id:'fictional-account',name:'Учебный счёт',amount:2000,
            updated_at:'2026-10-20T00:00:00Z',futureField:{keep:true}}];
          state.goals=[{id:'fictional-goal',name:'Учебная цель',target:9000,saved:17.251,
            monthly:2.25,futureField:{keep:true}}];
          weatherCache.data={temperature_2m:10,weather_code:0};weatherCache.at=Date.now();
          showApp();renderAll();
          for(const id of ['homeMonth','analyticsMonth'])document.getElementById(id).value='2026-10';
          for(const id of ['incomeMonth','carMonth'])document.getElementById(id).value='2026-11';
          document.getElementById('fMonth').value='2026-10';document.getElementById('fDay').value='2026-10-20';
          document.getElementById('eAmount').value='42,50';document.getElementById('eStore').value='Учебный черновик';
          document.getElementById('eDate').value='2026-11-02';document.getElementById('eComment').value='Сохранить черновик';
          renderHome();renderAnalytics();go('home');v97SetHomeOverview(false,false);
          document.querySelector('.v121-history-detail').open=true;
          window.__financialWrites=0;const original=saveAll;
          saveAll=function(...args){window.__financialWrites++;return original(...args)};
        }""")
        self.capture_before()

    def capture_before(self):
        self.before = self.snapshot()
        self.presentation_before = self.page.evaluate("""() => ({
          periods:Object.fromEntries(['homeMonth','analyticsMonth','incomeMonth','carMonth','fMonth','fDay']
            .map(id=>[id,document.getElementById(id).value])),
          draft:v97DraftFields(),balances:['2026-09','2026-10','2026-11'].map(v111MonthBalance),
          manual:v86CurrentAccounts().total})""")

    def assert_unchanged(self):
        self.assertEqual(self.snapshot(), self.before)
        current = self.page.evaluate("""() => ({
          periods:Object.fromEntries(['homeMonth','analyticsMonth','incomeMonth','carMonth','fMonth','fDay']
            .map(id=>[id,document.getElementById(id).value])),
          draft:v97DraftFields(),balances:['2026-09','2026-10','2026-11'].map(v111MonthBalance),
          manual:v86CurrentAccounts().total})""")
        self.assertEqual(current, self.presentation_before)
        self.assertEqual(self.page.evaluate('window.__financialWrites'), 0)

    def recipient_tile(self):
        return self.page.locator('#v99HomeDirectionTiles [data-v99-direction="person:Сергей"]')

    def exclusive_button(self, source='home'):
        root = '#familyBars' if source == 'home' else '#aPeopleChart'
        return self.page.locator(root+' button').filter(has_text='Сергей')

    def drill_ids(self):
        return self.page.locator('#v84DrillEntries [data-record-action="drill-entry-edit"]').evaluate_all(
            '(nodes)=>nodes.map(node=>JSON.parse(node.dataset.recordArgs)[0]).sort()')

    def assert_scope_description(self, expected):
        dialog = self.page.locator('#v84DrillModal .v84-modal')
        expect(dialog).to_have_attribute('aria-describedby', 'v114DrillScopeNote')
        expect(self.page.locator('#v114DrillScopeNote')).to_contain_text(expected)

    def close_drill(self):
        self.page.locator('#v84DrillModal .v84-close').click()
        expect(self.page.locator('#v84DrillModal')).to_be_hidden()

    def test_home_explains_100_exclusive_and_600_inclusive_and_opens_exact_rows(self):
        self.prepare()
        expect(self.page.locator('#v114ExclusiveScope')).to_contain_text('не входят в суммы по получателям')
        expect(self.page.locator('#v114InclusiveScope')).to_contain_text('включены все их покупки')
        self.assertEqual(self.recipient_tile().locator('span').inner_text(), 'Сергей · все покупки')
        self.assertIn('100,00', self.exclusive_button().inner_text())
        self.assertIn('600,00', self.recipient_tile().inner_text())
        self.assertIn('600,00', self.page.locator('#v99HomeExpenseTotal').inner_text())
        self.exclusive_button().click()
        self.assert_scope_description('нет автомобильных расходов')
        self.assertEqual(self.drill_ids(), ['fictional-food'])
        self.assertIn('100,00', self.page.locator('#v96DrillTotal').inner_text())
        self.close_drill()
        self.recipient_tile().click()
        expect(self.page.locator('#v84DrillTitle')).to_have_text('Сергей · все покупки')
        self.assert_scope_description('включая автомобиль и кредитные платежи')
        self.assertEqual(self.drill_ids(), ['fictional-credit', 'fictional-food', 'fictional-fuel'])
        self.assertIn('600,00', self.page.locator('#v96DrillTotal').inner_text())
        self.close_drill()
        self.assert_unchanged()

    def test_analytics_and_nested_cancel_keep_exclusive_scope_and_existing_filters(self):
        self.prepare()
        self.page.evaluate("go('analytics')")
        expect(self.page.locator('#peopleChartHint')).to_contain_text('выделены отдельно от получателей')
        self.exclusive_button('analytics').click()
        self.assert_scope_description('нет автомобильных расходов')
        self.assertEqual(self.drill_ids(), ['fictional-food'])
        self.page.locator('#v84DrillEntries [data-record-action="drill-entry-edit"]').click()
        self.page.keyboard.press('Escape')
        expect(self.page.locator('#editModal')).to_be_hidden()
        expect(self.page.locator('#v84DrillModal')).to_be_visible()
        self.assert_scope_description('нет автомобильных расходов')
        self.assertEqual(self.drill_ids(), ['fictional-food'])
        self.close_drill()
        self.assert_unchanged()

    def test_directions_and_untrusted_legacy_recipient_are_text_and_group_has_no_stale_description(self):
        self.prepare()
        name = 'Учебный <img src=x>'
        self.page.evaluate("""name=>{
          state.entries.push({id:'fictional-untrusted',type:'expense',date:'2026-10-20',amount:12.25,
            category:'Продукты',who:name,beneficiary:name,store:'Учебный магазин',futureField:{keep:true}});
          renderHome();renderAnalytics();
        }""", name)
        self.capture_before()
        tile = self.page.locator('#v99HomeDirectionTiles button').filter(has_text=name)
        expect(tile.locator('span')).to_have_text(name+' · все покупки')
        self.assertEqual(tile.locator('img').count(), 0)
        tile.click()
        expect(self.page.locator('#v84DrillTitle')).to_have_text(name+' · все покупки')
        self.assertEqual(self.drill_ids(), ['fictional-untrusted'])
        self.assert_scope_description('Все покупки указанного получателя')
        self.close_drill()
        self.page.locator('#v99HomeDirectionTiles [data-v99-direction="car"]').click()
        expect(self.page.locator('#v84DrillTitle')).to_have_text('Автомобиль')
        self.assert_scope_description('Тематический срез')
        self.assertEqual(self.drill_ids(), ['fictional-fuel'])
        self.close_drill()
        self.page.locator('#categoryLegend button').first.click()
        self.assertIsNone(self.page.locator('#v84DrillModal .v84-modal').get_attribute('aria-describedby'))
        self.assertEqual(self.page.locator('#v114DrillScopeNote').count(), 0)
        self.close_drill()
        self.assert_unchanged()

    def scale_financial_text(self, factor):
        self.page.evaluate("""factor=>{
          const selectors=['#v99TargetScaleTitle','#v114ExclusiveScope','#v99DirectionTitle','#v114InclusiveScope',
            '#v99HomeDirectionTiles button span','#v99HomeDirectionTiles button strong','#v84DrillTitle','#v114DrillScopeNote'];
          const nodes=[...document.querySelectorAll(selectors.join(','))].filter(el=>!el.dataset.scopeTextScale);
          const sizes=nodes.map(el=>parseFloat(getComputedStyle(el).fontSize));
          nodes.forEach((el,index)=>{el.dataset.scopeTextScale='1';el.style.setProperty('font-size',sizes[index]*factor+'px','important')});
        }""", factor)

    def assert_text_bounds(self, selectors):
        rows = self.page.locator(selectors).evaluate_all("""nodes=>nodes.map(el=>{
          const box=el.getBoundingClientRect(),range=document.createRange();range.selectNodeContents(el);
          return {text:el.textContent,visible:box.width>0&&box.height>0,
            overflow:[...range.getClientRects()].filter(r=>r.width&&r.height).some(r=>
              r.left<box.left-1||r.right>box.right+1||r.top<box.top-1||r.bottom>box.bottom+1),
            offscreen:box.left<0||box.right>innerWidth};
        })""")
        self.assertTrue(rows)
        for row in rows:
            self.assertTrue(row['visible'], row)
            self.assertFalse(row['overflow'], row)
            self.assertFalse(row['offscreen'], row)

    def test_scope_explanations_and_recipient_labels_reflow_at_320_through_desktop_and_200_percent(self):
        for width in (320, 390, 844, 1280):
            for factor in (1, 2):
                with self.subTest(width=width, text_scale=factor):
                    self.prepare(width)
                    self.scale_financial_text(factor)
                    self.assert_text_bounds('#v114ExclusiveScope,#v114InclusiveScope,#v99HomeDirectionTiles button span')
                    self.recipient_tile().click()
                    self.scale_financial_text(factor)
                    self.assert_scope_description('включая автомобиль и кредитные платежи')
                    self.assert_text_bounds('#v84DrillTitle,#v114DrillScopeNote')
                    title_words = self.page.locator('#v84DrillTitle').evaluate("""el=>{
                      const node=el.firstChild;return [...node.textContent.matchAll(/[А-Яа-яЁё]+/g)].map(match=>{
                        const range=document.createRange();range.setStart(node,match.index);range.setEnd(node,match.index+match[0].length);
                        return {word:match[0],lines:new Set([...range.getClientRects()].map(r=>Math.round(r.top))).size};
                      })
                    }""")
                    for word in title_words:
                        self.assertEqual(word['lines'], 1, word)
                    shot_dir = os.environ.get('MARICHEVY_FINANCIAL_SCREENSHOTS')
                    if shot_dir and factor == 2 and width in (320, 390):
                        Path(shot_dir).mkdir(parents=True, exist_ok=True)
                        self.page.screenshot(path=str(Path(shot_dir)/f'scope-drill-{width}-text200.png'))
                    self.close_drill()
                    self.assert_unchanged()


if __name__ == '__main__':
    unittest.main()
