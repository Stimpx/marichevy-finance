"""Family artwork settings: fictional images only, all external traffic blocked."""
import base64
import json
import struct
from pathlib import Path
import tempfile
import unittest

import test_local_data_safety as harness


class BrandingSettings(unittest.TestCase):
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
        self.open()
        self.page.evaluate("""() => {
          session=null;state=blankState();localStorage.clear();
          state.entries=[{id:'fictional-original',type:'expense',date:today(),amount:17.42,
            category:'Продукты',who:'Общее',comment:'Fictional original',future:{keep:true}}];
          state.settings.preferences.futurePreference={keep:'yes'};
          state.settings.preferences.branding={futureBranding:{keep:true}};
          weatherCache.data={temperature_2m:10,weather_code:0};weatherCache.at=Date.now();
          showApp();go('settings');
        }""")

    def image(self, width=500, height=260, mime='image/png'):
        data=self.page.evaluate("""({width,height,mime}) => {
          const canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;
          const ctx=canvas.getContext('2d');ctx.fillStyle='#3456ab';ctx.fillRect(0,0,width,height);
          ctx.fillStyle='#fff';ctx.fillRect(0,0,width/2,height/2);
          return canvas.toDataURL(mime).split(',')[1];
        }""",dict(width=width,height=height,mime=mime))
        return base64.b64decode(data)

    def upload(self, kind='logo', *, buffer=None, name='fictional.png', mime='image/png'):
        buffer=self.image() if buffer is None else buffer
        self.page.locator('#v96'+('Logo' if kind=='logo' else 'Favicon')+'File').set_input_files(
            {'name':name,'mimeType':mime,'buffer':buffer})
        self.page.wait_for_function("document.getElementById('v96BrandingStatus').textContent === 'Картинка подготовлена. Нажмите «Сохранить», чтобы применить.'")
        return buffer

    def stored(self):
        return self.page.evaluate("""() => ({entries:JSON.stringify(state.entries),
          prefs:JSON.stringify(state.settings.preferences),primary:localStorage.getItem(KEYS.state),
          pending:localStorage.getItem(KEYS.pending)})""")

    def test_upload_is_staged_then_saved_as_bounded_png_without_changing_history(self):
        self.prepare();before=self.stored();original=self.image()+b'PRIVATE_UNTRUSTED_TRAILING_METADATA'
        self.upload(buffer=original)
        self.assertEqual(self.stored(),before)
        self.assertEqual(self.page.locator('.brand-emblem img').count(),0)
        self.assertTrue(self.page.locator('#v96LogoPreview').is_visible())
        self.page.locator('#v96LogoSave').click()
        self.page.wait_for_function("!!state.settings.preferences.branding.logoDataUrl")
        result=self.page.evaluate("""() => ({data:state.settings.preferences.branding.logoDataUrl,
          future:state.settings.preferences.futurePreference,unknown:state.settings.preferences.branding.futureBranding,
          width:document.getElementById('v96LogoPreview').naturalWidth,
          height:document.getElementById('v96LogoPreview').naturalHeight,
          applied:document.querySelector('.brand-emblem img')?.getAttribute('src'),
          disk:JSON.parse(localStorage.getItem(KEYS.pending)).settings.preferences.branding.logoDataUrl,
          status:document.getElementById('v96BrandingStatus').textContent})""")
        self.assertEqual(self.stored()['entries'],before['entries'])
        self.assertTrue(result['data'].startswith('data:image/png;base64,'))
        self.assertLessEqual(len(result['data']),128*1024)
        self.assertLessEqual(result['width'],192);self.assertLessEqual(result['height'],192)
        self.assertNotIn(b'PRIVATE_UNTRUSTED_TRAILING_METADATA',base64.b64decode(result['data'].split(',')[1]))
        self.assertEqual(result['applied'],result['data']);self.assertEqual(result['disk'],result['data'])
        self.assertEqual(result['future'],{'keep':'yes'});self.assertEqual(result['unknown'],{'keep':True})
        self.assertIn('устройстве',result['status'])

    def test_unsafe_spoofed_or_oversized_files_are_rejected_before_decode_or_state_write(self):
        self.prepare();before=self.stored()
        png=bytearray(self.image(20,20));png[16:20]=(99999).to_bytes(4,'big')
        files=[(b'<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.invalid/leak"/></svg>','image/png'),
               (b'<html><script>alert(1)</script></html>','image/png'),
               (bytes(png),'image/png'),(b'x'*(1024*1024+1),'image/png')]
        calls=[];self.page.on('request',lambda request:calls.append(request.url))
        for data,mime in files:
            with self.subTest(kind=data[:8]):
                result=self.page.evaluate("""async ({data,mime}) => {
                  const file=new File([Uint8Array.from(data)],'spoof.png',{type:mime});
                  return await v96StageBranding('logo',file);
                }""",{'data':list(data),'mime':mime})
                self.assertFalse(result);self.assertEqual(self.stored(),before)
        self.assertEqual(self.page.locator('#v96LogoPreview').get_attribute('src'),None)
        self.assertFalse(any(url.startswith('https://') for url in calls))

    def test_supported_raster_formats_use_magic_and_are_reencoded_before_storage(self):
        self.prepare();before=self.stored()
        png=self.image(32,32)
        ico=struct.pack('<HHHBBBBHHII',0,1,1,32,32,0,0,1,32,len(png),22)+png
        samples=[self.image(90,45,'image/jpeg'),self.image(90,45,'image/webp'),ico]
        for data in samples:
            result=self.page.evaluate("""async data => {
              const ok=await v96StageBranding('logo',new File([Uint8Array.from(data)],'spoof.svg',{type:'text/html'}));
              return {ok,preview:document.getElementById('v96LogoPreview').getAttribute('src')};
            }""",list(data))
            self.assertTrue(result['ok']);self.assertTrue(result['preview'].startswith('data:image/png;base64,'))
            self.assertEqual(self.stored(),before)

    def test_favicon_and_full_device_backup_include_sanitized_family_settings(self):
        self.prepare();self.upload('favicon',buffer=self.image(120,60,'image/jpeg'),name='fictional.jpg',mime='image/jpeg')
        self.page.locator('#v96FaviconSave').click()
        self.page.wait_for_function("!!state.settings.preferences.branding.faviconDataUrl")
        data=self.page.evaluate('state.settings.preferences.branding.faviconDataUrl')
        self.assertLessEqual(len(data),32*1024)
        self.assertEqual(self.page.locator('#v96FaviconPreview').evaluate('(node)=>[node.naturalWidth,node.naturalHeight]'),[64,64])
        icons=self.page.locator('link[rel~="icon"]').evaluate_all('(nodes)=>nodes.map(n=>n.getAttribute("href"))')
        self.assertTrue(icons);self.assertTrue(all(value==data for value in icons))
        with self.page.expect_download() as download:
            self.page.get_by_role('button',name='↓ Полная копия устройства',exact=True).click()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'capture.json';download.value.save_as(path);capture=json.loads(path.read_text())
        self.assertEqual(json.loads(capture['memory_state_json'])['settings']['preferences']['branding']['faviconDataUrl'],data)
        pending=next(row['raw'] for row in capture['records'] if row['key']=='marichevy_pending_v10')
        self.assertEqual(json.loads(pending)['settings']['preferences']['branding']['faviconDataUrl'],data)

    def test_reset_and_gate_restore_defaults_and_clear_staged_private_artwork(self):
        self.prepare();defaults=self.page.locator('link[rel~="icon"]').evaluate_all('(nodes)=>nodes.map(n=>[n.getAttribute("href"),n.getAttribute("type")])')
        self.upload();self.page.locator('#v96LogoSave').click()
        self.page.wait_for_function("!!state.settings.preferences.branding.logoDataUrl")
        self.upload('favicon',buffer=self.image(32,32))
        self.page.locator('#v96FaviconSave').click()
        self.page.wait_for_function("!!state.settings.preferences.branding.faviconDataUrl")
        self.upload('favicon',buffer=self.image(24,24))
        self.page.evaluate('showGate()')
        self.assertEqual(self.page.locator('.brand-emblem img').count(),0)
        self.assertEqual(self.page.locator('#v96FaviconPreview').get_attribute('src'),None)
        self.assertEqual(self.page.evaluate('Object.keys(v96BrandingDraft)'),[])
        self.assertEqual(self.page.locator('link[rel~="icon"]').evaluate_all('(nodes)=>nodes.map(n=>[n.getAttribute("href"),n.getAttribute("type")])'),defaults)
        self.page.evaluate("showApp();go('settings')")
        self.assertEqual(self.page.locator('.brand-emblem img').count(),1)
        before=self.page.evaluate('JSON.stringify(state.entries)')
        self.page.get_by_role('button',name='Вернуть стандартное оформление',exact=True).click()
        self.page.wait_for_function("!state.settings.preferences.branding.logoDataUrl")
        self.assertEqual(self.page.locator('.brand-emblem img').count(),0)
        self.assertEqual(self.page.evaluate('state.settings.preferences.branding.futureBranding'),{'keep':True})
        self.assertEqual(self.page.evaluate('state.settings.preferences.futurePreference'),{'keep':'yes'})
        self.assertEqual(self.page.evaluate('JSON.stringify(state.entries)'),before)

    def test_late_decode_after_gate_cannot_repopulate_stage(self):
        self.prepare();result=self.page.evaluate("""async () => {
          let finish;const native=v96RasterBranding;
          const safe=document.createElement('canvas').toDataURL('image/png');
          v96RasterBranding=()=>new Promise(resolve=>finish=resolve);
          const waiting=v96StageBranding('logo',new File(['x'],'fake.png'));
          showGate();finish(safe);const result=await waiting;v96RasterBranding=native;
          return {result,keys:Object.keys(v96BrandingDraft),preview:document.getElementById('v96LogoPreview').getAttribute('src')};
        }""")
        self.assertEqual(result,{'result':False,'keys':[],'preview':None})

    def test_cached_private_artwork_is_not_shown_on_initial_login_gate(self):
        self.open()
        defaults=self.page.locator('link[rel~="icon"]').evaluate_all('(nodes)=>nodes.map(n=>[n.getAttribute("href"),n.getAttribute("type")])')
        private='data:image/png;base64,'+base64.b64encode(self.image(32,32)).decode()
        cached=harness.fixture();cached['settings']={'preferences':{'branding':{
            'logoDataUrl':private,'faviconDataUrl':private}}}
        self.open({harness.PRIMARY:json.dumps(cached)})
        self.assertEqual(self.page.evaluate('state.settings.preferences.branding.logoDataUrl'),private)
        self.assertTrue(self.page.locator('#appRoot').evaluate("node=>node.classList.contains('auth-locked')"))
        self.assertEqual(self.page.locator('.brand-emblem img').count(),0)
        self.assertEqual(self.page.locator('#v96LogoPreview').get_attribute('src'),None)
        self.assertEqual(self.page.locator('link[rel~="icon"]').evaluate_all('(nodes)=>nodes.map(n=>[n.getAttribute("href"),n.getAttribute("type")])'),defaults)
        self.page.evaluate('showApp()')
        self.assertEqual(self.page.locator('.brand-emblem img').get_attribute('src'),private)

    def test_quota_failure_reports_not_saved_and_preserves_last_durable_primary(self):
        self.prepare();self.page.evaluate('saveAll()');self.upload()
        before=self.page.evaluate('localStorage.getItem(KEYS.state)')
        self.page.evaluate("""() => {
          const write=Storage.prototype.setItem;
          Storage.prototype.setItem=function(key,value){if(key===KEYS.state||key===KEYS.pending)throw new DOMException('fictional quota','QuotaExceededError');return write.call(this,key,value)};
        }""")
        self.page.locator('#v96LogoSave').click()
        self.page.wait_for_function("document.getElementById('v96BrandingStatus').textContent.includes('Не удалось')")
        self.assertEqual(self.page.evaluate('localStorage.getItem(KEYS.state)'),before)
        self.assertTrue(self.page.evaluate('v89StorageFailed'))
        self.assertEqual(self.page.evaluate('state.entries.length'),1)

    def test_settings_controls_fit_phone_viewport(self):
        self.prepare();self.page.set_viewport_size({'width':320,'height':844})
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
        for selector in ['#v96LogoFile','#v96FaviconFile','#v96BrandingSave']:
            box=self.page.locator(selector).bounding_box()
            self.assertIsNotNone(box);self.assertGreater(box['width'],0)
            self.assertGreaterEqual(box['x'],0);self.assertLessEqual(box['x']+box['width'],321)

if __name__=='__main__':unittest.main()
