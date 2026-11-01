"""Weather lifecycle regressions; fictional responses and blocked external requests."""
import json
import time
import unittest

import test_local_data_safety as harness


WEATHER_KEY = 'marichevy_weather_last_good_v74'
WEATHER_INIT = r"""(() => {
  const nativeFetch=window.fetch.bind(window),nativeNow=Date.now.bind(Date);
  const nativeTimeout=window.setTimeout.bind(window),nativeInterval=window.setInterval.bind(window),
    nativeClearInterval=window.clearInterval.bind(window);
  const q=window.__weatherQA={calls:[],pending:[],queue:[],mode:'success',now:null,
    fastTimeout:false,intervals:[],payload:{current:{temperature_2m:12.4,
      apparent_temperature:10.1,weather_code:2,wind_speed_10m:3.1}}};
  Date.now=()=>q.now===null?nativeNow():q.now;
  q.advance=ms=>{q.now=Date.now()+ms};
  q.reset=()=>{q.calls=[];q.pending=[];q.queue=[];q.mode='hold';q.fastTimeout=false};
  window.setTimeout=(fn,delay,...args)=>nativeTimeout(fn,q.fastTimeout&&delay===10000?5:delay,...args);
  window.setInterval=(fn,delay,...args)=>{
    const id=nativeInterval(fn,delay,...args);q.intervals.push({fn,delay,id,active:true});return id;
  };
  window.clearInterval=id=>{q.intervals.forEach(x=>{if(x.id===id)x.active=false});nativeClearInterval(id)};
  q.fireWeatherIntervals=()=>{
    const timers=q.intervals.filter(x=>x.active&&/weather/i.test(String(x.fn)));
    timers.forEach(x=>x.fn());return timers.length;
  };
  window.fetch=(input,options={})=>{
    const url=String(input?.url||input);
    if(!url.startsWith('https://api.open-meteo.com/'))return nativeFetch(input,options);
    return new Promise((resolve,reject)=>{
      const call={url,settled:false,aborted:false,credentials:options.credentials,
        hasAuthorization:new Headers(options.headers).has('authorization')};q.calls.push(call);
      const finish=(kind='success',payload=q.payload)=>{
        if(call.settled)return;call.settled=true;
        if(kind==='network'){reject(new TypeError('Fictional weather network failure'));return}
        if(kind==='http'){resolve(new Response('fictional unavailable',{status:503}));return}
        if(kind==='badjson'){resolve(new Response('{fictional broken JSON',{status:200}));return}
        resolve(new Response(JSON.stringify(payload),{status:200,headers:{'Content-Type':'application/json'}}));
      };
      call.finish=finish;q.pending.push(call);
      options.signal?.addEventListener('abort',()=>{
        if(call.settled)return;call.settled=true;call.aborted=true;
        reject(new DOMException('Fictional weather timeout','AbortError'));
      },{once:true});
      const outcome=q.queue.length?q.queue.shift():q.mode;
      if(outcome!=='hold')queueMicrotask(()=>finish(outcome));
    });
  };
  q.finish=(kind='success',payload=q.payload)=>{
    const call=q.pending.find(x=>!x.settled);if(!call)throw new Error('No held fictional weather request');
    call.finish(kind,payload);
  };
})();"""


