"""Daily overview and browser navigation; fictional data, no authenticated requests."""
import re
import unittest

from playwright.sync_api import expect

import test_local_data_safety as harness


class HumanNavigation(unittest.TestCase):
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
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.open()
        self.period = self.page.evaluate("""() => {
          session=null;stopCloudSync();localStorage.clear();state=blankState();
          const m=previousMonthKey(month());
          state.entries=[
            {id:'fictional-prior-income',type:'income',date:previousMonthKey(m)+'-03',
             amount:1500.125,category:'Зарплата',who:'Учебный участник',store:'',comment:'',
             futureField:{keep:[true,null,{untouched:'legacy subcent'}]}},
            ...Array.from({length:16},(_,i)=>({id:'fictional-row-'+i,type:'expense',
             date:m+'-'+String(i+1).padStart(2,'0'),amount:10+i/10,
             category:i%2?'Продукты':'ЖКХ',who:'Сергей',beneficiary:'Сергей',
             store:'Fictional store '+i,comment:'Only fictional navigation data'}))
          ];
          state.settings.unknownNavigationExtension={preserve:true};
          weatherCache.data={temperature_2m:10,weather_code:0};weatherCache.at=Date.now();
          localStorage.setItem('fictional-navigation-sentinel','keep');
          showApp();homeMonth.value=m;analyticsMonth.value=m;renderAll();go('home');
          return m;
        }""")
        self.before = self.stable_snapshot()
        self.assertEqual(self.errors, [])

    def stable_snapshot(self):
        result = self.snapshot()
        for key in ('marichevy_weather_last_good_v74', 'marichevy_v73_short_overview'):
            result['storage'].pop(key, None)
        return result

    def assert_readonly(self):
        self.assertEqual(self.stable_snapshot(), self.before)
        self.assertEqual(self.errors, [])

    def test_home_preserves_carry_and_has_three_records_and_optional_details(self):
        self.prepare()
        expect(self.page.locator('#v121HomeAvailableTitle')).to_have_text('Остаток по истории')
        self.assertEqual(self.page.locator('#v121HomeAvailable').inner_text(),
                         self.page.evaluate('money2(v111MonthBalance(homeMonth.value).closing)'))
        expect(self.page.locator('#home .hero')).to_be_hidden()
        expect(self.page.locator('#v121HomeAnalyticsContent')).to_be_hidden()
        expect(self.page.locator('#v111HomeClosing')).to_be_hidden()
        expect(self.page.locator('#weatherCard')).to_be_visible()
        self.assertEqual(self.page.locator('#recent [role="listitem"]').count(), 3)
        self.page.locator('#v73OverviewToggle').click()
        expect(self.page.locator('#v73OverviewToggle')).to_have_attribute('aria-expanded', 'true')
        expect(self.page.locator('#v121HomeAnalyticsContent')).to_be_visible()
        expect(self.page.locator('#v111HomeClosing')).to_be_hidden()
        expect(self.page.locator('#weatherCard')).to_be_visible()
        self.assertEqual(self.page.locator('#recent [role="listitem"]').count(), 3)
        self.page.locator('.v121-history-detail > summary').click()
        expect(self.page.locator('#v111HomeClosing')).to_be_visible()
        self.assert_readonly()

    def test_available_amount_requires_complete_inputs_and_reasons_are_plain_text(self):
        self.prepare()
        cases = [
            ({'amount':0,'ownCash':700,'complete':True}, 'Доступно до следующего дохода',0),
            ({'amount':-50,'ownCash':700,'complete':True}, 'Доступно до следующего дохода',-50),
            ({'amount':999,'ownCash':700,'complete':False,'estimate':600,
              'reasons':['<img src=x onerror=alert(1)> Учебная причина']}, 'На доступных счетах',700),
            ({'amount':999,'ownCash':None,'complete':False}, 'Остаток по истории',None),
        ]
        self.page.evaluate('window.__realAvailableData=v118AvailableData')
        for data,title,amount in cases:
            with self.subTest(title=title,amount=amount):
                self.page.evaluate("""data => {v118AvailableData=()=>data;v121RenderHomeOverview()}""", data)
                expect(self.page.locator('#v121HomeAvailableTitle')).to_have_text(title)
                expected=self.page.evaluate('(amount)=>money2(amount??v111MonthBalance(homeMonth()).closing)',amount)
                self.assertEqual(self.page.locator('#v121HomeAvailable').inner_text(),expected)
                self.assertEqual(self.page.locator('#v121HomeReasons img').count(),0)
                if data.get('reasons'):
                    self.assertIn(data['reasons'][0],self.page.locator('#v121HomeReasons').text_content())
        self.page.evaluate('v118AvailableData=window.__realAvailableData;v121RenderHomeOverview()')
        self.assert_readonly()

    def test_daily_navigation_and_help_about_preserve_single_canonical_cards(self):
        self.prepare()
        self.assertEqual(self.page.locator('#nav [data-page="plans"]').count(),0)
        self.assertEqual(self.page.locator('#v74MorePanel [data-page="plans"]').count(),0)
        for page in ('accounts','planning'):
            self.page.locator(f'#v121HomeSummary button[onclick="go(\'{page}\')"]').click()
            expect(self.page.locator(f'#{page}')).to_be_visible()
            expect(self.page.locator(f'#nav button[data-page="{page}"]')).to_have_attribute('aria-current','page')
            self.assertEqual(self.page.locator('#v84AccountsCard').count(),1)
            self.assertEqual(self.page.locator('#v86Calendar').count(),1)
            self.page.evaluate("go('home')")
        self.page.locator('#v97HomePayments button').first.click()
        expect(self.page.locator('#planning')).to_be_visible()
        expect(self.page.locator('#v86Calendar')).to_be_visible()
        self.page.evaluate("go('help')")
        self.page.get_by_role('button',name='О приложении и обновления',exact=True).click()
        expect(self.page.locator('#plans')).to_be_visible()
        self.assertFalse(self.page.locator('#v121ProductPreview').evaluate('(node)=>node.open'))
        self.assert_readonly()

    def test_back_forward_restore_filters_and_scroll_without_saving_financial_data(self):
        self.prepare()
        self.page.evaluate("go('history');clearHistoryMonth()")
        self.page.locator('#fSearch').fill('fictional')
        self.page.evaluate("window.scrollTo(0,200)")
        self.page.wait_for_function("history.state.filters.fSearch==='fictional'&&history.state.scroll>100")
        old_scroll = self.page.evaluate('window.scrollY')
        self.page.evaluate("go('analytics')")
        self.page.go_back()
        self.page.wait_for_function("document.querySelector('.section.active').id==='history'&&fSearch.value==='fictional'")
        self.page.wait_for_function('(expected)=>Math.abs(window.scrollY-expected)<2',arg=old_scroll)
        expect(self.page.locator('#nav [data-page="history"]')).to_have_attribute('aria-current','page')
        self.page.go_forward()
        self.page.wait_for_function("document.querySelector('.section.active').id==='analytics'")
        self.assertEqual(self.page.locator('#analyticsMonth').input_value(),self.period)
        self.page.go_back()
        self.page.wait_for_function("document.querySelector('.section.active').id==='history'")
        self.page.locator('#fSearch').fill('Fictional store 1')
        self.page.wait_for_function("history.state.filters.fSearch==='Fictional store 1'")
        self.page.evaluate("go('home')")
        self.page.go_back()
        self.page.wait_for_function("document.querySelector('.section.active').id==='history'&&fSearch.value==='Fictional store 1'")
        self.assert_readonly()

    def test_route_reload_waits_for_unlock_and_help_anchors_stay_on_help(self):
        self.prepare()
        self.page.evaluate("go('help')")
        self.page.locator('#help a[href="#help-operations"]').click()
        self.page.wait_for_function("location.hash==='#help-operations'")
        expect(self.page.locator('#help')).to_be_visible()
        self.page.evaluate("go('history');fSearch.value='fictional';fSearch.dispatchEvent(new Event('input',{bubbles:true}))")
        self.page.wait_for_function("history.state.filters.fSearch==='fictional'")
        self.page.reload(wait_until='domcontentloaded')
        self.page.wait_for_function("typeof showApp==='function'")
        expect(self.page.locator('#authGate')).to_be_visible()
        expect(self.page.locator('#appRoot')).to_have_class(re.compile('auth-locked'))
        self.page.evaluate('session=null;stopCloudSync();showApp()')
        expect(self.page.locator('#history')).to_be_visible()
        self.assertEqual(self.page.locator('#fSearch').input_value(),'fictional')
        self.assertEqual(self.errors,[])

    def test_lock_blocks_route_history_from_exposing_data_or_stealing_gate_focus(self):
        self.prepare()
        self.page.evaluate("go('history');go('analytics');showGate('Учебная блокировка')")
        self.page.locator('#gateEmail').focus()
        self.page.go_back()
        expect(self.page.locator('#authGate')).to_be_visible()
        expect(self.page.locator('#appRoot')).to_have_class(re.compile('auth-locked'))
        expect(self.page.locator('#gateEmail')).to_be_focused()
        self.assert_readonly()

    def test_home_money_actions_and_weather_fit_devices_and_double_text(self):
        self.prepare()
        for width,height in ((320,740),(390,844),(844,390),(1024,768),(1920,1080)):
            for scale in (1,2):
                with self.subTest(width=width,scale=scale):
                    self.page.set_viewport_size({'width':width,'height':height})
                    self.page.evaluate("""scale=>{
                      document.querySelectorAll('[data-navigation-test-font]').forEach(node=>{
                        node.style.removeProperty('font-size');delete node.dataset.navigationTestFont;
                      });
                      if(scale===2){const nodes=[...document.querySelectorAll('#v121HomeSummary,#v121HomeSummary *,#v121HomeAnalysisCard > .v73-overview-toolbar,#v121HomeAnalysisCard > .v73-overview-toolbar *')];
                        const sizes=nodes.map(node=>parseFloat(getComputedStyle(node).fontSize));
                        nodes.forEach((node,i)=>{if(sizes[i]){node.dataset.navigationTestFont='1';node.style.setProperty('font-size',sizes[i]*2+'px','important')}})
                      }
                    }""",scale)
                    geometry=self.page.evaluate("""()=>{
                      const card=document.getElementById('v121HomeSummary'),box=card.getBoundingClientRect(),
                        fragments=[],walker=document.createTreeWalker(card,NodeFilter.SHOW_TEXT);
                      while(walker.nextNode()){
                        const parent=walker.currentNode.parentElement;if(!parent.getClientRects().length)continue;
                        const range=document.createRange();range.selectNodeContents(walker.currentNode);
                        for(const r of range.getClientRects())if(r.width&&r.height)fragments.push({left:r.left-box.left,right:r.right-box.right});
                      }
                      return {overflow:card.scrollWidth-card.clientWidth,left:box.left,right:box.right,
                        actions:[...card.querySelectorAll('button')].map(node=>{const r=node.getBoundingClientRect();return {width:r.width,height:r.height}}),fragments};
                    }""")
                    self.assertLessEqual(geometry['overflow'],1,geometry)
                    self.assertGreaterEqual(geometry['left'],0,geometry)
                    self.assertLessEqual(geometry['right'],width,geometry)
                    for fragment in geometry['fragments']:
                        self.assertGreaterEqual(fragment['left'],-1,fragment)
                        self.assertLessEqual(fragment['right'],1,fragment)
                    for action in geometry['actions']:
                        self.assertGreaterEqual(action['height'],44,action)
                    expect(self.page.locator('#weatherCard')).to_be_visible()
        self.assert_readonly()


if __name__=='__main__':
    unittest.main()
