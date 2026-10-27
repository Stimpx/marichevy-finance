"""Exercise the real launcher result handler with code-only child processes.

No macOS tools, runtime download, browser profile, or backup is involved. Only
the platform-specific preflight is bypassed; the checked-in completion function
and child-exit handler run unchanged in Bash, including a real SIGKILL.
"""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / 'tools/private_verify/Start Mac verification.command'
PRIVATE_MARKER = 'FICTIONAL_PRIVATE_ERROR_MUST_NOT_BE_PRINTED'
CHILD = '''import os, signal, sys
stage, version_mode, main_mode = sys.argv[1:]
mode = version_mode if stage == 'version' else main_mode
if stage == 'main':
    print('FIXTURE_MAIN_STARTED', flush=True)
if mode == 'kill':
    os.kill(os.getpid(), signal.SIGKILL)
if stage == 'version':
    if mode == 'ok':
        print('v22.23.4', flush=True)
        sys.exit(0)
    sys.stderr.write('FICTIONAL_PRIVATE_ERROR_MUST_NOT_BE_PRINTED')
    sys.exit(int(mode))
normal = {'passed': (0, 'passed', 'none'),
          'failed': (1, 'failed', 'fixture-check-failed'),
          'review': (2, 'review_required', 'fixture-review-required')}
if mode in normal:
    status, outcome, code = normal[mode]
    print('Результат: ' + outcome, flush=True)
    print('Коды: ' + code, flush=True)
    sys.exit(status)
sys.stderr.write('FICTIONAL_PRIVATE_ERROR_MUST_NOT_BE_PRINTED')
sys.exit(int(mode))
'''


class PrivateVerificationLauncherSignal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bash = shutil.which('bash')
        if cls.bash is None:
            raise unittest.SkipTest('Bash required for actual launcher execution')
        source = LAUNCHER.read_text()
        platform_gate = '\nif [ "$(/usr/bin/uname -s)" != Darwin ]; then'
        if source.count(platform_gate) != 1:
            raise AssertionError('Review launcher preflight boundary before testing')
        version_command = re.findall(r'^/usr/bin/env -i PATH=.*LANG=.*\$task_node.* --version.*$', source, re.M)
        main_command = re.findall(r'^/usr/bin/env -i PATH=.*LANG=.*\$task_node.*\$task_bootstrap.*$', source, re.M)
        if len(version_command) != 1 or len(main_command) != 1:
            raise AssertionError('Review launcher child invocation before testing')
        # Preserve the production completion function and complete status tail.
        # Positional arguments avoid interpolating shell paths or child text.
        stage = "printf '%s\\n' 'Этап: запуск среды программы'"
        if source.count(stage) != 1:
            raise AssertionError('Review launcher runtime probe before testing')
        cls.program = source.split(platform_gate, 1)[0] + '\n' + source[source.index(stage):]
        cls.program = cls.program.replace(version_command[0],
            '"$1" "$2" version "$3" "$4" >/dev/null 2>/dev/null', 1)
        cls.program = cls.program.replace(main_command[0],
            '"$1" "$2" main "$3" "$4" 2>/dev/null', 1)

    def run_child(self, mode, version_mode='ok'):
        with tempfile.TemporaryDirectory(prefix='fictional-launcher-signal-') as folder:
            script = Path(folder) / 'launcher-test.command'
            child = Path(folder) / 'child.py'
            script.write_text(self.program)
            child.write_text(CHILD)
            result = subprocess.run([self.bash, '-p', str(script), sys.executable, str(child), version_mode, mode],
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10)
        self.assertNotIn(PRIVATE_MARKER, result.stdout + result.stderr)
        self.assertNotIn('Сверка завершена.', result.stdout,
            'process completion must not claim the verification completed')
        self.assertIn('Работа программы завершена.', result.stdout)
        return result

    def test_normal_application_outcomes_are_preserved_without_duplicate_results(self):
        for mode, status, outcome, code in (
                ('passed', 0, 'passed', 'none'),
                ('failed', 1, 'failed', 'fixture-check-failed'),
                ('review', 2, 'review_required', 'fixture-review-required')):
            with self.subTest(mode=mode):
                result = self.run_child(mode)
                self.assertEqual(result.returncode, status)
                self.assertEqual(result.stdout.count('Результат:'), 1)
                self.assertEqual(result.stdout.count('Коды:'), 1)
                self.assertIn('Результат: ' + outcome, result.stdout)
                self.assertIn('Коды: ' + code, result.stdout)
                self.assertNotIn('verification-process-', result.stdout)
                self.assertIn('FIXTURE_MAIN_STARTED', result.stdout)

    def test_failed_runtime_probe_stops_before_main_or_file_selection(self):
        for mode, status, code in (('kill', 137, 'verification-runtime-signal-9'),
                                  ('7', 7, 'verification-runtime-start-failed')):
            with self.subTest(mode=mode):
                result = self.run_child('passed', version_mode=mode)
                self.assertEqual(result.returncode, status)
                self.assertIn('Этап: запуск среды программы', result.stdout)
                self.assertEqual(result.stdout.count('Результат:'), 1)
                self.assertEqual(result.stdout.count('Коды:'), 1)
                self.assertIn('Результат: failed', result.stdout)
                self.assertIn('Коды: ' + code, result.stdout)
                self.assertNotIn('FIXTURE_MAIN_STARTED', result.stdout)
                self.assertNotIn('Проверяем файлы программы.', result.stdout)

    def test_real_sigkill_has_a_fixed_failure_receipt_and_keeps_status_137(self):
        result = self.run_child('kill')
        self.assertEqual(result.returncode, 137)
        self.assertEqual(result.stdout.count('Результат:'), 1)
        self.assertEqual(result.stdout.count('Коды:'), 1)
        self.assertIn('Результат: failed', result.stdout)
        self.assertIn('Коды: verification-process-signal-9', result.stdout)
        self.assertIn('FIXTURE_MAIN_STARTED', result.stdout)

    def test_other_unexpected_child_exits_get_a_fixed_public_failure_code(self):
        for status in (7, 126, 130):
            with self.subTest(status=status):
                result = self.run_child(str(status))
                self.assertEqual(result.returncode, status)
                self.assertEqual(result.stdout.count('Результат:'), 1)
                self.assertEqual(result.stdout.count('Коды:'), 1)
                self.assertIn('Результат: failed', result.stdout)
                self.assertIn('Коды: verification-process-unexpected-exit', result.stdout)


if __name__ == '__main__':
    unittest.main()
