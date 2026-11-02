"""Real browser continuation checks, using only fictional private files.

The managed worker blocks file://. A GET-only loopback server exposes exactly
the rendered code-only page; selected fixture files enter through File API.
This does not claim native Windows/file:// acceptance or execute activation SQL.
"""
from __future__ import annotations

import base64
import copy
import csv
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
from pathlib import Path
import re
import shutil
import tempfile
import threading
import unittest
import zipfile

from playwright.sync_api import sync_playwright

from tests import test_sql_editor_activation as postgres_harness

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "activation_checkpoint_builder", ROOT / "tools/build_activation_checkpoint_page.py")
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)
MARKER = "FICTIONAL_PRIVATE_HISTORY_MUST_NOT_APPEAR"
HOUSE = "11111111-1111-4111-8111-111111111111"
PROJECT = "kqndxecziamypdjpxhyq"
PIN = "7fc72248cd65e790dfec12abc4da1811ae2146f414b8be46cd5cd7ae5244e248"
SLOTS = ("server", "mac-export", "mac-capture", "iphone-export", "iphone-capture",
         "windows-export", "windows-capture")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf8")


def downloaded_csv(value):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["backup_json"])
    writer.writerow([value])
    return stream.getvalue().encode("utf8")


def fixture():
    # Deliberately preserve JSON numbers JS Number cannot roundtrip. The page
    # must treat the complete snapshot as opaque text, never finance JSON.
    snapshot = ('{"family_state":[{"data":{"private":"' + MARKER
                + '<script>window.LEAKED=1</script>","large":9007199254740993,'
                '"small":0.0000000001000}}],"households":[],"household_members":[],'
                '"family_chore_deliveries":[]}')
    old = {"format": "marichevy-private-server-backup-v1", "read_only": True,
           "project_ref": PROJECT, "configured_household": HOUSE,
           "configured_household_count": 1, "database_timezone": "UTC",
           "snapshot_json": snapshot, "snapshot_json_sha256": digest(snapshot.encode()),
           "database_name": "postgres", "database_role": "postgres",
           "transaction_read_only": "off"}
    old_json = encoded(old).decode()
    files = {"server.bin": downloaded_csv(old_json)}
    for slot in SLOTS[1:]:
        files[slot + ".json"] = encoded({"fictional": MARKER, "slot": slot})
    report = {"format": "marichevy-private-local-verification-v1", "outcome": "passed",
              "phase": "device-comparison-and-optional-local-restore", "issues": [],
              "network_used": False, "inputs_modified": False,
              "restore_execution_verified": True, "release_authorized": False,
              "checks": {"input_scope_and_capture_hashes_valid": True,
                         "device_scope_is_owner_attestation": True,
                         "period_cent_and_known_links_valid": True,
                         "device_variants_match_server": True},
              "restore": {"outcome": "passed", "restore_execution_verified": True},
              "source_files": [{"slot": slot, "bytes": len(files[slot + (".bin" if slot == "server" else ".json")]),
                                "sha256": digest(files[slot + (".bin" if slot == "server" else ".json")])}
                               for slot in SLOTS]}
    files["verification-report.json"] = encoded(report)
    restored = {**old, "source_backup_sha256": digest(old_json.encode()),
                "restore_scope": "offline-four-app-tables-auth-id-stubs",
                "engine": "pglite-0.3.14-postgresql-17.5-wasm-in-memory"}
    files["server-restored-PRIVATE.json"] = encoded(restored)
    receipt = {"format": "marichevy-private-local-restore-receipt-v1", "outcome": "passed",
               "engine": restored["engine"], "outcome_scope": "four-app-table-restore-only",
               "restore_execution_verified": True, "release_authorized": False,
               "network_used": False, "production_changed": False,
               "original_files_modified": False, "four_table_roundtrip_verified": True,
               "foreign_keys_and_not_null_restored": True, "local_clone_rls_verified": True,
               "minimal_auth_user_stubs_only": True, "supabase_auth_restored": False,
               "supabase_platform_restored": False, "source_unknown_delivery_checks_reproduced": False,
               "migration_rehearsal_preserved_original_columns": True,
               "migration_rehearsal_local_cas_verified": True,
               "source_file_sha256": digest(old_json.encode()),
               "source_digest_scope": "decoded-backup-json-utf8",
               "source_snapshot_json_sha256": old["snapshot_json_sha256"],
               "readback_file_sha256": digest(files["server-restored-PRIVATE.json"]),
               "readback_snapshot_json_sha256": old["snapshot_json_sha256"],
               "app_data_review_required": False, "source_scope_is_owner_attestation": True}
    files["server-restore-receipt-PRIVATE.json"] = encoded(receipt)
    plan = {"format": "marichevy-sync-activation-plan-v1", "activation_sql_sha256": PIN,
            "expected_database": "postgres", "household_id": HOUSE,
            "expected_revision": 0, "expected_data_sha256": "a" * 64}
    fresh = {**old, "activation_checkpoint": plan, "export_method": "sql-editor-select-v1",
             "query_sha256": "b" * 64}
    return files, fresh


class ActivationCheckpointPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("chromium"):
            raise unittest.SkipTest("Chromium is required")
        cls.temp = tempfile.TemporaryDirectory(prefix="fictional-checkpoint-browser-")
        cls.root = Path(cls.temp.name)
        cls.archive = cls.root / "checkpoint.zip"
        cls.report = BUILDER.build(output=cls.archive)
        with zipfile.ZipFile(cls.archive) as archive:
            names = archive.namelist()
            assert len(names) == 1 and names[0].endswith(".html")
            cls.html = archive.read(names[0])
        html = cls.html

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != "/checkpoint.html":
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)

            def log_message(self, *_args):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = "http://127.0.0.1:" + str(cls.server.server_port) + "/checkpoint.html"
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path="/usr/bin/chromium", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.temp.cleanup()

    def setUp(self):
        self.case = tempfile.TemporaryDirectory(prefix="fictional-checkpoint-inputs-")
        self.case_root = Path(self.case.name)
        self.folder = self.case_root / "PRIVATE-verification-fictional"
        self.folder.mkdir()
        self.fresh_file = self.case_root / "fresh.csv"
        self.files, self.fresh = fixture()
        self.page = self.browser.new_page(accept_downloads=True)
        self.network, self.errors = [], []
        self.page.on("request", lambda request: self.network.append(request.url)
                     if request.url != self.url else None)
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.goto(self.url)

    def tearDown(self):
        self.assertEqual(self.network, [])
        self.assertEqual(self.errors, [])
        self.page.close()
        self.case.cleanup()

    def select(self, *, fresh_raw=None):
        for name, raw in self.files.items():
            (self.folder / name).write_bytes(raw)
        self.fresh_file.write_bytes(fresh_raw if fresh_raw is not None
                                    else downloaded_csv(encoded(self.fresh).decode()))
        self.page.locator("#folder").set_input_files(str(self.folder))
        self.page.locator("#fresh").set_input_files(str(self.fresh_file))

    def run_check(self):
        self.page.locator("#check").click()
        self.page.wait_for_function("() => /Result: (prepared-not-executed|failed|review_required)/.test(document.getElementById('codes').value)")
        text = self.page.locator("#codes").input_value()
        self.assertNotIn(MARKER, text)
        self.assertNotIn(HOUSE, text)
        self.assertNotIn(MARKER, self.page.locator("body").inner_text())
        self.assertIsNone(self.page.evaluate("window.LEAKED"))
        return text

    def download(self, kind):
        with self.page.expect_download() as event:
            self.page.locator('[data-download="' + kind + '"]').click()
        return Path(event.value.path()).read_text()

    def test_complete_file_bindings_prepare_private_sql_and_opaque_numbers(self):
        self.select()
        self.assertIn("prepared-not-executed", self.run_check())
        sql = self.download("activation")
        body = (ROOT / "server/activate_household_api.sql").read_text().rstrip()
        self.assertIn(body, sql)
        self.assertRegex(sql.strip().splitlines()[-1], r"^EXECUTE marichevy_activation_[a-f0-9]{24}\(")
        self.assertNotIn("DEALLOCATE", sql)
        self.assertNotIn(MARKER, sql)
        self.assertEqual(json.loads(self.download("plan")), self.fresh["activation_checkpoint"])
        self.assertRegex(self.download("cleanup").strip().splitlines()[-1],
                         r"^DEALLOCATE marichevy_activation_[a-f0-9]{24};$")

    def test_browser_generated_script_executes_offline_and_returns_actual_pg_receipt(self):
        # File bindings and opaque snapshot equality are checked separately.
        # This bridges the actual browser-generated SQL to the existing
        # fictional PG fixture, rather than claiming string matching executes SQL.
        PostgresHarness = postgres_harness.SqlEditorActivation
        PostgresHarness.node = shutil.which("node")
        if not PostgresHarness.node:
            self.skipTest("Node is required for real PostgreSQL WASM")
        metadata = PostgresHarness.run_engine({"mode": "describe"})
        self.assertEqual(metadata["database"], "template1")
        self.fresh["activation_checkpoint"]["expected_data_sha256"] = metadata["data_hash"]
        self.select()
        self.assertIn("prepared-not-executed", self.run_check())
        sql, cleanup = self.download("activation"), self.download("cleanup")
        # The unmodified page artifact correctly refuses this fixture's
        # template1 database. It is explicitly production-bound to postgres.
        refused = PostgresHarness.run_engine({
            "mode": "apply", "activation": sql, "cleanup": cleanup, "success": False,
        })
        self.assertEqual(refused["case"], "atomic-refusal")
        self.assertTrue(refused["source_unchanged"])
        # Change only the first EXECUTE bound value in a separate fictional
        # test copy to exercise syntax/receipt on the actual local DB. The
        # downloaded artifact, page guard and pinned SQL body remain unchanged.
        pattern = r"(^EXECUTE marichevy_activation_[a-f0-9]{24}\()E'postgres'"
        adapted, replaced = re.subn(
            pattern, lambda match: match.group(1) + postgres_harness.BUILDER.literal(metadata["database"]),
            sql, flags=re.M)
        self.assertEqual(replaced, 1)
        self.assertEqual(digest((ROOT / "server/activate_household_api.sql").read_bytes()), PIN)
        result = PostgresHarness.run_engine({
            "mode": "apply", "activation": adapted, "cleanup": cleanup, "success": True,
        })
        self.assertEqual(result["case"], "activation-receipt-last")
        self.assertTrue(result["receipt_columns_visible"])
        self.assertTrue(result["source_unchanged"])
        self.assertTrue(result["cleanup_separate"])
        self.assertFalse(result["production_changed"])

    def test_different_snapshot_refuses_even_when_json_numbers_equivalent(self):
        self.fresh["snapshot_json"] = self.fresh["snapshot_json"].replace("0.0000000001000", "0.0000000001")
        self.fresh["snapshot_json_sha256"] = digest(self.fresh["snapshot_json"].encode())
        self.select()
        self.assertIn("review_required", self.run_check())
        self.assertFalse(self.page.locator('[data-download="activation"]').is_visible())

    def test_changed_device_input_invalidates_saved_source_binding(self):
        self.files["mac-export.json"] += b" "
        self.select()
        self.assertNotIn("prepared-not-executed", self.run_check())

    def test_changed_readback_invalidates_restore_receipt(self):
        self.files["server-restored-PRIVATE.json"] += b" "
        self.select()
        self.assertNotIn("prepared-not-executed", self.run_check())

    def test_unverified_restore_and_wrong_checkpoint_are_rejected(self):
        receipt = json.loads(self.files["server-restore-receipt-PRIVATE.json"])
        receipt["migration_rehearsal_local_cas_verified"] = False
        self.files["server-restore-receipt-PRIVATE.json"] = encoded(receipt)
        self.select()
        self.assertNotIn("prepared-not-executed", self.run_check())
        self.files, self.fresh = fixture()
        report = json.loads(self.files["verification-report.json"])
        report["checks"]["device_variants_match_server"] = False
        self.files["verification-report.json"] = encoded(report)
        self.select()
        self.assertNotIn("prepared-not-executed", self.run_check())
        self.files, self.fresh = fixture()
        self.fresh["activation_checkpoint"]["expected_revision"] = 1
        self.select()
        self.assertNotIn("prepared-not-executed", self.run_check())

    def test_duplicate_wrapper_keys_are_rejected_without_leaking_values(self):
        raw = encoded(self.fresh).decode().replace('"read_only": true,', '"read_only": true, "read_only": true,')
        self.select(fresh_raw=downloaded_csv(raw))
        self.assertNotIn("prepared-not-executed", self.run_check())

    def test_unknown_or_nested_leaf_is_rejected_before_body_read(self):
        self.files["unknown-private.json"] = encoded({"private": MARKER})
        self.page.evaluate("""() => {
          window.readAttempts=0; const original=Blob.prototype.arrayBuffer;
          Blob.prototype.arrayBuffer=function(){window.readAttempts++;return original.call(this)};
        }""")
        self.select()
        self.assertNotIn("prepared-not-executed", self.run_check())
        self.assertEqual(self.page.evaluate("window.readAttempts"), 0)

    def test_file_size_is_guarded_before_body_read(self):
        self.page.evaluate("""() => {
          window.readAttempts=0; const original=Blob.prototype.arrayBuffer;
          Blob.prototype.arrayBuffer=function(){window.readAttempts++;return original.call(this)};
          Object.defineProperty(File.prototype,'size',{get(){return 33*1024*1024}});
        }""")
        self.select()
        self.assertNotIn("prepared-not-executed", self.run_check())
        self.assertEqual(self.page.evaluate("window.readAttempts"), 0)

    def test_new_selection_clears_success_and_late_old_read_cannot_restore_it(self):
        self.select()
        self.assertIn("prepared-not-executed", self.run_check())
        self.page.evaluate("""() => {
          const original=Blob.prototype.arrayBuffer;
          Blob.prototype.arrayBuffer=async function(){await new Promise(r=>setTimeout(r,100));return original.call(this)};
        }""")
        self.page.locator("#check").click()
        self.page.locator("#fresh").set_input_files([])
        self.page.wait_for_timeout(1400)
        self.assertNotIn("prepared-not-executed", self.page.locator("#codes").input_value())
        self.assertFalse(self.page.locator('[data-download="activation"]').is_visible())

    def test_exact_inline_csp_code_only_archive_and_no_overwrite(self):
        raw = self.html.decode()
        self.assertFalse(self.page.locator("#folder").is_visible())
        self.assertFalse(self.page.locator("#fresh").is_visible())
        self.assertTrue(self.page.locator("#choose-folder").is_visible())
        self.assertTrue(self.page.locator("#choose-fresh").is_visible())
        for directive in ("default-src 'none'", "connect-src 'none'", "form-action 'none'", "worker-src 'none'"):
            self.assertIn(directive, raw)
        for tag in ("script", "style"):
            body = re.search(r"<" + tag + r">([\s\S]*?)</" + tag + ">", raw).group(1)
            pin = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
            self.assertIn("'sha256-" + pin + "'", raw)
        self.assertNotIn(MARKER, raw)
        self.assertNotIn(HOUSE, raw)
        with self.assertRaises((ValueError, FileExistsError)):
            BUILDER.build(output=self.archive)


if __name__ == "__main__":
    unittest.main()
