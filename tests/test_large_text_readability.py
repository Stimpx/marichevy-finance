"""Large-text readability with fictional local data and all external traffic blocked."""
from pathlib import Path
import os
import unittest

from playwright.sync_api import expect

import test_local_data_safety as harness


class LargeTextReadability(unittest.TestCase):
    PROFILES = ((320, 740), (390, 844), (430, 932), (844, 390),
                (820, 1180), (1024, 768), (1920, 1080))

    @classmethod
    def setUpClass(cls):
        harness.LocalDataSafety.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        harness.LocalDataSafety.tearDownClass.__func__(cls)

    def setUp(self):
        self.context = self.browser.new_context(
            viewport={'width': 390, 'height': 844}, has_touch=True,
            timezone_id='Europe/Moscow', service_workers='block', reduced_motion='reduce')
        self.context.route('**/*', lambda route: route.continue_()
                           if route.request.url.startswith(self.base) else route.abort())
        self.page = self.context.new_page()
        self.page.set_default_timeout(4000)
        self.page.on('dialog', lambda dialog: dialog.dismiss())

    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open
    snapshot = harness.LocalDataSafety.snapshot

    def prepare(self, width, height, tab='income', empty=False):
        self.page.set_viewport_size({'width': width, 'height': height})
        self.open()
        self.page.evaluate("""({tab,empty})=>{
          session=null;stopCloudSync();localStorage.clear();state=blankState();
          today=()=> '2026-11-01';month=()=> '2026-11';
          telegramNotify=async()=>false;
          weatherCache.data={temperature_2m:10,weather_code:0};weatherCache.at=Date.now();
          loanScheduleData=()=>[{n:1,payDate:'2099-12-01',periodEnd:'2099-12-01',
            payment:1,interest:0,body:1,balance:0}];
          state.futureReadability={preserve:['fictional',null,true]};
          if(!empty){
            state.entries=[{id:'fictional-income-large',type:'income',date:'2026-11-01',
              amount:123456789.12,category:'Доход',
              who:'Вымышленный участник с длинным именем',
              store:'Вымышленный источник дополнительного семейного дохода',
              comment:'Длинное учебное описание поступления для проверки переносов',
              futureField:{preserve:'original'}},
              {id:'fictional-income-small',type:'income',date:'2026-11-01',amount:234.56,
              category:'Доход',who:'Сергей',store:'Учебный доход',comment:'Тестовая запись'},
              {id:'fictional-expense-untouched',type:'expense',date:'2026-10-31',amount:17.251,
              category:'Прочее',who:'Не указано',futureField:{preserve:'sub-cent'}}];
            state.goals=[{id:'fictional-readability-goal',name:'Вымышленная цель с длинным названием',
              target:2000000000,saved:123457023.68,monthly:0,
              deposits:[{id:'fictional-deposit-large',amount:123456789.12,date:'2026-11-01',
                who:'Вымышленный участник с длинным именем для проверки переносов',
                futureField:{preserve:'original'}},
                {id:'fictional-deposit-small',amount:234.56,date:'2026-10-31',who:'Сергей'}],
              futureField:{preserve:'goal'}}];
          }
          localStorage.setItem('fictional-readability-sentinel','unchanged');
          showApp();renderAll();
          document.getElementById('incomeMonth').value='2026-11';
          renderIncome();go(tab);
          window.__readabilityFormatted={
            income:state.entries.filter(e=>e.type==='income').map(e=>money(e.amount)),
            deposits:(state.goals[0]?.deposits||[]).map(d=>money2(d.amount))};
          window.__readabilityFontOverrides=new Map();
        }""", {'tab': tab, 'empty': empty})
        self.before = self.snapshot()

    def scale_text(self, scale):
        # Restore prior test overrides before measuring to avoid multiplying inherited sizes twice.
        self.page.evaluate("""scale=>{
          for(const [el,old] of window.__readabilityFontOverrides){
            if(old.value)el.style.setProperty('font-size',old.value,old.priority);
            else el.style.removeProperty('font-size');
          }
          window.__readabilityFontOverrides.clear();
          const nodes=[...document.querySelectorAll('body,body *')]
            .filter(el=>!['SCRIPT','STYLE','SVG','PATH'].includes(el.tagName));
          const sizes=nodes.map(el=>parseFloat(getComputedStyle(el).fontSize));
          nodes.forEach((el,i)=>{
            window.__readabilityFontOverrides.set(el,{value:el.style.getPropertyValue('font-size'),
              priority:el.style.getPropertyPriority('font-size')});
            if(sizes[i])el.style.setProperty('font-size',sizes[i]*scale+'px','important');
          });
        }""", scale)
        self.page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')

    def assert_text_fits(self, selector):
        result = self.page.locator(selector).evaluate_all(r"""nodes=>nodes.filter(el=>el.getClientRects().length).map(el=>{
          const box=el.getBoundingClientRect();let left=Math.max(0,box.left),right=Math.min(innerWidth,box.right);
          for(let p=el.parentElement;p;p=p.parentElement){
            const style=getComputedStyle(p);
            if(['hidden','clip','auto','scroll'].includes(style.overflowX)){
              const r=p.getBoundingClientRect();left=Math.max(left,r.left);right=Math.min(right,r.right);
            }
          }
          const fragments=[],walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT);
          while(walker.nextNode()){
            const node=walker.currentNode;
            if(!node.textContent.trim())continue;
            const range=document.createRange();range.selectNodeContents(node);
            for(const r of range.getClientRects())if(r.width&&r.height)
              fragments.push({left:r.left,right:r.right,top:r.top,bottom:r.bottom});
          }
          return {text:el.textContent.trim(),left,right,fragments};
        })""")
        self.assertTrue(result, selector)
        for item in result:
            self.assertTrue(item['fragments'], item['text'])
            for fragment in item['fragments']:
                self.assertGreaterEqual(fragment['left'] + 1, item['left'], item)
                self.assertLessEqual(fragment['right'], item['right'] + 1, item)

    def assert_income_layout(self):
        self.assert_text_fits('#income .money-green,#incomePeopleDonutTotal,#incomePeopleLegend b')
        self.assert_text_fits('#incomeList .bar-top>span,#incomePeopleLegend>div>span:not(.legend-dot)')
        rows = self.page.locator('#incomeList .bar-row').evaluate_all("""nodes=>nodes.map(row=>{
          const label=row.querySelector('.bar-top>span').getBoundingClientRect(),
            amount=row.querySelector('.bar-top>b').getBoundingClientRect(),
            actions=row.querySelector('.actions').getBoundingClientRect();
          const intersection=(a,b)=>Math.max(0,Math.min(a.right,b.right)-Math.max(a.left,b.left))*
            Math.max(0,Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top));
          return {labelAmount:intersection(label,amount),amountActions:intersection(amount,actions)};
        })""")
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertLessEqual(row['labelAmount'], 1, row)
            self.assertLessEqual(row['amountActions'], 1, row)
        expected = self.page.evaluate('window.__readabilityFormatted.income')
        for value in expected:
            self.assertIn(value, self.page.locator('#incomeList').inner_text())

    def assert_money_groups_whole(self, selector):
        groups = self.page.locator(selector).evaluate_all(r"""nodes=>nodes.filter(el=>el.getClientRects().length)
          .flatMap(el=>{
            const out=[],walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT);
            while(walker.nextNode()){
              const node=walker.currentNode;
              for(const match of node.textContent.matchAll(/\S+/g)){
                const range=document.createRange();range.setStart(node,match.index);
                range.setEnd(node,match.index+match[0].length);
                const rects=[...range.getClientRects()].filter(r=>r.width&&r.height);
                out.push({text:match[0],lines:new Set(rects.map(r=>Math.round(r.top))).size});
              }
            }
            return out;
          })""")
        self.assertTrue(groups, selector)
        for group in groups:
            self.assertEqual(group['lines'], 1, group)

    def assert_nav_layout(self):
        nav = self.page.locator('#mobileNav')
        expect(nav).to_be_visible()
        self.assert_text_fits('#mobileNav button span')
        layout = nav.evaluate("""nav=>{
          const rect=nav.getBoundingClientRect();return {left:rect.left,right:rect.right,
            bottom:rect.bottom,top:rect.top,height:rect.height,viewport:innerHeight,
            width:innerWidth,padding:parseFloat(getComputedStyle(document.querySelector('.main')).paddingBottom),
            buttons:[...nav.querySelectorAll('button')].map(button=>{
              const r=button.getBoundingClientRect(),label=button.querySelector('span').getBoundingClientRect();
              const hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
              return {width:r.width,height:r.height,labelLeft:label.left,labelRight:label.right,
                left:r.left,right:r.right,top:r.top,bottom:r.bottom,hit:button.contains(hit)};
            })};
        }""")
        self.assertGreaterEqual(layout['left'], 0)
        self.assertLessEqual(layout['right'], layout['width'])
        self.assertLessEqual(layout['bottom'], layout['viewport'] + 1)
        self.assertGreaterEqual(layout['padding'] + 1, layout['viewport'] - layout['top'])
        self.assertEqual(len(layout['buttons']), 5)
        for button in layout['buttons']:
            self.assertGreaterEqual(button['width'], 44)
            self.assertGreaterEqual(button['height'], 44)
            self.assertGreaterEqual(button['labelLeft'] + 1, button['left'])
            self.assertLessEqual(button['labelRight'], button['right'] + 1)
            self.assertTrue(button['hit'], button)

    def test_income_names_and_amounts_fit_at_large_text_before_and_after_render(self):
        for width, height in self.PROFILES:
            for scale in (1.5, 2):
                for order in ('before', 'after'):
                    with self.subTest(width=width, scale=scale, order=order):
                        self.prepare(width, height)
                        if order == 'before':
                            self.scale_text(scale)
                            self.page.evaluate('renderIncome()')
                        self.scale_text(scale)
                        self.assert_income_layout()
                        self.assertEqual(self.snapshot(), self.before)

    def test_goal_deposit_history_keeps_dates_names_and_full_amounts_readable(self):
        for width, height in self.PROFILES:
            for scale in (1.5, 2):
                with self.subTest(width=width, scale=scale):
                    self.prepare(width, height, 'goals')
                    self.scale_text(scale)
                    self.page.evaluate('renderGoals()')
                    self.scale_text(scale)
                    self.page.locator('.v78-goal-history summary').click()
                    self.assert_text_fits('.v78-goal-history-row>span,.v78-goal-history-row>b')
                    for value in self.page.evaluate('window.__readabilityFormatted.deposits'):
                        self.assertIn(value, self.page.locator('.v78-goal-history').inner_text())
                    self.assertEqual(self.snapshot(), self.before)
                    shot_dir = os.environ.get('MARICHEVY_READABILITY_SCREENSHOTS')
                    if shot_dir and scale == 2 and width in (320, 390):
                        Path(shot_dir).mkdir(parents=True, exist_ok=True)
                        self.page.locator('.v78-goal-history').screenshot(
                            path=str(Path(shot_dir) / f'goal-history-{width}-text200.png'),
                            style='#mobileNav{visibility:hidden!important}')

    def test_bottom_labels_targets_and_more_follow_real_nav_height_when_text_changes(self):
        for width, height in self.PROFILES[:-1]:
            with self.subTest(width=width, height=height):
                self.prepare(width, height, 'home')
                self.assert_nav_layout()
                normal_height = self.page.locator('#mobileNav').bounding_box()['height']
                self.scale_text(2)
                self.assert_nav_layout()
                if width <= 430:
                    self.assertGreater(self.page.locator('#mobileNav').bounding_box()['height'], normal_height)
                self.page.locator('#v74MoreToggle').tap()
                panel = self.page.locator('#v74MorePanel')
                expect(panel).to_be_visible()
                bounds = panel.evaluate("""panel=>{
                  const r=panel.getBoundingClientRect(),nav=mobileNav.getBoundingClientRect();
                  return {top:r.top,bottom:r.bottom,navTop:nav.top,left:r.left,right:r.right,width:innerWidth};
                }""")
                self.assertGreaterEqual(bounds['top'], 0)
                self.assertLessEqual(bounds['bottom'], bounds['navTop'])
                self.assertGreaterEqual(bounds['left'], 0)
                self.assertLessEqual(bounds['right'], bounds['width'])
                self.assert_text_fits('#v74MorePanel button span')
                button = panel.locator('button[data-page="goals"]')
                button.scroll_into_view_if_needed()
                button.tap()
                expect(self.page.locator('#goals')).to_be_visible()
                expect(panel).to_be_hidden()
                self.assert_nav_layout()
                self.assertEqual(self.snapshot(), self.before)

    def test_empty_income_and_goals_remain_readable_without_data_or_storage_writes(self):
        for tab in ('income', 'goals'):
            for width, height in ((320, 740), (390, 844), (844, 390), (820, 1180), (1920, 1080)):
                with self.subTest(tab=tab, width=width):
                    self.prepare(width, height, tab, empty=True)
                    self.scale_text(2)
                    selector = '#incomeList .empty' if tab == 'income' else '#goalsList .goal-empty'
                    self.assert_text_fits(selector)
                    self.assertEqual(self.snapshot(), self.before)

    def test_open_more_tracks_nav_growth_shrink_and_rotation_without_stale_spacing(self):
        self.prepare(1920, 1080, 'home')
        desktop_padding = self.page.locator('.main').evaluate(
            '(el)=>parseFloat(getComputedStyle(el).paddingBottom)')
        self.page.set_viewport_size({'width': 390, 'height': 844})
        expect(self.page.locator('#mobileNav')).to_be_visible()
        initial = self.page.locator('#mobileNav').bounding_box()['height']
        self.page.locator('#v74MoreToggle').tap()
        panel = self.page.locator('#v74MorePanel')
        for scale, width, height in ((2, 390, 844), (2, 844, 390),
                                     (1.5, 820, 1180), (1, 390, 844)):
            with self.subTest(scale=scale, width=width, height=height):
                self.page.set_viewport_size({'width': width, 'height': height})
                self.scale_text(scale)
                expect(panel).to_be_visible()
                self.assertTrue(panel.evaluate("""panel=>{
                  const p=panel.getBoundingClientRect(),n=mobileNav.getBoundingClientRect();
                  return p.top>=0&&p.bottom<=n.top;
                }"""))
                self.assert_text_fits('#mobileNav button span')
        self.page.keyboard.press('Escape')
        self.assert_nav_layout()
        self.assertAlmostEqual(self.page.locator('#mobileNav').bounding_box()['height'], initial, delta=1)
        self.page.set_viewport_size({'width': 1920, 'height': 1080})
        expect(self.page.locator('#mobileNav')).to_be_hidden()
        self.assertAlmostEqual(self.page.locator('.main').evaluate(
            '(el)=>parseFloat(getComputedStyle(el).paddingBottom)'), desktop_padding, delta=1)
        self.assertEqual(self.snapshot(), self.before)

    def test_trillion_scale_income_and_goal_deposits_keep_all_digits_and_original_values(self):
        for width, height in ((320, 740), (390, 844)):
            with self.subTest(width=width):
                self.prepare(width, height)
                self.page.evaluate("""()=>{
                  state.entries[0].amount=999999999999.99;
                  state.goals[0].target=2000000000000;
                  state.goals[0].saved=999999999999.99;
                  state.goals[0].deposits[0].amount=999999999999.99;
                  renderAll();document.getElementById('incomeMonth').value='2026-11';
                  renderIncome();go('income');
                  window.__readabilityFormatted={
                    income:state.entries.filter(e=>e.type==='income').map(e=>money(e.amount)),
                    deposits:state.goals[0].deposits.map(d=>money2(d.amount))};
                }""")
                self.before = self.snapshot()
                self.scale_text(2)
                self.assert_income_layout()
                self.assert_money_groups_whole(
                    '#income .money-green,#incomePeopleDonutTotal,#incomePeopleLegend b')
                shot_dir = os.environ.get('MARICHEVY_READABILITY_SCREENSHOTS')
                if shot_dir:
                    Path(shot_dir).mkdir(parents=True, exist_ok=True)
                    for name, selector in (('income-list', '#incomeList'),
                                           ('income-legend', '#incomePeopleLegend')):
                        self.page.locator(selector).screenshot(
                            path=str(Path(shot_dir) / f'{name}-{width}-text200.png'),
                            style='#mobileNav{visibility:hidden!important}')
                self.page.evaluate("go('goals')")
                self.scale_text(2)
                self.page.locator('.v78-goal-history summary').click()
                self.assert_text_fits('.v78-goal-history-row>span,.v78-goal-history-row>b')
                self.assert_money_groups_whole('.v78-goal-history-row>b')
                for value in self.page.evaluate('window.__readabilityFormatted.deposits'):
                    self.assertIn(value, self.page.locator('.v78-goal-history').inner_text())
                if shot_dir:
                    self.page.locator('.v78-goal-history').screenshot(
                        path=str(Path(shot_dir) / f'goal-history-max-{width}-text200.png'),
                        style='#mobileNav{visibility:hidden!important}')
                self.assertEqual(self.page.evaluate('state.entries[0].amount'), 999999999999.99)
                self.assertEqual(self.page.evaluate('state.goals[0].deposits[0].amount'), 999999999999.99)
                self.assertEqual(self.snapshot(), self.before)


if __name__ == '__main__':
    unittest.main()
