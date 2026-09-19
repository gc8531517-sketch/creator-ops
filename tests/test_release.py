import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import release_check as release


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.allowed = patch.object(release, 'ALLOWED', {'README.md'})
        self.allowed.start()
        self.addCleanup(self.allowed.stop)
        (self.root / 'README.md').write_text('safe public text', encoding='utf-8')

    def test_unknown_file_fails_closed(self):
        (self.root / 'private.pem').write_text('not public', encoding='utf-8')
        self.assertFalse(release.inspect(self.root)['scan_ok'])

    def test_runtime_is_not_part_of_public_manifest(self):
        (self.root / 'runtime').mkdir()
        (self.root / 'runtime' / 'private.json').write_text('private', encoding='utf-8')
        report = release.inspect(self.root)
        self.assertTrue(report['scan_ok'])
        self.assertEqual([x['file'] for x in report['files']], ['README.md'])

    def test_personal_path_fails_without_echoing_content(self):
        secret = 'C:' + '\\' + 'Users' + '\\' + 'synthetic-person' + '\\' + 'data'
        (self.root / 'README.md').write_text(secret, encoding='utf-8')
        result = release.inspect(self.root)
        self.assertFalse(result['scan_ok'])
        self.assertNotIn('synthetic-person', str(result))

    def test_missing_file_fails(self):
        (self.root / 'README.md').unlink()
        self.assertFalse(release.inspect(self.root)['scan_ok'])

    def test_scan_never_grants_publication_approval(self):
        self.assertFalse(release.inspect(self.root)['publication_approved'])


if __name__ == '__main__': unittest.main()
