"""Regression for the owner's cramped editor and scattered ledger actions.

Only a sanitized fictional page is served. Geometry checks exercise real browser
layout, including narrow CSS viewports equivalent to desktop browser zoom and
an independent enlarged-text approximation. This is not native Safari evidence.
"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_bundle
from test_release_ui import rich_fixture
from check_touch_flows import enlarge_text

PROFILES = ((320, 740), (390, 844), (430, 932), (768, 1024),
            (820, 1180), (844, 390), (1024, 768), (1280, 800),
            (1440, 900), (1920, 1080), (640, 400), (960, 540))


class ResponsiveEditorLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='fictional-responsive-')
        directory = Path(cls.temp.name)
        selected = Path(os.environ.get('RESPONSIVE_TEST_SOURCE', str(ROOT / 'index.html')))
        source = selected.read_text()
        cls.source_sha = hashlib.sha256(source.encode()).hexdigest()
        (directory / 'index.html').write_text(build_bundle.transform_demo(source))
        (directory / 'favicon.svg').write_text(build_bundle.ICON)

        class Quiet(SimpleHTTPRequestHandler):
            def log_message(self, *_args):
                pass

        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Quiet, directory=str(directory)))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}/'
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path='/usr/bin/chromium', headless=True)
        cls.records = []

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temp.cleanup()
        report = os.environ.get('RESPONSIVE_GEOMETRY_REPORT')
        if report:
            Path(report).write_text(json.dumps({'source_sha256': cls.source_sha,
                'fictional_only': True, 'engine': 'Chromium',
                'limitations': ['CSS viewport zoom equivalents and enlarged text approximations; no native Safari claim'],
                'checks': cls.records}, indent=2) + '\n')

    def page(self, width, height, text=1):
        context = self.browser.new_context(viewport={'width': width, 'height': height},
            timezone_id='Europe/Moscow', service_workers='block', has_touch=width < 1100)
        self.addCleanup(context.close)
        context.route('**/*', lambda route: route.continue_()
            if route.request.url.startswith(self.base) else route.abort())
        context.add_init_script("localStorage.setItem('marichevy_demo_state_v10'," +
            json.dumps(json.dumps(rich_fixture(), ensure_ascii=False)) + ");")
        page = context.new_page()
        page.set_default_timeout(5000)
        page.goto(self.base, wait_until='load')
        page.wait_for_function("typeof state==='object' && !appRoot.classList.contains('auth-locked')")
        page.add_style_tag(content='*,*::before,*::after{animation:none!important;transition:none!important}')
        if text != 1:
            # The editor is created dynamically; enlarge it after opening below.
            page.evaluate('window.__responsiveTextScale=' + str(text))
        return page, context

    def editor_geometry(self, page):
        return page.evaluate('''() => {
          const rect=el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,right:r.right,bottom:r.bottom}};
          const modal=document.querySelector('#editModal .modal');
          const controls=['xType','xAmount','xCat','xSubcategory','xBeneficiary','xDate','xStore','xComment']
            .map(id=>document.getElementById(id)).filter(el=>el.getBoundingClientRect().width);
          const canvas=document.createElement('canvas').getContext('2d');
          const fields=controls.map(el=>{
            const style=getComputedStyle(el);canvas.font=style.font;
            const label=el.tagName==='SELECT'?el.selectedOptions[0].textContent:
              el.type==='date'?'27.10.2026':'';
            return {id:el.id,...rect(el),required:label?canvas.measureText(label).width+
              parseFloat(style.paddingLeft)+parseFloat(style.paddingRight)+
              (el.tagName==='SELECT'?24:28):0};
          });
          const tools=[...document.querySelectorAll('#editForm .v96-amount-tools button')].map(rect);
          const heading=document.querySelector('#editModal h2');
          const h=heading.getBoundingClientRect();
          return {modal:rect(modal),fields,tools,innerWidth,innerHeight,
            modalScroll:modal.scrollWidth,modalClient:modal.clientWidth,
            headingVisible:h.top>=0&&h.bottom<=innerHeight,
            toolRows:new Set(tools.map(r=>Math.round(r.y))).size};
        }''')

    def test_editor_fields_and_amount_tools_fit_their_actual_container(self):
        for width, height in PROFILES:
            with self.subTest(width=width, height=height):
                page, context = self.page(width, height)
                before = page.evaluate('JSON.stringify(state)')
                page.evaluate("openEdit('qa-expense-0-0')")
                geometry = self.editor_geometry(page)
                self.records.append({'view': 'edit', 'width': width, 'height': height, **geometry})
                modal = geometry['modal']
                self.assertGreaterEqual(modal['x'], -1)
                self.assertLessEqual(modal['right'], width + 1)
                self.assertTrue(geometry['headingVisible'])
                self.assertLessEqual(geometry['modalScroll'], geometry['modalClient'] + 1)
                for control in geometry['fields']:
                    self.assertGreaterEqual(control['x'], modal['x'])
                    self.assertLessEqual(control['right'], modal['right'])
                    self.assertGreaterEqual(control['w'] + 2, control['required'], control['id'])
                self.assertLessEqual(geometry['toolRows'], 2, 'three tall tool rows recreate owner screenshot')
                if width >= 768:
                    self.assertEqual(geometry['toolRows'], 1, 'wide editor should keep amount actions together')
                self.assertEqual(before, page.evaluate('JSON.stringify(state)'))
                context.close()

    def test_history_edit_and_delete_are_adjacent_without_colliding(self):
        for width, height in PROFILES:
            with self.subTest(width=width, height=height):
                page, context = self.page(width, height)
                page.evaluate("go('history')")
                geometry = page.evaluate('''() => {
                  const row=document.querySelector('#historyBody .v76-entry-row');
                  const group=row.querySelector('.v76-action-group');
                  const rect=el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,right:r.right,bottom:r.bottom}};
                  return {row:rect(row),group:rect(group),display:getComputedStyle(row).display,
                    buttons:[...group.querySelectorAll('button')].map(rect),
                    edit:rect(group.querySelector('[data-action="edit"]')),
                    remove:rect(group.querySelector('[data-action="delete"]'))};
                }''')
                self.records.append({'view': 'history-actions', 'width': width, 'height': height, **geometry})
                self.assertLessEqual(abs(geometry['edit']['y'] - geometry['remove']['y']), 2)
                self.assertLessEqual(geometry['remove']['x'] - geometry['edit']['right'], 20,
                    'delete must not drift into the middle of a wide card')
                for index, first in enumerate(geometry['buttons']):
                    for second in geometry['buttons'][index+1:]:
                        intersection = min(first['right'], second['right']) - max(first['x'], second['x']) > 1 and \
                            min(first['bottom'], second['bottom']) - max(first['y'], second['y']) > 1
                        self.assertFalse(intersection, 'ledger action buttons overlap')
                context.close()

    def test_enlarged_text_and_short_height_keep_editor_actions_reachable(self):
        for width, height, scale in ((320, 740, 2), (390, 844, 1.5), (768, 600, 2), (1280, 700, 2), (844, 390, 1.5)):
            with self.subTest(width=width, height=height, text=scale):
                page, context = self.page(width, height)
                page.evaluate("openEdit('qa-expense-0-0')")
                enlarge_text(page, scale)
                geometry = self.editor_geometry(page)
                self.records.append({'view': 'edit-enlarged-text', 'width': width, 'height': height,
                    'text_scale': scale, **geometry})
                self.assertTrue(geometry['headingVisible'])
                self.assertLessEqual(geometry['modalScroll'], geometry['modalClient'] + 1)
                for control in geometry['fields']:
                    self.assertGreaterEqual(control['x'], geometry['modal']['x'] - 1)
                    self.assertLessEqual(control['right'], geometry['modal']['right'] + 1)
                save = page.locator('#editModal button').filter(has_text='Сохранить').first
                save.scroll_into_view_if_needed()
                self.assertTrue(save.evaluate('''el=>{const r=el.getBoundingClientRect();
                  const front=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
                  return r.top>=0&&r.bottom<=innerHeight&&el.contains(front)}'''))
                self.assertTrue(save.evaluate('''el=>{const style=getComputedStyle(el);
                  const ctx=document.createElement('canvas').getContext('2d');ctx.font=style.font;
                  return ctx.measureText(el.textContent.trim()).width <= el.clientWidth-
                    parseFloat(style.paddingLeft)-parseFloat(style.paddingRight)+1}'''),
                    'save label must remain readable as a whole word at enlarged text')
                context.close()

    def test_new_entry_does_not_recreate_the_narrow_amount_column(self):
        for width, height, scale in ((320, 740, 1), (390, 844, 1.5), (768, 1024, 1.5),
                                    (1024, 768, 1.5), (1280, 800, 1.5), (1920, 1080, 2)):
            with self.subTest(width=width, height=height, text=scale):
                page, context = self.page(width, height)
                page.evaluate("openEntry('expense')")
                if scale != 1:
                    enlarge_text(page, scale)
                geometry = page.evaluate('''() => {
                  const amount=document.getElementById('eAmount');
                  const tools=amount.closest('.field')?.querySelector('.v96-amount-tools') ||
                    document.querySelector('#today .v96-amount-tools');
                  const controls=[...tools.querySelectorAll('button')];
                  const bounds=el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,right:r.right}};
                  return {amount:bounds(amount),tools:bounds(tools),buttons:controls.map(bounds),
                    rows:new Set(controls.map(el=>Math.round(el.getBoundingClientRect().top))).size};
                }''')
                self.records.append({'view': 'new-entry-amount', 'width': width, 'height': height,
                    'text_scale': scale, **geometry})
                self.assertLessEqual(geometry['rows'], 2,
                    'a fixed narrow column must not stack all three amount actions')
                for button in geometry['buttons']:
                    self.assertGreaterEqual(button['x'], -1)
                    self.assertLessEqual(button['right'], width + 1)
                context.close()
