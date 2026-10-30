"""Independent calculator acceptance on synthetic local data; external requests blocked."""
import unittest
import test_amount_calculator as calc
import test_local_data_safety as harness

class GlobalCalculator(unittest.TestCase):
    @classmethod
    def setUpClass(cls): harness.LocalDataSafety.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls): harness.LocalDataSafety.tearDownClass.__func__(cls)
    setUp=harness.LocalDataSafety.setUp
    tearDown=harness.LocalDataSafety.tearDown
    open=harness.LocalDataSafety.open
    snapshot=harness.LocalDataSafety.snapshot
    prepare=calc.AmountCalculator.prepare

    def test_available_in_every_section_and_leaves_state_storage_and_draft_unchanged(self):
        self.prepare()
        self.page.locator('#eAmount').fill('81,17')
        self.page.locator('#eStore').fill('Fictional draft')
        before=self.snapshot()
        sections=self.page.evaluate("[...document.querySelectorAll('#nav [data-page]')].map(el=>el.dataset.page)")
        for section in sections:
            with self.subTest(section=section):
                self.page.evaluate('(section)=>go(section)',section)
                self.page.get_by_role('button',name='Открыть калькулятор',exact=True).click()
                self.assertTrue(self.page.locator('#v96Calculator').is_visible())
                self.assertFalse(self.page.locator('#v96CalcApply').is_visible())
                self.assertIsNone(self.page.evaluate('v96CalculatorTarget'))
                self.page.locator('#v96CalcExpression').fill('(250 + 125,50) / 2')
                self.assertEqual(self.page.locator('#v96CalcResult').input_value(),'187,75')
                self.assertFalse(self.page.evaluate('v96ApplyCalculatedAmount()'))
                self.page.get_by_role('button',name='Закрыть',exact=True).click()
                self.assertEqual(self.page.evaluate('document.activeElement.id'),'v104GlobalCalculator')
                self.assertEqual(self.page.locator('#eAmount').input_value(),'81,17')
                self.assertEqual(self.page.locator('#eStore').input_value(),'Fictional draft')
                self.assertEqual(self.snapshot(),before)

    def test_negative_and_zero_copy_without_operation_warning_and_form_reopens_normally(self):
        self.prepare()
        self.page.evaluate("""() => {window.__globalCopied=[];Object.defineProperty(navigator,'clipboard',{
          configurable:true,value:{writeText:async text=>window.__globalCopied.push(text)}})}""")
        self.page.get_by_role('button',name='Открыть калькулятор',exact=True).click()
        for n,(expression,result) in enumerate([('1-2','-1,00'),('1-1','0,00')],1):
            self.page.locator('#v96CalcExpression').fill(expression)
            self.assertNotIn('Для операции',self.page.locator('#v96CalcMessage').inner_text())
            self.page.get_by_role('button',name='Копировать результат',exact=True).click()
            self.page.wait_for_function('(n)=>window.__globalCopied.length===n',arg=n)
            self.assertEqual(self.page.evaluate('window.__globalCopied.at(-1)'),result)
        self.page.locator('#v96CalcExpression').press('Escape')
        self.assertFalse(self.page.locator('#v96Calculator').is_visible())
        self.assertEqual(self.page.locator('#v96CalcExpression').input_value(),'')
        self.page.evaluate("v96OpenCalculator('eAmount')")
        self.page.locator('#v96CalcExpression').fill('12+3')
        self.assertTrue(self.page.locator('#v96CalcApply').is_visible())
        self.page.get_by_role('button',name='Подставить сумму',exact=True).click()
        self.assertEqual(self.page.locator('#eAmount').input_value(),'15,00')

    def test_close_switch_mode_and_logout_reject_stale_clipboard_and_standalone_open(self):
        self.prepare()
        self.page.evaluate("""() => {
          Object.defineProperty(navigator,'clipboard',{configurable:true,value:{readText:()=>new Promise(resolve=>window.__resolveGlobalPaste=resolve)}});
          v96OpenCalculator();window.__globalPaste=v96PasteAmount('v96CalcExpression');
          v96CloseCalculator();v96OpenCalculator('eAmount');v96CalcExpression.value='99+1';v96RefreshCalculatedAmount();
        }""")
        self.assertFalse(self.page.evaluate("async()=>{window.__resolveGlobalPaste('4+5');return await window.__globalPaste}"))
        self.assertEqual(self.page.locator('#v96CalcExpression').input_value(),'99+1')
        self.page.evaluate('v96CloseCalculator();v96OpenCalculator();logout()')
        self.assertFalse(self.page.locator('#v96Calculator').is_visible())
        self.assertEqual(self.page.locator('#v96CalcExpression').input_value(),'')
        self.assertIsNone(self.page.evaluate('v104CalculatorOpener'))
        self.assertFalse(self.page.evaluate('v96OpenCalculator()'))

    def test_header_enlarged_text_fits_without_horizontal_scroll(self):
        import sys
        sys.path.insert(0,'/workspace/marichevy-finance/tools')
        from check_touch_flows import enlarge_text
        for width,scale in [(320,1.5),(390,2),(820,2),(1280,2)]:
            with self.subTest(width=width,scale=scale):
                self.prepare()
                self.page.set_viewport_size({'width':width,'height':900})
                self.page.evaluate("userLabel.textContent='Вымышленный участник · fictional-long-email@example.test';go('history')")
                self.page.get_by_role('button',name='Открыть калькулятор',exact=True).click()
                enlarge_text(self.page,scale)
                self.page.get_by_role('button',name='Закрыть калькулятор',exact=True).click()
                geometry=self.page.evaluate('''() => {
                  const header=document.querySelector('.top');
                  const targets=[header,document.querySelector('.v104-header-tools'),document.querySelector('.userbar'),document.getElementById('v104GlobalCalculator'),document.getElementById('authBtn')];
                  return {scroll:header.scrollWidth,client:header.clientWidth,rects:targets.map(el=>{const r=el.getBoundingClientRect();return {left:r.left,right:r.right}})};
                }''')
                self.assertLessEqual(geometry['scroll'],geometry['client']+1)
                for rect in geometry['rects']:
                    self.assertGreaterEqual(rect['left'],-1)
                    self.assertLessEqual(rect['right'],width+1)

    def test_header_button_and_calculator_fit_phone_tablet_and_desktop(self):
        self.prepare()
        self.page.evaluate("userLabel.textContent='Вымышленный участник · fictional@example.test';go('history')")
        for width,height in [(320,740),(390,844),(820,1180),(1280,800),(1440,900),(1920,1080)]:
            with self.subTest(width=width):
                self.page.set_viewport_size({'width':width,'height':height})
                button=self.page.locator('#v104GlobalCalculator')
                geometry=button.bounding_box()
                self.assertGreaterEqual(geometry['x'],0)
                self.assertLessEqual(geometry['x']+geometry['width'],width+1)
                self.assertGreaterEqual(geometry['height'],44)
                button.click()
                self.page.locator('#v96CalcExpression').fill('(1250,50 - 250) / 2')
                dialog=self.page.locator('#v96Calculator').bounding_box()
                self.assertGreaterEqual(dialog['x'],0)
                self.assertLessEqual(dialog['x']+dialog['width'],width+1)
                self.assertLessEqual(self.page.evaluate('v96Calculator.scrollWidth'),self.page.evaluate('v96Calculator.clientWidth'))
                if width in [390,1440]: self.page.screenshot(path=f'/tmp/global-calculator-{width}.png')
                self.page.get_by_role('button',name='Закрыть калькулятор',exact=True).click()

if __name__=='__main__': unittest.main()
