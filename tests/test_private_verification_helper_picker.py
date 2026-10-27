"""Actual Bash folder recovery and checksum gates, with native UI substituted.

Only uname/osascript are host-specific fixtures. The runtime is a harmless
fixture with its expected SHA substituted for the production binary's SHA;
the actual hash commands, comparisons, recovery loop and clean-env exec remain.
No owner files or macOS policy settings are involved.
"""
from pathlib import Path
import hashlib
import json
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / 'tools/private_verify/Start Mac verification.command'
ARM64_PIN = '2cc28a1880d0774616959f2210ee739bffa6ac695c887e8988a496a21271f6c0'
PRIVATE_MARKER = 'FICTIONAL_PRIVATE_SELECTED_FOLDER'


class PrivateVerificationHelperPicker(unittest.TestCase):
    def setUp(self):
        self.bash = shutil.which('bash')
        if not self.bash:
            self.skipTest('Bash required')
        self.temp = tempfile.TemporaryDirectory(prefix='fictional-helper-picker-')
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.addon = self.root / 'verification addon'
        (self.addon / 'app').mkdir(parents=True)
        self.bootstrap = self.addon / 'app/mac-bootstrap.cjs'
        self.bootstrap.write_text('// only a code fixture; never executed\n')
        self.events = self.root / 'runtime-events.txt'
        self.dialogs = self.root / 'dialog-events.json'
        self.responses = self.root / 'dialog-responses.json'
        self.uname = self.root / 'uname-fixture'
        self.uname.write_text('#!/bin/sh\ncase "$1" in -s) echo Darwin;; -m) echo arm64;; *) exit 3;; esac\n')
        self.uname.chmod(0o755)
        self.osascript = self.root / 'osascript-fixture'
        self.osascript.write_text('#!' + sys.executable + '\n' +
            'import json,sys\nfrom pathlib import Path\n' +
            'responses=Path(' + repr(str(self.responses)) + ')\n' +
            'events=Path(' + repr(str(self.dialogs)) + ')\n' +
            "script=sys.argv[2] if len(sys.argv)==3 and sys.argv[1]=='-e' else ''\n" +
            "kind='choose' if 'choose folder with prompt' in script else 'wrong' if 'display dialog' in script else 'invalid'\n" +
            'seen=json.loads(events.read_text()) if events.exists() else []\n' +
            'seen.append(kind);events.write_text(json.dumps(seen))\n' +
            'pending=json.loads(responses.read_text())\n' +
            'assert pending, "unexpected dialog"\n' +
            'expected,value=pending.pop(0);assert expected==kind\n' +
            'responses.write_text(json.dumps(pending))\n' +
            'if value=="NATIVE_ERROR":sys.exit(17)\n' +
            'print(value)\n')
        self.osascript.chmod(0o755)
        # Literal shell metacharacters must remain data from the folder picker.
        self.helper = self.root / (PRIVATE_MARKER + " owner's $(touch MUST_NOT_EXECUTE) `touch ALSO_NOT_EXECUTE`")
        self.create_helper(self.helper)

    def create_helper(self, helper):
        node = helper / 'runtime/arm64/node'
        node.parent.mkdir(parents=True, exist_ok=True)
        (helper / 'Start Mac backup.command').write_text('# fixture only\n')
        (helper / 'MANIFEST.json').write_text('{}\n')
        node.write_text('#!/bin/sh\n' +
            '[ "${NODE_OPTIONS+x}" != x ] || exit 91\n' +
            '[ "${DYLD_FIXTURE+x}" != x ] || exit 92\n' +
            'if [ "$1" = --version ]; then\n' +
            "  printf '%s\\n' version >> " + shlex.quote(str(self.events)) + '\n' +
            "  printf '%s\\n' v22.23.4\n  exit 0\nfi\n" +
            '[ "$1" = --no-global-search-paths ] || exit 93\n' +
            '[ "$2" = ' + shlex.quote(str(self.bootstrap)) + ' ] || exit 94\n' +
            '[ "$3" = ' + shlex.quote(str(helper)) + ' ] || exit 95\n' +
            "printf '%s\\n' main >> " + shlex.quote(str(self.events)) + '\n' +
            "printf '%s\\n' 'Результат: passed' 'Коды: none'\n")
        node.chmod(0o755)
        return node

    def run_launcher(self, choices, *, helper=None, bad_runtime=False, bad_bootstrap=False):
        helper = helper or self.helper
        node = helper / 'runtime/arm64/node'
        node_pin = hashlib.sha256(node.read_bytes()).hexdigest()
        bootstrap_pin = hashlib.sha256(self.bootstrap.read_bytes()).hexdigest()
        source = LAUNCHER.read_text()
        self.assertEqual(source.count(ARM64_PIN), 1)
        self.assertEqual(source.count('__ADDON_BOOTSTRAP_SHA256__'), 1)
        source = source.replace(ARM64_PIN, node_pin)
        source = source.replace('__ADDON_BOOTSTRAP_SHA256__', bootstrap_pin)
        source = source.replace('/usr/bin/uname', shlex.quote(str(self.uname)))
        source = source.replace('/usr/bin/osascript', shlex.quote(str(self.osascript)))
        script = self.addon / 'Start Mac verification.command'
        script.write_text(source)
        self.responses.write_text(json.dumps(choices))
        if bad_runtime:
            node.write_text(node.read_text() + '\n# changed runtime\n')
        if bad_bootstrap:
            self.bootstrap.write_text('// changed code\n')
        result = subprocess.run([self.bash, '-p', str(script)], stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=10,
            env={'PATH': '/usr/bin:/bin', 'NODE_OPTIONS': 'fixture-poison', 'DYLD_FIXTURE': 'fixture-poison'})
        self.assertNotIn(PRIVATE_MARKER, result.stdout + result.stderr)
        self.assertNotIn(str(self.root), result.stdout + result.stderr)
        self.assertFalse((self.addon / 'MUST_NOT_EXECUTE').exists())
        self.assertFalse((self.addon / 'ALSO_NOT_EXECUTE').exists())
        return result

    def runtime_events(self):
        return self.events.read_text().splitlines() if self.events.exists() else []

    def test_selected_folder_with_spaces_quotes_and_shell_syntax_is_literal(self):
        result = self.run_launcher([['choose', str(self.helper) + '/']])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Результат: passed', result.stdout)
        self.assertEqual(self.runtime_events(), ['version', 'main'])
        self.assertEqual(json.loads(self.dialogs.read_text()), ['choose'])

    def test_wrong_verification_folder_is_corrected_without_restart(self):
        result = self.run_launcher([['choose', str(self.addon) + '/'],
            ['wrong', 'choose-again'], ['choose', str(self.helper) + '/']])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.runtime_events(), ['version', 'main'])
        self.assertEqual(json.loads(self.dialogs.read_text()), ['choose', 'wrong', 'choose'])
        self.assertEqual(result.stdout.count('Этап: запуск среды программы'), 1)

    def test_picker_or_correction_cancellation_never_starts_runtime(self):
        for choices in ([['choose', 'helper-selection-cancelled']],
                        [['choose', str(self.addon)], ['wrong', 'helper-selection-cancelled']]):
            with self.subTest(choices=len(choices)):
                result = self.run_launcher(choices)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Коды: verification-helper-selection-cancelled', result.stdout)
                self.assertEqual(self.runtime_events(), [])

    def test_native_picker_failure_is_not_reported_as_cancellation(self):
        result = self.run_launcher([['choose', 'NATIVE_ERROR']])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Коды: verification-helper-selection-failed', result.stdout)
        self.assertEqual(self.runtime_events(), [])

    def test_linked_helper_folder_is_rejected_before_runtime(self):
        linked = self.root / 'linked-helper'
        linked.symlink_to(self.helper, target_is_directory=True)
        result = self.run_launcher([['choose', str(linked)],
            ['wrong', 'helper-selection-cancelled']])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('verification-helper-selection-cancelled', result.stdout)
        self.assertEqual(self.runtime_events(), [])
        self.assertEqual(json.loads(self.dialogs.read_text()), ['choose', 'wrong'])

    def test_runtime_and_bootstrap_tampering_stop_before_probe_and_main(self):
        for kind in ('runtime', 'bootstrap'):
            with self.subTest(kind=kind):
                # Restore the two exact fixture sources before each independent run.
                self.create_helper(self.helper)
                self.bootstrap.write_text('// only a code fixture; never executed\n')
                result = self.run_launcher([['choose', str(self.helper)]],
                    bad_runtime=kind == 'runtime', bad_bootstrap=kind == 'bootstrap')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('verification-' + ('runtime-checksum' if kind == 'runtime' else 'source-checksum'), result.stdout)
                self.assertEqual(self.runtime_events(), [])

    def test_valid_sibling_uses_auto_detection_without_opening_picker(self):
        sibling = self.root / 'mac-private-backup-helper-v95'
        self.create_helper(sibling)
        result = self.run_launcher([], helper=sibling)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.runtime_events(), ['version', 'main'])
        self.assertFalse(self.dialogs.exists())


if __name__ == '__main__':
    unittest.main()
