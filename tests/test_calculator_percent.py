"""Percentage arithmetic and keypad on fictional local data; all external requests blocked."""
from pathlib import Path
import os
import sys
import unittest

import test_amount_calculator as calc
import test_local_data_safety as harness
sys.path.insert(0, str(Path(harness.__file__).resolve().parents[1] / 'tools'))
from check_touch_flows import enlarge_text


class CalculatorPercent(unittest.TestCase):
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
    prepare = calc.AmountCalculator.prepare

    def test_percent_ordinary_calculator_context_and_exact_final_rounding(self):
        self.prepare(); before = self.snapshot()
        cases = {
            '10%': ('0,10', False),
            '100%': ('1,00', False),
            '200*10%': ('20,00', False),
            '200/10%': ('2000,00', False),
            '200+10%': ('220,00', False),
            '200-10%': ('180,00', False),
            '45+100+10%': ('159,50', False),
            '200+10%+5%': ('231,00', False),
            '100+12,5%+10%': ('123,75', False),
            '200+(5+5)%': ('220,00', False),
            '200+(10%)': ('220,00', False),
            '200+(-10%)': ('180,00', False),
            '-200+10%': ('-220,00', False),
            '200+10%*2': ('200,20', False),
            '200+(10%*2)': ('200,20', False),
            '200+10%/2': ('200,05', False),
            '(200+10%)*2': ('440,00', False),
            '(100/3)%*3': ('1,00', False),
            '0,05*10%': ('0,01', True),
            '-0,05*10%': ('-0,01', True),
            '0,03+50%': ('0,05', True),
            '0,01*10%*10%': ('0,00', True),
        }
        actual = self.page.evaluate('''cases=>Object.fromEntries(cases.map(expression=>{
          const value=v96CalculateAmount(expression);
          return [expression,[value.text,value.rounded]];
        }))''', list(cases))
        self.assertEqual(actual, {key:list(value) for key,value in cases.items()})
        self.assertEqual(self.snapshot(), before)

    def test_invalid_percent_syntax_limits_and_division_zero_stay_rejected(self):
        self.prepare(); before = self.snapshot()
        values = ['%', '%10', '10%%', '10%10', '200%10', '200+%', '200/(0%)',
                  '10%;window.__percentExecuted=true', '10%+window.alert(1)',
                  '1%+' * 100 + '1',
                  '(' * 20 + '1%' + ')' * 20, '90071992547409,91+0%']
        self.page.evaluate('window.__percentExecuted=false')
        failures = self.page.evaluate('''values=>values.map(expression=>{
          try{v96CalculateAmount(expression);return false}catch{return true}
        })''', values)
        self.assertTrue(all(failures))
        self.assertFalse(self.page.evaluate('window.__percentExecuted'))
        self.assertEqual(self.snapshot(), before)

    def test_visible_percent_key_copy_and_form_apply_preserve_state_until_save(self):
        self.prepare()
        self.page.locator('#eAmount').fill('81,17')
        self.page.locator('#eStore').fill('Fictional unchanged draft')
        before = self.snapshot()
        self.page.evaluate('''() => {
          window.__percentCopied=[];
          Object.defineProperty(navigator,'clipboard',{configurable:true,value:{
            writeText:async value=>window.__percentCopied.push(value)}});
        }''')
        self.page.get_by_role('button', name='Открыть калькулятор', exact=True).click()
        for key in ['2','0','0','−','1','0','%','=']:
            self.page.locator(f'[data-calc-key="{key}"]').click()
        self.assertEqual(self.page.locator('#v96CalcResult').input_value(), '180,00')
        self.page.get_by_role('button', name='Копировать результат', exact=True).click()
        self.page.wait_for_function("window.__percentCopied[0]==='180,00'")
        self.page.get_by_role('button', name='Закрыть', exact=True).click()
        self.assertEqual(self.page.locator('#eAmount').input_value(), '81,17')
        self.assertEqual(self.page.locator('#eStore').input_value(), 'Fictional unchanged draft')
        self.assertEqual(self.snapshot(), before)
        self.page.evaluate("v96OpenCalculator('eAmount')")
        self.page.locator('#v96CalcExpression').fill('200-10%')
        self.page.get_by_role('button', name='Подставить сумму', exact=True).click()
        self.assertEqual(self.page.locator('#eAmount').input_value(), '180,00')
        self.assertEqual(self.snapshot(), before)

    def test_keypad_geometry_remains_five_rows_and_touch_targets_fit(self):
        for width,height,scale in [(320,740,1),(390,844,1),(820,1180,1),
                                   (1440,1000,1),(320,740,2),(390,844,1.5)]:
            with self.subTest(width=width, scale=scale):
                self.prepare()
                self.page.set_viewport_size({'width':width,'height':height})
                self.page.get_by_role('button', name='Открыть калькулятор', exact=True).click()
                self.page.locator('#v96CalcExpression').fill('45+100+10%')
                if scale != 1:
                    enlarge_text(self.page, scale)
                info = self.page.evaluate('''() => {
                  const dialog=document.getElementById('v96Calculator');
                  const rect=el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,right:r.right,bottom:r.bottom}};
                  return {dialog:rect(dialog),client:dialog.clientWidth,scroll:dialog.scrollWidth,
                    keys:[...dialog.querySelectorAll('[data-calc-key]')].map(rect)};
                }''')
                self.assertLessEqual(info['scroll'], info['client']+1)
                self.assertGreaterEqual(info['dialog']['x'],0)
                self.assertLessEqual(info['dialog']['right'],width+1)
                self.assertEqual(len({round(key['y']) for key in info['keys']}),5)
                for key in info['keys']:
                    self.assertGreaterEqual(key['h'],44)
                    self.assertGreaterEqual(key['w'],44)
                    self.assertGreaterEqual(key['x'],info['dialog']['x'])
                    self.assertLessEqual(key['right'],info['dialog']['right'])
                if width==1440 and scale==1 and os.environ.get('PERCENT_SCREENSHOT_DIR'):
                    directory=Path(os.environ['PERCENT_SCREENSHOT_DIR'])
                    directory.mkdir(exist_ok=True)
                    self.page.screenshot(path=str(directory/'calculator-percent.png'))
                self.page.get_by_role('button',name='Закрыть калькулятор',exact=True).click()


if __name__=='__main__':
    unittest.main()
