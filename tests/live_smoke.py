"""Opt-in Feishu integration test. Creates synthetic data ONLY in a dedicated Base."""
import argparse
import json
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from runtime import load_config, atomic_json, read_json, exclusive
from feishu import Feishu
from pipeline import register, run, now, plan_path
from creator import complete_review
from openpyxl import Workbook
from parse_creator_export import HEADER_ALIASES


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--execute-in-dedicated-test-base', action='store_true', required=True)
    args = parser.parse_args()
    config = load_config(args.config)
    api = Feishu(config)
    root = Path(config['data_dir'])
    with exclusive(root / 'capture.lock'):
        work = '1' + str(time.time_ns())[-18:]
        actual = now().replace(microsecond=0)
        published = actual - timedelta(hours=72)
        folder = root / 'live-test' / work
        folder.mkdir(parents=True)
        proof = folder / 'synthetic-identity.json'
        atomic_json(proof, {'demo': True, 'note': '合成验收数据，不是真实作品'})
        metadata = {'work_id': work, 'title': '[模拟验收] Creator Ops', 'published_at': published.isoformat(),
                    'source_url': 'https://www.douyin.com/video/' + work, 'verified_in_creator_center': True, 'identity_evidence': str(proof)}
        plan = register(config, metadata, api, actual)
        book = Workbook()
        fields = list(HEADER_ALIASES)
        book.active.append([HEADER_ALIASES[k][0] for k in fields])
        values = {'title': metadata['title'], 'published_at': published.strftime('%Y-%m-%d %H:%M:%S'),
                  '播放量': 1000, '点赞数': 40, '评论数': 10, '分享数': 5, '收藏数': 20, '涨粉数': 3, '主页访问': 8,
                  '平均播放时长（秒）': 12, '完播率': '20%', '5秒完播率': '60%', '2秒跳出率': '10%', '封面点击率': None}
        book.active.append([values[k] for k in fields])
        xlsx = folder / 'synthetic.xlsx'
        book.save(xlsx)
        book.close()
    calls = []
    def collector(*_):
        calls.append(True)
        return xlsx, now()
    first = run(config, work, api, collector, actual)
    second = run(config, work, api, collector, actual)
    assert len(calls) == 1
    plan = read_json(plan_path(config, work))
    node = plan['nodes'][3]
    review = {'work_id': work, 'node': '72小时', 'evidence_sha256': node['evidence_sha256'],
              'facts': '合成验收数据：播放1000。', 'inferences': '模拟数据不支持任何账号结论。', 'next_action': '验收后不使用模拟数据进行账号分析。'}
    with exclusive(root / 'capture.lock'):
        complete_review(config, review, api)
    comments = {'work_id': work, 'source': 'synthetic integration test', 'captured_at': actual.isoformat(), 'demo': True,
                'comments': [{'id': 'synthetic-comment', 'text': '这是模拟问题', 'reply_draft': '这是未发送的模拟回复'}]}
    atomic_json(folder / 'comments.json', comments)
    from creator import sync_comments
    with exclusive(root / 'capture.lock'):
        comment_result = sync_comments(config, work, str((folder / 'comments.json').relative_to(root)), api)
    result = {'ok': True, 'synthetic': True, 'real_chrome_tested': False,
              'register': 'passed', 'capture_parse_write_readback': first['action'],
              'duplicate_execution': second['reason'], 'export_calls': len(calls),
              'review_writeback': 'passed', 'comment_drafts': comment_result['drafts_synced']}
    atomic_json(root / 'live-test-result.json', result)
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == '__main__': main()
