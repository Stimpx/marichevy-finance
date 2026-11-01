"""Branding reset intent survives stale snapshots; synthetic local data only."""
import json
import unittest

import test_branding_settings as branding
import test_local_data_safety as harness


class BrandingResetSync(unittest.TestCase):
    @classmethod
    def setUpClass(cls): harness.LocalDataSafety.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls): harness.LocalDataSafety.tearDownClass.__func__(cls)
    setUp = harness.LocalDataSafety.setUp
    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open
    prepare = branding.BrandingSettings.prepare
    image = branding.BrandingSettings.image
    upload = branding.BrandingSettings.upload

    def saved_artwork(self):
        self.prepare()
        self.defaults=self.page.locator('link[rel~="icon"]').evaluate_all(
            '(nodes)=>nodes.map(n=>[n.getAttribute("href"),n.getAttribute("type")])')
        self.upload('logo'); self.upload('favicon',buffer=self.image(32,32))
        self.page.evaluate("v96SaveBranding('all')")
        self.page.wait_for_function("!!state.settings.preferences.branding.faviconDataUrl && !v96BrandingBusy")
        self.page.evaluate("""() => {
          state.settings.updated_at='2001-01-01T00:00:00.000Z';
          window.__beforeBrandingReset=JSON.parse(JSON.stringify(state));
          rememberCloudBase(window.__beforeBrandingReset);
        }""")
        self.original=self.page.evaluate('window.__beforeBrandingReset')

    def assert_defaults(self):
        self.assertFalse(self.page.locator('#v96FaviconPreview').is_visible())
        self.assertIsNone(self.page.locator('#v96FaviconPreview').get_attribute('src'))
        self.assertEqual(self.page.locator('link[rel~="icon"]').evaluate_all(
            '(nodes)=>nodes.map(n=>[n.getAttribute("href"),n.getAttribute("type")])'),self.defaults)

    def assert_only_favicon_reset(self, current):
        expected=json.loads(json.dumps(self.original))
        expected['settings']['preferences']['branding']['faviconDataUrl']=None
        self.assertEqual(current['settings']['preferences'],expected['settings']['preferences'])
        self.assertEqual(current['settings']['loans'],expected['settings']['loans'])
        self.assertEqual(current['settings']['notifications'],expected['settings']['notifications'])
        for key in expected:
            if key!='settings': self.assertEqual(current[key],expected[key],key)

    def test_reset_favicon_survives_stale_read_before_write_merge_and_reload(self):
        self.saved_artwork()
        self.page.get_by_role('button',name='Стандартный фавикон',exact=True).click()
        self.page.wait_for_function('!v96BrandingBusy')
        result=self.page.evaluate("""() => {
          const local=JSON.parse(JSON.stringify(state));
          const merged=reconcileCloudSnapshot(__beforeBrandingReset,local,'fictional-branding-reset');
          return {local,merged,conflicts:reconcileCloudSnapshot.conflicts};
        }""")
        self.assertFalse(bool(result['merged']['settings']['preferences']['branding'].get('faviconDataUrl')),
            'the stale cloud favicon must not return after reset')
        self.assertEqual(result['conflicts'],[])
        self.assertIsNotNone(result['merged'])
        self.assert_only_favicon_reset(result['local'])
        self.assert_only_favicon_reset(result['merged'])
        self.page.evaluate("""merged=>{state=normalize(merged);saveLocal();savePendingLocal();
          v96ApplyBranding();v96RenderBrandingChoices()}""",result['merged'])
        self.assert_defaults()
        self.assertEqual(self.page.locator('.brand-emblem img').get_attribute('src'),
            self.original['settings']['preferences']['branding']['logoDataUrl'])
        self.page.reload(wait_until='domcontentloaded')
        self.page.wait_for_function("typeof state==='object' && typeof showApp==='function'")
        self.page.evaluate("showApp();go('settings')")
        self.assert_only_favicon_reset(self.page.evaluate('JSON.parse(JSON.stringify(state))'))
        self.assert_defaults()

    def test_reset_is_explicit_and_newer_in_full_merge_in_either_source_order(self):
        self.saved_artwork()
        for old_at in ('2001-01-01T00:00:00.000Z','2099-01-01T00:00:00.000Z'):
            with self.subTest(old_at=old_at):
                self.page.evaluate("""at=>{
                  state=normalize(JSON.parse(JSON.stringify(__beforeBrandingReset)));
                  state.settings.updated_at=at;
                  window.__staleBrandingSnapshot=JSON.parse(JSON.stringify(state));
                }""",old_at)
                self.page.evaluate("v96ResetBranding('favicon')")
                result=self.page.evaluate("""() => ({local:state,
                  left:mergeStates(__staleBrandingSnapshot,state),right:mergeStates(state,__staleBrandingSnapshot)})""")
                self.assertGreater(result['local']['settings']['updated_at'],old_at)
                for key in ('local','left','right'): self.assert_only_favicon_reset(result[key])

    def test_reset_cannot_mutate_draft_while_an_existing_save_is_pending(self):
        self.saved_artwork(); self.upload('favicon',buffer=self.image(24,24))
        self.page.evaluate("""() => {
          window.__nativeBrandingSaveAll=saveAll;
          saveAll=()=>new Promise(resolve=>window.__finishBrandingSave=resolve);
          window.__waitingBrandingSave=v96SaveBranding('favicon');
          window.__busyDraft=JSON.stringify(v96BrandingDraft);
          window.__busyState=JSON.stringify(state);
        }""")
        for name in ('Стандартный логотип','Стандартный фавикон','Вернуть стандартное оформление'):
            self.assertTrue(self.page.get_by_role('button',name=name,exact=True).is_disabled())
        self.assertFalse(self.page.evaluate("v96ResetBranding('favicon')"))
        self.assertEqual(self.page.evaluate('JSON.stringify(v96BrandingDraft)'),self.page.evaluate('__busyDraft'))
        self.assertEqual(self.page.evaluate('JSON.stringify(state)'),self.page.evaluate('__busyState'))
        self.page.evaluate("""async()=>{__finishBrandingSave(false);await __waitingBrandingSave;
          saveAll=__nativeBrandingSaveAll;}""")
        self.assertTrue(self.page.get_by_role('button',name='Стандартный фавикон',exact=True).is_enabled())

    def test_reset_discards_unsaved_icon_and_late_save_after_logout_reports_no_success(self):
        self.saved_artwork(); self.upload('favicon',buffer=self.image(24,24))
        self.page.evaluate("v96ResetBranding('favicon')")
        self.assert_defaults()
        self.assertIsNone(self.page.evaluate('state.settings.preferences.branding.faviconDataUrl'))
        self.assertEqual(self.page.evaluate('Object.keys(v96BrandingDraft)'),[])
        self.upload('favicon',buffer=self.image(20,20))
        self.page.evaluate("""() => {
          window.__nativeBrandingSaveAll=saveAll;
          saveAll=()=>new Promise(resolve=>window.__finishBrandingSave=resolve);
          window.__waitingBrandingSave=v96SaveBranding('favicon');
          logout();window.__afterBrandingLogout=v96BrandingStatus.textContent;
        }""")
        result=self.page.evaluate("""async()=>{__finishBrandingSave(true);const value=await __waitingBrandingSave;
          saveAll=__nativeBrandingSaveAll;return {value,status:v96BrandingStatus.textContent,
          expected:__afterBrandingLogout,keys:Object.keys(v96BrandingDraft)};}""")
        self.assertFalse(result['value'])
        self.assertEqual(result['status'],result['expected'])
        self.assertEqual(result['keys'],[])


if __name__=='__main__': unittest.main()
