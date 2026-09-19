import copy
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from openpyxl import Workbook
from runtime import atomic_json, read_json, exclusive
from pipeline import register, run, plan_path, now, save_evidence
from creator import complete_review
from parse_creator_export import parse_export, HEADER_ALIASES, find_columns


class FakeFeishu:
    def __init__(self):
        self.records = {}
        self.next_id = 0
        self.fail = False

    def ensure(self, table, key, value, fields):
        for (t, rid), row in self.records.items():
            if t == table and row.get(key) == value:
                return rid
        self.next_id += 1
        rid = 'synthetic-' + str(self.next_id)
        self.records[(table, rid)] = copy.deepcopy(fields)
        return rid

    def get(self, table, rid):
        return copy.deepcopy(self.records[(table, rid)])

    def write(self, table, rid, fields):
        if self.fail:
            raise ConnectionError('simulated network interruption')
        self.records[(table, rid)].update(copy.deepcopy(fields))
        return rid


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='新用户 空格 ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = {'data_dir': str(self.root), 'content_table_id': 'content', 'snapshot_table_id': 'snapshots'}
        self.api = FakeFeishu()
        self.actual = now().replace(microsecond=0)
        self.published = self.actual - timedelta(hours=12)
        proof = self.root / 'identity.txt'
        proof.write_text('synthetic creator metadata', encoding='utf-8')
        self.metadata = {'work_id': '1234567890123456789', 'title': '这是隔离测试作品',
            'source_url': 'https://www.douyin.com/video/1234567890123456789',
            'published_at': self.published.isoformat(), 'identity_evidence': str(proof), 'verified_in_creator_center': True}
        self.plan = register(self.config, self.metadata, self.api, self.actual)
        self.file = self.root / '作品列表.xlsx'
        self.book()
        self.collector = Mock(return_value=(self.file, self.actual))

    def book(self, duplicate=False, title=None, published=None, metric=None):
        book = Workbook()
        fields = list(HEADER_ALIASES)
        book.active.append([HEADER_ALIASES[k][0] for k in fields])
        data = {'title': title or self.metadata['title'], 'published_at': published or self.published.strftime('%Y-%m-%d %H:%M:%S'),
                '播放量': 1000, '点赞数': 20, '评论数': 4, '分享数': 5, '收藏数': 6, '涨粉数': 2, '主页访问': 8,
                '平均播放时长（秒）': 10, '完播率': '20%', '5秒完播率': '60%', '2秒跳出率': '10%', '封面点击率': None}
        if metric:
            data.update(metric)
        row = [data[k] for k in fields]
        book.active.append(row)
        if duplicate:
            book.active.append(row)
        book.save(self.file)
        book.close()

    def current(self):
        return read_json(plan_path(self.config, self.metadata['work_id']))

    def test_full_capture_then_no_second_click(self):
        result = run(self.config, self.metadata['work_id'], self.api, self.collector, self.actual)
        self.assertEqual(result['action'], 'captured_and_verified')
        run(self.config, self.metadata['work_id'], self.api, self.collector, self.actual)
        self.assertEqual(self.collector.call_count, 1)
        self.assertEqual(self.current()['nodes'][0]['base_sync_status'], 'success')

    def test_sync_failure_retries_without_recapture(self):
        self.api.fail = True
        with self.assertRaises(ConnectionError):
            run(self.config, self.metadata['work_id'], self.api, self.collector, self.actual)
        self.assertEqual(self.current()['nodes'][0]['status'], 'export_complete')
        self.api.fail = False
        run(self.config, self.metadata['work_id'], self.api, self.collector, self.actual)
        self.assertEqual(self.collector.call_count, 1)
        self.assertEqual(self.current()['nodes'][0]['status'], 'deep_complete')

    def test_duplicate_registration_does_not_reset_progress(self):
        run(self.config, self.metadata['work_id'], self.api, self.collector, self.actual)
        register(self.config, self.metadata, self.api, self.actual)
        self.assertEqual(len(self.api.records), 6)
        self.assertEqual(self.current()['nodes'][0]['status'], 'deep_complete')

    def test_export_uncertain_requires_human_not_auto_click(self):
        self.collector.side_effect = TimeoutError('timeout')
        with self.assertRaises(TimeoutError):
            run(self.config, self.metadata['work_id'], self.api, self.collector, self.actual)
        self.collector.side_effect = None
        run(self.config, self.metadata['work_id'], self.api, self.collector, self.actual)
        self.assertEqual(self.collector.call_count, 1)
        self.assertEqual(self.current()['nodes'][0]['status'], 'capture_uncertain')

    def test_crash_capturing_is_not_retried(self):
        plan = self.current()
        plan['nodes'][0]['status'] = 'capturing'
        atomic_json(plan_path(self.config, self.metadata['work_id']), plan)
        run(self.config, self.metadata['work_id'], self.api, self.collector, self.actual)
        self.collector.assert_not_called()

    def test_old_trigger_cannot_export_new_node(self):
        run(self.config, self.metadata['work_id'], self.api, self.collector, self.actual + timedelta(hours=12), expected_node='12小时')
        self.collector.assert_not_called()
        self.assertEqual(self.current()['nodes'][0]['status'], 'missed')

    def test_duplicate_identity_rejected(self):
        self.book(duplicate=True)
        with self.assertRaisesRegex(ValueError, 'AMBIGUOUS'):
            parse_export(self.file, self.plan, '12小时', self.actual)

    def test_partial_title_rejected(self):
        self.book(title=self.metadata['title'] + '不同内容')
        with self.assertRaisesRegex(ValueError, 'NOT_FOUND'):
            parse_export(self.file, self.plan, '12小时', self.actual)

    def test_different_second_rejected(self):
        self.book(published=(self.published + timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S'))
        with self.assertRaisesRegex(ValueError, 'NOT_FOUND'):
            parse_export(self.file, self.plan, '12小时', self.actual)

    def test_date_only_rejected(self):
        self.book(published=self.published.strftime('%Y-%m-%d'))
        with self.assertRaisesRegex(ValueError, 'NOT_FOUND'):
            parse_export(self.file, self.plan, '12小时', self.actual)

    def test_missing_metric_not_zero(self):
        self.book(metric={'播放量': None})
        with self.assertRaisesRegex(ValueError, 'MISSING_REQUIRED'):
            parse_export(self.file, self.plan, '12小时', self.actual)

    def test_evidence_tampering_rejected(self):
        node = self.plan['nodes'][0]
        save_evidence(self.config, self.plan, node, self.file, self.actual)
        Path(node['evidence']).write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'HASH_MISMATCH'):
            run(self.config, self.metadata['work_id'], self.api, self.collector, self.actual)
        self.collector.assert_not_called()

    def test_lock_rejects_parallel_writer(self):
        path = self.root / 'test.lock'
        with exclusive(path):
            with self.assertRaisesRegex(RuntimeError, 'BUSY'):
                with exclusive(path):
                    self.fail('second owner')
        with exclusive(path):
            pass

    def test_future_node_does_not_export(self):
        run(self.config, self.metadata['work_id'], self.api, self.collector, self.actual - timedelta(seconds=1))
        self.collector.assert_not_called()

    def test_review_cannot_complete_unverified_node(self):
        with self.assertRaisesRegex(ValueError, 'REVIEW_REQUIRES'):
            complete_review(self.config, {'work_id': self.metadata['work_id'], 'node': '72小时'}, self.api)

    def test_real_export_headers_do_not_confuse_completion_metrics(self):
        headers = ['作品名称', '发布时间', '体裁', '发布状态', '播放量', '完播率', '5s完播率', '作品时长', '2s跳出率', '平均播放时长', '点赞量', '评论量', '分享量', '收藏量', '主页访问量', '粉丝增量']
        fields = find_columns(headers)
        self.assertEqual(fields['完播率'], 5)
        self.assertEqual(fields['5秒完播率'], 6)
        self.assertEqual(fields['2秒跳出率'], 8)

    def test_remote_completed_node_never_recaptured(self):
        n = self.plan['nodes'][0]
        self.api.records[('snapshots', n['record_id'])]['执行状态'] = '成功'
        with self.assertRaisesRegex(ValueError, 'REMOTE_ALREADY_COMPLETE'):
            run(self.config, self.metadata['work_id'], self.api, self.collector, self.actual)
        self.collector.assert_not_called()

    def test_parse_failure_keeps_download_and_retry_uses_same_file(self):
        with patch('pipeline.parse_export', side_effect=ValueError('simulated parser failure')):
            with self.assertRaises(ValueError):
                run(self.config, self.metadata['work_id'], self.api, self.collector, self.actual)
        self.assertEqual(self.current()['nodes'][0]['status'], 'downloaded')
        run(self.config, self.metadata['work_id'], self.api, self.collector, self.actual)
        self.assertEqual(self.collector.call_count, 1)
        self.assertEqual(self.current()['nodes'][0]['status'], 'deep_complete')

    def test_all_five_nodes_with_explicit_simulated_clock(self):
        for node in self.plan['nodes']:
            actual = datetime.fromisoformat(node['planned_at'])
            self.book()
            os.utime(self.file, (actual.timestamp(), actual.timestamp()))
            self.collector.return_value = self.file, actual
            run(self.config, self.metadata['work_id'], self.api, self.collector, actual)
        self.assertEqual(self.collector.call_count, 5)
        self.assertTrue(all(n['status'] == 'deep_complete' for n in self.current()['nodes']))

    def test_mutated_plan_identity_rejected_before_export(self):
        plan = self.current()
        plan['work_id'] = '9999999999999999999'
        atomic_json(plan_path(self.config, self.metadata['work_id']), plan)
        with self.assertRaisesRegex(ValueError, 'PLAN_WORK_ID_CONFLICT'):
            run(self.config, self.metadata['work_id'], self.api, self.collector, self.actual)
        self.collector.assert_not_called()

    def test_review_uses_current_hash_and_does_not_overwrite_later_review(self):
        for node in self.plan['nodes']:
            actual = datetime.fromisoformat(node['planned_at'])
            self.book()
            os.utime(self.file, (actual.timestamp(), actual.timestamp()))
            self.collector.return_value = self.file, actual
            run(self.config, self.metadata['work_id'], self.api, self.collector, actual)
        plan = self.current()
        data = {'work_id': plan['work_id'], 'node': '7天', 'evidence_sha256': plan['nodes'][4]['evidence_sha256'], 'facts': '7d synthetic facts', 'inferences': 'synthetic inference', 'next_action': 'test only'}
        complete_review(self.config, data, self.api)
        data.update(node='72小时', evidence_sha256=plan['nodes'][3]['evidence_sha256'], facts='72h synthetic facts')
        result = complete_review(self.config, data, self.api)
        self.assertFalse(result['main_table_updated'])
        self.assertIn('7d synthetic', self.api.get('content', plan['content_record_id'])['复盘结论'])


if __name__ == '__main__': unittest.main()
