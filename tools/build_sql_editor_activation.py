#!/usr/bin/env python3
"""Prepare a private SQL Editor activation script without executing SQL.

The input is an explicit, separately verified six-field plan. No credential,
database connection, live revision lookup, network request or deployment occurs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import unicodedata
import uuid

ROOT = Path(__file__).resolve().parents[1]
FORMAT = "marichevy-sync-activation-plan-v1"
SQL_SHA256 = "7fc72248cd65e790dfec12abc4da1811ae2146f414b8be46cd5cd7ae5244e248"
PLAN_KEYS = frozenset(("format", "activation_sql_sha256", "expected_database",
                       "household_id", "expected_revision", "expected_data_sha256"))
OUTPUT_NAMES = ("activation.sql", "cleanup.sql", "activation-plan.json", "build-manifest.json")
MAX_PLAN = 16 * 1024
MAX_SQL = 32 * 1024


class PreparationError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def fail(code):
    raise PreparationError(code)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def absolute(value):
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or path == Path("/"):
        fail("activation-private-path-invalid")
    return path


def outside_checkout(value):
    path = absolute(value)
    if path.is_relative_to(ROOT):
        fail("activation-private-path-invalid")
    return path


def open_directory(path):
    """Descriptor walk; no symlink component is followed."""
    path = absolute(path)
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def private_directory(attributes):
    return (stat.S_ISDIR(attributes.st_mode)
            and attributes.st_uid == os.geteuid()
            and stat.S_IMODE(attributes.st_mode) == 0o700)


def identity(value):
    return (value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode,
            value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def regular_bytes(path, maximum, *, private):
    descriptor = parent = None
    try:
        path = outside_checkout(path) if private else absolute(path)
        parent = open_directory(path.parent)
        if private and not private_directory(os.fstat(parent)):
            fail("activation-private-input-invalid")
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=parent)
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_size <= 0 or before.st_size > maximum
                or (private and (before.st_uid != os.geteuid()
                                 or stat.S_IMODE(before.st_mode) != 0o600))):
            fail("activation-private-input-invalid" if private else "activation-sql-artifact-invalid")
        chunks, remaining = [], maximum + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        contents = b"".join(chunks)
        current = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        if (identity(before) != identity(os.fstat(descriptor))
                or identity(before) != identity(current) or len(contents) != before.st_size):
            fail("activation-private-input-invalid" if private else "activation-sql-artifact-invalid")
        return contents
    except PreparationError:
        raise
    except (OSError, ValueError, TypeError):
        fail("activation-private-input-invalid" if private else "activation-sql-artifact-invalid")
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if parent is not None:
            os.close(parent)


def object_unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            fail("activation-plan-invalid")
        value[key] = item
    return value


def invalid_number(_value):
    fail("activation-plan-invalid")


def validate_plan(raw):
    try:
        value = json.loads(raw.decode("utf8", errors="strict"),
                           object_pairs_hook=object_unique, parse_float=invalid_number,
                           parse_constant=invalid_number)
        if not isinstance(value, dict) or set(value) != PLAN_KEYS or value["format"] != FORMAT:
            fail("activation-plan-invalid")
        if value["activation_sql_sha256"] != SQL_SHA256:
            fail("activation-plan-sql-pin-invalid")
        database = value["expected_database"]
        if (not isinstance(database, str) or not 1 <= len(database.encode("utf8")) <= 63
                or any(unicodedata.category(character) in ("Cc", "Zl", "Zp")
                       for character in database)):
            fail("activation-plan-invalid")
        household = value["household_id"]
        if (not isinstance(household, str) or str(uuid.UUID(household)) != household
                or uuid.UUID(household).int == 0):
            fail("activation-plan-invalid")
        revision = value["expected_revision"]
        if type(revision) is not int or not 0 <= revision < 9223372036854775807:
            fail("activation-plan-invalid")
        digest = value["expected_data_sha256"]
        if not isinstance(digest, str) or re.fullmatch(r"[a-f0-9]{64}", digest) is None:
            fail("activation-plan-invalid")
        return value
    except PreparationError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        fail("activation-plan-invalid")


def literal(value):
    # Explicit E strings make escaping independent of standard_conforming_strings.
    return "E'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def encode_json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf8")


def prepare(*, plan_path, output_dir):
    """Return fixed public metadata; all parameters and hashes stay private."""
    raw = regular_bytes(plan_path, MAX_PLAN, private=True)
    plan = validate_plan(raw)
    reviewed = regular_bytes(ROOT / "server/activate_household_api.sql", MAX_SQL, private=False)
    if sha(reviewed) != SQL_SHA256:
        fail("activation-sql-artifact-invalid")
    try:
        body = reviewed.decode("utf8", errors="strict")
    except UnicodeError:
        fail("activation-sql-artifact-invalid")
    statement = "marichevy_activation_" + secrets.token_hex(12)
    arguments = ", ".join((literal(plan["expected_database"]),
                           literal(plan["household_id"]) + "::uuid",
                           str(plan["expected_revision"]),
                           literal(plan["expected_data_sha256"])))
    activation = (
        "-- PRIVATE PREPARED SCRIPT: not executed by this builder.\n"
        "-- Save the EXECUTE result (verified, activation_revision) privately.\n"
        "-- Cleanup is a separate file; do not append it before saving the receipt.\n"
        f"PREPARE {statement}(text,uuid,bigint,text) AS\n"
        + body.rstrip() + "\n"
        + f"EXECUTE {statement}({arguments});\n"
    ).encode("utf8")
    cleanup = (
        "-- Run separately only after saving the activation result.\n"
        f"DEALLOCATE {statement};\n"
    ).encode("utf8")
    files = {"activation.sql": activation, "cleanup.sql": cleanup,
             "activation-plan.json": encode_json(plan)}
    files["build-manifest.json"] = encode_json({
        "format": "marichevy-sql-editor-activation-build-v1",
        "outcome": "prepared-not-executed", "production_changed": False,
        "activation_executed": False, "activation_receipt_created": False,
        "source_plan_sha256": sha(raw), "source_sql_sha256": SQL_SHA256,
        "prepared_statement": statement,
        "files": {name: {"bytes": len(data), "sha256": sha(data)}
                  for name, data in sorted(files.items())},
    })
    output = outside_checkout(output_dir)
    parent = directory = None
    try:
        parent = open_directory(output.parent)
        # Exclusive mkdir refuses every existing path, even an empty directory.
        os.mkdir(output.name, 0o700, dir_fd=parent)
        directory = os.open(output.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=parent)
        if not private_directory(os.fstat(directory)):
            fail("activation-private-output-invalid")
        initial = os.fstat(directory)
        for name in OUTPUT_NAMES:
            data = files[name]
            descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=directory)
            try:
                os.fchmod(descriptor, 0o600)
                attributes = os.fstat(descriptor)
                if (not stat.S_ISREG(attributes.st_mode) or attributes.st_nlink != 1
                        or attributes.st_uid != os.geteuid()
                        or stat.S_IMODE(attributes.st_mode) != 0o600):
                    fail("activation-private-output-invalid")
                offset = 0
                while offset < len(data):
                    written = os.write(descriptor, data[offset:])
                    if written <= 0:
                        fail("activation-private-output-invalid")
                    offset += written
                os.fsync(descriptor)
                after = os.fstat(descriptor)
                if after.st_size != len(data) or after.st_nlink != 1:
                    fail("activation-private-output-invalid")
            finally:
                os.close(descriptor)
            reader = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            try:
                before_read = os.fstat(reader)
                copied = os.read(reader, len(data) + 1)
                if (copied != data or identity(before_read) != identity(os.fstat(reader))
                        or identity(before_read) != identity(
                            os.stat(name, dir_fd=directory, follow_symlinks=False))
                        or identity(before_read) != identity(after)):
                    fail("activation-private-output-invalid")
            finally:
                os.close(reader)
        os.fsync(directory)
        current = os.stat(output.name, dir_fd=parent, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (initial.st_dev, initial.st_ino):
            fail("activation-private-output-invalid")
        if not private_directory(current):
            fail("activation-private-output-invalid")
        return {"outcome": "prepared-not-executed", "activation_executed": False,
                "activation_receipt_created": False, "production_changed": False}
    except PreparationError:
        raise
    except (OSError, ValueError, TypeError):
        fail("activation-private-output-invalid")
    finally:
        if directory is not None:
            os.close(directory)
        if parent is not None:
            os.close(parent)


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "Result: failed\nCodes: activation-arguments-invalid\n")


def main():
    parser = SafeParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        prepare(plan_path=args.plan, output_dir=args.output_dir)
    except PreparationError as error:
        print("Result: failed\nCodes: " + error.code)
        return 1
    except Exception:
        print("Result: failed\nCodes: activation-preparation-failed")
        return 1
    print("Result: prepared-not-executed\nCodes: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
