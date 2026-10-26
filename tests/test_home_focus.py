"""Short home uses only fictional records and canonical payment allocation; no network."""
import json
import unittest

import test_local_data_safety as harness


class HomeFocus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.LocalDataSafety.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        harness.LocalDataSafety.tearDownClass.__func__(cls)

    setUp = harness.LocalDataSafety.setUp
    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open

    def prepare(self):
        self.open()
        self.page.evaluate("""() => {
          session=null;stopCloudSync();state=blankState();localStorage.clear();
          today=()=> '2026-10-26';month=()=> '2026-10';loanScheduleData=()=>[{n:1,payDate:'2099-12-01',periodEnd:'2099-12-01',payment:1,interest:0,body:1,balance:0}];
          v84NextPayDate=()=> '2026-11-05';
          state.entries=Array.from({length:10},(_,i)=>({id:'fictional-'+i,type:'expense',
            date:'2026-10-'+String(i+1).padStart(2,'0'),amount:10.01+i,category:'Продукты',
            who:'Вымышленный участник',store:'Учебный магазин '+i,future:{keep:true}}));
          state.settings.preferences.futureSetting={preserve:true};
          weatherCache.data={temperature_2m:10,weather_code:0};weatherCache.at=Date.now();
          showApp();renderAll();go('home');
        }""")

    def records(self):
        return self.page.evaluate("""()=>({state:JSON.stringify(state),storage:Object.fromEntries(
          Object.keys(localStorage).filter(key=>key!=='marichevy_v73_short_overview').sort()
          .map(key=>[key,localStorage.getItem(key)]))})""")

    def payments(self):
        self.page.evaluate("""() => {
          const plan=(id,date,amount,entryAmount)=>{
            const part={id:'part-'+id,date,amount};
            const item={id,title:'Фиктивный платёж '+id,kind:'split',parts:[part],links:{}};
            if(entryAmount!==undefined){const entry={id:'allocation-'+id,type:'expense',
              date:today(),amount:entryAmount,category:'Кредит',who:'Общее',future:'keep'};
              state.entries.push(entry);item.links[part.id]=entry.id;}
            return item;
          };
          state.installments=[plan('fully-paid','2026-09-18',900,900),
            plan('older-partial','2026-09-20',100.35,20.10),
            plan('kopecks','2026-10-25',0.30,0.10),plan('today','2026-10-26',10.25),
            plan('upcoming','2026-11-02',30.10),plan('beyond-horizon','2026-11-06',500)];
          renderAll();go('home');
        }""")

    def test_default_short_has_only_core_blocks_three_recent_and_two_add_actions(self):
        self.prepare();before=self.records()
        self.assertTrue(self.page.locator('#home').evaluate("node=>node.classList.contains('v73-focus')"))
        visible=self.page.locator('#home').evaluate("""root=>[...root.children].filter(node=>
          node.getBoundingClientRect().height>0).map(node=>node.id||node.className)""")
        self.assertCountEqual(visible,['hero','v96MonthlyReview','v97HomePayments',
                                      'v73-overview-toolbar','v97HomeRecent'])
        self.assertEqual(self.page.locator('#recent .v96-recent-row').count(),3)
        self.assertEqual(self.page.locator('#home .hero .quick button:visible').count(),2)
        self.assertTrue(self.page.get_by_role('button',name='Открыть полный обзор',exact=True).is_visible())
        self.assertEqual(self.page.locator('#v73OverviewToggle').get_attribute('aria-expanded'),'false')
        self.assertEqual(self.records(),before)

    def test_full_review_toggle_keeps_sections_ids_and_family_records_and_is_near_top(self):
        self.prepare();before=self.records()
        self.page.get_by_role('button',name='Открыть полный обзор',exact=True).click()
        for selector in ['#v86Calendar','#v84Pulse','#v84NoticesCard','.family-board','#moneyFlow']:
            self.assertTrue(self.page.locator(selector).is_visible(),selector)
        self.assertEqual(self.page.locator('#recent .v96-recent-row').count(),8)
        self.assertEqual(self.page.locator('#v73OverviewToggle').get_attribute('aria-expanded'),'true')
        self.assertLess(self.page.locator('#v73OverviewToggle').bounding_box()['y'],500)
        self.assertEqual(self.page.evaluate("localStorage.getItem('marichevy_v73_short_overview')"),'0')
        self.page.get_by_role('button',name='Свернуть до главного',exact=True).click()
        self.assertFalse(self.page.locator('#v86Calendar').is_visible())
        self.assertEqual(self.page.locator('#recent .v96-recent-row').count(),3)
        self.assertEqual(self.records(),before)

    def test_explicit_existing_full_preference_survives_page_reload(self):
        self.context.add_init_script("localStorage.setItem('marichevy_v73_short_overview','0')")
        self.open()
        self.page.evaluate("session=null;loanScheduleData=()=>[{n:1,payDate:'2099-12-01',periodEnd:'2099-12-01',payment:1,interest:0,body:1,balance:0}];showApp();go('home')")
        self.assertFalse(self.page.locator('#home').evaluate("node=>node.classList.contains('v73-focus')"))
        self.assertTrue(self.page.locator('#v86Calendar').is_visible())
        self.assertEqual(self.page.locator('#v73OverviewToggle').inner_text(),'Свернуть до главного')

    def test_no_payment_records_do_not_claim_account_balance_or_invent_obligations(self):
        self.prepare();before=self.records()
        self.assertEqual(self.page.evaluate('v97HomePaymentSummary().rows.length'),0)
        self.assertEqual(self.page.locator('.v97-home-payment-row').count(),0)
        text=self.page.locator('#v97HomePayments').inner_text()
        self.assertIn('нет неподтверждённых платежей до 05.11.2026',text)
        self.assertNotIn('0,00 ₽',text)
        self.assertNotIn('баланс',text.lower())
        self.assertEqual(self.records(),before)

    def test_remaining_kopecks_paid_exclusion_overdue_order_and_forecast_horizon(self):
        self.prepare();self.payments();before=self.records()
        result=self.page.evaluate("""()=>{const data=v97HomePaymentSummary();return {
          until:data.until,cents:data.remainingCents,rows:data.rows.map(row=>({
            title:row.event.title,cents:row.remainingCents,date:row.event.date}))}}""")
        self.assertEqual(result['until'],'2026-11-05')
        self.assertEqual(result['cents'],12080)
        self.assertEqual([r['cents'] for r in result['rows']],[8025,20,1025,3010])
        self.assertEqual([r['date'] for r in result['rows']],['2026-09-20','2026-10-25','2026-10-26','2026-11-02'])
        self.assertEqual(self.page.locator('.v97-home-payment-row').count(),3)
        self.assertIn('120,80',self.page.locator('#v97HomeRemaining').inner_text())
        self.assertIn('0,20',self.page.locator('.v97-home-payment-amount').nth(1).inner_text())
        self.assertIn('Срок прошёл',self.page.locator('.v97-home-payment-copy').first.inner_text())
        self.assertIn('Ещё платежей: 1',self.page.locator('.v97-home-payment-more').inner_text())
        self.assertNotIn('fully-paid',self.page.locator('#v97HomePayments').inner_text())
        self.assertNotIn('beyond-horizon',self.page.locator('#v97HomePayments').inner_text())
        self.assertEqual(self.records(),before)

    def test_historical_month_label_current_payment_basis_and_full_calendar_link(self):
        self.prepare();self.payments()
        self.page.evaluate("const select=document.getElementById('homeMonth');if(![...select.options].some(x=>x.value==='2026-09'))select.add(new Option('сентябрь 2026','2026-09'));select.value='2026-09';renderHome()")
        before=self.records();basis=self.page.locator('#v97HomePaymentsBasis').inner_text()
        self.assertIn('26.10.2026',basis);self.assertIn('05.11.2026',basis)
        self.assertIn('на сегодня, независимо от выбранного месяца',basis)
        self.page.locator('.v97-home-payment-row').first.get_by_role('button',name='Посмотреть',exact=True).click()
        self.assertTrue(self.page.locator('#v86Calendar').is_visible())
        self.assertEqual(self.page.locator('#v86CalendarMonth').input_value(),'2026-09')
        self.assertEqual(self.page.evaluate('v86CalendarFilter'),'pending')
        self.assertLess(self.page.locator('#v86Calendar').bounding_box()['y'],100)
        self.assertEqual(self.records(),before)

    def test_all_history_action_opens_records_without_existing_filters(self):
        self.prepare();before=self.records()
        self.page.evaluate("fSearch.value='does-not-exist';fMonth.value='2026-09'")
        self.page.get_by_role('button',name='Вся история операций',exact=True).click()
        self.assertTrue(self.page.locator('#history').is_visible())
        self.assertEqual(self.page.locator('#historyBody .v76-entry-row').count(),10)
        self.assertEqual(self.page.locator('#fSearch').input_value(),'')
        self.assertEqual(self.page.locator('#fMonth').input_value(),'')
        self.assertEqual(self.records(),before)

    def test_responsive_payment_controls_and_money_fit_without_horizontal_scroll(self):
        self.prepare();self.payments()
        self.page.evaluate("state.installments[1].title='Очень длинное фиктивное название платежа '.repeat(3);renderHome()")
        before=self.records()
        for width in [320,390,768,1280]:
            with self.subTest(width=width):
                self.page.set_viewport_size({'width':width,'height':844})
                layout=self.page.locator('#v97HomePayments').evaluate("""root=>({doc:document.documentElement.scrollWidth,
                  viewport:innerWidth,parts:[root,...root.querySelectorAll('.v97-home-payment-row,.v97-home-payment-amount,button')]
                    .map(node=>{const r=node.getBoundingClientRect();return {left:r.left,right:r.right,
                      width:r.width,height:r.height,tag:node.tagName,scroll:node.scrollWidth,client:node.clientWidth}})})""")
                self.assertLessEqual(layout['doc'],width+1)
                for part in layout['parts']:
                    self.assertGreaterEqual(part['left'],0,part);self.assertLessEqual(part['right'],width+1,part)
                    # CSSOM can report 43.9998779 for a 44px target after a
                    # viewport resize; keep the touch requirement with a tiny
                    # floating-point tolerance, rather than whole-pixel slack.
                    if part['tag']=='BUTTON':self.assertGreaterEqual(part['height']+0.01,44,part)
                    self.assertLessEqual(part['scroll'],part['client']+2,part)
        self.assertEqual(self.records(),before)


if __name__=='__main__':unittest.main()
