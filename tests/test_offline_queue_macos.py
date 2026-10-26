"""Darwin adapter contracts through mocks; native Mac selftest remains required."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OfflineMacAdapter(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is required for adapter contracts')
    def test_synthetic_macos_api_contracts(self):
        result = subprocess.run(
            ['node', '--test', str(ROOT / 'tests/test_offline_queue_macos.cjs')],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + '\n' + result.stderr)


if __name__ == '__main__':
    unittest.main()
