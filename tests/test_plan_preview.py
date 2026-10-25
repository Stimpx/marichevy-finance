"""Honest, nonpaying plan preview; fictional browser state and blocked network."""
import unittest

import test_local_data_safety as harness


class PlanPreview(unittest.TestCase):
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
        self.open();self.requests=[]
        self.page.on('request',lambda request:self.requests.append(request.url))
        self.page.evaluate("""() => {
          session=null;stopCloudSync();state=blankState();localStorage.clear();
          state.entries=[{id:'fictional-plan-preview',type:'expense',date:today(),amount:17.25,
            category:'Продукты',who:'Общее',beneficiary:'Алиса',comment:'Fictional only',
            futureField:{keep:[true,null,'unchanged']}}];
          showApp();renderAll();clearEntry();
        }""")
        self.before=self.snapshot()
        self.people=self.page.locator('#eBeneficiary option').evaluate_all('(items)=>items.map(x=>[x.value,x.textContent])')
        self.page.evaluate("go('plans')")
        self.assertTrue(self.page.locator('#plans').is_visible())

    def test_matrix_has_four_free_six_pro_pages_and_common_data_controls(self):
        self.prepare()
        matrix=self.page.evaluate("""() => ({
          free:[...document.querySelectorAll('#plans [data-plan-pages="free"] [data-plan-page]')].map(x=>x.dataset.planPage),
          pro:[...document.querySelectorAll('#plans [data-plan-pages="pro"] [data-plan-page]')].map(x=>x.dataset.planPage),
          common:[...document.querySelectorAll('#plans [data-common-feature]')].map(x=>x.dataset.commonFeature)
        })""")
        self.assertEqual(matrix['free'],['home','today','history','analytics'])
        self.assertEqual(matrix['pro'],['income','car','loans','goals','chores','dates'])
        self.assertEqual(matrix['common'],['settings','help','support','export'])
        self.assertEqual(self.snapshot(),self.before)

    def test_one_time_price_is_clear_and_checkout_has_no_active_payment_behavior(self):
        self.prepare()
        self.assertEqual(self.page.locator('#v96ProPrice').inner_text(),'990 ₽')
        self.assertEqual(self.page.locator('#v96ProPeriod').inner_text(),'один раз')
        self.assertIn('Разовая покупка',self.page.locator('#plans [data-plan="pro"]').inner_text())
        self.assertIn('без автоматических списаний',self.page.locator('#plans [data-plan="pro"]').inner_text())
        self.assertIn('Оплата пока не подключена',self.page.locator('#v96PlansPreviewStatus').inner_text())
        button=self.page.get_by_role('button',name='Оплата скоро',exact=True)
        self.assertTrue(button.is_disabled())
        self.assertEqual(self.page.locator('#plans form,#plans input,#plans iframe').count(),0)
        # Removing the visual disabled attribute must not fabricate a purchase.
        self.page.evaluate("v96ProCheckout.disabled=false;v96ProCheckout.click();v96ProCheckout.disabled=true")
        self.assertEqual(self.snapshot(),self.before)
        self.assertFalse(any(any(host in url.lower() for host in ['yookassa','yoomoney','stripe','checkout']) for url in self.requests))

    def test_preview_keeps_all_owner_sections_available_without_granting_pro_flag(self):
        self.prepare()
        self.assertIn('все разделы открыты',self.page.locator('#v96PlansPreviewStatus').inner_text())
        for page_id in ['income','car','loans','goals','chores','dates']:
            with self.subTest(page_id=page_id):
                self.page.evaluate('(id)=>go(id)',page_id)
                self.assertTrue(self.page.locator('#'+page_id).is_visible())
        self.assertEqual(self.snapshot(),self.before)
        self.assertEqual(self.page.locator('#eBeneficiary option').evaluate_all('(items)=>items.map(x=>[x.value,x.textContent])'),self.people)

    def test_common_settings_and_free_entry_navigation_do_not_create_orders_or_writes(self):
        self.prepare()
        self.page.get_by_role('button',name='Настройки и резервные копии',exact=True).click()
        self.assertTrue(self.page.locator('#settings').is_visible())
        self.assertEqual(self.snapshot(),self.before)
        self.page.evaluate("go('plans')")
        self.page.locator('#plans').get_by_role('button',name='Добавить операцию',exact=True).click()
        self.assertTrue(self.page.locator('#today').is_visible())
        self.assertEqual(self.snapshot(),self.before)

    def test_version_changes_and_future_pro_plus_have_no_unknown_price_checkout(self):
        self.prepare()
        self.assertIn('Кандидат v95',self.page.locator('#v96PlanVersion').inner_text())
        changes=self.page.locator('.v96-plans-changes').inner_text()
        for phrase in ['Калькулятор','Редактирование','Полная копия устройства']:
            self.assertIn(phrase,changes)
        roadmap=self.page.locator('.v96-plans-roadmap')
        self.assertIn('PRO+',roadmap.inner_text())
        self.assertIn('пока не определены',roadmap.inner_text())
        self.assertNotIn('₽',roadmap.inner_text())
        self.assertEqual(roadmap.locator('button:not([disabled]),a[href],form,input').count(),0)
        self.assertIn('Предлагаемый порядок',self.page.locator('#v96UpgradePolicy').inner_text())
        text=self.page.locator('#plans').inner_text().lower()
        for promise in ['навсегда','пожизненно','только сегодня','гарантированный доход']:
            self.assertNotIn(promise,text)
        self.assertIn('18+',text);self.assertIn('детей и питомцев',text)
        self.assertEqual(self.snapshot(),self.before)

    def test_plan_cards_and_controls_fit_phone_and_desktop(self):
        self.prepare()
        for width in [320,390,1280]:
            with self.subTest(width=width):
                self.page.set_viewport_size({'width':width,'height':900})
                size=self.page.evaluate("""() => ({viewport:innerWidth,width:document.documentElement.scrollWidth,
                  cards:[...document.querySelectorAll('#plans .v96-plan-card')].map(x=>{
                    const r=x.getBoundingClientRect();return{left:r.left,right:r.right,width:r.width};
                  })})""")
                self.assertLessEqual(size['width'],size['viewport'])
                for card in size['cards']:
                    self.assertGreaterEqual(card['left'],-1)
                    self.assertLessEqual(card['right'],width+1)


if __name__=='__main__':
    unittest.main()
