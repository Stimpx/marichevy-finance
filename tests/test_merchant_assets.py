"""Curated offline logo assets: provenance, safe SVG import and actual decoding."""
import importlib.util
import json
from pathlib import Path
import time
import unittest

import test_local_data_safety as harness

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('merchant_builder', ROOT/'tools/build_merchant_catalog.py')
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class MerchantAssetImport(unittest.TestCase):
    def test_embedded_assets_match_reviewable_catalogue_and_provenance(self):
        builder.build(check=True)

    def test_svg_import_refuses_active_content_and_external_resources(self):
        for payload in (
            '<script>alert(1)</script>', '<image href="https://example.invalid/x"/>',
            '<path onload="alert(1)"/>', '<foreignObject/>', '<style>@import url(x)</style>',
            '<path fill="url(https://example.invalid/x)"/>', '<path fill="url(#missing)"/>',
            '<path fill="URL(//example.invalid/x)"/>', '<path fill="u\\72l(//example.invalid/x)"/>',
            '<path fill="url/**/(//example.invalid/x)"/>',
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                builder.checked_svg('<svg viewBox="0 0 10 10">'+payload+'</svg>', 'fictional')
        with self.assertRaises(ValueError):
            builder.checked_svg('<!DOCTYPE svg [<!ENTITY x "bad">]><svg viewBox="0 0 1 1"/>', 'fictional')

    def test_local_svg_gradients_keep_their_references(self):
        value = builder.checked_svg('<svg viewBox="0 0 10 10"><defs><linearGradient id="a">'
                                    '<stop stop-color="#fff"/></linearGradient></defs>'
                                    '<path d="M0 0H10V10H0Z" fill="url(#a)"/></svg>', 'fictional')
        self.assertIn('id="v99-fictional-a"', value)
        self.assertIn('url(#v99-fictional-a)', value)
        self.assertIn('xmlns="http://www.w3.org/2000/svg"', value)

    def test_static_paint_classes_are_resolved_and_unsafe_css_is_rejected(self):
        svg = '<svg viewBox="0 0 10 10"><defs><style>.brand{fill:#ff465c}</style></defs><path id="Fill 5" class="brand" d="M0 0H10V10H0Z" style="fill-opacity:0.8"/></svg>'
        value = builder.checked_svg(svg, 'fictional')
        self.assertIn('fill="#ff465c"', value)
        self.assertIn('fill-opacity="0.8"', value)
        self.assertNotIn('<style', value)
        self.assertNotIn('class=', value)
        self.assertNotIn('Fill 5', value)
        for paint in ['fill:URL(//example.invalid/x)', 'fill:u\\72l(//example.invalid/x)', 'background-image:url(x)']:
            with self.subTest(paint=paint), self.assertRaises(ValueError):
                builder.checked_svg('<svg viewBox="0 0 10 10"><path style="'+paint+'"/></svg>', 'fictional')


class MerchantAssetBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.LocalDataSafety.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        harness.LocalDataSafety.tearDownClass.__func__(cls)

    setUp = harness.LocalDataSafety.setUp
    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open

    def test_all_shipped_logos_decode_offline_without_touching_the_ledger(self):
        weather = {'at':int(time.time()*1000), 'source':'Fictional weather fixture',
                   'data':{'temperature_2m':0,'apparent_temperature':0,'weather_code':0,'wind_speed_10m':0}}
        self.open({'marichevy_weather_last_good_v74':json.dumps(weather)})
        self.page.evaluate('session=null;stopCloudSync();state=blankState();showApp()')
        requests = []
        self.page.on('request', lambda request: requests.append(request.url))
        result = self.page.evaluate('''async () => {
          const before=JSON.stringify(state),node=document.createElement('div');
          node.innerHTML=V96_MERCHANTS.map(item=>v96MerchantBadge(item.value)).join('');
          document.body.append(node);
          const images=[...node.querySelectorAll('img')];
          await Promise.all(images.map(image=>image.decode()));
          const result={before,after:JSON.stringify(state),count:images.length,
            invalid:images.filter(image=>!image.naturalWidth||!image.naturalHeight||!image.src.startsWith('data:image/')).length,
            logoBrands:[...node.querySelectorAll('[data-merchant-mark="logo"]')].map(item=>item.dataset.merchantBrand),
            scripts:node.querySelectorAll('script,[onerror],[onload]').length};
          node.remove();return result;
        }''')
        manifest = json.loads((ROOT/'tools/merchant_logos/manifest.json').read_text())
        self.assertEqual(result['count'], len(manifest))
        self.assertEqual(result['invalid'], 0)
        self.assertEqual(result['scripts'], 0)
        self.assertEqual(result['before'], result['after'])
        self.assertEqual(set(result['logoBrands']), set(manifest))
        self.assertTrue({'pyaterochka','dixy','vkusvill','gorzdrav','rigla','stolichki'} <= set(manifest))
        self.assertEqual(requests, [])


if __name__ == '__main__':
    unittest.main()
