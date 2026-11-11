"""Family icon choices and uploads use shared, scoped settings without touching money.

Run: python -m unittest discover -s tests -p test_family_brand_icon.py
All external requests are blocked. Images are generated synthetic PNG fixtures.
"""
from pathlib import Path
import base64
import os
import shutil
import struct
import unittest
import zlib

from playwright.sync_api import sync_playwright


HTML = (Path(__file__).resolve().parents[1] / 'index.html').read_text()
BASE = 'http://127.0.0.1:9867/'


def png_fixture(width=48, height=24):
    def chunk(kind, data):
        return (struct.pack('!I', len(data)) + kind + data
                + struct.pack('!I', zlib.crc32(kind + data) & 0xffffffff))
    rows = b''.join(b'\0' + bytes([52, 124, 104, 255]) * width for _ in range(height))
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('!IIBBBBB', width, height, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


PNG = png_fixture()
PNG_DATA = 'data:image/png;base64,' + base64.b64encode(PNG).decode()


class FamilyBrandIcon(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = sync_playwright().start()
        executable = (os.environ.get('CHROMIUM_EXECUTABLE')
                      or shutil.which('chromium') or shutil.which('chromium-browser'))
        cls.browser = cls.p.chromium.launch(
            headless=True, **({'executable_path': executable} if executable else {}))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.p.stop()

    def setUp(self):
        self.context = self.browser.new_context(
            viewport={'width': 1440, 'height': 1100},
            timezone_id='Europe/Moscow', service_workers='block')
        self.outbound = []

        def route_request(route):
            if route.request.url == BASE:
                route.fulfill(status=200, content_type='text/html', body=HTML)
            else:
                self.outbound.append(route.request.url)
                route.abort()

        self.context.route('**/*', route_request)
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.on('dialog', lambda dialog: dialog.accept())
        self.page.goto(BASE, wait_until='domcontentloaded')
        self.page.wait_for_function("typeof v160StageLogoPreset==='function'")
        self.page.evaluate("""async () => {
          session=null;localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=null;
          localStorage.clear();state=blankState();
          state.entries=[{id:'icon-test-expense',type:'expense',date:'2026-11-12',
            amount:12.34,category:'Продукты',beneficiary:'Общее',who:'Общее',
            store:'Синтетический магазин',comment:'Не менять',
            created_at:'2026-11-12T12:00:00Z',updated_at:'2026-11-12T12:00:00Z'}];
          window.iconOriginalSaveAll=saveAll;saveAll=async()=>true;
          showApp();go('home');if(weatherRequest)await weatherRequest;
          v96ClearBrandingDraft();v96ApplyBranding();
          window.originalIconEntries=JSON.stringify(state.entries);
          window.originalIconName=document.querySelector('.brand-heading').textContent;
          window.originalIconFavicon=[...document.querySelectorAll('link[rel~=icon]')]
            .map(node=>[node.getAttribute('href'),node.getAttribute('type')]);
          window.readIcon=()=>({preset:state.settings.preferences.branding?.logoPreset??null,
            data:state.settings.preferences.branding?.logoDataUrl??null,
            html:document.querySelector('.brand-emblem').innerHTML,
            unchanged:JSON.stringify(state.entries)===originalIconEntries});
        }""")
        self.page.evaluate('(data)=>window.iconFixtureData=data', PNG_DATA)
        self.outbound.clear()

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def evaluate(self, code):
        return self.page.evaluate('async () => {' + code + '}')

    def open_choices(self):
        self.page.evaluate('v160OpenFamilyIconSettings()')

    def save_preset(self, preset):
        return self.page.evaluate("""async preset => {
          v160StageLogoPreset(preset);const saved=await v96SaveBranding('logo');
          return {saved,...readIcon()};
        }""", preset)

    def test_five_presets_apply_only_after_save_and_keep_finances_and_name(self):
        self.page.locator('#v160FamilyIconButton').click()
        self.assertTrue(self.page.locator('#settings').evaluate("e=>e.classList.contains('active')"))
        self.assertTrue(self.page.locator('#v96BrandingCard').is_visible())
        presets = self.page.locator('[data-v160-logo-preset]').evaluate_all(
            'nodes=>nodes.map(node=>node.dataset.v160LogoPreset)')
        self.assertEqual(presets, ['letter', 'family', 'home', 'tree', 'wallet'])
        renderings = []
        for preset in presets:
            before = self.page.locator('#v160FamilyIconButton').inner_html()
            self.page.locator('[data-v160-logo-preset="' + preset + '"]').click()
            self.assertEqual(self.page.locator('#v160FamilyIconButton').inner_html(), before)
            saved = self.evaluate("const saved=await v96SaveBranding('logo');return {saved,...readIcon()};")
            self.assertTrue(saved['saved'])
            self.assertEqual(saved['preset'], preset)
            self.assertIsNone(saved['data'])
            self.assertTrue(saved['unchanged'])
            renderings.append(saved['html'])
            self.assertEqual(self.page.locator('[data-v160-logo-preset="' + preset + '"]')
                             .get_attribute('aria-pressed'), 'true')
        self.assertEqual(len(set(renderings)), 5)
        self.assertTrue(self.evaluate("""
          renderAll();return JSON.stringify(state.entries)===originalIconEntries
            &&document.querySelector('.brand-heading').textContent===originalIconName
            &&JSON.stringify([...document.querySelectorAll('link[rel~=icon]')]
              .map(node=>[node.getAttribute('href'),node.getAttribute('type')]))
              ===JSON.stringify(originalIconFavicon);
        """))

    def test_shared_choice_survives_real_local_save_normalize_profile_change_and_reload(self):
        self.open_choices()
        result = self.evaluate("""
          saveAll=iconOriginalSaveAll;v160StageLogoPreset('tree');
          const saved=await v96SaveBranding('logo');validateBackup(state);
          const persisted=JSON.parse(localStorage.getItem(KEYS.state));
          state=normalize(JSON.parse(JSON.stringify(state)));
          session={user:{id:'another-member',email:'another-member@example.test',
            user_metadata:{name:'Другой участник'}}};v96ApplyBranding();
          return {saved,stored:persisted.settings.preferences.branding.logoPreset,
            current:readIcon(),storageFailed:v89StorageFailed};
        """)
        self.assertTrue(result['saved'])
        self.assertEqual(result['stored'], 'tree')
        self.assertEqual(result['current']['preset'], 'tree')
        self.assertTrue(result['current']['unchanged'])
        self.assertFalse(result['storageFailed'])
        html = result['current']['html']
        self.page.reload(wait_until='domcontentloaded')
        self.page.wait_for_function("typeof v160StageLogoPreset==='function'")
        result = self.evaluate("""
          session=null;localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=null;
          showApp();v96ApplyBranding();return {
            preset:state.settings.preferences.branding?.logoPreset,
            html:document.querySelector('.brand-emblem').innerHTML,
            count:state.entries.length};
        """)
        self.assertEqual(result, {'preset': 'tree', 'html': html, 'count': 1})

    def test_custom_png_file_is_previewed_resized_saved_replaced_and_reset(self):
        self.open_choices()
        self.save_preset('home')
        before = self.page.locator('#v160FamilyIconButton').inner_html()
        self.page.locator('#v96LogoFile').set_input_files(
            {'name': 'family.png', 'mimeType': 'image/png', 'buffer': png_fixture(320, 160)})
        self.page.wait_for_function("!document.getElementById('v96LogoPreview').hidden&&document.getElementById('v96LogoPreview').naturalWidth>0")
        self.assertEqual(self.page.locator('#v160FamilyIconButton').inner_html(), before)
        self.assertTrue(self.evaluate("return await v96SaveBranding('logo');"))
        result = self.evaluate("""
          const value=readIcon(),image=document.querySelector('.brand-emblem img');
          return {...value,safe:!!v96BrandingSafeData(value.data,'logo'),
            width:document.getElementById('v96LogoPreview').naturalWidth,
            height:document.getElementById('v96LogoPreview').naturalHeight,
            displayed:image?.getAttribute('src')===value.data,
            favicon:JSON.stringify([...document.querySelectorAll('link[rel~=icon]')]
              .map(node=>[node.getAttribute('href'),node.getAttribute('type')]))
              ===JSON.stringify(originalIconFavicon)};
        """)
        self.assertIsNone(result['preset'])
        self.assertTrue(result['safe'])
        self.assertTrue(result['displayed'])
        self.assertLessEqual(len(result['data']), 96 * 1024)
        self.assertLessEqual(result['width'], 192)
        self.assertLessEqual(result['height'], 192)
        self.assertTrue(result['favicon'])
        self.assertTrue(result['unchanged'])
        replaced = self.save_preset('wallet')
        self.assertEqual(replaced['preset'], 'wallet')
        self.assertIsNone(replaced['data'])
        self.assertNotIn('<img', replaced['html'])
        reset = self.evaluate("const saved=await v96ResetBranding('logo');return {saved,...readIcon()};")
        self.assertTrue(reset['saved'])
        self.assertEqual(reset['preset'], 'letter')
        self.assertIsNone(reset['data'])
        self.assertTrue(reset['unchanged'])
        self.assertEqual(self.outbound, [])

    def test_bad_svg_corrupt_and_oversized_files_keep_existing_icon_and_reject_unsafe_data(self):
        self.open_choices()
        self.save_preset('family')
        result = self.evaluate("""
          const before=JSON.stringify(state.settings.preferences.branding),
            svg=new File(['<svg xmlns="http://www.w3.org/2000/svg" onload="window.badIcon=1"/>'],
              'bad.svg',{type:'image/svg+xml'}),
            corrupt=new File([new Uint8Array([137,80,78,71,13,10,26,10])],
              'corrupt.png',{type:'image/png'}),
            large=new File([new Uint8Array(5*1024*1024+1)],'large.png',{type:'image/png'});
          const rejected=[];for(const file of [svg,corrupt,large])
            rejected.push(await v96StageBranding('logo',file));
          const safeSvg=v96BrandingSafeData('data:image/svg+xml;base64,'+btoa('<svg onload="alert(1)"/>'),'logo');
          return {rejected,unchanged:JSON.stringify(state.settings.preferences.branding)===before,
            safeSvg,bad:window.badIcon||0,icon:readIcon()};
        """)
        self.assertEqual(result['rejected'], [False, False, False])
        self.assertTrue(result['unchanged'])
        self.assertEqual(result['safeSvg'], '')
        self.assertEqual(result['bad'], 0)
        self.assertEqual(result['icon']['preset'], 'family')
        self.assertTrue(result['icon']['unchanged'])
        self.assertEqual(self.outbound, [])

    def test_viewer_and_stale_saved_logo_cannot_be_overwritten(self):
        self.open_choices()
        self.save_preset('home')
        result = self.evaluate("""
          const before=JSON.stringify(state.settings);window.__FINANCE_BRIDGE__={active:true,role:'viewer'};
          const preset=v160StageLogoPreset('tree'),save=await v96SaveBranding('logo'),
            file=await v96StageBranding('logo',new File(['x'],'x.png',{type:'image/png'}));
          v96RenderBrandingChoices();return {preset,save,file,
            unchanged:JSON.stringify(state.settings)===before,
            disabled:[...document.querySelectorAll('[data-v160-logo-preset]')]
              .every(node=>node.disabled)};
        """)
        self.assertEqual(result, {'preset': False, 'save': False, 'file': False,
                                  'unchanged': True, 'disabled': True})
        stale = self.evaluate("""
          window.__FINANCE_BRIDGE__=null;v96RenderBrandingChoices();
          v160StageLogoPreset('tree');
          state.settings.preferences.branding={...state.settings.preferences.branding,
            logoPreset:'family',logoDataUrl:null};
          state.settings.updated_at=new Date(Date.now()+1000).toISOString();v96ApplyBranding();
          const saved=await v96SaveBranding('logo');return {saved,...readIcon()};
        """)
        self.assertFalse(stale['saved'])
        self.assertEqual(stale['preset'], 'family')
        self.assertTrue(stale['unchanged'])

    def test_failed_save_rolls_back_logo_and_preserves_unrelated_settings(self):
        self.open_choices()
        self.save_preset('home')
        result = self.evaluate("""
          v160StageLogoPreset('wallet');saveAll=()=>new Promise(resolve=>window.resolveIconSave=resolve);
          const pending=v96SaveBranding('logo');
          state.settings.preferences.payday=25;state.settings.preferences.branding.faviconDataUrl=iconFixtureData;
          state.settings.preferences.branding.faviconUpdatedAt=new Date().toISOString();
          state.settings.updated_at=new Date(Date.now()+1000).toISOString();
          v89StorageFailed=true;resolveIconSave(false);const saved=await pending;
          return {saved,preset:state.settings.preferences.branding.logoPreset,
            payday:state.settings.preferences.payday,favicon:state.settings.preferences.branding.faviconDataUrl===iconFixtureData,
            unchanged:JSON.stringify(state.entries)===originalIconEntries,
            status:document.getElementById('v96BrandingStatus').textContent};
        """)
        self.assertFalse(result['saved'])
        self.assertEqual(result['preset'], 'home')
        self.assertEqual(result['payday'], 25)
        self.assertTrue(result['favicon'])
        self.assertTrue(result['unchanged'])
        self.assertTrue(result['status'])
        newer = self.evaluate("""
          v89StorageFailed=false;v96ClearBrandingDraft();v160StageLogoPreset('wallet');
          saveAll=()=>new Promise(resolve=>window.resolveIconSave=resolve);
          const pending=v96SaveBranding('logo');
          state.settings.preferences.branding={...state.settings.preferences.branding,
            logoPreset:'family',logoUpdatedAt:new Date(Date.now()+2000).toISOString()};
          v89StorageFailed=true;resolveIconSave(false);const saved=await pending;
          return {saved,preset:state.settings.preferences.branding.logoPreset};
        """)
        self.assertEqual(newer, {'saved': False, 'preset': 'family'})

    def test_saving_previous_household_never_changes_current_family_icon(self):
        self.open_choices()
        self.save_preset('home')
        result = self.evaluate("""
          v160StageLogoPreset('wallet');saveAll=()=>new Promise(resolve=>window.resolveIconSave=resolve);
          const pending=v96SaveBranding('logo');
          CONFIG.household+='-new-family';state=blankState();v96ClearBrandingDraft();v96ApplyBranding();
          v89StorageFailed=true;resolveIconSave(false);const saved=await pending;
          return {saved,branding:state.settings.preferences.branding||null,
            html:document.querySelector('.brand-emblem').innerHTML,
            busy:v96BrandingBusy};
        """)
        self.assertFalse(result['saved'])
        self.assertIsNone(result['branding'])
        self.assertNotIn('wallet', result['html'])
        self.assertFalse(result['busy'])

    def test_late_image_decode_cannot_replace_newer_preset_or_new_household(self):
        self.open_choices()
        first = self.page.evaluate("""async data => {
          v96RasterBranding=()=>new Promise(resolve=>window.resolveIconRaster=resolve);
          const pending=v96StageBranding('logo',new File(['fixture'],'late.png',{type:'image/png'}));
          v160StageLogoPreset('tree');resolveIconRaster(data);const staged=await pending;
          const saved=await v96SaveBranding('logo');return {staged,saved,...readIcon()};
        }""", PNG_DATA)
        self.assertFalse(first['staged'])
        self.assertTrue(first['saved'])
        self.assertEqual(first['preset'], 'tree')
        self.assertIsNone(first['data'])
        second = self.page.evaluate("""async data => {
          v96RasterBranding=()=>new Promise(resolve=>window.resolveIconRaster=resolve);
          const pending=v96StageBranding('logo',new File(['fixture'],'late.png',{type:'image/png'}));
          CONFIG.household+='-new-family';state=blankState();v96ClearBrandingDraft();v96ApplyBranding();
          resolveIconRaster(data);const staged=await pending;
          return {staged,branding:state.settings.preferences.branding||null,
            draft:!!v96BrandingDraft.logo,html:document.querySelector('.brand-emblem').innerHTML};
        }""", PNG_DATA)
        self.assertFalse(second['staged'])
        self.assertIsNone(second['branding'])
        self.assertFalse(second['draft'])
        self.assertNotIn('<img', second['html'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
