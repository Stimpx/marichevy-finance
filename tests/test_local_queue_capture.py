"""Read-only queue capture in an entirely synthetic browser; no external request."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / 'tools/capture_local_queue.js').read_text()
ORIGIN = 'https://finance.marichev.pro'
STATE = 'marichevy_state_v10'
PENDING = 'marichevy_pending_v10'
SESSION = 'marichevy_session_v10'


class LocalQueueCapture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path='/usr/bin/chromium',
            headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context(accept_downloads=True)
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.requests = []
        self.downloads = []
        self.page.on('download', lambda download: self.downloads.append(download))

    def open_fixture(self, values=None, origin=ORIGIN):
        fixture_url = origin + '/capture-fixture'
        def route(request):
            self.requests.append(request.request.url)
            if request.request.url == fixture_url:
                request.fulfill(status=200, content_type='text/html', body='''<!doctype html>
                    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; connect-src 'none'">
                    <title>Synthetic local queue fixture</title><body>Fictional fixture only</body>''')
            else:
                request.abort()
        self.page.route('**/*', route)
        self.page.goto(fixture_url, wait_until='domcontentloaded')
        self.page.evaluate('''values => {
          for (const [key, value] of Object.entries(values)) localStorage.setItem(key, value);
          window.__nativeRead = Storage.prototype.getItem;
          window.__nativeWrite = Storage.prototype.setItem;
          window.__captureReads = [];
          window.__captureWrites = [];
          Storage.prototype.getItem = function (key) {
            window.__captureReads.push(key);
            if (key === 'marichevy_session_v10' || key === 'unrelated-secret')
              throw new Error('PRIVATE_SESSION_MUST_NEVER_BE_READ');
            return window.__nativeRead.call(this, key);
          };
          for (const method of ['setItem', 'removeItem', 'clear']) {
            Storage.prototype[method] = function (...args) {
              window.__captureWrites.push([method, args[0]]);
              throw new Error('Capture must never write storage');
            };
          }
        }''', values or {})
        self.assertEqual(self.requests, [fixture_url])

    def snapshot(self):
        return self.page.evaluate('''() => Object.fromEntries(Object.keys(localStorage).sort()
          .map(key => [key, window.__nativeRead.call(localStorage, key)]))''')

    def test_exact_raw_strings_hashes_and_all_storage_survive_download(self):
        values = {
            STATE: '{"entries":[{"id":"fictional-entry","amount":1250.50,"note":"чай\\nкофе"}]}',
            PENDING: '{malformed pending\r\n  1\u202f250,50 😀',
            STATE + '_corrupt_v1': '\ufeffNOT JSON\u0000raw',
            PENDING + '_corrupt_v1': 'different damaged raw pending',
            STATE + '_cloud_base_v1': '{"household":"fictional","data":{"entries":[]}}',
            STATE + '_cloud_conflict_v1': '{"local":{"amount":21},"cloud":{"amount":31}}',
            STATE + '_cloud_conflict_v1_archive_aa11-bb22': '{old conflict not valid JSON',
            'marichevy_state_backup_v44': '{"data":{"entries":[]}}',
            'marichevy_state_backup_v44_corrupt_v1': 'raw old backup',
            'marichevy_pre_import_backup_v73': '{"data":{"futureField":"preserve"}}',
            'marichevy_pre_import_backup_v73_corrupt_v1': 'raw old preimport',
            SESSION: 'PRIVATE_SESSION_MUST_NEVER_BE_READ',
            'unrelated-secret': 'PRIVATE_UNRELATED_MUST_NEVER_BE_READ',
            STATE + '_cloud_conflict_v1_archive_/not-an-archive': 'DO_NOT_READ_LOOKALIKE',
            STATE + '_cloud_base_v1_suffix': 'DO_NOT_READ_LOOKALIKE'
        }
        self.open_fixture(values)
        before = self.snapshot()
        with self.page.expect_download() as pending_download:
            result = self.page.evaluate(SCRIPT)
        download = pending_download.value
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / download.suggested_filename
            download.save_as(path)
            raw_file = path.read_bytes()
            capture = json.loads(raw_file)
        self.assertEqual(result['outcome'], 'download-requested')
        self.assertIn('PRIVATE', download.suggested_filename)
        self.assertEqual(capture['format'], 'marichevy-local-queue-capture-v1')
        self.assertEqual(capture['origin'], ORIGIN)
        self.assertFalse(capture['device_clock_verified'])
        self.assertFalse(capture['session_included'])
        self.assertFalse(capture['storage_modified'])
        self.assertTrue(capture['captured_at_device_utc'].endswith('Z'))
        records = {record['key']: record for record in capture['records']}
        self.assertEqual(len(records), 11)
        self.assertEqual(capture['key_count'], len(records))
        self.assertEqual(result['key_count'], len(records))
        for key, record in records.items():
            self.assertEqual(record['raw'], values[key])
            encoded = values[key].encode('utf-8')
            self.assertEqual(record['sha256_utf8'], hashlib.sha256(encoded).hexdigest())
            self.assertEqual(record['sha256_utf16le'], hashlib.sha256(values[key].encode('utf-16-le')).hexdigest())
            self.assertEqual(record['utf8_bytes'], len(encoded))
            self.assertEqual(record['utf16_code_units'], len(values[key].encode('utf-16-le')) // 2)
        for secret in [b'PRIVATE_SESSION_MUST_NEVER_BE_READ', b'PRIVATE_UNRELATED_MUST_NEVER_BE_READ',
                       b'DO_NOT_READ_LOOKALIKE']:
            self.assertNotIn(secret, raw_file)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.page.evaluate('window.__captureWrites'), [])
        self.assertEqual(set(self.page.evaluate('window.__captureReads')), set(records))
        self.assertEqual(self.requests, [ORIGIN + '/capture-fixture'])

    def test_lone_utf16_surrogate_is_preserved_and_distinguished_by_code_unit_hash(self):
        values = {STATE: 'left\ud800right', PENDING: 'left\ufffdright'}
        self.open_fixture(values)
        before = self.snapshot()
        with self.page.expect_download() as pending_download:
            result = self.page.evaluate(SCRIPT)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'capture.json'
            pending_download.value.save_as(path)
            raw_file = path.read_bytes()
            capture = json.loads(raw_file)
        self.assertEqual(result['outcome'], 'download-requested')
        records = {record['key']: record for record in capture['records']}
        self.assertIn(b'\\ud800', raw_file)
        self.assertEqual(records[STATE]['raw'], values[STATE])
        self.assertEqual(records[PENDING]['raw'], values[PENDING])
        self.assertEqual(records[STATE]['sha256_utf8'], records[PENDING]['sha256_utf8'])
        self.assertNotEqual(records[STATE]['sha256_utf16le'], records[PENDING]['sha256_utf16le'])
        for key in values:
            self.assertEqual(records[key]['sha256_utf16le'],
                             hashlib.sha256(values[key].encode('utf-16-le', errors='surrogatepass')).hexdigest())
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.page.evaluate('window.__captureWrites'), [])
        self.assertEqual(self.requests, [ORIGIN + '/capture-fixture'])

    def test_manual_link_downloads_when_async_programmatic_click_is_blocked(self):
        values = {STATE: '{"entries":[]}', PENDING: '{raw fictional pending'}
        self.open_fixture(values)
        before = self.snapshot()
        self.page.evaluate("""() => {
          HTMLAnchorElement.prototype.click = function () { throw Error('blocked async click'); };
        }""")
        result = self.page.evaluate(SCRIPT)
        self.assertEqual(result['outcome'], 'download-prepared')
        self.assertEqual(self.downloads, [])
        link = self.page.get_by_role('link', name='Скачать частную копию очереди', exact=True)
        self.assertTrue(link.is_visible())
        with self.page.expect_download() as download:
            link.click()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'capture.json'
            download.value.save_as(path)
            data = json.loads(path.read_text())
        self.assertEqual({r['key']: r['raw'] for r in data['records']}, values)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.page.evaluate('window.__captureWrites'), [])
        self.assertEqual(self.requests, [ORIGIN + '/capture-fixture'])

    def test_wrong_origin_refuses_before_any_storage_read_or_download(self):
        self.open_fixture({STATE: 'fictional', SESSION: 'secret'}, origin='https://example.invalid')
        before = self.snapshot()
        self.assertEqual(self.page.evaluate(SCRIPT), {'outcome': 'blocked', 'reason': 'wrong-origin'})
        self.assertEqual(self.page.evaluate('window.__captureReads'), [])
        self.assertEqual(self.page.evaluate('window.__captureWrites'), [])
        self.assertEqual(self.downloads, [])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.requests, ['https://example.invalid/capture-fixture'])

    def test_denied_allowed_value_fails_without_partial_download_or_error_content(self):
        self.open_fixture({STATE: 'fictional', PENDING: 'fictional-pending', SESSION: 'secret'})
        before = self.snapshot()
        console = []
        self.page.on('console', lambda message: console.append(message.text))
        self.page.evaluate('''() => {
          const normal = Storage.prototype.getItem;
          Storage.prototype.getItem = function (key) {
            if (key === 'marichevy_state_v10') throw new Error('PRIVATE_STORAGE_ERROR_CONTENT');
            return normal.call(this, key);
          };
        }''')
        self.assertEqual(self.page.evaluate(SCRIPT), {'outcome': 'blocked', 'reason': 'capture-failed'})
        self.assertEqual(self.downloads, [])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.page.evaluate('window.__captureWrites'), [])
        self.assertNotIn('PRIVATE_STORAGE_ERROR_CONTENT', '\n'.join(console))
        self.assertEqual(self.requests, [ORIGIN + '/capture-fixture'])

    def test_concurrent_application_change_is_rejected_without_download(self):
        self.open_fixture({STATE: 'first fictional state', PENDING: 'fictional pending'})
        self.page.evaluate('''() => {
          const normal = crypto.subtle.digest.bind(crypto.subtle);
          crypto.subtle.digest = (...args) => {
            window.__nativeWrite.call(localStorage, 'marichevy_state_v10', 'new fictional application state');
            return normal(...args);
          };
        }''')
        self.assertEqual(self.page.evaluate(SCRIPT),
                         {'outcome': 'blocked', 'reason': 'storage-changed-during-capture'})
        self.assertEqual(self.downloads, [])
        self.assertEqual(self.page.evaluate('window.__captureWrites'), [])
        self.assertEqual(self.snapshot()[STATE], 'new fictional application state')
        self.assertEqual(self.requests, [ORIGIN + '/capture-fixture'])

    def test_no_financial_keys_is_not_reported_as_a_backup(self):
        self.open_fixture({SESSION: 'PRIVATE_SESSION_MUST_NEVER_BE_READ', 'unrelated-secret': 'secret'})
        before = self.snapshot()
        self.assertEqual(self.page.evaluate(SCRIPT), {'outcome': 'blocked', 'reason': 'no-financial-keys'})
        self.assertEqual(self.page.evaluate('window.__captureReads'), [])
        self.assertEqual(self.downloads, [])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.requests, [ORIGIN + '/capture-fixture'])


if __name__ == '__main__':
    unittest.main()
