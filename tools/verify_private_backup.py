#!/usr/bin/env python3
"""Offline, read-only comparison of explicitly supplied private backup files.

No network, environment credentials, database commands, import, merge or repair.
Reports contain fixed issue codes, counts and whole-file SHA-256, never history.
See docs/PRIVATE_RESTORE_ACCEPTANCE.md for authorization and input provenance.
"""
import argparse
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid

MAX_FILE = 32 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
MAX_FILES = 16
MAX_NODES = 500_000
ORIGIN = "https://finance.marichev.pro"
STATE = "marichevy_state_v10"
PENDING = "marichevy_pending_v10"
BASE = STATE + "_cloud_base_v1"
CONFLICT = STATE + "_cloud_conflict_v1"
BACKUPS = {"marichevy_state_backup_v44", "marichevy_pre_import_backup_v73"}
KEYS = {STATE, PENDING, BASE, CONFLICT, *BACKUPS}
KEYS |= {key + "_corrupt_v1" for key in (STATE, PENDING, *BACKUPS)}
TABLE_KEYS = {"households": ("id",), "household_members": ("household_id", "user_id"),
              "family_state": ("household_id",),
              "family_chore_deliveries": ("household_id", "chore_id", "due_date", "chat_id")}
COLLECTIONS = {"entries": "deletedEntries", "goals": "deletedGoals",
               "birthdays": "deletedBirthdays", "boardItems": "deletedBoardItems",
               "chores": "deletedChores", "installments": "deletedInstallments"}


class InvalidBackup(Exception):
    """Only fixed, non-sensitive reason codes may cross the CLI boundary."""


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message):
        self.exit(2, "invalid-command-arguments\n")


def fail(code):
    raise InvalidBackup(code)


def number(text):
    if len(text) > 512:
        fail("number-size-limit")
    value = Decimal(text)
    if not value.is_finite() or abs(value.as_tuple().exponent) > 1000:
        fail("invalid-number")
    return value


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            fail("duplicate-json-key")
        result[key] = value
    return result


def parse(raw):
    try:
        value = json.loads(raw, parse_float=number, parse_int=number,
                           parse_constant=lambda _: fail("invalid-number"), object_pairs_hook=pairs)
    except (ValueError, RecursionError, UnicodeError):
        fail("invalid-json")
    nodes = 0

    def visit(item, depth):
        nonlocal nodes
        nodes += 1
        if nodes > MAX_NODES or depth > 64:
            fail("json-complexity-limit")
        if isinstance(item, dict):
            for child in item.values():
                visit(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                visit(child, depth + 1)
    visit(value, 0)
    return value


def equal(left, right):
    # bool must not compare equal to the numeric values 0/1.
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(equal(v, right[k]) for k, v in left.items())
    if isinstance(left, list):
        return len(left) == len(right) and all(equal(a, b) for a, b in zip(left, right))
    return left == right


def identifier(value):
    if not isinstance(value, str) or not value or len(value) > 512 or re.search(r"[\x00-\x1f\x7f]", value):
        fail("invalid-record-id")
    return value


def uuid_value(value):
    try:
        if not isinstance(value, str) or str(uuid.UUID(value)) != value:
            fail("invalid-scope-id")
    except (ValueError, AttributeError):
        fail("invalid-scope-id")
    return value


def dated(value):
    return isinstance(value, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)) and _valid_date(value)


def _valid_date(value):
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def cents(value):
    try:
        if isinstance(value, bool) or not isinstance(value, (str, Decimal)):
            return False
        amount = number(value) if isinstance(value, str) else value
        if amount.is_zero():
            return True
        if abs(amount.adjusted()) > 18:
            return False
        # Avoid context rounding: inspect trailing decimal digits exactly.
        digits, exponent = amount.as_tuple().digits, amount.as_tuple().exponent
        return exponent >= -2 or all(d == 0 for d in digits[exponent + 2:])
    except (InvalidOperation, InvalidBackup, ValueError):
        return False


def state_rows(state):
    if not isinstance(state, dict) or not isinstance(state.get("entries"), list) or not isinstance(state.get("settings"), dict):
        fail("invalid-state-shape")
    result = {}
    for name in COLLECTIONS:
        rows = state.get(name, [])
        if not isinstance(rows, list):
            fail("invalid-collection")
        result[name] = indexed(rows, keep_duplicates=True)
    intelligence = state.get("intelligence", {})
    if not isinstance(intelligence, dict):
        fail("invalid-collection")
    for name in ("budgets", "recurring", "accounts"):
        rows = intelligence.get(name, [])
        if not isinstance(rows, list):
            fail("invalid-collection")
        result["intelligence." + name] = indexed(rows, keep_duplicates=True)
    for row in result["installments"].values():
        if not isinstance(row.get("parts", []), list):
            fail("invalid-collection")
        indexed(row.get("parts", []), keep_duplicates=True)
    for key in COLLECTIONS.values():
        tombstones(state.get(key, {}))
    deleted = intelligence.get("deleted", {})
    if not isinstance(deleted, dict):
        fail("invalid-tombstones")
    for key in ("budgets", "recurring", "accounts"):
        tombstones(deleted.get(key, {}))
    return result


