"""Local merchant aliases, embedded logos and explicit autocomplete; fictional stores only."""
import json
import time
import unittest
import test_local_data_safety as harness


class MerchantBadges(unittest.TestCase):
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
        # Keep the unrelated weather card on its supported fresh-cache path so
        # the no-request assertion measures this merchant feature alone.
        weather={'at':int(time.time()*1000),'source':'Fictional weather fixture',
                 'data':{'temperature_2m':0,'apparent_temperature':0,'weather_code':0,'wind_speed_10m':0}}
        self.open({'marichevy_weather_last_good_v74':json.dumps(weather)})
        self.page.evaluate("session=null;state=blankState();localStorage.clear();showApp();clearEntry();openEntry('expense')")

    def seed_merchants(self):
        self.page.evaluate("""() => {
          state.entries=[['fictional-kb','кб','Продукты'],['fictional-familia','фамилия','Одежда'],
            ['fictional-dm','Детский мир','Здоровье']].map(([id,store,category])=>({
              id,store,category,type:'expense',date:today(),amount:17.42,who:'Общее',comment:'Fictional fixture'}));
          document.getElementById('homeMonth').value=month();document.getElementById('analyticsMonth').value=month();
          for(const id of ['fType','fCat','fWho','fSearch'])document.getElementById(id).value='';
          document.getElementById('fMonth').value=month();
        }""")

    def test_requested_brand_aliases_use_safe_local_assets(self):
        self.prepare();requests=[]
        self.page.on('request',lambda request: requests.append(request.url))
        result=self.page.evaluate(r"""() => ['КБ','к&б','КрасноеБелое','Красное & Белое','Красное и Белое',
          'ДЕТСКИЙ МИР','Детский-мир','фамилия','Familia','familia'].map(store=>{
            const box=document.createElement('div');box.innerHTML=v96MerchantBadge(store);
            return {display:v96MerchantDisplayName(store),brand:box.firstElementChild?.dataset.merchantBrand,
              hidden:box.firstElementChild?.getAttribute('aria-hidden'),
              external:[...box.querySelectorAll('script,[onerror],image,use,[href],[src]')].filter(node=>node.tagName==='SCRIPT'||node.hasAttribute('onerror')||node.hasAttribute('href')||(node.hasAttribute('src')&&!/^data:image\/(?:png|svg\+xml);base64,/.test(node.getAttribute('src')))).length};
          })""")
        for record in result[:5]:
            self.assertEqual(record['display'],'Красное & Белое');self.assertEqual(record['brand'],'krasnoe-beloe')
        for record in result[5:7]:
            self.assertEqual(record['display'],'Детский мир');self.assertEqual(record['brand'],'detskiy-mir')
        for record in result[7:]:
            self.assertEqual(record['display'],'Familia');self.assertEqual(record['brand'],'familia')
        self.assertTrue(all(r['hidden']=='true' and r['external']==0 for r in result))
        self.assertEqual(requests,[])

    def test_unknown_names_are_safe_and_boundaries_do_not_guess_brands(self):
        self.prepare()
        names=['КБ Альфа банк','КБанк','Банк КрасноеБелое','Детский мирный','нефамилия','MyFamiliaShop',
               '<img src="https://merchant.invalid/track" onerror="window.__merchantXss=1">','Моя вымышленная лавка']
        result=self.page.evaluate(r"""names=>names.map(store=>{
          const first=v96MerchantBadge(store),second=v96MerchantBadge(store);
          const box=document.createElement('div');box.innerHTML=first;
          return {same:first===second,display:v96MerchantDisplayName(store),brand:box.firstElementChild?.dataset.merchantBrand,
            external:[...box.querySelectorAll('script,[onerror],image,use,[href],[src]')].filter(node=>node.tagName==='SCRIPT'||node.hasAttribute('onerror')||node.hasAttribute('href')||(node.hasAttribute('src')&&!/^data:image\/(?:png|svg\+xml);base64,/.test(node.getAttribute('src')))).length};
        })""",names)
        for name,record in zip(names,result):
            self.assertEqual(record['display'],name);self.assertEqual(record['brand'],'generic')
            self.assertTrue(record['same']);self.assertEqual(record['external'],0)
        self.assertEqual(self.page.evaluate("v96MerchantBadge('   ')"),'')
        self.assertIsNone(self.page.evaluate('window.__merchantXss'))

    def test_all_four_operation_views_show_badges_without_rewriting_history(self):
        self.prepare();self.seed_merchants()
        result=self.page.evaluate(r"""() => {
          const before=JSON.stringify(state.entries);renderToday();renderHistory();renderHome();
          v84Drill('group',expenseEntryGroup(state.entries[0]),'home');
          return {before,after:JSON.stringify(state.entries),
            views:['todayList','historyBody','recent','v84DrillEntries'].map(id=>{
              const root=document.getElementById(id);
              return {id,brands:[...root.querySelectorAll('[data-merchant-brand]')].map(e=>e.dataset.merchantBrand),text:root.textContent};
            })};
        }""")
        self.assertEqual(result['after'],result['before'])
        for view in result['views']:
            with self.subTest(view=view['id']):
                self.assertIn('krasnoe-beloe',view['brands']);self.assertIn('Красное & Белое',view['text'])
                if view['id']!='v84DrillEntries':
                    self.assertIn('familia',view['brands']);self.assertIn('Familia',view['text'])
                    self.assertIn('detskiy-mir',view['brands']);self.assertIn('Детский мир',view['text'])

    def test_history_search_matches_typed_and_canonical_aliases_not_equal_amounts(self):
        self.prepare();self.seed_merchants()
        self.page.evaluate("go('history')")
        original=self.page.evaluate('JSON.stringify(state.entries)')
        for query,label in [('кб','Красное & Белое'),('Красное & Белое','Красное & Белое'),
                            ('familia','Familia'),('фамилия','Familia'),('детский мир','Детский мир')]:
            with self.subTest(query=query):
                self.page.locator('#fSearch').fill(query)
                self.assertEqual(self.page.locator('#historyBody tr').count(),1)
                self.assertIn(label,self.page.locator('#historyBody').inner_text())
        self.assertEqual(self.page.evaluate('JSON.stringify(state.entries)'),original)

    def test_autocomplete_requires_explicit_choice_and_preserves_category(self):
        self.prepare();self.page.evaluate("v90Choose('Продукты')")
        field=self.page.locator('#eStore');field.fill('кб')
        self.assertEqual(field.input_value(),'кб')
        self.assertEqual(field.get_attribute('role'),'combobox')
        choice=self.page.locator('#eStoreSuggestions').get_by_role('option',name='Красное & Белое')
        self.assertTrue(choice.is_visible())
        field.press('Escape');self.assertEqual(field.input_value(),'кб')
        self.assertEqual(field.get_attribute('aria-expanded'),'false')
        field.fill('кб');choice.click();self.assertEqual(field.input_value(),'Красное & Белое')
        self.assertEqual(self.page.locator('#eCategory').input_value(),'Продукты')
        self.page.locator('#eAmount').fill('17,42');self.page.evaluate('addEntry()')
        self.assertEqual(self.page.evaluate('state.entries.at(-1).store'),'Красное & Белое')
        self.assertEqual(self.page.evaluate('state.entries.at(-1).category'),'Продукты')

    def test_saved_unknown_store_is_suggested_and_edit_keyboard_choice_is_explicit(self):
        self.prepare()
        self.page.evaluate("""() => {
          state.entries=[{id:'fictional-entry',type:'expense',date:today(),amount:17.42,
            store:'Лавка у дома',category:'Продукты',who:'Общее'}];
        }""")
        field=self.page.locator('#eStore');field.fill('лавка')
        self.assertTrue(self.page.locator('#eStoreSuggestions').get_by_role('option',name='Лавка у дома').is_visible())
        before=self.page.evaluate('JSON.stringify(state.entries)')
        self.page.evaluate("openEdit('fictional-entry')")
        edit=self.page.locator('#xStore');edit.fill('фамилия')
        self.assertEqual(edit.input_value(),'фамилия');self.assertEqual(self.page.evaluate('JSON.stringify(state.entries)'),before)
        edit.press('ArrowDown');edit.press('Enter')
        self.assertEqual(edit.input_value(),'Familia')
        self.assertEqual(self.page.evaluate('JSON.stringify(state.entries)'),before)
        self.page.evaluate('saveEdit()')
        self.assertEqual(self.page.evaluate('state.entries[0].store'),'Familia')
        self.assertEqual(self.page.evaluate('state.entries[0].category'),'Продукты')
        self.assertLessEqual(self.page.evaluate("v96MerchantSuggestions('а').length"),8)


if __name__=='__main__':
    unittest.main()
