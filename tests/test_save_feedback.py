"""Visible save failures and notices; fictional local records, no external requests."""
import json
import os
from pathlib import Path
import unittest

from playwright.sync_api import expect

import test_local_data_safety as harness


class SaveFeedback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.LocalDataSafety.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        harness.LocalDataSafety.tearDownClass.__func__(cls)

    def setUp(self):
        self.context = self.browser.new_context(
            viewport={'width': 390, 'height': 844}, locale='ru-RU',
            timezone_id='Europe/Moscow', service_workers='block', reduced_motion='no-preference')
        self.context.route('**/*', lambda route: route.continue_()
                           if route.request.url.startswith(self.base) else route.abort())
        self.page = self.context.new_page()
        self.page.set_default_timeout(4000)
        self.page.on('dialog', lambda dialog: dialog.dismiss())

    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open
    snapshot = harness.LocalDataSafety.snapshot
    fail_writes = harness.LocalDataSafety.fail_writes

    def prepare(self, width=390, height=844, scale=1):
        self.page.set_viewport_size({'width': width, 'height': height})
        self.open()
        self.page.evaluate("""() => {
          session=null;stopCloudSync();state=blankState();localStorage.clear();
          telegramNotify=()=>Promise.resolve(false);
          state.entries=[{id:'fictional-feedback-history',type:'expense',amount:17.251,
            date:'2026-10-21',category:'Historical category',who:'Historical recipient',
            store:'Учебный магазин',futureField:{preserve:[true,null,'fictional']}}];
          state.futureTop={preserve:['fictional',true]};
          state.settings.futureField={original:true};
          weatherCache.data={temperature_2m:10,weather_code:0};weatherCache.at=Date.now();
          loanScheduleData=()=>[{n:1,payDate:'2099-12-01',periodEnd:'2099-12-01',
            payment:1,interest:0,body:1,balance:0}];
          showApp();renderAll();clearEntry();go('today');
          window.__feedbackWrites={saves:0,pending:0};
          const originalSave=saveAll,originalSet=Storage.prototype.setItem;
          saveAll=function(...args){window.__feedbackWrites.saves++;return originalSave(...args)};
          Storage.prototype.setItem=function(key,value){
            if(key===KEYS.pending)window.__feedbackWrites.pending++;
            return originalSet.call(this,key,value);
          };
        }""")
        if scale != 1:
            self.scale_text(scale)
        self.before = self.snapshot()

    def scale_text(self, scale):
        self.page.evaluate("""scale => {
          const nodes=[...document.querySelectorAll('body,body *')]
            .filter(el=>!['SCRIPT','STYLE','SVG','PATH'].includes(el.tagName));
          const sizes=nodes.map(el=>parseFloat(getComputedStyle(el).fontSize));
          nodes.forEach((el,i)=>{if(sizes[i])el.style.setProperty('font-size',sizes[i]*scale+'px','important')});
        }""", scale)

    def writes(self):
        return self.page.evaluate('window.__feedbackWrites')

    def submit(self):
        self.page.locator('#v90Save').click()
        self.page.wait_for_function('!v90Saving')

    def assert_no_write(self):
        self.assertEqual(self.writes(), {'saves': 0, 'pending': 0})
        self.assertEqual(self.snapshot(), self.before)

    def assert_inline_visible(self, field, error):
        expect(self.page.locator(error)).to_be_visible()
        expect(self.page.locator(field)).to_be_focused()
        self.assertEqual(self.page.locator(field).get_attribute('aria-invalid'), 'true')
        error_id = error.removeprefix('#')
        self.assertIn(error_id, (self.page.locator(field).get_attribute('aria-describedby') or '').split())
        self.page.wait_for_function("""([field,error]) => {
          const input=document.querySelector(field),message=document.querySelector(error),
            r=input.getBoundingClientRect(),m=message.getBoundingClientRect(),
            viewport=window.visualViewport,top=viewport?.offsetTop||0,
            bottom=top+(viewport?.height||innerHeight),nav=document.getElementById('mobileNav'),
            n=nav.getClientRects().length?nav.getBoundingClientRect():null,
            limit=n&&n.top<bottom?Math.min(bottom,n.top):bottom;
          return r.top>=top-1&&r.bottom<=limit+1&&m.top>=top-1&&m.bottom<=limit+1;
        }""", arg=[field, error])

    def assert_errors_cleared(self):
        for selector in ('#eAmountError', '#v114CategoryError', '#v114CreditError'):
            expect(self.page.locator(selector)).to_be_hidden()
        self.assertEqual(self.page.locator('#today [aria-invalid="true"]').count(), 0)

    def screenshot(self, name):
        directory = os.environ.get('MARICHEVY_FEEDBACK_SCREENSHOTS')
        if directory:
            Path(directory).mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(Path(directory) / name))

    def test_invalid_amount_focuses_visible_inline_error_at_phone_landscape_and_tablet_sizes(self):
        for width, height in ((320, 740), (390, 844), (844, 390), (820, 1180)):
            for scale in (1, 2):
                with self.subTest(width=width, height=height, scale=scale):
                    self.prepare(width, height, scale)
                    self.submit()
                    self.assert_inline_visible('#eAmount', '#eAmountError')
                    self.assertIn('сумм', self.page.locator('#eAmountError').inner_text().lower())
                    self.assert_no_write()
                    self.screenshot(f'amount-{width}x{height}-text{scale*100}.png')

    def test_malformed_amounts_do_not_write_and_editing_clears_stale_invalid_state(self):
        self.prepare()
        for amount in ('', '0', '-1', '1,234', '1e3', '1 2'):
            with self.subTest(amount=amount):
                self.page.locator('#eAmount').fill(amount)
                self.submit()
                self.assert_inline_visible('#eAmount', '#eAmountError')
                self.assert_no_write()
                self.page.locator('#eAmount').fill('1 250,50')
                expect(self.page.locator('#eAmountError')).to_be_hidden()
                self.assertNotEqual(self.page.locator('#eAmount').get_attribute('aria-invalid'), 'true')

    def test_missing_category_is_local_then_actual_choice_and_corrected_amount_save_exactly_once(self):
        self.prepare()
        self.page.locator('#eAmount').press_sequentially('1 250,50')
        self.submit()
        self.assert_inline_visible('#v90Search', '#v114CategoryError')
        self.assert_no_write()
        self.page.locator('#v90Quick [data-cat="Продукты"]').click()
        expect(self.page.locator('#v114CategoryError')).to_be_hidden()
        self.page.locator('#eStore').fill('Учебная новая покупка')
        self.submit()
        self.assertEqual(self.writes(), {'saves': 1, 'pending': 1})
        saved = self.page.evaluate('JSON.parse(JSON.stringify(state))')
        original = json.loads(self.before['state'])
        self.assertEqual(saved['entries'][:-1], original['entries'])
        self.assertEqual(saved['futureTop'], original['futureTop'])
        self.assertEqual(saved['settings']['futureField'], original['settings']['futureField'])
        self.assertEqual(saved['entries'][-1]['amount'], 1250.50)
        self.assertEqual(saved['entries'][-1]['category'], 'Продукты')
        self.assertEqual(self.page.evaluate('JSON.parse(localStorage.getItem(KEYS.pending))'), saved)
        self.assertEqual(self.page.locator('#eAmount').input_value(), '')
        self.assert_errors_cleared()
        expect(self.page.locator('#saveMsg .success')).to_be_visible()

    def test_credit_error_targets_visible_select_and_mode_changes_clear_stale_error(self):
        self.prepare()
        self.page.locator('#eAmount').fill('125,50')
        self.page.locator('#v91All').click()
        self.page.locator('#v90Quick [data-cat="Кредит"]').click()
        for mode in ('', 'full'):
            with self.subTest(mode=mode):
                self.page.locator('#v93CreditAccounting').select_option(mode)
                self.submit()
                expect(self.page.locator('#v114CreditError')).to_be_visible()
                target = self.page.locator('#v93CreditAccounting').locator('..').get_by_role('combobox')
                expect(target).to_be_focused()
                self.assertEqual(target.get_attribute('aria-invalid'), 'true')
                self.assertIn('v114CreditError', (target.get_attribute('aria-describedby') or '').split())
                self.assert_no_write()
                self.page.locator('#v93CreditAccounting').select_option('payment')
                expect(self.page.locator('#v114CreditError')).to_be_hidden()
                self.assertNotEqual(target.get_attribute('aria-invalid'), 'true')

    def test_clear_and_operation_change_remove_errors_and_preserve_unsaved_financial_state(self):
        self.prepare()
        self.submit()
        self.page.locator('#eType').select_option('income')
        self.assert_errors_cleared()
        self.submit()
        self.assert_inline_visible('#eAmount', '#eAmountError')
        self.page.get_by_role('button', name='Очистить', exact=True).click()
        self.assert_errors_cleared()
        self.assertEqual(self.page.locator('#saveMsg').inner_text(), '')
        self.assert_no_write()

    def test_failed_local_storage_keeps_draft_and_displays_failure_in_visible_summary(self):
        self.prepare()
        self.page.locator('#eAmount').fill('1 250,50')
        self.page.locator('#v90Quick [data-cat="Продукты"]').click()
        self.page.locator('#eStore').fill('Учебный несохранённый магазин')
        self.fail_writes(harness.PRIMARY)
        self.submit()
        expect(self.page.locator('#saveMsg .error')).to_be_visible()
        self.assertEqual(self.page.locator('#saveMsg .success').count(), 0)
        self.assertEqual(self.page.locator('#eAmount').input_value(), '1 250,50')
        self.assertEqual(self.page.locator('#eStore').input_value(), 'Учебный несохранённый магазин')
        self.assertEqual(self.page.evaluate('state.entries.slice(0,-1)'), json.loads(self.before['state'])['entries'])
        self.assertEqual(self.writes()['saves'], 1)
        self.page.wait_for_function("""() => {
          const r=document.getElementById('saveMsg').getBoundingClientRect(),
            nav=document.getElementById('mobileNav').getBoundingClientRect();
          return r.top>=0&&r.bottom<=nav.top+1;
        }""")
        self.screenshot('local-storage-failure-390.png')

    def assert_toast_bounds(self):
        expect(self.page.locator('#v114ToastRegion .v114-toast')).to_be_visible()
        self.page.wait_for_function("""() => {
          const region=document.getElementById('v114ToastRegion'),r=region.getBoundingClientRect(),
            viewport=window.visualViewport,left=viewport?.offsetLeft||0,top=viewport?.offsetTop||0,
            right=left+(viewport?.width||innerWidth),bottom=top+(viewport?.height||innerHeight),
            nav=document.getElementById('mobileNav'),n=nav.getClientRects().length?nav.getBoundingClientRect():null,
            limit=n&&n.top<bottom?Math.min(bottom,n.top):bottom;
          return r.top>=top-1&&r.bottom<=limit+1&&r.left>=left-1&&r.right<=right+1&&
            region.scrollWidth<=region.clientWidth+1;
        }""")

    def test_toast_wraps_above_navigation_at_regular_and_large_text_sizes(self):
        message = 'Учебное уведомление: проверьте сумму и категорию покупки. Изменения ещё не сохранены.'
        for width, height in ((320, 740), (390, 844), (844, 390), (820, 1180), (1280, 900)):
            for scale in (1, 2):
                with self.subTest(width=width, height=height, scale=scale):
                    self.prepare(width, height)
                    self.page.evaluate('message=>toast(message)', message)
                    expect(self.page.locator('#v114ToastRegion .v114-toast')).to_be_visible()
                    if scale != 1:
                        self.scale_text(scale)
                    self.assert_toast_bounds()
                    self.assertEqual(self.page.locator('#v114ToastRegion').inner_text(), message)
                    self.assert_no_write()
                    self.screenshot(f'toast-{width}x{height}-text{scale*100}.png')

    def test_toast_repositions_for_resize_and_available_visual_viewport(self):
        self.prepare()
        self.page.evaluate("toast('Учебное сообщение при изменении доступного экрана')")
        self.assert_toast_bounds()
        self.page.set_viewport_size({'width': 844, 'height': 390})
        self.assert_toast_bounds()
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.page.evaluate("""() => {
          const viewport=new EventTarget();Object.assign(viewport,
            {offsetTop:20,offsetLeft:35,width:320,height:350});
          Object.defineProperty(window,'visualViewport',{configurable:true,value:viewport});
          window.dispatchEvent(new Event('resize'));
        }""")
        self.assert_toast_bounds()
        self.assert_no_write()

    def test_late_storage_failure_has_priority_over_generic_success_notice(self):
        self.prepare()
        self.page.evaluate("""() => {
          toast('Успешно сохранено: учебное сообщение');
          v89StorageFailed=true;
        }""")
        self.assert_toast_bounds()
        text = self.page.locator('#v114ToastRegion').inner_text()
        self.assertNotIn('Успешно сохранено', text)
        self.assertTrue(any(word in text.lower() for word in ('не удалось', 'не сохран', 'ошибк')), text)
        self.page.evaluate("toast('Ошибка разбора учебного файла')")
        expect(self.page.locator('#v114ToastRegion .v114-toast')).to_have_text('Ошибка разбора учебного файла')
        self.assertEqual(self.page.locator('#v114ToastRegion .v114-toast').count(), 1)

    def test_notice_inside_editor_stays_accessible_without_moving_dialog_focus(self):
        self.prepare()
        self.page.evaluate("go('history');clearHistoryMonth()")
        row = self.page.locator('#historyBody tr').filter(has_text='Учебный магазин')
        row.get_by_role('button', name='Редактировать операцию', exact=True).click()
        expect(self.page.locator('#xAmount')).to_be_focused()
        self.page.evaluate("toast('Учебная ошибка: проверьте данные операции')")
        self.assert_toast_bounds()
        self.assertFalse(self.page.locator('#v114ToastRegion').evaluate('(node)=>!!node.closest("[inert]")'))
        expect(self.page.get_by_role('status').filter(has_text='Учебная ошибка: проверьте данные операции')).to_be_visible()
        expect(self.page.locator('#xAmount')).to_be_focused()
        self.assertEqual(self.snapshot(), self.before)
        self.page.keyboard.press('Escape')
        expect(self.page.locator('#editModal')).to_be_hidden()
        self.assertEqual(self.snapshot(), self.before)


if __name__ == '__main__':
    unittest.main()
