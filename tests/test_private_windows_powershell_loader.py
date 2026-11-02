"""Execute the real PowerShell loader against fictional code-only inputs.

PowerShell on Linux exercises parsing, .NET overloads, UTF-8, hashing and the
captured-script invocation. It does not establish Windows native acceptance.
Set MARICHEVY_TEST_PWSH to a portable PowerShell executable when it is not on PATH.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "private_windows_loader_builder", ROOT / "tools/build_private_verification_windows_bundle.py")
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)
MARKER = "FICTIONAL-LOADER-INVOKED"
PRIVATE_MARKER = "FICTIONAL_PRIVATE_EXCEPTION_MUST_NOT_LEAK"
VALID_SCRIPT = (
    "Set-Content -LiteralPath 'fictional-invoked.txt' -Value 'fixture-only'\n"
    f"[Console]::Out.WriteLine('{MARKER}')\n"
).encode("utf8")


class PrivateWindowsPowerShellLoader(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.powershell = (os.environ.get("MARICHEVY_TEST_PWSH")
                          or shutil.which("pwsh") or shutil.which("powershell"))
        if not cls.powershell:
            raise unittest.SkipTest("Real PowerShell is required for loader execution")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fictional-powershell-loader-")
        self.root = Path(self.temp.name)
        self.bundle = self.root / "bundle"
        self.bundle.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def execute(self, data: bytes | None, *, expected: bytes | None = None, prologue=""):
        if data is not None:
            (self.bundle / BUILDER.PREFLIGHT).write_bytes(data)
        pin = hashlib.sha256(expected if expected is not None else data or VALID_SCRIPT).hexdigest()
        self.assertEqual(BUILDER.PREFLIGHT_LOADER.count("__WINDOWS_PREFLIGHT_SHA256__"), 1)
        script = prologue + BUILDER.PREFLIGHT_LOADER.replace("__WINDOWS_PREFLIGHT_SHA256__", pin)
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        environment = os.environ.copy()
        # Keep PowerShell's own Linux caches outside the read-only home. These
        # are test-runtime paths, unrelated to any owner backup or browser.
        environment.update(
            XDG_CACHE_HOME=str(self.root / "runtime-cache"),
            XDG_CONFIG_HOME=str(self.root / "runtime-config"),
            XDG_DATA_HOME=str(self.root / "runtime-data"),
        )
        result = subprocess.run(
            [self.powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            cwd=self.bundle, env=environment, capture_output=True, text=True,
            encoding="utf8", timeout=30,
        )
        self.assertEqual(result.returncode, 0, "PowerShell loader process failed")
        self.assertEqual(result.stderr, "", "Raw PowerShell diagnostics must remain hidden")
        for private in (str(self.bundle), PRIVATE_MARKER):
            self.assertNotIn(private, result.stdout)
        return result.stdout.replace("\r\n", "\n")

    def assert_not_invoked(self):
        self.assertFalse((self.bundle / "fictional-invoked.txt").exists())

    def assert_fixed_failure(self, data, code, *, expected=None):
        self.assertEqual(self.execute(data, expected=expected),
                         "Result: failed\nCodes: " + code + "\n")
        self.assert_not_invoked()

    def test_real_loader_hashes_and_invokes_exact_captured_ascii_bytes(self):
        self.assertEqual(self.execute(VALID_SCRIPT), MARKER + "\n")
        self.assertEqual((self.bundle / "fictional-invoked.txt").read_text().strip(), "fixture-only")

    def test_unicode_space_and_shell_metacharacters_in_folder_are_literal(self):
        self.bundle = self.root / "Проверка 1 ' $() ` & папка"
        self.bundle.mkdir()
        self.assertEqual(self.execute(VALID_SCRIPT), MARKER + "\n")
        self.assertTrue((self.bundle / "fictional-invoked.txt").is_file())

    def test_changed_ps1_is_rejected_at_hash_before_invocation(self):
        self.assert_fixed_failure(VALID_SCRIPT + b"\n# altered\n",
                                  "verification-launch-loader-hash", expected=VALID_SCRIPT)

    def test_matching_hash_does_not_allow_invalid_utf8(self):
        self.assert_fixed_failure(VALID_SCRIPT + b"\xff\xfe\x80",
                                  "verification-launch-loader-utf8")

    def test_missing_ps1_has_fixed_metadata_code(self):
        self.assert_fixed_failure(None, "verification-launch-loader-metadata")

    def test_matching_hash_does_not_allow_syntactically_invalid_ps1(self):
        bad_script = (f"throw '{PRIVATE_MARKER}'\nif (\n").encode("utf8")
        self.assert_fixed_failure(bad_script, "verification-launch-loader-parse")

    def test_script_runtime_exception_is_hidden_behind_invoke_code(self):
        self.assert_fixed_failure((f"throw '{PRIVATE_MARKER}'\n").encode("utf8"),
                                  "verification-launch-loader-invoke")

    def test_constrained_child_shell_refuses_before_missing_file_access(self):
        # Tighten only this disposable test process. Do not change a machine
        # policy or restore/bypass a restriction on the owner's computer.
        stdout = self.execute(
            None, prologue="$ExecutionContext.SessionState.LanguageMode = 'ConstrainedLanguage';\n")
        self.assertEqual(stdout, "Result: failed\nCodes: verification-shell-restricted\n")
        self.assert_not_invoked()

    def test_published_ps1_parses_and_enters_inner_platform_guard(self):
        # This is the original delivered code, not a Windows runtime substitute.
        # On Linux the inner local-drive guard refuses it; on Windows this
        # deliberately incomplete fixture has no runtime and refuses it there.
        with zipfile.ZipFile(ROOT / "preview/windows-private-verification-v95.zip") as archive:
            data = archive.read(BUILDER.PREFLIGHT)
        self.assertEqual(self.execute(data),
                         "Результат: failed\nКоды: verification-launch-integrity-failed\n")
        self.assert_not_invoked()


if __name__ == "__main__":
    unittest.main()
