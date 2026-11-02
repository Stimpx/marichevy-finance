"""Real browser checks with fictional files; no owner data is read.

The managed worker blocks file:// navigation. A GET-only loopback handler
serves exactly the code-only HTML, never fixture files or owner inputs. These
checks do not establish native Windows file:// acceptance.
"""
from __future__ import annotations

import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import re
import shutil
import tempfile
import threading
import unittest
import zipfile

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "capture_header_builder", ROOT / "tools/build_capture_header_check.py")
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)
MARKER = "FICTIONAL_PRIVATE_HISTORY_MUST_NOT_APPEAR"
FORMAT = "marichevy-local-queue-capture-v1"
ORIGIN = "https://finance.marichev.pro"
NAMES = ("mac-capture.json", "iphone-capture.json", "windows-capture.json")


def capture(**changes):
    value = {"format": FORMAT, "origin": ORIGIN,
             "records": [{"key": MARKER, "raw": MARKER + "<script>window.LEAKED=1</script>"}]}
    value.update(changes)
    return value


def selected(name, value):
    raw = value if isinstance(value, bytes) else json.dumps(value).encode()
    return {"name": name, "mimeType": "application/json", "buffer": raw}


class CaptureHeaderCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("chromium"):
            raise unittest.SkipTest("Chromium is required")
        cls.temp = tempfile.TemporaryDirectory(prefix="fictional-header-check-")
        cls.root = Path(cls.temp.name)
        cls.archive = cls.root / "checker.zip"
        cls.report = BUILDER.build(output=cls.archive)
        with zipfile.ZipFile(cls.archive) as archive:
            names = archive.namelist()
            assert len(names) == 1 and names[0].endswith(".html")
            cls.html = cls.root / names[0]
            cls.html.write_bytes(archive.read(names[0]))
        html_bytes = cls.html.read_bytes()
        class CodeOnlyHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != "/checker.html":
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html_bytes)))
                self.end_headers()
                self.wfile.write(html_bytes)
            def log_message(self, *args):
                pass
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), CodeOnlyHandler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.url = "http://127.0.0.1:" + str(cls.server.server_port) + "/checker.html"
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path="/usr/bin/chromium", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=5)
        cls.temp.cleanup()

    def setUp(self):
        self.page = self.browser.new_page()
        self.network = []
        self.errors = []
        self.page.on("request", lambda request: self.network.append(request.url)
                     if request.url != self.url else None)
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.goto(self.url)

    def tearDown(self):
        self.assertEqual(self.network, [], "Header checks must not send network requests")
        self.assertEqual(self.errors, [], "Reader errors must be handled with fixed messages")
        self.page.close()

    def files(self, *values):
        if not values:
            values = (capture(), capture(), capture())
        self.page.locator("#files").set_input_files(
            [selected(name, value) for name, value in zip(NAMES, values)])

    def codes(self, contains):
        self.page.wait_for_function(
            "(text) => document.getElementById('codes').value.includes(text)", arg=contains)
        output = self.page.locator("#codes").input_value()
        self.assertNotIn(MARKER, output)
        self.assertNotIn(MARKER, self.page.locator("body").inner_text())
        self.assertIsNone(self.page.evaluate("window.LEAKED"))
        return output

    def test_expected_headers_only_and_no_record_rendering_or_network(self):
        self.files()
        output = self.codes("windows:")
        for slot in ("mac", "iphone", "windows"):
            self.assertRegex(output, slot + r":.*format=expected.*origin=expected.*ordinary=no")
        self.assertNotIn(ORIGIN, output)
        self.assertNotIn(FORMAT, output)
        self.assertTrue(self.page.locator("#codes").get_attribute("readonly") is not None)

    def test_identifies_ordinary_wrong_origin_and_wrong_format_without_raw_values(self):
        self.files({"entries": [], "settings": {"private": MARKER}},
                   capture(origin="https://" + MARKER + ".invalid/private"),
                   capture(format=MARKER))
        output = self.codes("windows:")
        self.assertRegex(output, r"mac:.*format=missing.*origin=missing.*ordinary=yes")
        self.assertRegex(output, r"iphone:.*format=expected.*origin=other")
        self.assertRegex(output, r"windows:.*format=other.*origin=expected")

    def test_bad_field_types_invalid_json_and_nonobject_root_have_fixed_codes(self):
        self.files(capture(format={"private": MARKER}, origin=[MARKER]), b"{\xff}", [])
        output = self.codes("windows:")
        self.assertRegex(output, r"mac:.*format=type-other.*origin=type-other")
        self.assertIn("iphone: json=unreadable", output)
        self.assertIn("windows: root=other", output)

    def test_utf8_and_utf16_bom_headers_are_classified_without_normalizing_sources(self):
        raw = json.dumps(capture(), ensure_ascii=False)
        self.files(b"\xef\xbb\xbf" + raw.encode(), b"\xff\xfe" + raw.encode("utf-16le"),
                   b"\xfe\xff" + raw.encode("utf-16be"))
        output = self.codes("windows:")
        self.assertEqual(output.count("format=expected"), 3)
        self.assertEqual(output.count("origin=expected"), 3)

    def test_unknown_filename_and_duplicate_clear_previous_results(self):
        self.files()
        self.codes("windows:")
        self.page.locator("#files").set_input_files(
            [selected(MARKER + ".json", capture())])
        output = self.codes("selection=wrong-files")
        self.assertNotIn("mac:", output)
        self.page.locator("#files").set_input_files(
            [selected(NAMES[0], capture()), selected(NAMES[0], capture()), selected(NAMES[2], capture())])
        self.codes("selection=duplicate")

    def test_file_size_guard_runs_before_any_body_read(self):
        self.page.evaluate("""() => {
          window.readAttempts = 0;
          const original = Blob.prototype.arrayBuffer;
          Blob.prototype.arrayBuffer = function() {window.readAttempts++; return original.call(this)};
          Object.defineProperty(File.prototype, 'size', {get() {return 33 * 1024 * 1024}});
        }""")
        self.files()
        self.codes("selection=size-limit")
        self.assertEqual(self.page.evaluate("window.readAttempts"), 0)

    def test_new_selection_during_read_cannot_reintroduce_previous_result(self):
        self.page.evaluate("""() => {
          const original = Blob.prototype.arrayBuffer;
          Blob.prototype.arrayBuffer = async function() {
            await new Promise(resolve => setTimeout(resolve, 150));
            return original.call(this);
          };
        }""")
        self.files()
        self.page.locator("#files").set_input_files([selected("unrecognized.json", capture())])
        self.codes("selection=wrong-files")
        self.page.wait_for_timeout(650)
        self.assertNotIn("mac:", self.page.locator("#codes").input_value())
        self.assertTrue(self.page.locator("#choose").is_enabled())

    def test_standalone_archive_exact_inline_hashes_and_exclusive_output(self):
        raw = self.html.read_text()
        self.assertIn("default-src 'none'", raw)
        self.assertIn("connect-src 'none'", raw)
        for tag in ("script", "style"):
            body = re.search(r"<" + tag + r"(?:\s[^>]*)?>([\s\S]*?)</" + tag + ">", raw).group(1)
            pin = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
            self.assertIn("'sha256-" + pin + "'", raw)
        with self.assertRaises((ValueError, FileExistsError)):
            BUILDER.build(output=self.archive)
        with zipfile.ZipFile(self.archive) as archive:
            self.assertEqual(archive.namelist(), [self.html.name])


if __name__ == "__main__":
    unittest.main()
