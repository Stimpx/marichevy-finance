"""Family Capital presentation preserves financial data and personal artwork."""
import unittest
import sys
from pathlib import Path

import test_local_data_safety as harness
sys.path.insert(0,str(Path(harness.__file__).resolve().parents[1]/'tools'))
from check_touch_flows import enlarge_text


class FamilyCapitalBrand(unittest.TestCase):
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
          session=null;stopCloudSync();localStorage.clear();state=blankState();
          state.entries=[{id:'fictional-brand-history',type:'expense',date:today(),
            amount:0.125,category:'Прочее',who:'Учебный участник',
            store:'Вымышленный магазин',futureEntry:{keep:[null,true,'opaque']}}];
          state.futureRoot={preserve:'unchanged'};
          state.settings.futureSetting={preserve:true};
          state.settings.preferences.branding={futureBranding:{keep:17}};
          weatherCache.data={temperature_2m:10,weather_code:0};weatherCache.at=Date.now();
          localStorage.setItem('fictional-brand-sentinel','preserve');
        }""")

    def test_public_name_is_consistent_before_and_after_unlock(self):
        self.prepare()
        self.assertEqual(self.page.title(), 'Семейный капитал')
        for name in ('application-name','apple-mobile-web-app-title'):
            self.assertEqual(self.page.locator('meta[name="'+name+'"]').get_attribute('content'),
                             'Семейный капитал')
        for selector in ('.auth-gate-brand', '.login-brand', '.brand-heading', '.page-eyebrow'):
            with self.subTest(selector=selector):
                text=self.page.locator(selector).text_content().casefold()
                self.assertIn('семейный капитал',text)
                self.assertNotIn('траты.банк',text)
                self.assertNotIn('маричевы',text)
        self.page.evaluate("showApp();go('home')")
        self.assertEqual(self.page.title(),'Главная · Семейный капитал')
        self.assertEqual(self.page.locator('.brand-emblem').inner_text(),'С')
        before=self.snapshot()
        enlarge_text(self.page,2)
        words=self.page.locator('.brand-heading').evaluate("""el=>{
          const text=[...el.childNodes].find(node=>node.nodeType===Node.TEXT_NODE);
          let offset=0;return text.textContent.split(' ').map(word=>{
            const range=document.createRange();range.setStart(text,offset);range.setEnd(text,offset+word.length);
            offset+=word.length+1;return {word,lines:[...range.getClientRects()].filter(r=>r.width>.5).length};
          }).filter(item=>item.word);
        }""")
        self.assertEqual([word['lines'] for word in words],[1,1],words)
        self.assertEqual(self.snapshot(),before)

    def test_route_titles_have_no_release_suffix_and_navigation_never_rewrites_state(self):
        self.prepare()
        self.page.evaluate("showApp();go('home')")
        before=self.snapshot()
        for route,title in (('analytics','Анализ расходов'),('accounts','Счета и сверка'),
                            ('planning','План месяца'),('settings','Настройки и данные')):
            with self.subTest(route=route):
                self.page.evaluate('(route)=>go(route)',route)
                self.assertEqual(self.page.title(),title+' · Семейный капитал')
                self.assertNotIn('rc2',self.page.title())
                self.assertEqual(self.snapshot(),before)

    def test_custom_logo_and_favicon_remain_authoritative_after_render_and_navigation(self):
        self.prepare()
        expected=self.page.evaluate("""() => {
          const canvas=document.createElement('canvas');canvas.width=32;canvas.height=32;
          const ctx=canvas.getContext('2d');ctx.fillStyle='#5274ad';ctx.fillRect(0,0,32,32);
          const image=canvas.toDataURL('image/png');
          state.settings.preferences.branding={...state.settings.preferences.branding,
            logoDataUrl:image,faviconDataUrl:image};
          showApp();go('settings');v96ApplyBranding();return image;
        }""")
        before=self.snapshot()
        for route in ('home','analytics','accounts','planning','settings'):
            with self.subTest(route=route):
                self.page.evaluate('(route)=>{go(route);renderAll();v96ApplyBranding()}',route)
                self.assertEqual(self.page.locator('.brand-emblem img').get_attribute('src'),expected)
                icons=self.page.locator('link[rel~="icon"]').evaluate_all(
                    '(nodes)=>nodes.map(node=>node.getAttribute("href"))')
                self.assertTrue(icons)
                self.assertEqual(icons,[expected]*len(icons))
                self.assertEqual(self.snapshot(),before)


if __name__=='__main__':
    unittest.main()
