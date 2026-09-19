import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from feishu import Feishu, LarkError, equivalent


class FeishuTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.api = Feishu({'data_dir': self.temp.name})
        self.api.fields_cache['table'] = {'key': 'field_key', 'views': 'field_views'}

    def test_duplicate_key_stops(self):
        self.api.rows = Mock(return_value=[('a', {}), ('b', {})])
        with self.assertRaisesRegex(LarkError, 'DUPLICATE'):
            self.api.find('table', 'key', 'x')

    def test_create_timeout_is_not_blindly_repeated(self):
        self.api.find = Mock(return_value=None)
        self.api.call = Mock(side_effect=LarkError('timeout'))
        with self.assertRaises(LarkError):
            self.api.ensure('table', 'key', 'x', {'key': 'x'})
        with self.assertRaisesRegex(LarkError, 'CREATE_OUTCOME_UNCERTAIN'):
            self.api.ensure('table', 'key', 'x', {'key': 'x'})
        self.assertEqual(self.api.call.call_count, 1)

    def test_remote_created_after_timeout_is_reused(self):
        self.api.find = Mock(return_value=('existing', {'key': 'x'}))
        self.api.call = Mock()
        self.assertEqual(self.api.ensure('table', 'key', 'x', {'key': 'x'}), 'existing')
        self.api.call.assert_not_called()

    def test_write_only_once_readback_retried(self):
        self.api.call = Mock(return_value={})
        self.api.get = Mock(side_effect=[{'views': 1}, {'views': 2}])
        with patch('feishu.time.sleep'):
            self.api.write('table', 'record', {'views': 2})
        self.assertEqual(self.api.call.call_count, 1)
        self.assertEqual(self.api.get.call_count, 2)

    def test_readback_mismatch_fails(self):
        self.api.call = Mock(return_value={})
        self.api.get = Mock(return_value={'views': None})
        with patch('feishu.time.sleep'), self.assertRaisesRegex(LarkError, 'MISMATCH'):
            self.api.write('table', 'record', {'views': 0})

    def test_missing_is_not_zero(self):
        self.assertFalse(equivalent(None, 0))
        self.assertFalse(equivalent(False, 0))
        self.assertFalse(equivalent(float('nan'), 0))
        self.assertTrue(equivalent(['成功'], '成功'))

    def test_unknown_field_rejected_before_write(self):
        self.api.call = Mock()
        with self.assertRaisesRegex(LarkError, 'UNKNOWN_WRITE_FIELDS'):
            self.api.write('table', 'record', {'private': 'x'})
        self.api.call.assert_not_called()

    def test_matrix_wrong_record_rejected(self):
        self.api.call = Mock(return_value={'record_id_list': ['other'], 'data': [[]], 'field_id_list': []})
        with self.assertRaisesRegex(LarkError, 'READBACK_RECORD'):
            self.api.get('table', 'requested')


if __name__ == '__main__': unittest.main()
