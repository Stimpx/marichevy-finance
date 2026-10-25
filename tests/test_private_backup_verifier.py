"""Fictional offline backup/capture comparison; no network, secrets or real rows."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import verify_private_backup as verifier

HOUSE = "11111111-1111-4111-8111-111111111111"
USER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER = "22222222-2222-4222-8222-222222222222"
PROJECT = "abcdefghijklmnopqrst"
MARKER = "PRIVATE_HISTORY_MUST_NOT_APPEAR"


def state():
    return {"entries": [{"id": "entry", "type": "expense", "amount": 1250.5,
                         "date": "2026-10-23", "installmentId": "plan", "installmentPartId": "part",
                         "comment": MARKER, "unknown": {"keep": [None, True, {"x": 3}]}}],
            "goals": [{"id": "goal", "target": "12.30", "deposits": [{"amount": "0.10", "date": "2025-01-01"}]}],
            "birthdays": [{"id": "birthday", "date": "1990-01-01"}],
            "boardItems": [{"id": "board", "text": MARKER}], "chores": [{"id": "chore"}],
            "installments": [{"id": "plan", "amount": 1250.5,
                              "parts": [{"id": "part", "amount": 1250.5, "date": "2026-10-23"}],
                              "links": {"part": "entry"}, "futurePlanField": {"preserve": True}}],
            "deletedEntries": {"deleted-entry": "2020-01-01T00:00:00Z"},
            "deletedGoals": ["deleted-goal"], "deletedChores": {}, "deletedBirthdays": {},
            "deletedBoardItems": {}, "deletedInstallments": {},
            "settings": {"futureField": {"nested": [1, 2, None]}},
            "intelligence": {"budgets": [{"id": "budget", "amount": 100}],
                             "recurring": [{"id": "recurring", "amount": 12.34}],
                             "accounts": [{"id": "account", "amount": -2.01}],
                             "deleted": {"budgets": {"old": "2020-01-01"}, "accounts": {}, "recurring": {}},
                             "unknown": {"nested": MARKER}},
            "futureCollection": [{"anything": MARKER}]}


def tables(data):
    return {"households": [{"id": HOUSE, "name": MARKER, "created_at": "2020-01-01T00:00:00Z"}],
            "household_members": [{"household_id": HOUSE, "user_id": USER,
                                   "role": "owner", "created_at": "2020-01-01T00:00:00Z"}],
            "family_state": [{"household_id": HOUSE, "data": data,
                              "updated_at": "2026-10-23T00:00:00Z", "updated_by": USER}],
            "family_chore_deliveries": [{"household_id": HOUSE, "chore_id": "chore",
                                         "due_date": "2026-10-23", "chat_id": MARKER,
                                         "status": "fixture-status", "attempts": 1,
                                         "last_attempt_at": None, "sent_at": None,
                                         "telegram_message_id": None, "last_error": None,
                                         "created_at": "2020-01-01T00:00:00Z"}]}


def snapshot(data):
    raw = json.dumps(tables(data), ensure_ascii=True)
    return {"format": "marichevy-private-server-backup-v1", "project_ref": PROJECT,
            "configured_household": HOUSE, "configured_household_count": 1,
            "database_timezone": "UTC",
            "read_only": True, "captured_at_utc": "2026-10-23T00:00:00Z",
            "query_sha256": "0" * 64, "snapshot_json": raw,
            "snapshot_json_sha256": hashlib.sha256(raw.encode()).hexdigest()}


def captured(values):
    records = []
    for key, raw in values.items():
        utf16, utf8 = raw.encode("utf-16-le", errors="surrogatepass"), verifier.utf8_js(raw)
        records.append({"key": key, "raw": raw, "utf16_code_units": len(utf16) // 2,
                        "utf8_bytes": len(utf8), "sha256_utf8": hashlib.sha256(utf8).hexdigest(),
                        "sha256_utf16le": hashlib.sha256(utf16).hexdigest()})
    return {"format": "marichevy-local-queue-capture-v1", "origin": verifier.ORIGIN,
            "device_clock_verified": False, "session_included": False, "storage_modified": False,
            "captured_at_device_utc": "2099-01-01T00:00:00Z", "key_count": len(records), "records": records}


class PrivateBackupVerifier(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.data = state()
        self.write("server.json", snapshot(self.data))
        self.write("restored.json", snapshot(self.data))
        for n in (1, 2):
            self.write(f"export{n}.json", self.data)
            self.write(f"capture{n}.json", captured({verifier.STATE: json.dumps(self.data)}))
        self.plan = {"format": "marichevy-private-restore-plan-v1", "project_ref": PROJECT,
                     "household_id": HOUSE, "server_file": "server.json", "restored_file": "restored.json",
                     "devices": [{"scope_verified_by_owner": True, "export_file": f"export{n}.json",
                                  "capture_file": f"capture{n}.json"} for n in (1, 2)]}
        self.write("plan.json", self.plan)

    def test_ui_memory_divergence_cannot_be_ignored(self):
        value = self.read("capture1.json")
        memory = copy.deepcopy(self.data)
        memory["entries"][0]["amount"] = 999
        value["memory_state_json"] = json.dumps(memory)
        self.write("capture1.json", value)
        self.assertEqual(self.verify()["outcome"], "review_required")

    def write(self, name, value):
        (self.root / name).write_text(json.dumps(value, ensure_ascii=True), encoding="utf-8")

    def read(self, name):
        return json.loads((self.root / name).read_text())

    def verify(self):
        return verifier.verify(self.root / "plan.json", allow_private_input=True)

    def alter_restored(self, change):
        value = self.read("restored.json")
        content = json.loads(value["snapshot_json"])
        change(content)
        value["snapshot_json"] = json.dumps(content)
        value["snapshot_json_sha256"] = hashlib.sha256(value["snapshot_json"].encode()).hexdigest()
        self.write("restored.json", value)

    def test_complete_private_roundtrip_matches_without_changing_or_disclosing_inputs(self):
        before = {path: path.read_bytes() for path in self.root.iterdir()}
        report = self.verify()
        self.assertEqual(report["outcome"], "passed", report)
        self.assertFalse(report["restore_execution_verified"])
        self.assertFalse(report["release_authorized"])
        serialized = json.dumps(report)
        for secret in (MARKER, HOUSE, USER, "1250.5", "2026-10-23", "deleted-entry", str(self.root)):
            self.assertNotIn(secret, serialized)
        self.assertEqual({path: path.read_bytes() for path in self.root.iterdir()}, before)

    def test_raw_pending_divergence_and_same_content_pending_both_require_review(self):
        for modified in (False, True):
            data = copy.deepcopy(self.data)
            if modified:
                data["entries"][0]["amount"] = 99
            self.write("capture1.json", captured({verifier.STATE: json.dumps(self.data), verifier.PENDING: json.dumps(data)}))
            report = self.verify()
            self.assertEqual(report["outcome"], "review_required")
            self.assertIn("pending-acknowledgement-required", report["issues"])
            self.assertEqual("divergent-active-values" in report["issues"], modified)

    def test_unknown_nested_fields_tombstones_ids_and_cents_are_compared_exactly(self):
        changes = [lambda t: t["family_state"][0]["data"]["futureCollection"].clear(),
                   lambda t: t["family_state"][0]["data"]["deletedEntries"].clear(),
                   lambda t: t["family_state"][0]["data"]["entries"][0].update(amount=1250.51),
                   lambda t: t["family_state"][0]["data"]["entries"][0].update(id="another-id"),
                   lambda t: t["family_state"][0]["data"]["settings"]["futureField"].update(nested=[1, 2, False])]
        for change in changes:
            self.write("restored.json", snapshot(self.data))
            self.alter_restored(change)
            report = self.verify()
            self.assertEqual(report["outcome"], "review_required")
            self.assertFalse(report["checks"]["all_server_rows_and_unknown_fields_restored"])

    def test_foreign_family_project_or_cloud_base_fails(self):
        value = self.read("server.json")
        value["configured_household"] = OTHER
        self.write("server.json", value)
        self.assertIn("foreign-family-or-project", self.verify()["issues"])
        self.write("server.json", snapshot(self.data))
        self.write("capture1.json", captured({verifier.STATE: json.dumps(self.data),
                                              verifier.BASE: json.dumps({"household": OTHER, "url": "https://" + PROJECT + ".supabase.co", "data": self.data})}))
        self.assertEqual(self.verify()["outcome"], "failed")

    def test_corrupt_json_and_duplicate_keys_fail_without_raw_error_output(self):
        for raw in ('{"x":', '{"entries":[],"settings":{},"settings":{"secret":"' + MARKER + '"}}', '{"amount":NaN}'):
            (self.root / "export1.json").write_text(raw)
            report = self.verify()
            self.assertEqual(report["outcome"], "failed")
            self.assertNotIn(MARKER, json.dumps(report))

    def test_tampered_snapshot_or_capture_hash_fails(self):
        value = self.read("server.json")
        value["snapshot_json"] += " "
        self.write("server.json", value)
        self.assertIn("snapshot-json-integrity-mismatch", self.verify()["issues"])
        self.write("server.json", snapshot(self.data))
        value = self.read("capture1.json")
        value["records"][0]["raw"] += " "
        self.write("capture1.json", value)
        self.assertIn("raw-capture-integrity-mismatch", self.verify()["issues"])

    def test_boolean_scope_count_or_capture_lengths_are_not_numeric_metadata(self):
        value = snapshot(self.data)
        value["configured_household_count"] = True
        self.write("server.json", value)
        self.assertIn("invalid-snapshot-scope-count", self.verify()["issues"])
        self.write("server.json", snapshot(self.data))
        value = captured({verifier.STATE: json.dumps(self.data)})
        value["key_count"] = True
        self.write("capture1.json", value)
        self.assertIn("invalid-capture-records", self.verify()["issues"])
        for field in ("utf8_bytes", "utf16_code_units"):
            value = captured({verifier.STATE: json.dumps(self.data), verifier.PENDING + "_corrupt_v1": "A"})
            value["records"][1][field] = True
            self.write("capture1.json", value)
            self.assertIn("raw-capture-integrity-mismatch", self.verify()["issues"])

    def test_lone_surrogate_damage_is_preserved_but_not_accepted_as_healthy_queue(self):
        self.write("capture1.json", captured({verifier.STATE: json.dumps(self.data), verifier.PENDING + "_corrupt_v1": "left\ud800right"}))
        report = self.verify()
        self.assertEqual(report["outcome"], "review_required")
        self.assertIn("corrupt-preserved-values", report["issues"])
        value = self.read("capture1.json")
        value["records"][1]["raw"] = "left\ufffdright"
        self.write("capture1.json", value)
        self.assertIn("raw-capture-integrity-mismatch", self.verify()["issues"])

    def test_valid_json_quarantine_is_preserved_and_still_requires_review(self):
        old_variant = copy.deepcopy(self.data)
        old_variant["entries"][0]["amount"] = 7
        self.write("capture1.json", captured({verifier.STATE: json.dumps(self.data), verifier.PENDING + "_corrupt_v1": json.dumps(old_variant)}))
        report = self.verify()
        self.assertEqual(report["outcome"], "review_required")
        self.assertIn("corrupt-preserved-values", report["issues"])

    def test_conflict_packet_is_retained_and_never_resolved_by_wrong_clock(self):
        packet = {"format": "family-sync-conflict-v1", "household": HOUSE,
                  "local": self.data, "cloud": {"entries": [], "settings": {}}}
        self.write("capture1.json", captured({verifier.STATE: json.dumps(self.data), verifier.CONFLICT: json.dumps(packet)}))
        report = self.verify()
        self.assertEqual(report["outcome"], "review_required")
        self.assertIn("conflict-packets", report["issues"])

    def test_financial_subcent_period_and_link_damage_requires_review(self):
        for change, code in [(lambda d: d["entries"][0].update(amount="0.001"), "invalid-cent-values"),
                             (lambda d: d["entries"][0].update(date="2026-02-30"), "invalid-period-values"),
                             (lambda d: d["installments"][0].update(links={"part": "missing"}), "broken-known-links")]:
            changed = copy.deepcopy(self.data)
            change(changed)
            self.write("server.json", snapshot(changed))
            self.write("restored.json", snapshot(changed))
            report = self.verify()
            self.assertEqual(report["outcome"], "review_required")
            self.assertIn(code, report["issues"])

    def test_whole_json_number_comparison_is_decimal_exact_and_bool_distinct(self):
        self.assertTrue(verifier.equal(verifier.parse('{"n":123456789012345678901234567890.123456789}'), verifier.parse('{"n":123456789012345678901234567890.123456789}')))
        self.assertFalse(verifier.equal(verifier.parse('{"n":123456789012345678901234567890.123456789}'), verifier.parse('{"n":123456789012345678901234567890.123456788}')))
        self.assertFalse(verifier.equal(verifier.parse('{"n":true}'), verifier.parse('{"n":1}')))
        self.assertTrue(verifier.cents(verifier.number("1.2300")))
        self.assertFalse(verifier.cents(verifier.number("1.2301")))
        self.assertTrue(verifier.cents(verifier.number("0.00000000000000000000")))

    def test_legacy_duplicate_ids_are_preserved_and_flagged_without_losing_rows(self):
        duplicate = copy.deepcopy(self.data["entries"][0])
        duplicate["comment"] = "another legacy variant"
        self.data["entries"].append(duplicate)
        self.write("server.json", snapshot(self.data))
        self.write("restored.json", snapshot(self.data))
        for n in (1, 2):
            self.write(f"export{n}.json", self.data)
            self.write(f"capture{n}.json", captured({verifier.STATE: json.dumps(self.data)}))
        report = self.verify()
        self.assertEqual(report["outcome"], "review_required")
        self.assertTrue(report["checks"]["all_server_rows_and_unknown_fields_restored"])
        self.assertIn("ambiguous-duplicate-ids", report["issues"])

    def test_private_files_are_not_read_without_explicit_input_flag(self):
        report = verifier.verify(self.root / "missing-private-file.json")
        self.assertEqual(report["issues"], ["private-input-not-authorized"])

    def test_wrong_scope_attestation_missing_device_or_incomplete_table_coverage_stops_acceptance(self):
        self.plan["devices"][0]["scope_verified_by_owner"] = False
        self.write("plan.json", self.plan)
        self.assertEqual(self.verify()["outcome"], "review_required")
        self.plan["devices"] = self.plan["devices"][:1]
        self.write("plan.json", self.plan)
        self.assertIn("both-device-bundles-required", self.verify()["issues"])
        self.plan["devices"] = [{"scope_verified_by_owner": True, "export_file": f"export{n}.json",
                                 "capture_file": f"capture{n}.json"} for n in (1, 2)]
        self.write("plan.json", self.plan)
        self.alter_restored(lambda t: t.pop("family_chore_deliveries"))
        self.assertIn("incomplete-server-table-coverage", self.verify()["issues"])

    def test_session_key_and_foreign_origin_are_refused(self):
        self.write("capture1.json", captured({"marichevy_session_v10": MARKER}))
        self.assertIn("unexpected-or-duplicate-storage-key", self.verify()["issues"])
        value = captured({verifier.STATE: json.dumps(self.data)})
        value["origin"] = "https://other.invalid"
        self.write("capture1.json", value)
        self.assertIn("invalid-capture-format-or-origin", self.verify()["issues"])

    def test_symlink_path_escape_reused_file_and_size_limits_fail(self):
        self.plan["restored_file"] = "server.json"
        self.write("plan.json", self.plan)
        self.assertIn("input-file-reused", self.verify()["issues"])
        self.plan["restored_file"] = "../outside.json"
        self.write("plan.json", self.plan)
        self.assertIn("path-outside-private-folder", self.verify()["issues"])
        self.plan["restored_file"] = "linked.json"
        (self.root / "linked.json").symlink_to(self.root / "restored.json")
        self.write("plan.json", self.plan)
        self.assertIn("symlink-not-allowed", self.verify()["issues"])
        self.plan["restored_file"] = "restored.json"
        self.write("plan.json", self.plan)
        with mock.patch.object(verifier, "MAX_FILE", 16):
            self.assertIn("invalid-or-oversized-input-file", self.verify()["issues"])

    def test_cli_report_is_safe_and_original_files_unchanged(self):
        result = subprocess.run([sys.executable, str(Path(verifier.__file__)), "--manifest", str(self.root / "plan.json"), "--allow-private-input"],
                                text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["outcome"], "passed")
        self.assertNotIn(MARKER, result.stdout + result.stderr)

    def test_invalid_cli_arguments_do_not_echo_sensitive_values(self):
        result = subprocess.run([sys.executable, str(Path(verifier.__file__)), "--unexpected", MARKER],
                                text=True, capture_output=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "invalid-command-arguments\n")
        self.assertNotIn(MARKER, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
