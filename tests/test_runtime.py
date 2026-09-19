import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from runtime import atomic_json, load_config, exclusive, read_json


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='新安装 空格 ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_config_is_relative_to_its_own_location(self):
        path = self.root / 'config.json'
        atomic_json(path, {'schema_version': 1, 'data_dir': 'data'})
        self.assertEqual(load_config(path)['data_dir'], str(self.root / 'data'))

    def test_credentials_not_accepted(self):
        path = self.root / 'config.json'
        atomic_json(path, {'schema_version': 1, 'app_secret': 'synthetic'})
        with self.assertRaisesRegex(ValueError, 'CREDENTIALS'):
            load_config(path)

    def test_crashed_process_releases_lock(self):
        tools = Path(__file__).resolve().parents[1] / 'tools'
        lock = self.root / 'crash.lock'
        code = "import sys,os; sys.path.insert(0,sys.argv[1]); from runtime import exclusive; " + "\nwith exclusive(sys.argv[2]): os._exit(0)"
        subprocess.run([sys.executable, '-c', code, str(tools), str(lock)], check=True, timeout=15)
        with exclusive(lock):
            pass

    def test_atomic_json_rejects_nan_preserving_original(self):
        path = self.root / 'data.json'
        atomic_json(path, {'value': 1})
        with self.assertRaises(ValueError): atomic_json(path, {'value': float('nan')})
        self.assertEqual(read_json(path), {'value': 1})


if __name__ == '__main__': unittest.main()
