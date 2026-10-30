#!/usr/bin/env python3
"""Check the extracted fictional demo, never a live family profile or endpoint."""
import argparse
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import zipfile

from playwright.sync_api import sync_playwright


@contextmanager
def serve_demo(directory):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            name = {'/': 'index.html', '/favicon.svg': 'favicon.svg'}.get(self.path)
            if not name:
                self.send_error(404)
                return
            body = (directory / name).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8' if name.endswith('.html') else 'image/svg+xml')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/'
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def check(archive: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    demo = output / 'fictional-demo'
    if demo.exists():
        raise ValueError('Use a fresh output directory')
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        if names != {'BUILD.json', 'MANIFEST.json', 'OWNER_REVIEW_RU.md', 'README.txt', '_headers', 'favicon.svg', 'index.html'}:
            raise ValueError('Unexpected demo files')
        manifest = json.loads(bundle.read('MANIFEST.json'))
        for name, expected in manifest.items():
            if hashlib.sha256(bundle.read(name)).hexdigest() != expected:
                raise ValueError('Demo manifest mismatch')
        bundle.extractall(demo)
    results = []
    with serve_demo(demo) as base, sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', headless=True)
        for width in (320, 390, 768, 1280, 1536, 1920):
            context = browser.new_context(viewport={'width': width, 'height': 1000}, timezone_id='Europe/Moscow', service_workers='block')
            requests, errors = [], []
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base) else (requests.append(route.request.url), route.abort()))
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)[:180]))
            page.goto(base, wait_until='load')
            page.wait_for_selector('#v99HomeDirectionTiles button')
            before = page.evaluate('JSON.stringify(state)')
            total = page.evaluate('sum(expenses(homeMonth()))')
            stages = []
            for stage in ('home', 'subscription', 'entry'):
                if stage == 'subscription':
                    page.locator('#v99HomeDirectionTiles [data-v99-direction="subscriptions"]').click()
                    page.wait_for_selector('#v84DrillModal.open')
                elif stage == 'entry':
                    page.evaluate("v84CloseDrill();openEntry('expense')")
                    page.locator('[data-v99-entry-direction="person:Елена"]').click()
                    page.locator('[data-v99-entry-direction="subscriptions"]').click()
                    assert page.locator('#eBeneficiary').input_value() == 'Елена'
                    assert page.locator('#eCategory').input_value() == 'Подписки'
                metrics = page.evaluate("""() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,
                  bad:[...document.querySelectorAll('#v99HomeSpending,#v99HomeDirections,#v99HomeSlices,#v99EntryDirections,.v99-entry-direction,#v84DrillModal.open .v84-modal')]
                  .filter(n=>n.getBoundingClientRect().height>0).map(n=>{const r=n.getBoundingClientRect();return {id:n.id,left:r.left,right:r.right,scroll:n.scrollWidth,client:n.clientWidth}})
                  .filter(r=>r.left<-.5||r.right>innerWidth+.5||r.scroll>r.client+2)})""")
                assert metrics['scroll'] <= width + 1, (width, stage, metrics)
                assert not metrics['bad'], (width, stage, metrics)
                assert page.evaluate('JSON.stringify(state)') == before, (width, stage, 'render changed records')
                stages.append(stage)
                if width in (390, 1536):
                    page.screenshot(path=str(output / f'v95-family-{stage}-{width}.png'), full_page=stage != 'subscription')
                    if stage == 'home':
                        page.screenshot(path=str(output / f'v95-family-home-first-screen-{width}.png'))
            assert not requests, requests
            assert not errors, errors
            results.append({'width': width, 'stages': stages, 'records_unchanged': True, 'expense_total': total, 'external_requests': 0, 'javascript_errors': 0, 'horizontal_overflow': 0})
            context.close()
        browser.close()
    report = {'status': 'passed', 'data': 'fictional only', 'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'cases': results, 'native_device_acceptance': 'pending'}
    (output / 'family-dashboard-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = check(args.archive, args.output)
    print('Fictional demo: six widths, three views, no record changes, network requests, JavaScript errors or overflow.')