def indexed(rows, keys=("id",), keep_duplicates=False):
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            fail("invalid-record")
        identity = tuple(identifier(row.get(key)) for key in keys)
        if identity in result:
            if not keep_duplicates:
                fail("duplicate-record-id")
            # Preserve every row in a legacy ambiguous collection. The caller
            # counts ambiguity; it must never choose/overwrite one variant.
            identity += (len(result),)
        result[identity] = row
    return result


def tombstones(value):
    if isinstance(value, list):
        list(map(identifier, value))
    elif isinstance(value, dict):
        for key, at in value.items():
            identifier(key)
            if not isinstance(at, str):
                fail("invalid-tombstones")
    else:
        fail("invalid-tombstones")


def state_health(state):
    rows = state_rows(state)
    invalid_money = invalid_dates = broken_links = 0
    duplicate_ids = sum(len(values) - len({key[0] for key in values}) for values in rows.values())
    money = []
    dates = []
    for row in rows["entries"].values():
        money.append(row.get("amount"))
        dates.append(row.get("date"))
    for row in rows["goals"].values():
        money.extend(row[key] for key in ("target", "saved", "monthly") if key in row)
        for deposit in row.get("deposits", []):
            if not isinstance(deposit, dict):
                fail("invalid-record")
            if "amount" in deposit:
                money.append(deposit["amount"])
            if deposit.get("date"):
                dates.append(deposit["date"])
    for row in rows["installments"].values():
        money.extend(row[key] for key in ("amount", "total") if key in row)
        parts = indexed(row.get("parts", []), keep_duplicates=True)
        duplicate_ids += len(parts) - len({key[0] for key in parts})
        for part in parts.values():
            money.append(part.get("amount"))
            dates.append(part.get("date"))
        links = row.get("links", {})
        if not isinstance(links, dict):
            fail("invalid-links")
        for part_id, entry_id in links.items():
            if (part_id,) not in parts or (entry_id,) not in rows["entries"]:
                broken_links += 1
    for name in ("budgets", "recurring", "accounts"):
        for row in rows["intelligence." + name].values():
            if "amount" in row:
                money.append(row["amount"])
    for row in rows["entries"].values():
        if row.get("installmentId"):
            installment = rows["installments"].get((row["installmentId"],))
            deleted = state.get("deletedInstallments", {})
            if installment is None and row["installmentId"] not in deleted:
                broken_links += 1
            elif installment is not None and row.get("installmentPartId") and (row["installmentPartId"],) not in indexed(installment.get("parts", []), keep_duplicates=True):
                broken_links += 1
        if row.get("recurringId"):
            deleted = state.get("intelligence", {}).get("deleted", {}).get("recurring", {})
            if (row["recurringId"],) not in rows["intelligence.recurring"] and row["recurringId"] not in deleted:
                broken_links += 1
        if row.get("recurringPeriod") and not (re.fullmatch(r"\d{4}-\d{2}", str(row["recurringPeriod"])) and dated(row["recurringPeriod"] + "-01")):
            invalid_dates += 1
    invalid_money += sum(not cents(value) for value in money)
    invalid_dates += sum(not dated(value) for value in dates)
    for key in COLLECTIONS.values():
        deleted = state.get(key, {})
        if isinstance(deleted, list):
            duplicate_ids += len(deleted) - len(set(deleted))
    return {"invalid_cent_values": invalid_money, "invalid_period_values": invalid_dates,
            "ambiguous_duplicate_ids": duplicate_ids,
            "broken_known_links": broken_links, "records": sum(map(len, rows.values()))}


