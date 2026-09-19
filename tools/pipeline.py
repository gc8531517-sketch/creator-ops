"""Five-node capture, durable evidence and idempotent Feishu synchronization."""
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from runtime import PACKAGE, atomic_json, read_json, exclusive, executable, chrome_path
from parse_creator_export import parse_export, BULK_REQUIRED, PERCENT_FIELDS
from bootstrap import NODES

OFFSETS = [12, 24, 48, 72, 168]
TERMINAL = {'deep_complete', 'missed', 'blocked'}


def now():
    return datetime.now(timezone(timedelta(hours=8)))


def timestamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('TIMEZONE_REQUIRED')
    return result


def ident(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{10,25}', value):
        raise ValueError('INVALID_WORK_ID')
    return value


def plan_path(config, work):
    return Path(config['data_dir']) / '.tmp/douyin-v4/plans' / (ident(work) + '.json')


def validate_plan(plan, work):
    if plan.get('work_id') != ident(work):
        raise ValueError('PLAN_WORK_ID_CONFLICT')
    nodes = plan.get('nodes', [])
    if [n.get('node') for n in nodes] != NODES:
        raise ValueError('PLAN_MUST_CONTAIN_FIVE_ORDERED_NODES')
    published = timestamp(plan['published_at'])
    for node, hours in zip(nodes, OFFSETS):
        if timestamp(node['planned_at']) != published + timedelta(hours=hours):
            raise ValueError('PLAN_NODE_TIME_CONFLICT')
        if node.get('status') not in {'pending', 'failed', 'blocked', 'missed', 'capturing', 'capture_uncertain', 'downloaded', 'export_complete', 'deep_complete'}:
            raise ValueError('PLAN_UNKNOWN_STATUS')
    if plan.get('registration_complete'):
        records = [n.get('record_id') for n in nodes]
        if not all(isinstance(r, str) and r for r in records) or len(set(records)) != 5:
            raise ValueError('PLAN_RECORD_IDS_INVALID')


def register(config, metadata, api, at=None):
    at = at or now()
    work = ident(metadata.get('work_id'))
    published = timestamp(metadata['published_at'])
    if published.utcoffset() != timedelta(hours=8):
        raise ValueError('PUBLISHED_AT_REQUIRES_CHINA_TIME_OFFSET')
    if published > at:
        raise ValueError('PUBLISHED_IN_FUTURE')
    if not metadata.get('title') or metadata.get('verified_in_creator_center') is not True:
        raise ValueError('CREATOR_CENTER_IDENTITY_VERIFICATION_REQUIRED')
    if not Path(metadata.get('identity_evidence', '')).is_file():
        raise ValueError('IDENTITY_EVIDENCE_FILE_REQUIRED')
    if not re.fullmatch(r'https://www\.douyin\.com/video/' + work + r'/?', metadata.get('source_url', '')):
        raise ValueError('CANONICAL_WORK_URL_REQUIRED')
    path = plan_path(config, work)
    if path.exists():
        plan = read_json(path)
        if any(plan[k] != metadata[k] for k in ('work_id', 'title', 'published_at', 'source_url')):
            raise ValueError('EXISTING_PLAN_IDENTITY_CONFLICT')
    else:
        plan = {k: metadata[k] for k in ('work_id', 'title', 'published_at', 'source_url')}
        plan['nodes'] = [{'node': n, 'planned_at': (published + timedelta(hours=h)).isoformat(), 'status': 'pending', 'attempts': 0,
                          'snapshot_name': plan['title'][:35] + ' · ' + work + '｜' + n} for n, h in zip(NODES, OFFSETS)]
        due = [n for n in plan['nodes'] if timestamp(n['planned_at']) <= at]
        for n in due[:-1]:
            n['status'] = 'missed'
        atomic_json(path, plan)
    initial = {'抖音作品ID': work, '视频标题': plan['title'], '作品链接': plan['source_url'], '发布时间': plan['published_at'], '采集状态': '待采集'}
    plan['content_record_id'] = api.ensure(config['content_table_id'], '抖音作品ID', work, initial)
    from feishu import equivalent
    content = api.get(config['content_table_id'], plan['content_record_id'])
    if any(not equivalent(content.get(k), initial[k]) for k in ('抖音作品ID', '视频标题', '作品链接', '发布时间')):
        raise ValueError('REMOTE_WORK_IDENTITY_CONFLICT')
    atomic_json(path, plan)
    for node in plan['nodes']:
        node['record_id'] = api.ensure(config['snapshot_table_id'], '快照键', work + '｜' + node['node'], base_fields(plan, node))
        atomic_json(path, plan)
    plan['registration_complete'] = True
    atomic_json(path, plan)
    return plan


def base_fields(plan, node, evidence=None):
    states = {'pending': '待采集', 'failed': '失败', 'downloaded': '失败', 'blocked': '被阻塞', 'missed': '已错过', 'capturing': '采集中', 'capture_uncertain': '被阻塞'}
    fields = {'快照键': plan['work_id'] + '｜' + node['node'], '抖音作品ID': plan['work_id'],
              '快照名称': node.get('snapshot_name', plan['title'][:50] + '｜' + node['node']), '采集节点': node['node'],
              '计划采集时间': node['planned_at'], '执行状态': states.get(node['status'], '待采集'),
              '数据完整度V2': '未读取', '最近错误': node.get('last_error')}
    if evidence is not None:
        if evidence.get('work_id') != plan['work_id'] or evidence.get('node') != node['node'] or evidence.get('planned_at') != node['planned_at']:
            raise ValueError('EVIDENCE_IDENTITY_CONFLICT')
        if evidence.get('ok') is not True or evidence.get('identity_match') != 'title+publish_time':
            raise ValueError('EVIDENCE_NOT_VERIFIED')
        metrics = evidence['metrics']
        if any(type(metrics.get(k)) not in (int, float) or not math.isfinite(metrics[k]) for k in BULK_REQUIRED):
            raise ValueError('INVALID_CORE_METRICS')
        for key, value in metrics.items():
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or (key in PERCENT_FIELDS and not 0 <= value <= 1)):
                raise ValueError('INVALID_METRIC')
            if value is not None and key not in PERCENT_FIELDS and value < 0:
                raise ValueError('NEGATIVE_METRIC')
        actual = timestamp(evidence['actual_at'])
        delay = (actual - timestamp(node['planned_at'])).total_seconds()
        if delay < 0:
            raise ValueError('CAPTURE_BEFORE_PLANNED_TIME')
        fields.update(metrics)
        fields.update({'实际采集时间': evidence['actual_at'], '执行状态': '延迟补采' if delay > 1800 else '成功',
                       '数据完整度V2': '核心指标完整；详情未读取', '最近错误': None,
                       '原始证据摘要': 'sha256:' + node['evidence_sha256']})
    return fields


