"""Weather remains visible in either overview; fictional cached data and blocked network."""
import json
import re
import time
import unittest

from playwright.sync_api import expect

import test_local_data_safety as harness


CACHE_KEY = 'marichevy_weather_last_good_v74'
OVERVIEW_KEY = 'marichevy_v73_short_overview'


class WeatherVisibility(unittest.TestCase):
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

    def prepare(self, preference=None):
        cached = {'at': int(time.time() * 1000), 'source': 'Open-Meteo',
                  'data': {'temperature_2m': -12.4, 'apparent_temperature': -16,
                           'weather_code': 71, 'wind_speed_10m': 9.8}}
        storage = {CACHE_KEY: json.dumps(cached), harness.PRIMARY: json.dumps(harness.fixture())}
        if preference is not None:
            storage[OVERVIEW_KEY] = preference
        self.open(storage)
        self.page.evaluate("""() => {
          session=null;stopCloudSync();
          window.fetch=async()=>({ok:true,json:async()=>({current:{temperature_2m:-12.4,
            apparent_temperature:-16,weather_code:71,wind_speed_10m:9.8}})});
          showApp();go('home');
        }""")
        expect(self.page.locator('#weatherCard')).to_be_visible()

    def stable_snapshot(self):
        result = self.snapshot()
        result['storage'].pop(CACHE_KEY, None)
        result['storage'].pop(OVERVIEW_KEY, None)
        return result

    def show_after_reload(self):
        self.page.reload(wait_until='domcontentloaded')
        self.page.wait_for_function("typeof state==='object'&&typeof exportData==='function'")
        self.page.evaluate("session=null;stopCloudSync();showApp();go('home')")
        expect(self.page.locator('#weatherCard')).to_be_visible()

    def test_default_short_overview_keeps_weather_without_revealing_other_full_blocks(self):
        self.prepare()
        expect(self.page.locator('#home')).to_have_class(re.compile(r'\bv73-focus\b'))
        expect(self.page.locator('.home-top-today .today-greeting')).to_be_hidden()
        expect(self.page.locator('#v86Calendar')).to_be_hidden()
        expect(self.page.locator('#weatherTemp')).to_have_text('-12°')
        expect(self.page.get_by_role('button', name='Обновить погоду', exact=True)).to_be_visible()
        before = self.stable_snapshot()
        self.page.locator('#v73OverviewToggle').click()
        expect(self.page.locator('#home')).not_to_have_class(re.compile(r'\bv73-focus\b'))
        expect(self.page.locator('.home-top-today .today-greeting')).to_be_visible()
        expect(self.page.locator('#v86Calendar')).to_be_visible()
        expect(self.page.locator('#weatherCard')).to_be_visible()
        self.assertEqual(self.stable_snapshot(), before)
        self.page.locator('#v73OverviewToggle').click()
        expect(self.page.locator('.home-top-today .today-greeting')).to_be_hidden()
        expect(self.page.locator('#weatherCard')).to_be_visible()
        self.assertEqual(self.stable_snapshot(), before)

    def test_saved_overview_preference_survives_reload_and_weather_stays_visible(self):
        self.prepare('0')
        expect(self.page.locator('.home-top-today .today-greeting')).to_be_visible()
        entries = self.page.evaluate('JSON.parse(JSON.stringify(state.entries))')
        self.show_after_reload()
        expect(self.page.locator('.home-top-today .today-greeting')).to_be_visible()
        self.assertEqual(self.page.evaluate('state.entries'), entries)
        self.page.locator('#v73OverviewToggle').click()
        self.assertEqual(self.page.evaluate('(key)=>localStorage.getItem(key)', OVERVIEW_KEY), '1')
        self.show_after_reload()
        expect(self.page.locator('.home-top-today .today-greeting')).to_be_hidden()
        expect(self.page.locator('#weatherCard')).to_be_visible()
        self.assertEqual(self.page.evaluate('state.entries'), entries)

    def test_status_text_and_refresh_fit_both_overviews_at_normal_and_enlarged_sizes(self):
        self.prepare()
        before = self.stable_snapshot()
        for width, height in ((320,740),(390,844),(844,390),(1024,768),(1920,1080)):
            for scale in (1,2):
                for short in (True,False):
                    with self.subTest(width=width, height=height, scale=scale, short=short):
                        self.page.set_viewport_size({'width':width,'height':height})
                        self.page.evaluate("""({short,scale})=>{
                          document.querySelectorAll('[data-weather-test-font]').forEach(el=>{
                            el.style.removeProperty('font-size');delete el.dataset.weatherTestFont;
                          });
                          v97SetHomeOverview(short,false);
                          if(scale===2){
                            const nodes=[...document.querySelectorAll('body,body *')]
                              .filter(el=>!['SCRIPT','STYLE','SVG','PATH'].includes(el.tagName));
                            const sizes=nodes.map(el=>parseFloat(getComputedStyle(el).fontSize));
                            nodes.forEach((el,i)=>{if(sizes[i]){
                              el.dataset.weatherTestFont='1';
                              el.style.setProperty('font-size',sizes[i]*2+'px','important');
                            }});
                          }
                          document.getElementById('weatherText').textContent=
                            'Москва · снег · ощущается −16° · ветер 10 м/с';
                          document.getElementById('weatherMeta').textContent=
                            'Сохранённые данные за 1 ноября, 22:30. Сейчас обновить не удалось — попробуем снова.';
                        }""", {'short':short,'scale':scale})
                        expect(self.page.locator('#weatherCard')).to_be_visible()
                        self.page.locator('#weatherRefresh').scroll_into_view_if_needed()
                        self.page.wait_for_function("""()=>{
                          const b=document.getElementById('weatherRefresh'),r=b.getBoundingClientRect();
                          const hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
                          return b.contains(hit);
                        }""")
                        geometry = self.page.evaluate("""()=>{
                          const card=document.getElementById('weatherCard'),box=card.getBoundingClientRect(),
                            main=card.querySelector('.today-weather-main').getBoundingClientRect(),
                            button=document.getElementById('weatherRefresh').getBoundingClientRect(),
                            copy=card.querySelector('.today-weather-copy'),bounds=copy.getBoundingClientRect(),
                            walker=document.createTreeWalker(copy,NodeFilter.SHOW_TEXT),fragments=[];
                          while(walker.nextNode()){
                            const range=document.createRange();range.selectNodeContents(walker.currentNode);
                            for(const r of range.getClientRects())if(r.width&&r.height)
                              fragments.push({left:r.left-bounds.left,right:r.right-bounds.right,
                                top:r.top-box.top,bottom:r.bottom-box.bottom});
                          }
                          return {overflow:card.scrollWidth-card.clientWidth,left:box.left,right:box.right,
                            button:{width:button.width,height:button.height,
                              left:button.left-box.left,right:button.right-box.right,
                              top:button.top-box.top,bottom:button.bottom-box.bottom},
                            overlap:Math.max(0,Math.min(main.right,button.right)-Math.max(main.left,button.left))*
                              Math.max(0,Math.min(main.bottom,button.bottom)-Math.max(main.top,button.top)),
                            columns:getComputedStyle(document.querySelector('.home-top-today')).gridTemplateColumns,
                            fragments};
                        }""")
                        self.assertLessEqual(geometry['overflow'],1,geometry)
                        self.assertGreaterEqual(geometry['left'],0,geometry)
                        self.assertLessEqual(geometry['right'],width,geometry)
                        self.assertGreaterEqual(geometry['button']['width'],44,geometry)
                        self.assertGreaterEqual(geometry['button']['height'],44,geometry)
                        for edge in ('left','top'):
                            self.assertGreaterEqual(geometry['button'][edge],-1,geometry)
                        for edge in ('right','bottom'):
                            self.assertLessEqual(geometry['button'][edge],1,geometry)
                        self.assertLessEqual(geometry['overlap'],1,geometry)
                        self.assertGreaterEqual(len(geometry['fragments']),3,geometry)
                        for fragment in geometry['fragments']:
                            self.assertGreaterEqual(fragment['left'],-1,fragment)
                            self.assertLessEqual(fragment['right'],1,fragment)
                            self.assertGreaterEqual(fragment['top'],-1,fragment)
                            self.assertLessEqual(fragment['bottom'],1,fragment)
                        if short:
                            self.assertEqual(len(geometry['columns'].split()),1)
                        elif width==1920:
                            self.assertEqual(len(geometry['columns'].split()),2)
                        self.assertEqual(self.stable_snapshot(),before)


if __name__=='__main__':
    unittest.main()
