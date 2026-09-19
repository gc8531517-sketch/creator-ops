"""Creator Ops entrypoint. No implicit upload, comment sending or predictions."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from runtime import PACKAGE, atomic_json, read_json, load_config, exclusive, executable, chrome_path, lark_command


def doctor(config):
    checks = {'python_311_plus': sys.version_info >= (3, 11), 'windows': os.name == 'nt'}
    for name, fn in [('pwsh', lambda: executable(config.get('pwsh_path'), 'pwsh')), ('chrome', lambda: chrome_path(config)), ('lark', lambda: lark_command(config))]:
        try:
            fn()
            checks[name] = True
        except ValueError:
            checks[name] = False
    for module in ('openpyxl', 'defusedxml'):
        try:
            __import__(module)
            checks[module] = True
        except ImportError:
            checks[module] = False
    checks['download_dir'] = Path(config['download_dir']).is_dir()
    checks['feishu_initialized'] = all(config.get(k) for k in ('base_token', 'content_table_id', 'snapshot_table_id', 'comments_table_id', 'dashboard_id'))
    return {'ok': all(checks.values()), 'checks': checks,
            'manual_checks': ['Chrome日常配置加载extension目录且登录正确账号', '飞书CLI已配置且选定身份可编辑专用Base', '电脑运行及用户登录时才可采集'],
            'note': '环境检测不等于实际端到端验收'}


def complete_review(config, data, api):
    from pipeline import plan_path, NODES, repair_summary
    work, node_name = data['work_id'], data['node']
    plan = read_json(plan_path(config, work))
    node = next(n for n in plan['nodes'] if n['node'] == node_name)
    if node_name not in ('72小时', '7天') or node['status'] != 'deep_complete':
        raise ValueError('REVIEW_REQUIRES_VERIFIED_72H_OR_7D')
    if data.get('evidence_sha256') != node['evidence_sha256']:
        raise ValueError('STALE_REVIEW_EVIDENCE')
    for key in ('facts', 'inferences', 'next_action'):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError('REVIEW_FIELD_REQUIRED:' + key)
    marker = Path(config['data_dir']) / 'reviews' / (work + '-' + str(NODES.index(node_name)) + '.json')
    # Durable analysis saved before writeback. The same payload can be retried.
    atomic_json(marker, {**data, 'state': 'pending_writeback'})
    later_review = any(n.get('review_complete') for n in plan['nodes'][NODES.index(node_name) + 1:])
    if not later_review:
        api.write(config['content_table_id'], plan['content_record_id'], {'复盘结论': '事实：\n' + data['facts'] + '\n推断：\n' + data['inferences'], '下一步动作': data['next_action']})
    node['review_complete'] = True
    atomic_json(plan_path(config, work), plan)
    repair_summary(config, plan, api)
    atomic_json(marker, {**data, 'state': 'analysis_complete'})
    return {'ok': True, 'analysis_saved': True, 'main_table_updated': not later_review}


def sync_comments(config, work, source, api):
    import creator_ops
    pack = creator_ops.comment_pack(Path(config['data_dir']), work, source)
    raw = read_json(Path(config['data_dir']) / source)
    count = 0
    for comment in raw['comments']:
        key = hashlib.sha256((work + '\n' + comment['id']).encode()).hexdigest()
        values = {'评论键': key, '抖音作品ID': work, '原评论': comment['text'],
                  '回复草稿': comment.get('reply_draft', ''), '来源': raw['source'],
                  '采集时间': raw['captured_at'], '状态': '未发送草稿', '模拟数据': raw['demo']}
        table = config['comments_table_id']
        record = api.ensure(table, '评论键', key, values)
        api.write(table, record, values)
        count += 1
    return {'ok': True, 'drafts_synced': count, 'sending_available': False}


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=str(PACKAGE / 'config.local.json'))
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('init-config')
    sub.add_parser('doctor')
    sub.add_parser('list')
    p = sub.add_parser('init-feishu'); p.add_argument('--name', default='Creator Ops 验收工作区')
    p = sub.add_parser('register'); p.add_argument('metadata')
    p = sub.add_parser('run'); p.add_argument('work_id'); p.add_argument('--expected-node')
    p = sub.add_parser('schedule'); p.add_argument('work_id'); p.add_argument('--apply', action='store_true')
    p = sub.add_parser('review'); p.add_argument('work_id')
    p = sub.add_parser('compare'); p.add_argument('work_id'); p.add_argument('other_id'); p.add_argument('--node', required=True)
    p = sub.add_parser('complete-review'); p.add_argument('input')
    p = sub.add_parser('comments'); p.add_argument('work_id'); p.add_argument('input'); p.add_argument('--sync-feishu', action='store_true')
    p = sub.add_parser('archive'); p.add_argument('input')
    p = sub.add_parser('reset-capture'); p.add_argument('work_id'); p.add_argument('--node', required=True); p.add_argument('--reason', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'init-config':
            file = Path(args.config).resolve()
            if file.exists():
                raise ValueError('CONFIG_EXISTS_NOT_OVERWRITTEN')
            atomic_json(file, read_json(PACKAGE / 'config.example.json'))
            result = {'ok': True, 'next': 'configure lark-cli and local config, then init-feishu'}
        else:
            config = load_config(args.config)
            root = Path(config['data_dir'])
            root.mkdir(parents=True, exist_ok=True)
            from feishu import Feishu
            from pipeline import register, run, plan_path
            import creator_ops
            if args.command == 'doctor':
                result = doctor(config)
            elif args.command == 'list':
                result = {'works': [{k: read_json(p).get(k) for k in ('work_id', 'title', 'published_at')} for p in sorted((root / '.tmp/douyin-v4/plans').glob('*.json'))], 'scope': '本地已登记作品，不代表账号全部作品'}
            elif args.command == 'run':
                result = run(config, args.work_id, Feishu(config), expected_node=args.expected_node)
            elif args.command == 'review':
                result = creator_ops.review(root, args.work_id)
            elif args.command == 'compare':
                result = creator_ops.compare(root, args.work_id, args.other_id, args.node)
            elif args.command == 'comments' and not args.sync_feishu:
                result = creator_ops.comment_pack(root, args.work_id, args.input)
            elif args.command == 'schedule':
                command = [executable(config.get('pwsh_path'), 'pwsh'), '-NoProfile', '-File', str(PACKAGE / 'scripts/schedule.ps1'), '-ConfigPath', config['_path'], '-PlanPath', str(plan_path(config, args.work_id)), '-PythonPath', sys.executable]
                if args.apply:
                    command.append('-Apply')
                completed = subprocess.run(command, capture_output=True, timeout=60)
                if completed.returncode:
                    raise RuntimeError('SCHEDULE_FAILED: inspect permissions and config')
                result = json.loads(completed.stdout.decode('utf-8-sig'))
            else:
                with exclusive(root / 'capture.lock', timeout=0):
                    api = Feishu(config)
                    if args.command == 'init-feishu':
                        from bootstrap import provision
                        result = provision(config, api, args.name)
                    elif args.command == 'register':
                        p = register(config, read_json(args.metadata), api)
                        result = {'ok': True, 'work_id': p['work_id'], 'node_count': len(p['nodes']), 'next': 'schedule (preview), then schedule --apply'}
                    elif args.command == 'complete-review':
                        result = complete_review(config, read_json(args.input), api)
                    elif args.command == 'comments':
                        result = sync_comments(config, args.work_id, args.input, api)
                    elif args.command == 'archive':
                        import creator_assets
                        result = creator_assets.archive(root, read_json(args.input))
                    elif args.command == 'reset-capture':
                        p = read_json(plan_path(config, args.work_id))
                        n = next(n for n in p['nodes'] if n['node'] == args.node)
                        if n['status'] not in ('capture_uncertain', 'blocked') or not args.reason.strip():
                            raise ValueError('RESET_REQUIRES_BLOCKED_STATE_AND_HUMAN_REASON')
                        n.setdefault('reset_history', []).append({'previous': n['status'], 'reason': args.reason})
                        n.update(status='pending', last_error=None)
                        atomic_json(plan_path(config, args.work_id), p)
                        result = {'ok': True, 'note': '已解除本地阻塞；未触发采集'}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get('ok', True) else 1
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=True))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
