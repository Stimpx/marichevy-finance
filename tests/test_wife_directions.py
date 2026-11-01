"""Family direction views and explicit configuration on fictional data only."""
import json
from pathlib import Path
import sys
import unittest

import test_local_data_safety as harness


class WifeDirections(unittest.TestCase):
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
          session=null;stopCloudSync();state=blankState();localStorage.clear();showApp();
          const row=(id,amount,category,beneficiary,extra={})=>({id,type:'expense',
            date:month()+'-05',amount,category,beneficiary,who:'Original author',
            comment:'Fictional purchase',futureField:{keep:[true,null,id]},...extra});
          state.entries=[row('personal-sub',100.01,'Подписки','Сергей',{store:'Учебный сервис'}),
            row('taxi',20.02,'Авто и транспорт','Виктория',{subcategory:'Такси'}),
            row('car',300.03,'Бензин','Сергей'),row('medicine',40.04,'Аптека и медицина',''),
            row('gift',50.05,'Подарки','Алиса'),row('unlinked-split',100.06,'Кредит','Общее',{comment:'Сплит'}),
            row('linked-loan',20.07,'Кредит','Виктория',{installmentId:'fictional-loan'}),
            row('utilities',80.08,'ЖКХ','Общее'),
            {...row('income',999,'Доход','Сергей'),type:'income'},
            {...row('transfer',80,'Движение денег','Сергей'),type:'transfer'}];
          state.installments=[{id:'fictional-loan',title:'Учебная рассрочка',parts:[],links:{part:'linked-loan'}}];
          renderAll();clearEntry();openEntry('expense');document.getElementById('v90Extra').open=true;
        }""")

    def test_read_only_views_reconcile_once_and_overlap_only_as_views(self):
        self.prepare()
        before = self.snapshot()
        result = self.page.evaluate("""() => {
          const rows=expenses(month()),tiles=v99DirectionTiles(rows);
          return {total:Math.round(sum(rows)*100),
            person:tiles.find(t=>t.id==='person:Сергей').cents,
            service:tiles.find(t=>t.id==='subscriptions').cents,
            car:tiles.find(t=>t.id==='car').entries.map(e=>e.id),
            loan:tiles.find(t=>t.id==='loans').entries.map(e=>e.id),
            gifts:tiles.find(t=>t.id==='gifts').cents,
            unlinked:v99DirectionDetail('loans',state.entries.find(e=>e.id==='unlinked-split')),
            linked:v99DirectionDetail('loans',state.entries.find(e=>e.id==='linked-loan')),
            serviceName:v99DirectionDetail('subscriptions',state.entries[0]),
            recipientTotal:Math.round(v86TargetTotals(rows).reduce((n,p)=>n+p[1],0)*100)};
        }""")
        self.assertEqual(result['total'], 71036)
        self.assertEqual(result['recipientTotal'], result['total'])
        self.assertEqual(result['person'], 40004)
        self.assertEqual(result['service'], 10001)
        self.assertEqual(result['car'], ['car'])
        self.assertEqual(result['loan'], ['unlinked-split', 'linked-loan'])
        self.assertEqual(result['gifts'], 5005)
        self.assertIn('Без привязки', result['unlinked'])
        self.assertEqual(result['linked'], 'Учебная рассрочка')
        self.assertEqual(result['serviceName'], 'Учебный сервис')
        self.assertEqual(self.snapshot(), before)

    def choose_destination(self, value):
        self.page.get_by_role('combobox',name='Для кого или на что?',exact=True).click()
        self.page.get_by_role('option',name=value,exact=True).click()

    def test_one_destination_select_routes_special_choices_and_preserves_dirty_fields(self):
        self.prepare()
        before = self.snapshot()
        self.page.locator('#eAmount').fill('55,25')
        self.page.locator('#eStore').fill('Фиктивное место')
        self.page.locator('#eComment').fill('Мой комментарий')
        self.page.locator('#eDate').fill('2026-10-19')
        draft = self.page.evaluate("({amount:eAmount.value,store:eStore.value,comment:eComment.value,date:eDate.value,pay:ePay.value})")
        self.assertEqual(self.page.locator('#v99EntryDirectionTiles').count(),0)
        self.assertEqual(self.page.locator('#v99EntryDirectionsTitle').count(),0)
        self.assertEqual(self.page.locator('#v81BeneficiaryField').get_by_role('combobox').count(),1)
        self.assertEqual(self.page.locator('#eBeneficiary').input_value(),'Не указано')
        self.choose_destination('Автомобиль')
        self.assertEqual(self.page.locator('#eBeneficiary').input_value(),'Автомобиль')
        self.assertEqual(self.page.locator('#eCategory').input_value(),'Авто и транспорт')
        self.choose_destination('Сергей')
        self.assertEqual(self.page.locator('#eBeneficiary').input_value(),'Сергей')
        self.assertEqual(self.page.locator('#eCategory').input_value(),'Авто и транспорт')
        self.choose_destination('Кредиты и рассрочки')
        self.assertEqual(self.page.locator('#eBeneficiary').input_value(),'Кредиты и рассрочки')
        self.assertEqual(self.page.locator('#eCategory').input_value(),'Кредит')
        self.assertTrue(self.page.locator('#v93CreditHelp').is_visible())
        self.assertEqual(self.page.locator('#v93CreditAccounting').input_value(),'')
        self.assertEqual(self.page.evaluate("({amount:eAmount.value,store:eStore.value,comment:eComment.value,date:eDate.value,pay:ePay.value})"),draft)
        self.assertEqual(self.snapshot(),before)
        self.page.locator('#v90Save').click()
        self.assertEqual(self.snapshot(),before)

    def test_only_global_calculator_remains_and_copy_paste_are_available(self):
        self.prepare();before=self.snapshot()
        tools=self.page.locator('#eAmount').locator('..').locator('.v96-amount-tools')
        self.assertEqual(tools.get_by_role('button',name='Калькулятор',exact=True).count(),0)
        self.assertEqual(tools.get_by_role('button',name='Копировать сумму',exact=True).count(),1)
        self.assertEqual(tools.get_by_role('button',name='Вставить сумму',exact=True).count(),1)
        self.page.get_by_role('button',name='Открыть калькулятор',exact=True).click()
        self.assertTrue(self.page.locator('#v96Calculator').is_visible())
        self.page.get_by_role('button',name='Закрыть калькулятор',exact=True).click()
        self.assertEqual(self.snapshot(),before)

    def test_locked_select_and_add_custom_control_unlock_without_clear(self):
        self.open()
        self.assertTrue(self.page.evaluate("document.getElementById('appRoot').classList.contains('auth-locked')"))
        self.page.evaluate("showApp();openEntry('expense')")
        self.choose_destination('Сергей')
        self.assertEqual(self.page.locator('#eBeneficiary').input_value(),'Сергей')
        self.page.evaluate('showGate()')
        self.assertFalse(self.page.evaluate("v99OpenDirectionEditor('entry')"))
        self.page.evaluate("showApp();openEntry('expense')")
        self.choose_destination('Автомобиль')
        self.assertEqual(self.page.locator('#eCategory').input_value(),'Авто и транспорт')

    def test_generated_downloadable_demo_destination_select_works_without_clear(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
        try:
            from build_bundle import transform_demo
            demo=transform_demo(harness.HTML.read_text())
        finally:
            sys.path.pop(0)
        self.context.route(self.base,lambda route:route.fulfill(status=200,content_type='text/html',body=demo))
        self.page.goto(self.base,wait_until='load')
        self.page.wait_for_function("!document.getElementById('appRoot').classList.contains('auth-locked')")
        before=self.page.evaluate('JSON.stringify(state)')
        self.page.evaluate("openEntry('expense')")
        self.choose_destination('Елена')
        self.assertEqual(self.page.locator('#eBeneficiary').input_value(),'Елена')
        self.choose_destination('Кредиты и рассрочки')
        self.assertEqual(self.page.locator('#eCategory').input_value(),'Кредит')
        self.assertEqual(self.page.evaluate('JSON.stringify(state)'),before)

    def test_opening_legacy_edit_preserves_original_recipient_and_category(self):
        self.prepare();before=self.snapshot()
        self.page.evaluate("openEdit('car')")
        self.assertEqual(self.page.locator('label[for="xBeneficiary"]').inner_text(),'Для кого или на что?')
        self.assertEqual(self.page.locator('#xBeneficiary').input_value(),'Сергей')
        self.assertEqual(self.page.locator('#xCat').input_value(),'Бензин')
        self.assertTrue(self.page.locator('#xBeneficiary option[value="Автомобиль"]').count())
        self.assertTrue(self.page.locator('#xBeneficiary option[value="Кредиты и рассрочки"]').count())
        self.page.locator('#editModal').get_by_role('button',name='Отмена',exact=True).click()
        self.assertEqual(self.snapshot(),before)

    def test_all_person_choices_are_equal_and_unknown_historical_targets_remain(self):
        self.prepare()
        result = self.page.evaluate("""() => {
          state.entries.push({id:'legacy-recipient',type:'expense',date:today(),amount:1,
            category:'Продукты',beneficiary:'Старинное направление'});
          const old=JSON.stringify(state);
          const choices=['Сергей','Виктория','Алиса','Майя','Макс','Дени'].map(person=>{
            v81FillDetails('e','Спорт и здоровье','',person);
            return [...document.querySelector('#eCategory').options].map(o=>o.value);
          });
          return {choices,unknown:v99BeneficiaryChoices().includes('Старинное направление'),
            tile:v99DirectionTiles(expenses(month())).find(t=>t.id==='custom:Старинное направление')?.cents,
            unchanged:old===JSON.stringify(state)};
        }""")
        self.assertTrue(all(c == result['choices'][0] for c in result['choices']))
        self.assertIn('Спорт и здоровье', result['choices'][0])
        self.assertIn('Аптека и медицина', result['choices'][0])
        self.assertTrue(result['unknown'])
        self.assertEqual(result['tile'], 100)
        self.assertTrue(result['unchanged'])

    def open_editor(self, name):
        self.page.evaluate("v99OpenDirectionEditor('entry')")
        self.page.locator('#v99DirectionName-entry').fill(name)

    def submit_editor(self):
        return self.page.evaluate("v99SubmitDirectionEditor('entry')")

    def test_explicit_custom_config_save_preserves_history_and_dirty_draft(self):
        self.prepare()
        self.page.locator('#eAmount').fill('123,45')
        self.page.locator('#v90Search').fill('Мой незавершённый поиск')
        self.page.locator('#eComment').fill('Незавершённая покупка')
        before = self.page.evaluate("({rows:JSON.stringify(state.entries),draft:v97DraftFields()})")
        self.open_editor('Дача')
        self.assertTrue(self.submit_editor())
        result = self.page.evaluate("""() => ({rows:JSON.stringify(state.entries),
          directions:state.settings.preferences.expenseDirections,
          saved:JSON.parse(localStorage.getItem(KEYS.state)).settings.preferences.expenseDirections,
          pending:localStorage.getItem(KEYS.pending)!==null,
          option:[...document.querySelector('#eBeneficiary').options].some(option=>option.value==='Дача')})""")
        self.assertEqual(result['rows'], before['rows'])
        self.assertEqual(result['directions'], ['Дача'])
        self.assertEqual(result['saved'], ['Дача'])
        self.assertTrue(result['pending'])
        self.assertTrue(result['option'])
        self.assertEqual(self.page.locator('#eAmount').input_value(), '123,45')
        self.assertEqual(self.page.locator('#v90Search').input_value(), 'Мой незавершённый поиск')
        self.assertEqual(self.page.locator('#eComment').input_value(), 'Незавершённая покупка')
        self.assertEqual(self.page.evaluate('v97DraftFields()'), before['draft'])
        self.choose_destination('Дача')
        self.assertEqual(self.page.locator('#eBeneficiary').input_value(), 'Дача')

    def test_duplicate_reserved_limit_and_locked_or_viewer_config_do_not_write(self):
        self.prepare()
        for name in ('Сергей', '  сЕРГЕЙ  ', 'Подписки и онлайн-сервисы', 'Подписки', 'Семья', 'семья / общее', '__proto__'):
            self.open_editor(name)
            before = self.snapshot()
            self.assertFalse(self.submit_editor())
            self.assertEqual(self.snapshot(), before)
        self.page.evaluate("state.settings.preferences.expenseDirections=Array.from({length:32},(_,i)=>'Свое '+i)")
        self.open_editor('Тридцать третье')
        before = self.snapshot()
        self.assertFalse(self.submit_editor())
        self.assertEqual(self.snapshot(), before)
        self.page.evaluate("window.__FINANCE_BRIDGE__={active:true,role:'viewer'}")
        self.assertFalse(self.page.evaluate("v99OpenDirectionEditor('home')"))
        self.assertFalse(self.page.evaluate("v99ChooseEntryDirection('person:Сергей')"))
        self.assertEqual(self.snapshot(), before)
        self.page.evaluate("delete window.__FINANCE_BRIDGE__;document.getElementById('appRoot').classList.add('auth-locked')")
        self.assertFalse(self.page.evaluate("v99OpenDirectionEditor('home')"))
        self.assertEqual(self.snapshot(), before)

    def test_quota_failure_is_not_reported_saved_and_retry_does_not_duplicate(self):
        self.prepare()
        self.open_editor('На ремонт')
        self.page.evaluate("() => {window.__originalSetItem=Storage.prototype.setItem;Storage.prototype.setItem=function(){throw new DOMException('fictional quota','QuotaExceededError')}}")
        self.assertFalse(self.submit_editor())
        self.assertTrue(self.page.locator('#v99DirectionEditorEntry').is_visible())
        self.assertIn('Не удалось сохранить', self.page.locator('#v99DirectionEditorEntry [role=status]').inner_text())
        self.page.evaluate("() => {Storage.prototype.setItem=window.__originalSetItem}")
        self.assertTrue(self.submit_editor())
        self.assertEqual(self.page.evaluate('state.settings.preferences.expenseDirections'), ['На ремонт'])

    def test_malformed_imported_config_is_preserved_and_late_save_does_not_reopen(self):
        self.prepare()
        for raw in ([' С пробелами '], ['Дача', 'дача'], [17], 'unknown future settings'):
            self.page.evaluate('(raw) => {state.settings.preferences.expenseDirections=raw}', raw)
            self.open_editor('Новая плитка')
            before=self.snapshot()
            self.assertFalse(self.submit_editor())
            self.assertEqual(self.snapshot(), before)
        self.page.evaluate("delete state.settings.preferences.expenseDirections")
        self.open_editor('На отдых')
        self.page.evaluate("() => {window.__originalSaveAll=saveAll;window.__releaseDirectionSave=null;saveAll=()=>new Promise(resolve=>window.__releaseDirectionSave=resolve);window.__directionSaving=v99SubmitDirectionEditor('entry')}")
        self.page.wait_for_function('window.__releaseDirectionSave!==null')
        self.assertFalse(self.page.evaluate("v99OpenDirectionEditor('entry')"))
        self.page.evaluate("() => {authEpoch++;document.getElementById('appRoot').classList.add('auth-locked');window.__releaseDirectionSave(true)}")
        self.assertFalse(self.page.evaluate('window.__directionSaving'))
        self.assertEqual(self.page.locator('#v99DirectionEditorEntry [role=status]').inner_text(), '')
        self.page.evaluate("() => {saveAll=window.__originalSaveAll}")
        self.page.evaluate("document.getElementById('appRoot').classList.remove('auth-locked')")
        self.assertTrue(self.page.evaluate("v99OpenDirectionEditor('entry')"))

    def test_custom_label_is_escaped_and_select_stays_inside_mobile_card(self):
        self.prepare()
        self.page.set_viewport_size({'width':320,'height':900})
        self.open_editor('<b>Дача</b>')
        self.assertTrue(self.submit_editor())
        option=self.page.locator('#eBeneficiary option').filter(has_text='<b>Дача</b>')
        self.assertEqual(option.inner_text(),'<b>Дача</b>')
        self.assertEqual(option.locator('b').count(),0)
        self.page.get_by_role('combobox',name='Для кого или на что?',exact=True).click()
        visible=self.page.get_by_role('option',name='<b>Дача</b>',exact=True)
        self.assertEqual(visible.locator('b').count(),0)
        self.assertEqual(self.page.evaluate('document.documentElement.scrollWidth>innerWidth'),False)
        box=visible.bounding_box()
        self.assertGreaterEqual(box['x'],0)
        self.assertLessEqual(box['x']+box['width'],320)
        visible.click()
        self.assertEqual(self.page.locator('#eBeneficiary').input_value(),'<b>Дача</b>')


if __name__ == '__main__':
    unittest.main()
