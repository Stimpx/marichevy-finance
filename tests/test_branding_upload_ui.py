"""Modern branding chooser; fictional image, local browser only."""
from pathlib import Path
import sys
import unittest

import test_branding_settings as branding
import test_local_data_safety as harness
sys.path.insert(0, str(Path(harness.__file__).resolve().parents[1] / 'tools'))
from check_touch_flows import enlarge_text


class BrandingUploadUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls): harness.LocalDataSafety.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls): harness.LocalDataSafety.tearDownClass.__func__(cls)
    setUp = harness.LocalDataSafety.setUp
    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open
    prepare = branding.BrandingSettings.prepare
    image = branding.BrandingSettings.image
    stored = branding.BrandingSettings.stored

    def test_chooser_stages_only_and_cancel_reselect_preserve_existing_preview(self):
        self.prepare(); before = self.stored()
        payload={'name':'fictional-logo.png','mimeType':'image/png','buffer':self.image()}
        with self.page.expect_file_chooser() as chooser:
            self.page.get_by_role('button',name='Выбрать логотип',exact=True).click()
        chooser.value.set_files(payload)
        self.page.wait_for_function("!!v96BrandingDraft.logo")
        staged=self.page.evaluate("({draft:JSON.stringify(v96BrandingDraft),preview:v96LogoPreview.getAttribute('src')})")
        self.assertEqual(self.stored(), before)
        with self.page.expect_file_chooser() as chooser:
            self.page.get_by_role('button',name='Выбрать логотип',exact=True).click()
        self.assertEqual(self.page.locator('#v96LogoFile').input_value(),'')
        chooser.value.set_files([])
        self.assertEqual(self.page.evaluate("({draft:JSON.stringify(v96BrandingDraft),preview:v96LogoPreview.getAttribute('src')})"),staged)
        self.assertEqual(self.stored(),before)
        with self.page.expect_file_chooser() as chooser:
            self.page.get_by_role('button',name='Выбрать логотип',exact=True).click()
        chooser.value.set_files(payload)
        self.page.wait_for_function("!!v96BrandingDraft.logo")
        self.assertEqual(self.page.evaluate("v96LogoPreview.getAttribute('src')"),staged['preview'])
        self.assertEqual(self.stored(),before)
        self.assertEqual(self.page.locator('.brand-emblem img').count(),0)

    def test_busy_and_gate_do_not_open_chooser_or_change_data(self):
        self.prepare();before=self.stored()
        self.page.evaluate('v96BrandingBusy=true;v96RenderBrandingChoices()')
        self.assertTrue(self.page.get_by_role('button',name='Выбрать логотип',exact=True).is_disabled())
        self.assertFalse(self.page.evaluate("v109ChooseBrandingFile('logo')"))
        self.page.evaluate('v96BrandingBusy=false;showGate()')
        self.assertTrue(self.page.locator('#v109LogoChoose').is_disabled())
        self.assertTrue(self.page.locator('#v109FaviconChoose').is_disabled())
        self.assertFalse(self.page.evaluate("v109ChooseBrandingFile('favicon')"))
        self.assertFalse(self.page.evaluate("v109ChooseBrandingFile('unknown')"))
        self.assertEqual(self.stored(),before)

    def test_chooser_controls_fit_at_phone_and_enlarged_text(self):
        for width,height,scale in [(320,844,1),(390,844,1),(820,1180,1),(1440,1000,1),(320,844,2),(390,844,1.5)]:
            with self.subTest(width=width,scale=scale):
                self.prepare();before=self.stored()
                self.page.set_viewport_size({'width':width,'height':height})
                if scale!=1: enlarge_text(self.page,scale)
                for selector in ['#v109LogoChoose','#v109FaviconChoose']:
                    button=self.page.locator(selector);button.scroll_into_view_if_needed()
                    info=button.evaluate('''el=>{
                      const r=el.getBoundingClientRect(),s=getComputedStyle(el);
                      return {left:r.left,right:r.right,height:r.height,scroll:el.scrollWidth,client:el.clientWidth};
                    }''')
                    self.assertGreaterEqual(info['left'],0)
                    self.assertLessEqual(info['right'],width+1)
                    self.assertGreaterEqual(info['height'],44)
                    self.assertLessEqual(info['scroll'],info['client']+1)
                self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),width+1)
                self.assertEqual(self.stored(),before)
                if width==1440:
                    directory=Path('/workspace/unified-controls-review-20261101');directory.mkdir(exist_ok=True)
                    self.page.locator('#v96BrandingCard').screenshot(path=str(directory/'branding-upload.png'))


if __name__=='__main__': unittest.main()