def capture(config, job):
    cmd = [executable(config.get('pwsh_path'), 'pwsh'), '-NoProfile', '-File', str(PACKAGE / 'scripts/trigger-export.ps1'),
           '-JobId', job, '-DownloadDirectory', config['download_dir'], '-ChromePath', chrome_path(config)]
    proc = subprocess.run(cmd, capture_output=True, timeout=130)
    try:
        data = json.loads(proc.stdout.decode('utf-8-sig'))
    except (ValueError, UnicodeError):
        raise RuntimeError('EXPORT_OUTCOME_UNCERTAIN') from None
    if proc.returncode or data.get('ok') is not True:
        raise RuntimeError('EXPORT_OUTCOME_UNCERTAIN: check login, extension and downloads')
    return Path(data['new_excel']), timestamp(data['completed_at'])


def save_evidence(config, plan, node, path, actual):
    path = Path(path).resolve()
    age = actual.timestamp() - path.stat().st_mtime
    if not -5 <= age <= 180:
        raise ValueError('NOT_FRESH_EXPORT')
    evidence = parse_export(path, plan, node['node'], actual)
    destination = Path(config['data_dir']) / 'evidence' / (plan['work_id'] + '-' + str(OFFSETS[NODES.index(node['node'])]))
    destination.mkdir(parents=True, exist_ok=True)
    # Keep a durable input copy before any remote operation.
    if path.resolve() != (destination / 'export.xlsx').resolve():
        shutil.copy2(path, destination / 'export.xlsx')
    evidence['source']['xlsx'] = str(destination / 'export.xlsx')
    file = destination / 'evidence.json'
    atomic_json(file, evidence)
    node.update(status='export_complete', actual_at=actual.isoformat(), evidence=str(file),
                evidence_sha256=hashlib.sha256(file.read_bytes()).hexdigest())
    node.pop('last_error', None)
    atomic_json(plan_path(config, plan['work_id']), plan)


def synchronize(config, plan, node, api):
    path = Path(node['evidence'])
    if hashlib.sha256(path.read_bytes()).hexdigest() != node['evidence_sha256']:
        raise ValueError('EVIDENCE_HASH_MISMATCH')
    fields = base_fields(plan, node, read_json(path))
    existing = api.get(config['snapshot_table_id'], node['record_id'])
    from feishu import equivalent
    for key in ('快照键', '抖音作品ID', '采集节点', '计划采集时间'):
        if not equivalent(existing.get(key), fields[key]):
            raise ValueError('REMOTE_SNAPSHOT_IDENTITY_CONFLICT')
    if equivalent(existing.get('执行状态'), '已错过'):
        raise ValueError('CANNOT_OVERWRITE_MISSED_SNAPSHOT')
    if any(equivalent(existing.get('执行状态'), s) for s in ('成功', '延迟补采')):
        if not all(equivalent(existing.get(k), v) for k, v in fields.items()):
            raise ValueError('REMOTE_COMPLETED_EVIDENCE_CONFLICT')
    else:
        api.write(config['snapshot_table_id'], node['record_id'], fields)
    node.update(status='deep_complete', base_sync_status='success')
    atomic_json(plan_path(config, plan['work_id']), plan)


