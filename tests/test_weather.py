"""Weather always settles, validates provider observations and recovers offline.

All requests are synthetic and external network access is blocked. No fabricated
weather is used as an application fallback; fixtures only exercise the parser.
"""
from pathlib import Path
import os
import shutil
import unittest
from playwright.sync_api import sync_playwright

HTML = (Path(__file__).resolve().parents[1] / 'index.html').read_text()
BASE = 'http://127.0.0.1:9871/'


class Weather(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = sync_playwright().start()
        executable = os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium') or shutil.which('chromium-browser')
        cls.browser = cls.p.chromium.launch(headless=True, **({'executable_path': executable} if executable else {}))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.p.stop()

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 1280, 'height': 1100}, timezone_id='Europe/Moscow', service_workers='block')
        self.context.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body=HTML) if route.request.url == BASE else route.abort())
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.goto(BASE, wait_until='domcontentloaded')
        self.page.wait_for_function("typeof v115DecodeWeather==='function'")
        self.page.evaluate('''async () => {
          session=null;localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=null;
          localStorage.clear();state=blankState();showApp();go('home');
          if(weatherRequest)await weatherRequest;
          weatherRequest=null;weatherCache={at:0,data:null};weatherLastFailure=0;
          weatherLoading=false;weatherLastRecoveryAttempt=0;
          const originalTimeout=window.setTimeout.bind(window);
          window.setTimeout=(fn,ms,...args)=>originalTimeout(fn,ms===WEATHER_TIMEOUT_MS?20:ms,...args);
          window.weatherCalls=[];
          window.primaryWeather=(temp=6,at=Date.now())=>({current:{
            time:Math.floor(at/1000),temperature_2m:temp,apparent_temperature:3,
            weather_code:3,wind_speed_10m:4}});
          window.wttrWeather=(temp='7',at=Date.now())=>{
            const date=new Date(at+3*3600000),hour=date.getUTCHours(),pad=n=>String(n).padStart(2,'0');
            return {current_condition:[{temp_C:temp,FeelsLikeC:'4',weatherCode:'116',
              windspeedKmph:'18',lang_ru:[{value:'Переменная облачность'}],
              localObsDateTime:date.toISOString().slice(0,10)+' '+pad(hour%12||12)+':'+pad(date.getUTCMinutes())+' '+(hour<12?'AM':'PM')}]};
          };
          window.weatherResponse=payload=>({ok:true,json:async()=>payload});
          v115RenderWeather();
        }''')

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def evaluate(self, code):
        return self.page.evaluate('async () => {' + code + '}')

    def test_primary_success_shared_request_and_fresh_cache_display_real_observation(self):
        result = self.evaluate('''
          fetch=async url=>{weatherCalls.push(url);return weatherResponse(primaryWeather(6))};
          await Promise.all([loadWeather(true),loadWeather(true),loadWeather(true)]);
          await loadWeather();
          return {calls:weatherCalls.length,temp:document.getElementById('weatherTemp').textContent,
            text:document.getElementById('weatherText').textContent,
            meta:document.getElementById('weatherMeta').textContent,
            observed:weatherCache.observedAt,loading:weatherLoading,
            disabled:document.getElementById('weatherRefresh').disabled};
        ''')
        self.assertEqual(result['calls'], 1)
        self.assertEqual(result['temp'], '6°')
        self.assertIn('Москва', result['text'])
        self.assertIn('Пасмурно', result['text'])
        self.assertIn('Open-Meteo', result['meta'])
        self.assertGreater(result['observed'], 0)
        self.assertFalse(result['loading'])
        self.assertFalse(result['disabled'])

    def test_independent_wttr_fallback_parses_strings_units_and_russian_conditions(self):
        result = self.evaluate('''
          fetch=async url=>{weatherCalls.push(url);if(url.includes('open-meteo'))throw Error('Primary unavailable');return weatherResponse(wttrWeather())};
          const data=await loadWeather(true);
          return {calls:weatherCalls,temp:data.temperature_2m,wind:data.wind_speed_10m,
            source:weatherCache.source,text:document.getElementById('weatherText').textContent,
            meta:document.getElementById('weatherMeta').textContent};
        ''')
        self.assertEqual(len(result['calls']), 2)
        self.assertIn('api.open-meteo.com', result['calls'][0])
        self.assertIn('wttr.in/55.7558,37.6173', result['calls'][1])
        self.assertEqual(result['temp'], 7)
        self.assertEqual(result['wind'], 5)
        self.assertEqual(result['source'], 'wttr.in')
        self.assertIn('Переменная облачность', result['text'])
        self.assertIn('wttr.in', result['meta'])

    def test_unresponsive_fetch_ignoring_abort_never_locks_refresh_forever(self):
        result = self.evaluate('''
          fetch=url=>{weatherCalls.push(url);return new Promise(()=>{})};
          const data=await loadWeather(true);
          return {data,calls:weatherCalls.length,loading:weatherLoading,
            request:weatherRequest,disabled:document.getElementById('weatherRefresh').disabled,
            text:document.getElementById('weatherText').textContent,
            busy:document.getElementById('weatherCard').getAttribute('aria-busy')};
        ''')
        self.assertIsNone(result['data'])
        self.assertEqual(result['calls'], 2)
        self.assertFalse(result['loading'])
        self.assertIsNone(result['request'])
        self.assertFalse(result['disabled'])
        self.assertIn('временно недоступна', result['text'])
        self.assertEqual(result['busy'], 'false')

    def test_hanging_response_body_times_out_and_late_result_cannot_replace_fallback(self):
        result = self.evaluate('''
          fetch=async url=>{weatherCalls.push(url);return url.includes('open-meteo')?
            {ok:true,json:()=>new Promise(resolve=>window.finishLateWeather=resolve)}:
            weatherResponse(wttrWeather('8'))};
          await loadWeather(true);const before=JSON.stringify(weatherCache);
          finishLateWeather(primaryWeather(50));await Promise.resolve();await Promise.resolve();
          return {same:before===JSON.stringify(weatherCache),temp:weatherCache.data.temperature_2m,
            source:weatherCache.source,loading:weatherLoading};
        ''')
        self.assertTrue(result['same'])
        self.assertEqual(result['temp'], 8)
        self.assertEqual(result['source'], 'wttr.in')
        self.assertFalse(result['loading'])

    def test_failed_refresh_keeps_labeled_saved_weather_and_online_recovers(self):
        self.evaluate('''
          weatherCache={at:Date.now()-6*3600000,observedAt:Date.now()-6*3600000,
            data:primaryWeather(-2).current,source:'Open-Meteo'};
          fetch=async()=>{weatherCalls.push('failed');throw Error('Offline')};
          await loadWeather(true);
        ''')
        self.assertEqual(self.page.locator('#weatherTemp').inner_text(), '-2°')
        self.assertIn('Сохранённые данные', self.page.locator('#weatherMeta').inner_text())
        self.evaluate('''
          fetch=async url=>{weatherCalls.push(url);return weatherResponse(primaryWeather(9))};
          dispatchEvent(new Event('online'));
        ''')
        self.page.wait_for_function("document.getElementById('weatherTemp').textContent==='9°'")
        self.assertNotIn('Сохранённые данные', self.page.locator('#weatherMeta').inner_text())
        self.assertFalse(self.evaluate('return weatherLoading||document.getElementById("weatherRefresh").disabled;'))

    def test_expired_or_invalid_provider_data_does_not_become_fake_zero(self):
        result = self.evaluate('''
          const stale=primaryWeather(20,Date.now()-4*3600000),empty=wttrWeather('');
          fetch=async url=>weatherResponse(url.includes('open-meteo')?stale:empty);
          const data=await loadWeather(true);
          return {data,temp:document.getElementById('weatherTemp').textContent,
            cached:weatherCache.data,disabled:document.getElementById('weatherRefresh').disabled};
        ''')
        self.assertIsNone(result['data'])
        self.assertEqual(result['temp'], '—')
        self.assertIsNone(result['cached'])
        self.assertFalse(result['disabled'])

    def test_parser_accepts_actual_zero_but_rejects_missing_future_and_old_observations(self):
        result = self.evaluate('''
          const attempts=[wttrWeather(null),wttrWeather('7',Date.now()-4*3600000),
            wttrWeather('7',Date.now()+25*60000),wttrWeather('7')];
          delete attempts[3].current_condition[0].localObsDateTime;
          const rejected=attempts.map(payload=>{try{v115DecodeWeather({format:'wttr'},payload);return false}catch{return true}});
          const iso=primaryWeather(5);iso.current.time=new Date(Date.now()+3*3600000).toISOString().slice(0,19);
          return {zero:v115DecodeWeather({format:'wttr'},wttrWeather('0')).data.temperature_2m,
            rejected,primary:v115DecodeWeather({},iso).data.temperature_2m};
        ''')
        self.assertEqual(result['zero'], 0)
        self.assertEqual(result['rejected'], [True] * 4)
        self.assertEqual(result['primary'], 5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