class Reader:
    def __init__(self, manifest_path):
        self.root = manifest_path.parent.resolve()
        self.total = 0
        self.digests = []
        self.paths = set()

    def read(self, path):
        if len(self.paths) >= MAX_FILES:
            fail("file-count-limit")
        if not path.is_absolute():
            path = self.root / path
        try:
            relative = path.relative_to(self.root)
            if any(piece in ("..", "") for piece in relative.parts):
                fail("path-outside-private-folder")
            current = self.root
            for piece in relative.parts:
                current = current / piece
                if current.is_symlink():
                    fail("symlink-not-allowed")
            if path in self.paths:
                fail("input-file-reused")
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE:
                    fail("invalid-or-oversized-input-file")
                raw = stream.read(MAX_FILE + 1)
                after = os.fstat(stream.fileno())
            if len(raw) > MAX_FILE or (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                fail("input-file-changed-or-too-large")
        except (OSError, ValueError):
            fail("input-file-unavailable")
        self.paths.add(path)
        self.total += len(raw)
        if self.total > MAX_TOTAL:
            fail("total-input-limit")
        self.digests.append(hashlib.sha256(raw).hexdigest())
        return parse(raw)

    def named(self, value):
        if not isinstance(value, str) or not value or Path(value).is_absolute():
            fail("invalid-private-filename")
        return self.read(Path(value))


def snapshot(value, project, household):
    if not isinstance(value, dict) or value.get("format") != "marichevy-private-server-backup-v1" or value.get("read_only") is not True:
        fail("invalid-snapshot-format")
    if value.get("project_ref") != project or value.get("configured_household") != household:
        fail("foreign-family-or-project")
    if type(value.get("configured_household_count")) is not Decimal or value["configured_household_count"] != 1:
        fail("invalid-snapshot-scope-count")
    zone = value.get("database_timezone")
    if not isinstance(zone, str) or not zone or len(zone) > 128 or re.search(r"[\x00-\x1f\x7f]", zone):
        fail("invalid-snapshot-timezone")
    raw = value.get("snapshot_json")
    if not isinstance(raw, str):
        fail("invalid-snapshot-json")
    try:
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    except UnicodeEncodeError:
        fail("invalid-snapshot-json")
    if value.get("snapshot_json_sha256") != digest:
        fail("snapshot-json-integrity-mismatch")
    tables = parse(raw)
    if not isinstance(tables, dict) or tables.keys() != TABLE_KEYS.keys():
        fail("incomplete-server-table-coverage")
    for name, keys in TABLE_KEYS.items():
        rows = tables[name]
        if not isinstance(rows, list):
            fail("invalid-table-shape")
        indexed(rows, keys)
        for row in rows:
            if row.get("id" if name == "households" else "household_id") != household:
                fail("foreign-family-or-project")
    if len(tables["family_state"]) != 1 or len(tables["households"]) != 1 or not tables["household_members"]:
        fail("incomplete-server-table-coverage")
    for row in tables["household_members"]:
        uuid_value(row.get("user_id"))
    data = tables["family_state"][0].get("data")
    health = state_health(data)
    return tables, data, health


def utf8_js(raw):
    # JS TextEncoder replaces lone UTF-16 surrogates, but joins surrogate pairs.
    units = raw.encode("utf-16-le", errors="surrogatepass")
    return units.decode("utf-16-le", errors="replace").encode("utf-8")


def capture(value, project, household, server, exported):
    if not isinstance(value, dict) or value.get("format") != "marichevy-local-queue-capture-v1" or value.get("origin") != ORIGIN:
        fail("invalid-capture-format-or-origin")
    if value.get("session_included") is not False or value.get("storage_modified") is not False or value.get("device_clock_verified") is not False:
        fail("invalid-capture-safety-flags")
    records = value.get("records")
    if not isinstance(records, list) or not records or type(value.get("key_count")) is not Decimal or value["key_count"] != len(records):
        fail("invalid-capture-records")
    seen = set()
    counts = {"divergent_active_values": 0, "corrupt_preserved_values": 0,
              "conflict_packets": 0, "pending_values": 0}
    primary_seen = False
    for row in records:
        if not isinstance(row, dict):
            fail("invalid-capture-records")
        key, raw = row.get("key"), row.get("raw")
        if not isinstance(key, str) or not (key in KEYS or re.fullmatch(re.escape(CONFLICT) + r"_archive_[A-Za-z0-9_-]+", key)) or key in seen or not isinstance(raw, str):
            fail("unexpected-or-duplicate-storage-key")
        seen.add(key)
        utf16, utf8 = raw.encode("utf-16-le", errors="surrogatepass"), utf8_js(raw)
        if (type(row.get("utf16_code_units")) is not Decimal or type(row.get("utf8_bytes")) is not Decimal
                or row["utf16_code_units"] != len(utf16) // 2 or row["utf8_bytes"] != len(utf8)
                or row.get("sha256_utf8") != hashlib.sha256(utf8).hexdigest()
                or row.get("sha256_utf16le") != hashlib.sha256(utf16).hexdigest()):
            fail("raw-capture-integrity-mismatch")
        if key.endswith("_corrupt_v1"):
            # A valid JSON value can still be an unresolved quarantined variant.
            # Its name, not parse success, establishes that review is necessary.
            counts["corrupt_preserved_values"] += 1
            continue
        try:
            parsed = parse(raw)
        except InvalidBackup:
            counts["corrupt_preserved_values"] += 1
            continue
        if key == BASE or key.startswith(CONFLICT):
            if not isinstance(parsed, dict) or parsed.get("household") != household:
                fail("foreign-family-or-project")
            if key == BASE and parsed.get("url") != "https://" + project + ".supabase.co":
                fail("foreign-family-or-project")
            if key == BASE:
                state_rows(parsed.get("data"))
        if key.startswith(CONFLICT):
            counts["conflict_packets"] += 1
        if key in (STATE, PENDING):
            primary_seen |= key == STATE
            counts["pending_values"] += key == PENDING
            state_rows(parsed)
            if not equal(parsed, server) or not equal(parsed, exported):
                counts["divergent_active_values"] += 1
        elif key in BACKUPS:
            if not isinstance(parsed, dict) or not isinstance(parsed.get("data"), dict):
                counts["corrupt_preserved_values"] += 1
            else:
                state_rows(parsed["data"])
    if not primary_seen:
        counts["corrupt_preserved_values"] += 1
    return counts


def verify(manifest_path, *, allow_private_input=False):
    report = {"format": "marichevy-private-backup-verification-v1", "outcome": "failed",
              "network_used": False, "inputs_modified": False,
              "restore_execution_verified": False, "release_authorized": False,
              "issues": [], "checks": {}, "counts": {}}
    try:
        if not allow_private_input:
            fail("private-input-not-authorized")
        path = Path(manifest_path).absolute()
        reader = Reader(path)
        manifest = reader.read(path)
        if not isinstance(manifest, dict) or manifest.get("format") != "marichevy-private-restore-plan-v1":
            fail("invalid-plan-format")
        project, household = manifest.get("project_ref"), uuid_value(manifest.get("household_id"))
        if not isinstance(project, str) or not re.fullmatch(r"[a-z0-9]{20}", project):
            fail("invalid-project-ref")
        source, state, health = snapshot(reader.named(manifest.get("server_file")), project, household)
        restored, _, _ = snapshot(reader.named(manifest.get("restored_file")), project, household)
        restored_equal = all(equal(indexed(source[t], k), indexed(restored[t], k)) for t, k in TABLE_KEYS.items())
        report["checks"]["all_server_rows_and_unknown_fields_restored"] = restored_equal
        if not restored_equal:
            report["issues"].append("restored-snapshot-diverges")
        report["counts"].update(health)
        devices = manifest.get("devices")
        if not isinstance(devices, list) or not 2 <= len(devices) <= 6:
            fail("both-device-bundles-required")
        report["counts"]["devices"] = len(devices)
        for device in devices:
            if not isinstance(device, dict):
                fail("invalid-device-plan")
            if device.get("scope_verified_by_owner") is not True:
                report["issues"].append("device-family-scope-not-attested")
            exported = reader.named(device.get("export_file"))
            device_health = state_health(exported)
            for key in ("invalid_cent_values", "invalid_period_values", "broken_known_links", "ambiguous_duplicate_ids"):
                report["counts"][key] += device_health[key]
            if not equal(exported, state):
                report["issues"].append("device-export-diverges")
            captured = capture(reader.named(device.get("capture_file")), project, household, state, exported)
            for key, value in captured.items():
                report["counts"][key] = report["counts"].get(key, 0) + value
        for key in ("invalid_cent_values", "invalid_period_values", "broken_known_links", "ambiguous_duplicate_ids",
                    "divergent_active_values", "corrupt_preserved_values", "conflict_packets"):
            if report["counts"].get(key):
                report["issues"].append(key.replace("_", "-"))
        if report["counts"].get("pending_values"):
            report["issues"].append("pending-acknowledgement-required")
        report["checks"].update({"input_scope_and_capture_hashes_valid": True,
                                 "device_scope_is_owner_attestation": True,
                                 "period_cent_and_known_links_valid": not any(report["counts"].get(k) for k in ("invalid_cent_values", "invalid_period_values", "broken_known_links")),
                                 "device_variants_match_server": not any(code in report["issues"] for code in ("device-export-diverges", "divergent-active-values", "corrupt-preserved-values", "conflict-packets"))})
        report["issues"] = sorted(set(report["issues"]))
        report["source_file_sha256"] = reader.digests
        report["outcome"] = "passed" if not report["issues"] else "review_required"
    except InvalidBackup as error:
        report["issues"].append(str(error))
    except Exception:
        # Parsing/filesystem internals may contain raw text or private filenames.
        report["issues"].append("internal-verifier-error")
    return report


def main(argv=None):
    parser = SafeArgumentParser(prog="verify_private_backup", description=__doc__)
    parser.add_argument("--manifest", required=True, help="private local plan JSON; no upload")
    parser.add_argument("--allow-private-input", action="store_true", help="explicit permission to read the selected private files locally")
    args = parser.parse_args(argv)
    report = verify(args.manifest, allow_private_input=args.allow_private_input)
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return {"passed": 0, "review_required": 2, "failed": 1}[report["outcome"]]


if __name__ == "__main__":
    sys.exit(main())
