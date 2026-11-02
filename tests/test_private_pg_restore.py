"""Private restore machinery using fictional rows and offline cached PostgreSQL."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import restore_private_backup as restore
import verify_private_backup as verify
import test_private_backup_verifier as fixtures


def canonical_snapshot(data=None):
    wrapper = fixtures.snapshot(data or fixtures.state())
    # pg_catalog to_jsonb timestamptz emits offset notation, not the equivalent Z.
    tables = json.loads(wrapper["snapshot_json"])
    for rows in tables.values():
        for row in rows:
            for key in ("created_at", "updated_at", "last_attempt_at", "sent_at"):
                if isinstance(row.get(key), str) and row[key].endswith("Z"):
                    row[key] = row[key][:-1] + "+00:00"
    wrapper["snapshot_json"] = json.dumps(tables)
    wrapper["snapshot_json_sha256"] = hashlib.sha256(wrapper["snapshot_json"].encode()).hexdigest()
    return wrapper


class PrivatePgRestore(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / "server-PRIVATE.json"
        self.output = self.root / "restored-PRIVATE.json"
        self.wrapper = canonical_snapshot()
        self.write()

    def write(self):
        self.source.write_text(json.dumps(self.wrapper, ensure_ascii=True))

    def change_tables(self, change):
        content = json.loads(self.wrapper["snapshot_json"])
        change(content)
        self.wrapper["snapshot_json"] = json.dumps(content)
        self.wrapper["snapshot_json_sha256"] = hashlib.sha256(self.wrapper["snapshot_json"].encode()).hexdigest()
        self.write()

    def run_restore(self, **kwargs):
        return restore.restore(self.source, self.output, allow_private_input=True, **kwargs)

    def test_all_four_tables_unknown_json_tombstones_numeric_precision_and_migrations(self):
        content = json.loads(self.wrapper["snapshot_json"])
        content["family_state"][0]["data"]["futureExact"] = "DECIMAL_LITERAL_PLACEHOLDER"
        raw = json.dumps(content).replace('"DECIMAL_LITERAL_PLACEHOLDER"', '123456789012345678901234567890.123456789')
        self.wrapper["snapshot_json"] = raw
        self.wrapper["snapshot_json_sha256"] = hashlib.sha256(raw.encode()).hexdigest()
        self.write()
        before = self.source.read_bytes()
        report = self.run_restore(rehearse_migrations=True)
        self.assertEqual(report["outcome"], "passed", report)
        self.assertTrue(report["four_table_roundtrip_verified"])
        self.assertTrue(report["migration_rehearsal_preserved_original_columns"])
        self.assertTrue(report["migration_rehearsal_local_cas_verified"])
        self.assertTrue(report["local_clone_rls_verified"])
        self.assertFalse(report["supabase_auth_restored"])
        self.assertFalse(report["supabase_platform_restored"])
        self.assertFalse(report["source_unknown_delivery_checks_reproduced"])
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)
        restored = verify.parse(self.output.read_bytes())
        self.assertTrue(restore.compare_rows(verify.parse(raw), verify.parse(restored["snapshot_json"])))
        export_raw = json.dumps(content["family_state"][0]["data"]).replace('"DECIMAL_LITERAL_PLACEHOLDER"', '123456789012345678901234567890.123456789')
        for n in (1, 2):
            (self.root / f"export{n}.json").write_text(export_raw)
            (self.root / f"capture{n}.json").write_text(json.dumps(fixtures.captured({verify.STATE: export_raw})))
        plan = {"format": "marichevy-private-restore-plan-v1", "project_ref": fixtures.PROJECT,
                "household_id": fixtures.HOUSE, "server_file": self.source.name,
                "restored_file": self.output.name,
                "devices": [{"scope_verified_by_owner": True, "export_file": f"export{n}.json",
                             "capture_file": f"capture{n}.json"} for n in (1, 2)]}
        (self.root / "plan.json").write_text(json.dumps(plan))
        verified = verify.verify(self.root / "plan.json", allow_private_input=True)
        self.assertEqual(verified["outcome"], "passed", verified)
        (self.root / "capture1.json").write_text(json.dumps(fixtures.captured({verify.STATE: export_raw, verify.PENDING: export_raw})))
        queued = verify.verify(self.root / "plan.json", allow_private_input=True)
        self.assertEqual(queued["outcome"], "review_required")
        self.assertIn("pending-acknowledgement-required", queued["issues"])
        encoded = json.dumps(report)
        for private in (fixtures.MARKER, fixtures.HOUSE, fixtures.USER, "1250.5", "deleted-entry", str(self.root)):
            self.assertNotIn(private, encoded)

    def test_copy_framing_never_executes_private_strings_as_sql(self):
        payload = "\\.\nDROP TABLE public.households CASCADE; -- ' ; \\\t"
        self.change_tables(lambda t: t["family_state"][0]["data"].update(futureText=payload))
        report = self.run_restore()
        self.assertEqual(report["outcome"], "passed", report)
        restored = verify.parse(self.output.read_bytes())
        recovered = verify.parse(restored["snapshot_json"])["family_state"][0]["data"]["futureText"]
        self.assertEqual(recovered, payload)

    def test_recorded_non_utc_timezone_restores_timestamp_text_consistently(self):
        self.wrapper["database_timezone"] = "Europe/Moscow"
        self.change_tables(lambda t: [row.update({key: value.replace("+00:00", "+03:00")
            for key, value in row.items() if key in ("created_at", "updated_at") and isinstance(value, str)})
            for rows in t.values() for row in rows])
        report = self.run_restore()
        self.assertEqual(report["outcome"], "passed", report)
        recovered = verify.parse(self.output.read_bytes())
        self.assertEqual(recovered["database_timezone"], "Europe/Moscow")
        self.assertTrue(restore.compare_rows(verify.parse(self.wrapper["snapshot_json"]), verify.parse(recovered["snapshot_json"])))

    def test_unknown_columns_foreign_family_and_bad_types_refuse_before_docker(self):
        base = canonical_snapshot()
        cases = [(lambda t: t["family_state"][0].update(unreviewed="keep"), "unknown-or-missing-outer-table-columns"),
                 (lambda t: t["household_members"][0].update(household_id=fixtures.OTHER), "foreign-family-or-project"),
                 (lambda t: t["family_chore_deliveries"][0].update(attempts="2"), "invalid-column-type")]
        for change, code in cases:
            with self.subTest(code=code):
                self.wrapper = copy.deepcopy(base)
                self.change_tables(change)
                with mock.patch.object(restore, "docker") as docker:
                    report = self.run_restore()
                self.assertEqual(report["outcome"], "failed", report)
                self.assertEqual(report["issues"], [code])
                docker.assert_not_called()
                self.assertFalse(self.output.exists())

    def test_malformed_json_hash_and_missing_timezone_are_safely_rejected(self):
        for mutate, code in [(lambda w: w.update(snapshot_json=w["snapshot_json"] + " "), "snapshot-json-integrity-mismatch"),
                             (lambda w: w.pop("database_timezone"), "missing-or-invalid-database-timezone")]:
            self.wrapper = canonical_snapshot()
            mutate(self.wrapper)
            self.write()
            with mock.patch.object(restore, "docker") as docker:
                report = self.run_restore()
            self.assertEqual(report["issues"], [code])
            docker.assert_not_called()
            self.assertNotIn(fixtures.MARKER, json.dumps(report))

    def test_private_flag_and_output_no_overwrite_are_enforced(self):
        with mock.patch.object(restore, "load_backup") as read:
            report = restore.restore(self.source, self.output)
        self.assertEqual(report["outcome"], "blocked")
        read.assert_not_called()
        self.output.write_bytes(b"EXISTING_PRIVATE_OUTPUT")
        report = self.run_restore()
        self.assertEqual(report["issues"], ["output-already-exists"])
        self.assertEqual(self.output.read_bytes(), b"EXISTING_PRIVATE_OUTPUT")

    def test_checkout_paths_parent_symlink_and_wrong_owner_are_refused_before_read(self):
        with mock.patch.object(restore, "ROOT", self.root), mock.patch.object(restore, "load_backup") as read:
            report = self.run_restore()
        self.assertEqual(report["issues"], ["private-input-must-be-outside-checkout"])
        read.assert_not_called()
        with mock.patch.object(restore.os, "geteuid", return_value=os.geteuid() + 1), mock.patch.object(restore, "load_backup") as read:
            report = self.run_restore()
        self.assertEqual(report["issues"], ["output-folder-must-be-private-and-owned"])
        read.assert_not_called()
        target = self.root / "target"
        target.mkdir(mode=0o700)
        alias = self.root / "alias"
        alias.symlink_to(target, target_is_directory=True)
        report = restore.restore(self.source, alias / "restored.json", allow_private_input=True)
        self.assertEqual(report["issues"], ["unsafe-or-unavailable-output-folder"])
        self.assertFalse((target / "restored.json").exists())

    def test_interrupted_private_write_removes_own_partial_readback(self):
        fake = mock.MagicMock()
        fake.__enter__.return_value = fake
        fake.sql.return_value = self.wrapper["snapshot_json"]
        with mock.patch.object(restore, "Clone", return_value=fake), mock.patch.object(restore.os, "fsync", side_effect=KeyboardInterrupt):
            report = self.run_restore()
        self.assertEqual(report["issues"], ["private-restore-interrupted"])
        self.assertFalse(self.output.exists())
        self.assertTrue(self.source.exists())

    def test_unknown_cli_argument_never_echoes_private_value(self):
        result = subprocess.run([sys.executable, str(Path(restore.__file__)), "--unexpected", fixtures.MARKER],
                                text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(fixtures.MARKER, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "private-restore-cli-arguments-invalid\n")

    def test_actual_foreign_keys_reject_unknown_household_without_leaking_row(self):
        with restore.Clone("UTC") as clone:
            before = clone.sql("SELECT count(*) FROM public.household_members;")
            query = "INSERT INTO public.household_members VALUES ('" + fixtures.HOUSE + "','" + fixtures.USER + "','" + fixtures.MARKER + "',now());"
            with self.assertRaises(restore.RestoreError) as caught:
                clone.sql(query)
            self.assertEqual(str(caught.exception), "local-docker-or-postgresql-failed")
            self.assertNotIn(fixtures.MARKER, str(caught.exception))
            self.assertEqual(clone.sql("SELECT count(*) FROM public.household_members;"), before)

    def test_original_broken_application_link_is_preserved_and_marked_for_review(self):
        self.change_tables(lambda t: t["family_state"][0]["data"]["installments"][0].update(links={"part": "missing-entry"}))
        report = self.run_restore()
        self.assertEqual(report["outcome"], "review_required", report)
        self.assertTrue(report["four_table_roundtrip_verified"])
        self.assertGreater(report["app_health_counts"]["broken_known_links"], 0)
        self.assertTrue(self.output.exists())

    def test_container_has_no_network_ports_or_log_store_and_always_removed(self):
        calls = []

        def fake_docker(*args, **kwargs):
            calls.append(args)
            if args[0] == "run":
                raise restore.RestoreError("synthetic-start-failure")
            return subprocess.CompletedProcess(args, 0, "", "")

        clone = restore.Clone("UTC")
        with mock.patch.object(restore, "docker", side_effect=fake_docker):
            with self.assertRaises(restore.RestoreError):
                with clone:
                    pass
        run = next(args for args in calls if args[0] == "run")
        self.assertIn("--network=none", run)
        self.assertIn("--log-driver=none", run)
        self.assertIn("--pull=never", run)
        self.assertNotIn("--publish", run)
        self.assertTrue(any(args[:2] == ("rm", "--force") for args in calls))


if __name__ == "__main__":
    unittest.main()
