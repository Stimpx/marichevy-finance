"""Windows API contracts tested through injected APIs; no native Windows claim."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OfflineWindowsAdapter(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is required for the API contract fixtures')
    def test_synthetic_windows_api_contracts(self):
        result = subprocess.run(['node','--test',str(ROOT/'tests/test_offline_queue_windows.cjs')],
                                capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)


if __name__ == '__main__':
    unittest.main()
