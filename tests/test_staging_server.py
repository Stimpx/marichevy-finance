"""The local preview must never enable a production connection or expose Git."""
from http.server import ThreadingHTTPServer
import importlib.util
from pathlib import Path
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


SPEC = importlib.util.spec_from_file_location(
    'serve_staging', Path(__file__).resolve().parents[1] / 'tools' / 'serve_staging.py')
staging = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(staging)


class StagingSafety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class QuietHandler(staging.StagingHandler):
            def log_message(self, *_args):
                pass
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        cls.server.fixture_mode = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_preview_blocks_backend_and_uses_separate_storage(self):
        with urlopen(self.base + '/', timeout=5) as response:
            policy = response.headers['Content-Security-Policy']
            body = response.read().decode()
        for rule in ["connect-src 'none'", "form-action 'none'", "base-uri 'none'", "object-src 'none'"]:
            self.assertIn(rule, policy)
        self.assertNotIn('https:', policy)
        self.assertIn("const CONFIG=Object.freeze({url:'',key:'',household:'local-staging'});", body)
        self.assertIn("state:'marichevy_staging_state_v10'", body)
        self.assertIn("session:'marichevy_staging_session_v10'", body)
        self.assertIn("pending:'marichevy_staging_pending_v10'", body)
        self.assertNotIn('marichevy_state_backup_v44', body)
        self.assertNotIn('marichevy_pre_import_backup_v73', body)

    def test_head_has_same_policy_and_no_body(self):
        with urlopen(Request(self.base + '/', method='HEAD'), timeout=5) as response:
            self.assertIn("connect-src 'none'", response.headers['Content-Security-Policy'])
            self.assertEqual(response.read(), b'')

    def test_private_files_and_mutating_requests_are_denied(self):
        for path in ['/.git/config', '/../.git/config', '/docs/PR1_TESTING.md']:
            with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                urlopen(self.base + path, timeout=5)
            self.assertEqual(error.exception.code, 404)
        for method in ['POST', 'PUT', 'PATCH', 'DELETE']:
            with self.subTest(method=method), self.assertRaises(HTTPError) as error:
                urlopen(Request(self.base + '/', method=method, data=b'fictional'), timeout=5)
            self.assertEqual(error.exception.code, 405)


if __name__ == '__main__':
    unittest.main()
