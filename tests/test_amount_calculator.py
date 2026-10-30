"""Amount calculator/clipboard regressions on fictional browser data only."""
import unittest

import test_local_data_safety as harness


class AmountCalculator(unittest.TestCase):
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
          session=null;stopCloudSync();state=blankState();localStorage.clear();
          state.entries=[{id:'fictional-old',type:'expense',date:today(),amount:17.25,
            category:'Historical category',who:'Historical recipient',
            futureField:{preserve:[true,null,'fictional']}}];
          showApp();renderAll();clearEntry();openEntry('expense');
        }""")
        self.page.wait_for_function("typeof v96CalculateAmount==='function'")

    def test_exact_arithmetic_precedence_groups_and_final_only_rounding(self):
        self.prepare()
        actual=self.page.evaluate("""() => Object.fromEntries([
          '0,10+0,20','1 250,50 - 200 + (2 * 12,25)',
          '385/3','1/200','100/3*3','(12.50+7,50)×3','1-2'
        ].map(x=>[x,v96CalculateAmount(x)]))""")
        expected={
            '0,10+0,20':(30,'0,30',False),
            '1 250,50 - 200 + (2 * 12,25)':(107500,'1075,00',False),
            '385/3':(12833,'128,33',True),
            '1/200':(1,'0,01',True),
            '100/3*3':(10000,'100,00',False),
            '(12.50+7,50)×3':(6000,'60,00',False),
            '1-2':(-100,'-1,00',False),
        }
        self.assertEqual(actual,{k:dict(cents=v[0],text=v[1],rounded=v[2]) for k,v in expected.items()})

    def test_invalid_text_zero_division_limits_and_script_are_rejected_without_mutation(self):
        self.prepare();before=self.snapshot()
        result=self.page.evaluate("""() => {
          window.__calculatorExecuted=false;
          const cases=['1/0','0.001','1 2','1+)', '1 250,5.0','1e3','2 ** 4',
            '999999999999999999','90071992547409,91','('.repeat(20)+'1'+')'.repeat(20),
            'window.__calculatorExecuted=true','1+'.repeat(100)+'1'];
          return {cases:cases.map(value=>{try{v96CalculateAmount(value);return false}catch{return true}}),
            executed:window.__calculatorExecuted};
        }""")
        self.assertTrue(all(result['cases']));self.assertFalse(result['executed'])
        self.assertEqual(self.snapshot(),before)

    def test_large_amount_keeps_serialized_cents_or_is_rejected(self):
        self.prepare()
        result=self.page.evaluate("""() => {
          const unsafe=parseMoneyInput('90071992547409,91');
          const safe=parseMoneyInput('90071992547409,90');
          return {unsafeRejected:Number.isNaN(unsafe),safeJson:JSON.stringify({amount:safe}),
            safeCalculator:v96CalculateAmount('90071992547409,90')};
        }""")
        self.assertTrue(result['unsafeRejected'])
        self.assertEqual(result['safeJson'],'{"amount":90071992547409.9}')
        self.assertEqual(result['safeCalculator'],{
            'cents':9007199254740990,'text':'90071992547409,90','rounded':False})
        self.page.evaluate("""() => {
          window.__largeCopied='';
          Object.defineProperty(navigator,'clipboard',{configurable:true,value:{
            writeText:async text=>{window.__largeCopied=text}
          }});
          eAmount.value='90071992547409,90';
        }""")
        self.page.get_by_role('button',name='Копировать сумму',exact=True).click()
        self.page.wait_for_function("window.__largeCopied==='90071992547409,90'")
        self.page.get_by_role('button',name='Калькулятор',exact=True).click()
        self.page.get_by_role('button',name='Подставить сумму',exact=True).click()
        self.assertFalse(self.page.locator('#v96Calculator').is_visible())
        self.assertEqual(self.page.locator('#eAmount').input_value(),'90071992547409,90')

    def test_apply_changes_only_input_and_explicit_save_keeps_exact_cents_once(self):
        self.prepare();before=self.snapshot()
        self.page.locator('#eAmount').fill('12,34')
        self.page.get_by_role('button',name='Калькулятор',exact=True).click()
        self.page.locator('#v96CalcExpression').fill('0,10 + 0,20')
        self.page.locator('#v96CalcExpression').press('Enter')
        self.assertEqual(self.page.locator('#v96CalcResult').input_value(),'0,30')
        self.assertEqual(self.page.locator('#eAmount').input_value(),'12,34')
        self.assertEqual(self.snapshot(),before)
        self.page.get_by_role('button',name='Подставить сумму',exact=True).click()
        self.assertFalse(self.page.locator('#v96Calculator').is_visible())
        self.assertEqual(self.page.locator('#eAmount').input_value(),'0,30')
        self.assertEqual(self.snapshot(),before)
        saved=self.page.evaluate("""async () => {
          const original=JSON.stringify(state.entries[0]);v90Choose('Продукты');
          await Promise.all([addEntry(),addEntry()]);
          return {count:state.entries.length,amount:state.entries.at(-1).amount,
            oldUnchanged:JSON.stringify(state.entries[0])===original};
        }""")
        self.assertEqual(saved,{'count':2,'amount':0.3,'oldUnchanged':True})

    def test_rounding_is_visible_and_cancel_or_invalid_result_never_changes_amount(self):
        self.prepare();before=self.snapshot()
        self.page.locator('#eAmount').fill('44,50')
        self.page.get_by_role('button',name='Калькулятор',exact=True).click()
        self.page.locator('#v96CalcExpression').fill('385 / 3')
        self.assertEqual(self.page.locator('#v96CalcResult').input_value(),'128,33')
        self.assertIn('округлён',self.page.locator('#v96CalcMessage').inner_text())
        self.page.locator('#v96CalcExpression').fill('1 / 0')
        self.assertTrue(self.page.locator('#v96CalcApply').is_disabled())
        self.assertIn('ноль',self.page.locator('#v96CalcMessage').inner_text())
        self.page.locator('#v96CalcExpression').fill('1 - 2')
        self.assertTrue(self.page.locator('#v96CalcApply').is_disabled())
        self.page.get_by_role('button',name='Закрыть калькулятор',exact=True).click()
        self.assertEqual(self.page.locator('#eAmount').input_value(),'44,50')
        self.assertEqual(self.snapshot(),before)

    def test_explicit_clipboard_amount_buttons_normalize_currency_without_saving(self):
        self.prepare();before=self.snapshot()
        self.page.evaluate("""() => {
          window.__clipboardReads=0;window.__clipboardWritten=[];
          Object.defineProperty(navigator,'clipboard',{configurable:true,value:{
            readText:async()=>{window.__clipboardReads++;return '1\\u202f250,50 ₽'},
            writeText:async value=>window.__clipboardWritten.push(value)
          }});
        }""")
        self.page.get_by_role('button',name='Калькулятор',exact=True).click()
        self.assertEqual(self.page.evaluate('window.__clipboardReads'),0)
        self.page.get_by_role('button',name='Закрыть калькулятор',exact=True).click()
        self.page.get_by_role('button',name='Вставить сумму',exact=True).click()
        self.page.wait_for_function("document.getElementById('eAmount').value==='1250,50'")
        self.assertEqual(self.page.evaluate('window.__clipboardReads'),1)
        self.page.get_by_role('button',name='Копировать сумму',exact=True).click()
        self.page.wait_for_function('window.__clipboardWritten.length===1')
        self.assertEqual(self.page.evaluate('window.__clipboardWritten'),['1250,50'])
        self.assertIn('скопирована',self.page.locator('#eAmountClipboardStatus').inner_text())
        self.assertEqual(self.snapshot(),before)

    def test_clipboard_rejection_or_nonamount_leaves_value_and_offers_native_menu(self):
        self.prepare();before=self.snapshot();self.page.locator('#eAmount').fill('17,25')
        result=self.page.evaluate("""async () => {
          Object.defineProperty(navigator,'clipboard',{configurable:true,value:{
            readText:async()=>{throw Error('PRIVATE_CLIPBOARD_DENIED')},
            writeText:async()=>{throw Error('PRIVATE_CLIPBOARD_DENIED')}
          }});
          const pasted=await v96PasteAmount('eAmount'),copied=await v96CopyAmount('eAmount');
          return {pasted,copied,selected:eAmount.value.slice(eAmount.selectionStart,eAmount.selectionEnd),
            status:document.getElementById('eAmountClipboardStatus').textContent};
        }""")
        self.assertFalse(result['pasted']);self.assertFalse(result['copied'])
        self.assertEqual(result['selected'],'17,25');self.assertIn('Выберите',result['status'])
        self.assertNotIn('PRIVATE_CLIPBOARD_DENIED',result['status'])
        self.page.evaluate("""() => Object.defineProperty(navigator,'clipboard',{configurable:true,
          value:{readText:async()=> 'Чек: молоко 200, итог 350'}})""")
        self.page.get_by_role('button',name='Вставить сумму',exact=True).click()
        self.page.wait_for_function("document.getElementById('eAmountClipboardStatus').textContent.includes('нет корректной суммы')")
        self.assertEqual(self.page.locator('#eAmount').input_value(),'17,25')
        self.assertEqual(self.snapshot(),before)

    def test_paste_does_not_overwrite_changes_while_permission_prompt_is_pending(self):
        self.prepare();self.page.locator('#eAmount').fill('12,34')
        self.page.evaluate("""() => {
          Object.defineProperty(navigator,'clipboard',{configurable:true,value:{
            readText:()=>new Promise(resolve=>window.__resolveAmountPaste=resolve)
          }});
          window.__amountPastePromise=v96PasteAmount('eAmount');
        }""")
        self.page.locator('#eAmount').fill('99,50')
        accepted=self.page.evaluate("""async () => {
          window.__resolveAmountPaste('5,25');return await window.__amountPastePromise;
        }""")
        self.assertFalse(accepted);self.assertEqual(self.page.locator('#eAmount').input_value(),'99,50')
        self.assertIn('изменилось',self.page.locator('#eAmountClipboardStatus').inner_text())

    def test_negative_and_zero_results_copy_but_cannot_be_applied(self):
        self.prepare()
        self.page.evaluate("""() => {
          window.__copiedResults=[];
          Object.defineProperty(navigator,'clipboard',{configurable:true,value:{
            writeText:async text=>window.__copiedResults.push(text)
          }});
          v96OpenCalculator('eAmount');
        }""")
        for count,(expression,expected) in enumerate([('1-2','-1,00'),('1-1','0,00')],1):
            self.page.locator('#v96CalcExpression').fill(expression)
            self.assertTrue(self.page.locator('#v96CalcApply').is_disabled())
            self.page.get_by_role('button',name='Копировать результат',exact=True).click()
            self.page.wait_for_function('(n)=>window.__copiedResults.length===n',arg=count)
            self.assertEqual(self.page.evaluate('window.__copiedResults.at(-1)'),expected)
        self.assertEqual(self.page.locator('#eAmount').input_value(),'')

    def test_late_clipboard_response_cannot_change_reopened_calculator(self):
        self.prepare()
        self.page.evaluate("""() => {
          Object.defineProperty(navigator,'clipboard',{configurable:true,value:{
            readText:()=>new Promise(resolve=>window.__resolveCalcPaste=resolve)
          }});
          v96OpenCalculator('eAmount');
          window.__calcPaste=v96PasteAmount('v96CalcExpression');
          v96CloseCalculator();v96OpenCalculator('eAmount');
          v96CalcExpression.value='99+1';v96RefreshCalculatedAmount();
        }""")
        accepted=self.page.evaluate("""async () => {
          window.__resolveCalcPaste('1+2');return await window.__calcPaste;
        }""")
        self.assertFalse(accepted)
        self.assertEqual(self.page.locator('#v96CalcExpression').input_value(),'99+1')
        self.assertEqual(self.page.locator('#v96CalcResult').input_value(),'100,00')

    def test_keypad_and_pasted_expression_compute_without_saving(self):
        self.prepare();before=self.snapshot()
        self.page.locator('#eAmount').fill('12,34')
        self.page.get_by_role('button',name='Калькулятор',exact=True).click()
        for key in ['C','7','×','(','2','+','3',')','=']:
            self.page.locator('#v96Calculator').get_by_role('button',name={
                'C':'Очистить расчёт','=':'Вычислить'}.get(key,key),exact=True).click()
        self.assertEqual(self.page.locator('#v96CalcResult').input_value(),'35,00')
        self.assertEqual(self.page.locator('#eAmount').input_value(),'12,34')
        self.page.evaluate("""() => Object.defineProperty(navigator,'clipboard',{configurable:true,
          value:{readText:async()=>'(100,50 + 99,50) / 2'}})""")
        self.page.get_by_role('button',name='Вставить расчёт',exact=True).click()
        self.page.wait_for_function("v96CalcResult.value==='100,00'")
        self.assertEqual(self.page.locator('#eAmount').input_value(),'12,34')
        self.page.get_by_role('button',name='Закрыть калькулятор',exact=True).click()
        self.assertEqual(self.snapshot(),before)

    def test_native_keyboard_copy_and_paste_still_work(self):
        self.prepare();before=self.snapshot()
        self.context.grant_permissions(['clipboard-read','clipboard-write'],origin=self.base.rstrip('/'))
        self.page.evaluate("navigator.clipboard.writeText('1 250,50')")
        field=self.page.locator('#eAmount');field.focus();field.press('Control+V')
        self.assertEqual(field.input_value(),'1 250,50')
        field.press('Control+A');field.press('Control+C')
        self.assertEqual(self.page.evaluate('navigator.clipboard.readText()'),'1 250,50')
        self.assertEqual(self.snapshot(),before)

    def test_edit_calculator_applies_to_only_the_original_live_input(self):
        self.prepare();before=self.snapshot()
        self.page.evaluate("openEdit('fictional-old')")
        self.page.locator('#editModal').get_by_role('button',name='Калькулятор',exact=True).click()
        self.page.locator('#v96CalcExpression').fill('(10 + 7) / 2')
        self.page.get_by_role('button',name='Подставить сумму',exact=True).click()
        self.assertEqual(self.page.locator('#xAmount').input_value(),'8,50')
        self.assertEqual(self.snapshot(),before)
        self.page.evaluate("v96OpenCalculator('xAmount')")
        self.page.locator('#v96CalcExpression').fill('999')
        self.page.evaluate("openEdit('fictional-old')")
        self.assertFalse(self.page.evaluate('v96ApplyCalculatedAmount()'))
        self.assertEqual(self.page.locator('#xAmount').input_value(),'17.25')
        self.assertEqual(self.snapshot(),before)

    def assert_calculator_locked(self):
        locked=self.page.evaluate("""() => ({
          locked:appRoot.classList.contains('auth-locked'),
          open:document.getElementById('v96Calculator')?.open||false,
          expression:document.getElementById('v96CalcExpression')?.value||'',
          result:document.getElementById('v96CalcResult')?.value||'',
          hasTarget:v96CalculatorTarget!==null
        })""")
        self.assertEqual(locked,{'locked':True,'open':False,'expression':'','result':'','hasTarget':False})
        self.assertFalse(self.page.locator('#v96Calculator').is_visible())

    def test_logout_closes_and_clears_calculator_and_refuses_reopening(self):
        self.prepare();self.page.locator('#eAmount').fill('17.25')
        before=self.page.evaluate('JSON.stringify(state)')
        self.page.get_by_role('button',name='Калькулятор',exact=True).click()
        self.assertEqual(self.page.locator('#v96CalcExpression').input_value(),'17.25')
        self.assertEqual(self.page.locator('#v96CalcResult').input_value(),'17,25')
        self.page.evaluate('logout()')
        self.assert_calculator_locked()
        self.assertFalse(self.page.evaluate('v96ApplyCalculatedAmount()'))
        self.page.evaluate("v96OpenCalculator('eAmount')")
        self.assert_calculator_locked()
        self.assertEqual(self.page.evaluate('JSON.stringify(state)'),before)

    def test_logout_invalidates_pending_calculator_clipboard_result_without_focus_leak(self):
        self.prepare();self.page.locator('#eAmount').fill('17.25')
        self.page.evaluate("""() => {
          Object.defineProperty(navigator,'clipboard',{configurable:true,value:{
            readText:()=>new Promise(resolve=>window.__resolveLogoutClipboard=resolve)
          }});
          v96OpenCalculator('eAmount');
          window.__logoutPaste=v96PasteAmount('v96CalcExpression');
          logout();document.getElementById('gateEmail').focus();
        }""")
        self.assert_calculator_locked()
        accepted=self.page.evaluate("""async () => {
          window.__resolveLogoutClipboard('999+1');return await window.__logoutPaste;
        }""")
        self.assertFalse(accepted);self.assert_calculator_locked()
        self.assertEqual(self.page.evaluate('document.activeElement.id'),'gateEmail')
        self.page.evaluate("v96OpenCalculator('eAmount')")
        self.assert_calculator_locked()

    def test_logout_invalidates_pending_amount_paste_even_without_calculator_dialog(self):
        self.prepare();self.page.locator('#eAmount').fill('17.25')
        self.page.evaluate("""() => {
          Object.defineProperty(navigator,'clipboard',{configurable:true,value:{
            readText:()=>new Promise(resolve=>window.__resolveLogoutAmount=resolve)
          }});
          window.__logoutAmountPaste=v96PasteAmount('eAmount');
          logout();document.getElementById('gateEmail').focus();
          window.__amountAfterLogout=eAmount.value;
        }""")
        accepted=self.page.evaluate("""async () => {
          window.__resolveLogoutAmount('999,25');return await window.__logoutAmountPaste;
        }""")
        self.assertFalse(accepted)
        self.assertEqual(self.page.evaluate('eAmount.value'),self.page.evaluate('window.__amountAfterLogout'))
        self.assertEqual(self.page.evaluate('document.activeElement.id'),'gateEmail')
        self.page.evaluate("v96OpenCalculator('eAmount')")
        self.assert_calculator_locked()

    def test_denied_late_clipboard_prompt_after_logout_does_not_focus_hidden_amount(self):
        self.prepare();self.page.locator('#eAmount').fill('17.25')
        self.page.evaluate("""() => {
          Object.defineProperty(navigator,'clipboard',{configurable:true,value:{
            readText:()=>new Promise((resolve,reject)=>window.__rejectLogoutClipboard=reject)
          }});
          v96OpenCalculator('eAmount');
          window.__deniedLogoutPaste=v96PasteAmount('v96CalcExpression');
          logout();document.getElementById('gateEmail').focus();
        }""")
        accepted=self.page.evaluate("""async () => {
          window.__rejectLogoutClipboard(Error('PRIVATE_LATE_PROMPT_DENIED'));
          return await window.__deniedLogoutPaste;
        }""")
        self.assertFalse(accepted);self.assert_calculator_locked()
        self.assertEqual(self.page.evaluate('document.activeElement.id'),'gateEmail')



if __name__=='__main__':
    unittest.main()
