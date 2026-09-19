import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import creator_assets as ca


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'final.md'
        self.source.write_text('测试终稿，不是真实作品', encoding='utf-8')
        self.spec = dict(folder='待发布_2026-09-12_隔离测试', source=str(self.source),
                         kind='script', version='v1', confirmed=True, work_id=None,
                         confirmation_ref='test fixture only', confirmation_quote='测试确认')

    def test_archive_and_idempotency(self):
        a = ca.archive(self.root, self.spec)
        b = ca.archive(self.root, self.spec)
        self.assertEqual(a['status'], 'archived')
        self.assertEqual(b['status'], 'already_archived')
        self.assertEqual((self.root / a['asset']['archived_path']).read_bytes(), self.source.read_bytes())
        self.assertEqual(len(ca.load_manifest(ca.folder_path(self.root, self.spec['folder']))['assets']), 1)

    def test_reject_unconfirmed(self):
        self.spec['confirmed'] = False
        with self.assertRaises(ValueError): ca.archive(self.root, self.spec)

    def test_same_version_changed(self):
        ca.archive(self.root, self.spec)
        self.source.write_text('changed', encoding='utf-8')
        with self.assertRaises(ValueError): ca.archive(self.root, self.spec)

    def test_new_version_preserves_old(self):
        first = ca.archive(self.root, self.spec)
        self.source.write_text('new', encoding='utf-8')
        self.spec['version'] = 'v2'
        second = ca.archive(self.root, self.spec)
        self.assertNotEqual(first['asset']['archived_path'], second['asset']['archived_path'])
        self.assertTrue((self.root / first['asset']['archived_path']).exists())

    def test_repair_after_projection_failure(self):
        with patch.object(ca, 'refresh', side_effect=OSError('test failure')):
            with self.assertRaises(OSError): ca.archive(self.root, self.spec)
        result = ca.archive(self.root, self.spec)
        self.assertEqual(result['status'], 'already_archived')
        self.assertIn(ca.START, (ca.folder_path(self.root, self.spec['folder']) / '00_资产索引.md').read_text(encoding='utf-8'))

    def test_bind_published_id(self):
        ca.archive(self.root, self.spec)
        self.spec['work_id'] = '1234567890123456789'
        ca.archive(self.root, self.spec)
        self.assertIn('| 1234567890123456789 |', (self.root / '视频资产/作品关联索引.md').read_text(encoding='utf-8'))

    def test_missing_source(self):
        self.spec['source'] = str(self.root / 'missing')
        with self.assertRaises(ValueError): ca.archive(self.root, self.spec)

    def test_preserves_manual_index(self):
        folder = ca.folder_path(self.root, self.spec['folder'])
        folder.mkdir(parents=True)
        index = folder / '00_资产索引.md'
        index.write_text('# 历史正文\n不能覆盖\n', encoding='utf-8')
        ca.archive(self.root, self.spec)
        self.assertTrue(index.read_text(encoding='utf-8').startswith('# 历史正文\n不能覆盖'))

    def test_lock_rejects_concurrent_writer(self):
        with ca.locked(self.root):
            with self.assertRaises(ValueError): ca.archive(self.root, self.spec)

    def test_folder_escape(self):
        self.spec['folder'] = '../outside'
        with self.assertRaises(ValueError): ca.archive(self.root, self.spec)


if __name__ == '__main__': unittest.main()