def repair_summary(config, plan, api):
    complete = [n for n in plan['nodes'] if n['status'] == 'deep_complete']
    review_nodes = [n for n in complete if n['node'] in ('72小时', '7天')]
    for n in review_nodes:
        marker = Path(config['data_dir']) / 'reviews' / (plan['work_id'] + '-' + str(NODES.index(n['node'])) + '.json')
        if not marker.exists():
            atomic_json(marker, {'work_id': plan['work_id'], 'node': n['node'], 'evidence_sha256': n['evidence_sha256'], 'state': 'pending_analysis'})
    pending = [n for n in review_nodes if not n.get('review_complete')]
    latest = complete[-1]['node'] if complete else ''
    state = '待复盘' if pending else ('已完成' if all(n['status'] in TERMINAL for n in plan['nodes']) else '采集中')
    api.write(config['content_table_id'], plan['content_record_id'], {'采集状态': state, '当前复盘节点': latest})


def run(config, work, api, collector=capture, at=None, expected_node=None):
    # One installation owns one Chrome profile/download directory. All works
    # serialize through the same OS lock; events may wait without exporting.
    with exclusive(Path(config['data_dir']) / 'capture.lock', timeout=480):
        path = plan_path(config, work)
        plan = read_json(path)
        validate_plan(plan, work)
        if not plan.get('registration_complete'):
            raise ValueError('REGISTRATION_INCOMPLETE')
        for node in plan['nodes']:
            if node['status'] == 'downloaded':
                receipt = node['download_receipt']
                exported = Path(receipt['path'])
                if hashlib.sha256(exported.read_bytes()).hexdigest() != receipt['sha256']:
                    raise ValueError('DOWNLOADED_FILE_HASH_MISMATCH')
                save_evidence(config, plan, node, exported, timestamp(receipt['actual_at']))
            if node['status'] == 'export_complete':
                synchronize(config, plan, node, api)
        at = at or now()
        due = [n for n in plan['nodes'] if timestamp(n['planned_at']) <= at]
        if not due:
            return {'action': 'none', 'reason': 'no_due_node'}
        latest = due[-1]
        for node in due[:-1]:
            if node['status'] in ('pending', 'failed', 'missed') and not node.get('missed_synced'):
                from feishu import equivalent
                previous_remote = api.get(config['snapshot_table_id'], node['record_id'])
                if any(equivalent(previous_remote.get('执行状态'), s) for s in ('成功', '延迟补采')):
                    raise ValueError('REMOTE_ALREADY_COMPLETE: restore local evidence instead of marking missed')
            if node['status'] in ('pending', 'failed'):
                node.update(status='missed', last_error='历史时点不可还原，未倒填当前累计值')
                atomic_json(path, plan)
            if node['status'] == 'missed' and not node.get('missed_synced'):
                api.write(config['snapshot_table_id'], node['record_id'], base_fields(plan, node))
                node['missed_synced'] = True
                atomic_json(path, plan)
        if expected_node and latest['node'] != expected_node:
            return {'action': 'none', 'reason': 'stale_exact_trigger'}
        if latest['status'] == 'capturing':
            latest.update(status='capture_uncertain', last_error='上次采集进程中断；请检查下载，不自动重复点击')
            atomic_json(path, plan)
        if latest['status'] not in ('pending', 'failed'):
            if latest['status'] in ('blocked', 'capture_uncertain'):
                api.write(config['snapshot_table_id'], latest['record_id'], base_fields(plan, latest))
            repair_summary(config, plan, api)
            return {'action': 'none', 'reason': latest['status']}
        from feishu import equivalent
        remote = api.get(config['snapshot_table_id'], latest['record_id'])
        expected = base_fields(plan, latest)
        if any(not equivalent(remote.get(k), expected[k]) for k in ('快照键', '抖音作品ID', '采集节点', '计划采集时间')):
            raise ValueError('REMOTE_SNAPSHOT_IDENTITY_CONFLICT')
        if any(equivalent(remote.get('执行状态'), s) for s in ('成功', '延迟补采', '已错过')):
            raise ValueError('REMOTE_ALREADY_COMPLETE: restore local evidence instead of recapturing')
        latest.update(status='capturing', attempts=latest.get('attempts', 0) + 1)
        atomic_json(path, plan)
        try:
            file, actual = collector(config, 'creator_' + uuid4().hex)
            stored = Path(config['data_dir']) / 'downloads' / (plan['work_id'] + '-' + str(NODES.index(latest['node'])) + '.xlsx')
            stored.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, stored)
            latest.update(status='downloaded', download_receipt={'path': str(stored), 'actual_at': actual.isoformat(), 'sha256': hashlib.sha256(stored.read_bytes()).hexdigest()})
            atomic_json(path, plan)
            save_evidence(config, plan, latest, stored, actual)
        except Exception as error:
            message = str(error)
            state = 'blocked' if 'TARGET_WORK_' in message else ('downloaded' if latest.get('download_receipt') else 'capture_uncertain')
            latest.update(status=state, last_error=message.split(':', 1)[0])
            atomic_json(path, plan)
            api.write(config['snapshot_table_id'], latest['record_id'], base_fields(plan, latest))
            raise
        # Never reclassify exported evidence as capture failure if sync fails.
        synchronize(config, plan, latest, api)
        repair_summary(config, plan, api)
        return {'action': 'captured_and_verified', 'node': latest['node']}