class WeatherLoading(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.LocalDataSafety.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        harness.LocalDataSafety.tearDownClass.__func__(cls)

    def setUp(self):
        harness.LocalDataSafety.setUp(self)
        self.context.add_init_script(WEATHER_INIT)

    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open

    def prepare(self):
        self.open()
        self.page.wait_for_function('weatherRequest===null')
        self.page.evaluate("""async () => {
          session=null;stopCloudSync();localStorage.clear();state=blankState();
          state.entries=[{id:'fictional-weather-finance',date:today(),type:'expense',
            amount:17.251,category:'Прочее',who:'Вымышленный участник',
            futureField:{preserve:[true,null,'weather-read-only']}}];
          state.futureField={preserve:'fictional'};
          weatherCache={at:Date.now(),data:__weatherQA.payload.current,source:'Open-Meteo'};
          weatherLastFailure=0;showApp();renderAll();go('home');
          if(weatherRequest)await weatherRequest;
          __weatherQA.reset();weatherCache={at:0,data:null,source:null};weatherLastFailure=0;
          renderTodayHeader();
        }""")
        self.before = self.financial_snapshot()

    def financial_snapshot(self):
        return self.page.evaluate("""() => ({state:JSON.stringify(state),
          storage:Object.fromEntries(Object.keys(localStorage).sort()
            .filter(key=>key!==WEATHER_STORAGE_KEY).map(key=>[key,localStorage.getItem(key)]))})""")

    def assert_finance_unchanged(self):
        self.assertEqual(self.financial_snapshot(), self.before)
        self.assertIsNone(self.page.evaluate('session'))

    def ui(self):
        return self.page.evaluate("""() => ({
          temp:document.getElementById('weatherTemp').textContent,
          text:document.getElementById('weatherText').textContent,
          meta:document.getElementById('weatherMeta').textContent,
          loading:document.getElementById('weatherCard').classList.contains('weather-loading'),
          disabled:document.getElementById('weatherRefresh').disabled,
          calls:__weatherQA.calls.length,pending:!!weatherRequest})""")

    def start(self, force=True):
        self.page.evaluate('(force)=>{window.__weatherPending=loadWeather(force)}', force)

    def finish(self):
        self.page.evaluate('__weatherQA.finish()')
        self.page.evaluate('window.__weatherPending')

    def test_fresh_persisted_cache_paints_immediately_and_survives_reload_without_fetch(self):
        at = int(time.time() * 1000) - 5 * 60000
        self.open({WEATHER_KEY: json.dumps({'at': at, 'data': {
            'temperature_2m': 14.2, 'weather_code': 3,
            'apparent_temperature': 13, 'wind_speed_10m': 2}, 'source': 'Open-Meteo'})})
        self.page.evaluate("session=null;stopCloudSync();showApp();go('home')")
        self.assertEqual(self.ui()['temp'], '14°')
        self.assertEqual(self.ui()['calls'], 0)
        self.page.reload(wait_until='domcontentloaded')
        self.page.wait_for_function("typeof state==='object'&&typeof loadWeather==='function'")
        self.page.evaluate("session=null;stopCloudSync();showApp();go('home');renderTodayHeader()")
        self.assertEqual(self.ui()['temp'], '14°')
        self.assertEqual(self.ui()['calls'], 0)
        self.assertFalse(self.ui()['loading'])

    def test_pending_request_keeps_loading_and_deduplicates_render_and_manual_retry(self):
        self.prepare()
        self.start()
        self.assertEqual(self.ui()['calls'], 1)
        self.page.evaluate("() => {renderAll();renderTodayHeader();loadWeather();loadWeather(true)}")
        pending = self.ui()
        self.assertEqual(pending['calls'], 1)
        self.assertTrue(pending['pending'])
        self.assertTrue(pending['loading'])
        self.assertTrue(pending['disabled'])
        self.assertRegex(pending['text'] + pending['meta'], r'(?i)загру|получ|подключ|обнов')
        self.finish()
        settled = self.ui()
        self.assertEqual(settled['temp'], '12°')
        self.assertFalse(settled['loading'])
        self.assertFalse(settled['disabled'])
        self.assertFalse(settled['pending'])
        self.assert_finance_unchanged()

    def test_empty_failure_remains_unavailable_across_renders_and_cooldown(self):
        self.prepare()
        self.page.evaluate("__weatherQA.mode='network'")
        self.page.evaluate('loadWeather(true)')
        failed = self.ui()
        self.assertEqual(failed['temp'], '—')
        self.assertRegex(failed['text'] + failed['meta'], r'(?i)недоступ|не удалось|нет соедин')
        self.page.evaluate("renderAll();renderTodayHeader();loadWeather()")
        after = self.ui()
        self.assertEqual(after['calls'], failed['calls'])
        self.assertEqual(after['temp'], '—')
        self.assertRegex(after['text'] + after['meta'], r'(?i)недоступ|не удалось|нет соедин')
        self.assertFalse(after['loading'])
        self.assertFalse(after['disabled'])
        self.page.evaluate("__weatherQA.advance(3*60000+1000);__weatherQA.mode='success';__weatherQA.fireWeatherIntervals()")
        self.page.wait_for_function("document.getElementById('weatherTemp').textContent==='12°'")
        self.assertEqual(self.ui()['calls'], failed['calls'] + 1)
        self.assert_finance_unchanged()

    def test_failed_refresh_retains_valid_cache_with_explicit_stale_label(self):
        self.prepare()
        self.page.evaluate("""() => {
          weatherCache={at:Date.now()-45*60000,data:__weatherQA.payload.current,source:'Open-Meteo'};
          __weatherQA.mode='network';
        }""")
        self.page.evaluate('loadWeather(true)')
        before = self.ui()
        self.assertEqual(before['temp'], '12°')
        self.assertRegex(before['meta'], r'(?i)сохран|послед|не удалось|не обнов')
        self.assertRegex(before['meta'], r'\d{1,2}:\d{2}')
        self.page.evaluate('renderAll();renderTodayHeader()')
        after = self.ui()
        self.assertEqual(after['temp'], '12°')
        self.assertRegex(after['meta'], r'(?i)сохран|послед|не удалось|не обнов')
        self.assertRegex(after['meta'], r'\d{1,2}:\d{2}')
        self.assertEqual(after['calls'], before['calls'])
        self.assert_finance_unchanged()

    def test_invalid_cache_timestamps_values_and_expired_memory_are_not_displayed(self):
        self.prepare()
        self.page.evaluate("localStorage.setItem(WEATHER_STORAGE_KEY,'{fictional broken JSON')")
        self.assertIsNone(self.page.evaluate('readLastWeather()'))
        results = self.page.evaluate("""() => {
          const now=Date.now(),data=__weatherQA.payload.current;
          return [
            {at:now+86400000,data}, {at:String(now-1000),data}, {at:null,data},
            {at:now-49*3600000,data}, {at:now,data:{temperature_2m:'12'}},
            {at:now,data:{temperature_2m:null}}
          ].map(value=>{
            localStorage.setItem(WEATHER_STORAGE_KEY,JSON.stringify(value));
            const accepted=!!readLastWeather();weatherCache=value;weatherLastFailure=0;
            renderTodayHeader();
            return {accepted,temp:document.getElementById('weatherTemp').textContent,
              text:document.getElementById('weatherText').textContent};
          });
        }""")
        for result in results:
            self.assertFalse(result['accepted'], result)
            self.assertEqual(result['temp'], '—', result)
            self.assertNotIn('NaN', result['text'])
        self.assert_finance_unchanged()

    def test_primary_http_json_or_payload_failure_uses_model_fallback_once(self):
        self.prepare()
        for outcome in ('http', 'badjson', 'invalid'):
            with self.subTest(outcome=outcome):
                self.page.evaluate("""kind => {
                  weatherCache={at:0,data:null,source:null};weatherLastFailure=0;__weatherQA.reset();
                  __weatherQA.queue=kind==='invalid'?['hold','success']:[kind,'success'];
                }""", outcome)
                if outcome == 'invalid':
                    self.start()
                    self.page.evaluate("__weatherQA.finish('success',{current:{temperature_2m:'fictional'}})")
                    self.page.evaluate('window.__weatherPending')
                else:
                    self.page.evaluate('loadWeather(true)')
                self.assertEqual(self.ui()['temp'], '12°')
                urls = self.page.evaluate('__weatherQA.calls.map(call=>call.url)')
                self.assertEqual(len(urls), 2)
                self.assertIn('/v1/forecast?', urls[0])
                self.assertIn('/v1/dwd-icon?', urls[1])
                self.assertTrue(self.page.evaluate("__weatherQA.calls.every(call=>call.credentials==='omit'&&!call.hasAuthorization)"))
                self.assertFalse(self.ui()['loading'])
                self.assert_finance_unchanged()

    def test_timeouts_finish_both_attempts_and_manual_retry_can_recover(self):
        self.prepare()
        self.page.evaluate('__weatherQA.fastTimeout=true')
        self.page.evaluate('loadWeather(true)')
        self.assertEqual(self.ui()['calls'], 2)
        self.assertEqual(self.page.evaluate('__weatherQA.calls.filter(call=>call.aborted).length'), 2)
        self.assertFalse(self.ui()['pending'])
        self.assertFalse(self.ui()['loading'])
        self.assertFalse(self.ui()['disabled'])
        self.page.evaluate("__weatherQA.fastTimeout=false;__weatherQA.mode='success'")
        self.page.locator('#weatherRefresh').click()
        self.page.wait_for_function("document.getElementById('weatherTemp').textContent==='12°'")
        self.assertEqual(self.ui()['calls'], 3)
        self.assert_finance_unchanged()

    def test_synchronous_fetch_exception_does_not_leave_shared_request_stuck(self):
        self.prepare()
        self.page.evaluate("""async () => {
          const controlledFetch=window.fetch;__weatherQA.syncCalls=0;
          window.fetch=(input,options)=>{
            if(String(input?.url||input).startsWith('https://api.open-meteo.com/')){
              __weatherQA.syncCalls++;throw new TypeError('Fictional synchronous weather policy failure');
            }
            return controlledFetch(input,options);
          };
          try{await loadWeather(true)}finally{window.fetch=controlledFetch}
        }""")
        self.assertEqual(self.page.evaluate('__weatherQA.syncCalls'), 2)
        self.assertFalse(self.ui()['pending'])
        self.assertFalse(self.ui()['loading'])
        self.assertFalse(self.ui()['disabled'])
        self.page.evaluate("__weatherQA.mode='success'")
        self.page.evaluate('loadWeather(true)')
        self.assertEqual(self.ui()['calls'], 1)
        self.assertEqual(self.ui()['temp'], '12°')
        self.assert_finance_unchanged()

    def test_online_and_visible_recover_without_waiting_full_cooldown_or_storming(self):
        self.prepare()
        self.page.evaluate("__weatherQA.mode='network'")
        self.page.evaluate('loadWeather(true)')
        before = self.ui()['calls']
        self.page.evaluate("""() => {
          __weatherQA.mode='network';
          Object.defineProperty(navigator,'onLine',{configurable:true,value:true});
          window.dispatchEvent(new Event('online'));
        }""")
        self.page.wait_for_function(f'__weatherQA.calls.length==={before+2}&&weatherRequest===null')
        self.page.evaluate("""window.dispatchEvent(new Event('online'));
          window.dispatchEvent(new Event('focus'));document.dispatchEvent(new Event('visibilitychange'))""")
        self.assertEqual(self.ui()['calls'], before + 2)
        self.page.evaluate("""() => {
          Object.defineProperty(document,'visibilityState',{configurable:true,value:'hidden'});
          document.dispatchEvent(new Event('visibilitychange'));
          __weatherQA.advance(31000);__weatherQA.mode='hold';
          Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'});
          document.dispatchEvent(new Event('visibilitychange'));window.dispatchEvent(new Event('focus'));
        }""")
        self.page.wait_for_function(f'__weatherQA.calls.length==={before+3}')
        self.assertEqual(self.ui()['calls'], before + 3)
        self.assertTrue(self.ui()['loading'])
        self.page.evaluate('__weatherQA.finish()')
        self.page.wait_for_function('weatherRequest===null')
        self.assertEqual(self.ui()['temp'], '12°')
        self.page.evaluate("""window.dispatchEvent(new Event('online'));
          window.dispatchEvent(new Event('focus'));document.dispatchEvent(new Event('visibilitychange'))""")
        self.assertEqual(self.ui()['calls'], before + 3)
        self.assert_finance_unchanged()

    def test_interval_refreshes_expired_data_but_not_hidden_or_unrelated_views(self):
        self.prepare()
        self.page.evaluate("""() => {
          weatherCache={at:Date.now(),data:__weatherQA.payload.current,source:'Open-Meteo'};
          __weatherQA.advance(31*60000);
          Object.defineProperty(document,'visibilityState',{configurable:true,value:'hidden'});
        }""")
        self.assertGreater(self.page.evaluate('__weatherQA.fireWeatherIntervals()'), 0)
        timers = self.page.evaluate("__weatherQA.intervals.filter(x=>x.active&&/weather/i.test(String(x.fn))).map(x=>x.delay)")
        self.assertTrue(all(0 < delay <= 60000 for delay in timers), timers)
        self.assertEqual(self.ui()['calls'], 0)
        self.page.evaluate("""() => {
          Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'});
          go('history');__weatherQA.fireWeatherIntervals();
        }""")
        self.assertEqual(self.ui()['calls'], 0)
        self.page.evaluate("go('home');__weatherQA.fireWeatherIntervals()")
        self.page.wait_for_function('__weatherQA.calls.length===1')
        self.page.evaluate('__weatherQA.fireWeatherIntervals();__weatherQA.fireWeatherIntervals()')
        self.assertEqual(self.ui()['calls'], 1)
        self.page.evaluate('__weatherQA.finish()')
        self.page.wait_for_function('weatherRequest===null')
        self.assertEqual(self.ui()['temp'], '12°')
        self.assert_finance_unchanged()

    def test_browser_offline_keeps_snapshot_without_fetch_then_online_recovers(self):
        self.prepare()
        self.page.evaluate("""() => {
          weatherCache={at:Date.now()-45*60000,data:__weatherQA.payload.current,source:'Open-Meteo'};
          Object.defineProperty(navigator,'onLine',{configurable:true,value:false});
        }""")
        self.page.evaluate('loadWeather(true)')
        self.assertEqual(self.ui()['calls'], 0)
        self.assertEqual(self.ui()['temp'], '12°')
        self.assertRegex(self.ui()['meta'], r'(?i)сохран|послед|не удалось|не обнов')
        self.assertFalse(self.ui()['disabled'])
        self.page.evaluate("window.dispatchEvent(new Event('focus'));document.dispatchEvent(new Event('visibilitychange'))")
        self.assertEqual(self.ui()['calls'], 0)
        self.page.evaluate("""() => {
          Object.defineProperty(navigator,'onLine',{configurable:true,value:true});
          window.dispatchEvent(new Event('online'));
        }""")
        self.page.wait_for_function('__weatherQA.calls.length===1')
        self.page.evaluate('__weatherQA.finish()')
        self.page.wait_for_function('weatherRequest===null')
        self.assertEqual(self.ui()['temp'], '12°')
        self.assertEqual(self.page.evaluate('weatherLastFailure'), 0)
        self.assert_finance_unchanged()

    def test_cache_write_failure_and_optional_invalid_fields_do_not_damage_finance(self):
        self.prepare()
        before_flag = self.page.evaluate('v89StorageFailed')
        self.page.evaluate("""() => {
          const write=Storage.prototype.setItem;
          Storage.prototype.setItem=function(key,value){
            if(key===WEATHER_STORAGE_KEY)throw new DOMException('Fictional cache quota','QuotaExceededError');
            return write.call(this,key,value);
          };
        }""")
        self.start()
        self.page.evaluate("""__weatherQA.finish('success',{current:{temperature_2m:-2.4,
          apparent_temperature:'fictional',wind_speed_10m:null,weather_code:null}})""")
        self.page.evaluate('window.__weatherPending')
        self.assertEqual(self.ui()['temp'], '-2°')
        self.assertNotIn('NaN', self.ui()['text'] + self.ui()['meta'])
        self.assertFalse(self.ui()['pending'])
        self.assertFalse(self.ui()['disabled'])
        self.assertEqual(self.page.evaluate('v89StorageFailed'), before_flag)
        self.assert_finance_unchanged()


if __name__ == '__main__':
    unittest.main()
