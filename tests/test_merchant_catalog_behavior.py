"""Merchant matching and explicit accessible choices; synthetic, network-blocked browser."""
import json
import time
import unittest

import test_local_data_safety as harness


class MerchantCatalogBehavior(unittest.TestCase):
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
        weather = {'at':int(time.time()*1000),'source':'Synthetic local weather',
                   'data':{'temperature_2m':0,'apparent_temperature':0,'weather_code':0,'wind_speed_10m':0}}
        self.open({'marichevy_weather_last_good_v74':json.dumps(weather)})
        self.page.evaluate("""() => {
          session=null;stopCloudSync();state=blankState();localStorage.clear();showApp();
          const ensure=(value,aliases,sector)=>{
            let item=V96_MERCHANTS.find(row=>row.value===value);
            if(!item){item={value,aliases:[],sector};V96_MERCHANTS.push(item)}
            item.aliases=[...new Set([...(item.aliases||[]),...aliases])];
            if(sector)item.sector=sector;
          };
          ensure('ВкусВилл',['вкусвилл','vkusvill'],'продукты');
          ensure('Пятёрочка',['пятерочка','пятёрочка','pyaterochka'],'продукты');
          ensure('Бургер Кинг',['бургер кинг','burger king'],'рестораны');
          ensure('УчебнаяАптека',['uchebnaya pharmacy'],'аптеки');
          ensure('Учебная марка А',['общая учебная марка'],'учебный сектор');
          ensure('Учебная марка Б',['общая учебная марка'],'учебный сектор');
          ensure('Учебный точный',['ранг'],'учебное ранжирование');
          ensure('РангПрефикс',['рангпрефикс'],'учебное ранжирование');
          ensure('Учебный Ранг',['учебный ранг'],'учебное ранжирование');
          state.entries=[{id:'fictional-entry',type:'expense',date:today(),amount:17.42,
            category:'Дети',subcategory:'Подгузники',beneficiary:'Fictional recipient',
            who:'Legacy recipient',store:'vkusvill',comment:'Explicit synthetic purchase',
            pay:'Карта',futureField:{keep:[true,null]}}];
          renderAll();clearEntry();openEntry('expense');v90Choose('Дети');
          document.getElementById('eAmount').value='17,42';
          document.getElementById('eComment').value='Unsaved explicit note';
          v97SetOption('eSubcategory','Подгузники');v97SetOption('eBeneficiary','Fictional recipient');
        }""")
        self.before = self.snapshot()

    def draft(self):
        return self.page.evaluate('v97DraftFields()')

    def settled_field(self, target):
        field = self.page.locator('#'+target)
        field.scroll_into_view_if_needed();field.focus()
        self.page.evaluate('() => new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        return field

    def assert_only_store_changed(self, before, store):
        after = self.draft();self.assertEqual(after.pop('store'), store)
        old = dict(before);old.pop('store');self.assertEqual(after, old)
        self.assertEqual(self.snapshot(), self.before)

    def test_normalization_and_exact_ru_latin_punctuation_aliases_are_canonical(self):
        self.prepare()
        result = self.page.evaluate("""() => ({normal:v96MerchantNormal('  ПЯТЁРОЧКА — 17!  '),
          aliases:['ВКУСВИЛЛ','VkusVill','ПЯТЕРОЧКА','Пятёрочка','pyaterochka',
            'Бургер-Кинг','BURGER.KING','К&Б'].map(raw=>({raw,identity:v96MerchantIdentity(raw)}))})""")
        self.assertEqual(result['normal'], 'пятерочка 17')
        expected = ['ВкусВилл','ВкусВилл','Пятёрочка','Пятёрочка','Пятёрочка',
                    'Бургер Кинг','Бургер Кинг','Красное & Белое']
        for record, canonical in zip(result['aliases'], expected):
            self.assertEqual(record['identity']['original'], record['raw'])
            self.assertEqual(record['identity']['display'], canonical)
        self.assertEqual(self.snapshot(), self.before)

    def test_only_explicit_numeric_or_address_branch_suffixes_identify_a_unique_brand(self):
        self.prepare()
        positive = ['ВкусВилл №17','vkusvill 17','ВкусВилл, ул. Лесная, д.7',
                    'Пятерочка № 25','Бургер Кинг, ул. Учебная, д. 4']
        identities = self.page.evaluate('rows=>rows.map(v96MerchantIdentity)', positive)
        self.assertEqual([item['display'] for item in identities],
                         ['ВкусВилл','ВкусВилл','ВкусВилл','Пятёрочка','Бургер Кинг'])
        negative = ['Не Вкусвилл','Вкусвилл сервис','Вкусвилл17','КБКредит','Сбербанк','КБбанк',
                    'КБ Альфа банк','Бургер Кинг сервис','Мой ВкусВилл','Детский мирный']
        identities = self.page.evaluate('rows=>rows.map(v96MerchantIdentity)', negative)
        for raw, identity in zip(negative, identities):
            self.assertEqual(identity['display'], raw)
            self.assertEqual(identity['brand'], 'generic')
        self.assertEqual(self.snapshot(), self.before)

    def test_duplicate_alias_cannot_silently_pick_the_first_catalog_brand(self):
        self.prepare()
        values = ['общая учебная марка','Общая учебная марка №17',
                  'Общая учебная марка, ул. Лесная, д.7']
        results = self.page.evaluate('rows=>rows.map(v96MerchantIdentity)', values)
        for raw, identity in zip(values, results):
            self.assertEqual(identity['display'], raw)
            self.assertEqual(identity['brand'], 'generic')

    def test_canonical_display_and_alias_history_search_preserve_raw_saved_store(self):
        self.prepare()
        self.page.evaluate("go('history');document.getElementById('fMonth').value='';renderHistory()")
        self.assertIn('ВкусВилл', self.page.locator('#historyBody').inner_text())
        for query in ['vkusvill','ВкусВилл']:
            self.page.locator('#fSearch').fill(query)
            self.assertEqual(self.page.locator('#historyBody .v76-entry-row').count(), 1)
            self.assertIn('ВкусВилл', self.page.locator('#historyBody').inner_text())
        text = self.page.evaluate("v96MerchantSearchText('vkusvill')")
        self.assertIn('vkusvill', text.lower());self.assertIn('ВкусВилл', text)
        self.assertEqual(self.page.evaluate('state.entries[0].store'), 'vkusvill')
        self.assertEqual(self.snapshot(), self.before)

    def test_suggestion_rank_alias_sector_search_limit_and_dedup_are_meaningful(self):
        self.prepare()
        result = self.page.evaluate("""() => {
          for(let i=0;i<12;i++)V96_MERCHANTS.push({value:'УчебныйЛимит '+i,aliases:['лимитпроверки '+i],sector:'учебное'});
          state.entries.push({...state.entries[0],id:'same-brand',store:'ВКУСВИЛЛ'});
          const saved=V96_MERCHANTS.slice();let sector;
          try {
            // Isolate the sector behavior from the production catalog's eight-result cap.
            V96_MERCHANTS.splice(0,V96_MERCHANTS.length,saved.find(item=>item.value==='УчебнаяАптека'));
            sector=v96MerchantSuggestions('аптеки').map(item=>item.value);
          } finally {V96_MERCHANTS.splice(0,V96_MERCHANTS.length,...saved)}
          return {rank:v96MerchantSuggestions('ранг').map(item=>item.value),
            token:v96MerchantSuggestions('кинг').map(item=>item.value),
            alias:v96MerchantSuggestions('uchebnaya pharmacy').map(item=>item.value),
            sector,
            limit:v96MerchantSuggestions('лимитпроверки').map(item=>item.value),
            unique:v96MerchantSuggestions('vkusvill').map(item=>item.value)};
        }""")
        ranked = result['rank']
        self.assertLess(ranked.index('Учебный точный'), ranked.index('РангПрефикс'))
        self.assertLess(ranked.index('РангПрефикс'), ranked.index('Учебный Ранг'))
        self.assertIn('Бургер Кинг', result['token'])
        self.assertIn('УчебнаяАптека', result['alias']);self.assertIn('УчебнаяАптека', result['sector'])
        self.assertEqual(len(result['limit']), 8)
        self.assertEqual(len(set(result['limit'])), 8)
        self.assertEqual(result['unique'].count('ВкусВилл'), 1)

    def test_typing_render_and_explicit_pointer_choice_change_only_store_draft(self):
        self.prepare();requests=[]
        self.page.on('request', lambda request: requests.append(request.url))
        draft = self.draft();field = self.page.locator('#eStore');field.fill('vkus')
        self.assert_only_store_changed(draft, 'vkus')
        self.page.evaluate('renderToday();renderHistory();renderAnalytics()')
        self.assert_only_store_changed(draft, 'vkus')
        option = self.page.locator('#eStoreSuggestions').get_by_role('option', name='ВкусВилл', exact=True)
        self.assertTrue(option.is_visible());option.click()
        self.assert_only_store_changed(draft, 'ВкусВилл')
        self.assertEqual(field.get_attribute('aria-expanded'), 'false')
        self.assertEqual(requests, [])

    def test_combobox_keyboard_navigation_and_explicit_enter_follow_active_option(self):
        self.prepare();draft = self.draft();field = self.page.locator('#eStore');field.fill('ранг')
        self.assertEqual(field.get_attribute('role'), 'combobox')
        self.assertEqual(field.get_attribute('aria-autocomplete'), 'list')
        self.assertEqual(field.get_attribute('aria-controls'), 'eStoreSuggestions')
        options = self.page.locator('#eStoreSuggestions [role="option"]')
        self.assertGreaterEqual(options.count(), 3)
        field.press('End')
        last = options.last;self.assertEqual(field.get_attribute('aria-activedescendant'), last.get_attribute('id'))
        self.assertEqual(last.get_attribute('aria-selected'), 'true')
        field.press('Home')
        self.assertEqual(field.get_attribute('aria-activedescendant'), options.first.get_attribute('id'))
        field.press('ArrowDown')
        self.assertEqual(field.get_attribute('aria-activedescendant'), options.nth(1).get_attribute('id'))
        field.press('ArrowUp')
        self.assertEqual(field.get_attribute('aria-activedescendant'), options.first.get_attribute('id'))
        chosen = options.first.locator('span').last.inner_text();field.press('Enter')
        self.assert_only_store_changed(draft, chosen)
        self.assertEqual(field.get_attribute('aria-expanded'), 'false')
        self.assertIsNone(field.get_attribute('aria-activedescendant'))

    def test_escape_tab_and_ime_enter_never_implicitly_choose_a_merchant(self):
        self.prepare();draft = self.draft();field = self.page.locator('#eStore');field.fill('vkus')
        self.page.evaluate("""() => {
          const field=document.getElementById('eStore');
          field.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));
          field.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',isComposing:true,bubbles:true}));
        }""")
        self.assert_only_store_changed(draft, 'vkus')
        self.page.evaluate("document.getElementById('eStore').dispatchEvent(new CompositionEvent('compositionend',{bubbles:true}))")
        field.press('Escape');self.assertEqual(field.get_attribute('aria-expanded'), 'false')
        self.assert_only_store_changed(draft, 'vkus')
        field.fill('vkus');field.press('Tab')
        self.assert_only_store_changed(draft, 'vkus')
        self.page.wait_for_function("document.getElementById('eStore').getAttribute('aria-expanded')==='false'")

    def test_portal_geometry_and_stacking_fit_phone_and_desktop_in_entry_and_edit_modal(self):
        self.prepare()
        for width in [320,390,1280]:
            with self.subTest(width=width):
                self.page.set_viewport_size({'width':width,'height':900})
                for target in ['eStore','xStore']:
                    if target == 'xStore':
                        self.page.evaluate("openEdit('fictional-entry')")
                    try:
                        field = self.settled_field(target);field.fill('vkus')
                        dropdown = self.page.locator('#'+target+'Suggestions')
                        self.assertTrue(dropdown.is_visible())
                        geometry = dropdown.evaluate("""el=>{
                          const r=el.getBoundingClientRect(),option=el.querySelector('[role=option]'),o=option.getBoundingClientRect();
                          const top=document.elementFromPoint(o.left+Math.min(o.width/2,20),o.top+o.height/2);
                          return {body:el.parentElement===document.body,position:getComputedStyle(el).position,
                            left:r.left,right:r.right,top:r.top,bottom:r.bottom,viewport:innerWidth,height:innerHeight,
                            onTop:!!top&&option.contains(top)};
                        }""")
                        self.assertTrue(geometry['body']);self.assertEqual(geometry['position'], 'fixed')
                        self.assertGreaterEqual(geometry['left'], 0);self.assertLessEqual(geometry['right'], width)
                        self.assertGreaterEqual(geometry['top'], 0);self.assertLessEqual(geometry['bottom'], 900)
                        self.assertTrue(geometry['onTop'], target)
                    finally:
                        if target == 'xStore':
                            self.page.evaluate('closeEdit()')
                        else:
                            self.page.locator('#eStore').press('Escape')
                self.assertEqual(self.snapshot(), self.before)

    def test_portals_close_on_logout_input_disconnect_and_modal_reopen_without_duplicate_ids(self):
        self.prepare();errors=[]
        self.page.on('pageerror', lambda error: errors.append(str(error)))
        field = self.page.locator('#eStore')
        for attribute in ['readOnly','disabled']:
            with self.subTest(locked=attribute):
                field.fill('vkus')
                self.assertTrue(self.page.locator('#eStoreSuggestions').is_visible())
                self.page.evaluate("""attribute=>{
                  const input=document.getElementById('eStore');
                  const stale=document.querySelector('#eStoreSuggestions [role=option]');
                  input[attribute]=true;
                  input.dispatchEvent(new Event('focus'));
                  input.dispatchEvent(new Event('input',{bubbles:true}));
                  input.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true}));
                  input.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
                  stale?.click();
                }""", attribute)
                self.assertFalse(self.page.locator('#eStoreSuggestions').is_visible())
                self.assertEqual(field.input_value(), 'vkus')
                self.assertEqual(self.snapshot(), self.before)
                self.page.evaluate("attribute=>document.getElementById('eStore')[attribute]=false", attribute)
        field.fill('vkus')
        self.assertTrue(self.page.locator('#eStoreSuggestions').is_visible())
        self.page.evaluate("window.dispatchEvent(new Event('scroll'))")
        self.page.wait_for_function("document.getElementById('eStore').getAttribute('aria-expanded')==='false'")
        self.assertEqual(errors, [])
        self.page.evaluate("openEdit('fictional-entry')")
        original_style = self.page.locator('#editModal .modal').get_attribute('style')
        self.page.locator('#editModal .modal').evaluate("el=>{el.style.maxHeight='220px';el.style.overflowY='auto'}")
        self.settled_field('xStore').fill('vkus')
        self.assertTrue(self.page.locator('#xStoreSuggestions').is_visible())
        scroll = self.page.locator('#editModal .modal').evaluate("""el=>{
          const before=el.scrollTop;el.scrollTop=before>0?0:el.scrollHeight-el.clientHeight;
          return {before,after:el.scrollTop};
        }""")
        self.assertNotEqual(scroll['before'], scroll['after'])
        self.page.wait_for_function("document.getElementById('xStore').getAttribute('aria-expanded')==='false'")
        self.assertEqual(errors, [])
        self.page.locator('#editModal .modal').evaluate("(el,style)=>{if(style===null)el.removeAttribute('style');else el.setAttribute('style',style)}", original_style)
        self.page.evaluate('closeEdit()')
        for _ in range(3):
            self.page.evaluate("openEdit('fictional-entry')")
            self.settled_field('xStore').fill('vkus')
            self.assertEqual(self.page.locator('#xStoreSuggestions').count(), 1)
            self.assertTrue(self.page.locator('#xStoreSuggestions').is_visible())
            self.page.evaluate('closeEdit()')
            self.assertFalse(self.page.locator('#xStoreSuggestions').is_visible())
        self.page.evaluate("openEdit('fictional-entry')")
        self.settled_field('xStore').fill('vkus')
        self.page.evaluate("document.getElementById('xStore').remove()")
        self.page.wait_for_function("!document.getElementById('xStoreSuggestions')||document.getElementById('xStoreSuggestions').hidden")
        self.page.evaluate('closeEdit()')
        self.page.locator('#eStore').fill('vkus');self.page.evaluate('logout()')
        self.assertFalse(self.page.locator('#eStoreSuggestions').is_visible())
        self.assertEqual(self.page.locator('[id="xStoreSuggestions"]').count(), 0)
        self.assertEqual(self.page.evaluate('state.entries[0].store'), 'vkusvill')
        self.assertEqual(errors, [])

    def test_explicit_touch_choice_inside_edit_modal_preserves_finances_until_separate_save(self):
        self.prepare()
        self.page.evaluate("openEdit('fictional-entry')")
        fields = self.page.locator('#editForm input,#editForm select').evaluate_all(
            '(rows)=>Object.fromEntries(rows.map(el=>[el.id,el.value]))')
        self.page.locator('#xStore').fill('vkus')
        option = self.page.locator('#xStoreSuggestions').get_by_role('option', name='ВкусВилл', exact=True)
        option.dispatch_event('pointerdown', {'pointerType':'touch','isPrimary':True})
        option.dispatch_event('click')
        self.assertEqual(self.page.locator('#xStore').input_value(), 'ВкусВилл')
        after = self.page.locator('#editForm input,#editForm select').evaluate_all(
            '(rows)=>Object.fromEntries(rows.map(el=>[el.id,el.value]))')
        fields.pop('xStore');after.pop('xStore');self.assertEqual(after, fields)
        self.assertEqual(self.snapshot(), self.before)

    def test_large_history_query_builds_one_catalog_and_identifies_each_unique_store_once(self):
        self.prepare()
        result = self.page.evaluate("""() => {
          // Do not render these rows: this regression measures the autocomplete query alone.
          state.entries=Array.from({length:20000},(_,index)=>({id:'fictional-large-'+index,
            type:'expense',date:today(),amount:1.25,category:'Прочее',
            store:index%2?'Учебная лавка Б':'Учебная лавка А',
            who:'Fictional recipient',comment:'Synthetic performance fixture'}));
          const stateBefore=JSON.stringify(state),storageBefore=JSON.stringify(
            Object.fromEntries(Object.keys(localStorage).sort().map(key=>[key,localStorage.getItem(key)])));
          const catalogBefore=V96_MERCHANTS.slice();
          const syntheticMatches=new Set(['УчебнаяАптека','Учебная марка А','Учебная марка Б']);
          const nativeCatalog=window.v96MerchantCatalog,nativeIdentity=window.v96MerchantIdentity;
          let catalogs=0,identities=0;
          try {
            V96_MERCHANTS.splice(0,V96_MERCHANTS.length,...catalogBefore.filter(item=>!syntheticMatches.has(item.value)));
            window.v96MerchantCatalog=function(...args){catalogs++;return nativeCatalog.apply(this,args)};
            window.v96MerchantIdentity=function(...args){identities++;return nativeIdentity.apply(this,args)};
            const suggestions=v96MerchantSuggestions('учебная');
            return {catalogs,identities,labels:suggestions.map(item=>item.label),
              rowsUnchanged:stateBefore===JSON.stringify(state),
              storageUnchanged:storageBefore===JSON.stringify(Object.fromEntries(
                Object.keys(localStorage).sort().map(key=>[key,localStorage.getItem(key)])))};
          } finally {
            window.v96MerchantCatalog=nativeCatalog;window.v96MerchantIdentity=nativeIdentity;
            V96_MERCHANTS.splice(0,V96_MERCHANTS.length,...catalogBefore);
          }
        }""")
        self.assertEqual(result['catalogs'], 1)
        self.assertLessEqual(result['identities'], 4)
        self.assertEqual(set(result['labels']), {'Учебная лавка А','Учебная лавка Б'})
        self.assertEqual(len(result['labels']), 2)
        self.assertTrue(result['rowsUnchanged'])
        self.assertTrue(result['storageUnchanged'])


if __name__ == '__main__':
    unittest.main()
