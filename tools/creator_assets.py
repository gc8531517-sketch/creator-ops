"""Confirmed asset archive. No platform writes; no inferred user approval."""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from runtime import exclusive

ROOT = Path(__file__).resolve().parents[1]
KINDS = {'script': '01_文案', 'title': '01_文案', 'subtitle': '01_文案',
         'cover': '03_视觉资产/封面', 'video': '07_发布'}
START, END = '<!-- creator-assets:start -->', '<!-- creator-assets:end -->'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def atomic_text(path, content):
    temp = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        with temp.open('w', encoding='utf-8', newline='\n') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists(): temp.unlink()


@contextmanager
def locked(root):
    path = root / '视频资产/.creator-assets.lock'
    try:
        with exclusive(path):
            yield
    except RuntimeError as error:
        raise ValueError('归档正由其他进程执行，请稍后重试') from error


def folder_path(root, folder):
    if not folder or Path(folder).name != folder or folder in ('.', '..') or re.search(r'[<>:"|?*\x00-\x1f]', folder) or folder.endswith((' ', '.')):
        raise ValueError('folder必须是视频资产下的单层目录名')
    path = (root / '视频资产' / folder).resolve()
    if not path.is_relative_to((root / '视频资产').resolve()):
        raise ValueError('归档目录越界')
    return path


def load_manifest(folder):
    path = folder / '00_归档记录.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'schema_version': 1, 'work_id': None, 'assets': []}


def validate_index(root, folder, ident):
    index = root / '视频资产/作品关联索引.md'
    text = index.read_text(encoding='utf-8') if index.exists() else '# 作品关联索引\n'
    if ident:
        rows = [r for r in text.splitlines() if r.startswith('| ' + ident + ' |')]
        relative = (folder / '00_资产索引.md').relative_to(root).as_posix()
        if len(rows) > 1 or (rows and relative not in rows[0].replace('\\', '/')):
            raise ValueError('发布ID已关联其他目录或重复，先人工核对版本')
    return text


def refresh(root, folder, manifest):
    # Manifest is authoritative. A failed projection is repairable by repeating the command.
    page = folder / '00_资产索引.md'
    old = page.read_text(encoding='utf-8') if page.exists() else '# 作品资产索引\n'
    if old.count(START) != old.count(END) or old.count(START) > 1:
        raise ValueError('资产索引管理区损坏，保留原文件等待修复')
    lines = [START, '## 已确认成品归档记录', '',
             '以下为确认成品的版本记录；不等于这些版本已被发布采用。历史正文保留。', '']
    for item in manifest['assets']:
        lines += [f"- {item['kind']} / {item['version']}：`{item['archived_path']}`",
                  f"  - SHA256：{item['sha256']}；确认依据：{item['confirmation_ref']}；确认原话：{item['confirmation_quote']}"]
    lines += [END]
    block = '\n'.join(lines)
    if START in old:
        a, tail = old.split(START, 1)
        _, b = tail.split(END, 1)
        content = a + block + b
    else:
        content = old.rstrip() + '\n\n' + block + '\n'
    atomic_text(page, content)
    text = validate_index(root, folder, manifest['work_id'])
    reference = (folder / '00_资产索引.md').relative_to(root).as_posix()
    ident = manifest['work_id']
    needs_entry = (not any(r.startswith('| ' + ident + ' |') for r in text.splitlines())
                   if ident else reference not in text.replace('\\', '/'))
    if needs_entry:
        addition = (f'\n| {ident} | {folder.name} | `{reference}` | 已确认资产见索引；发布采用版本另核对 |\n'
                    if ident else f'\n- 未发布作品：`{reference}`\n')
        atomic_text(root / '视频资产/作品关联索引.md', text.rstrip() + '\n' + addition)


def archive(root, spec):
    required = ('folder', 'source', 'kind', 'version', 'confirmation_ref', 'confirmation_quote')
    if any(not isinstance(spec.get(k), str) or not spec[k].strip() for k in required):
        raise ValueError('缺少文件、作品目录、类型、版本或确认依据')
    if spec.get('confirmed') is not True:
        raise ValueError('没有明确的终稿确认，不归档')
    if spec['kind'] not in KINDS or not re.fullmatch(r'[A-Za-z0-9_-]{1,50}', spec['version']):
        raise ValueError('类型或版本格式不合法')
    ident = spec.get('work_id')
    if ident is not None and (not isinstance(ident, str) or not re.fullmatch(r'\d{10,25}', ident)):
        raise ValueError('作品ID必须是数字字符串，未发布用null')
    source = Path(spec['source']).resolve()
    if not source.is_file(): raise ValueError('源文件不存在')
    folder = folder_path(root, spec['folder'])
    with locked(root):
        validate_index(root, folder, ident)
        manifest = load_manifest(folder)
        if manifest['work_id'] is not None and ident != manifest['work_id']:
            raise ValueError('作品ID冲突，不重绑历史资料')
        fingerprint = digest(source)
        existing = [a for a in manifest['assets'] if a['kind'] == spec['kind'] and a['version'] == spec['version']]
        if existing:
            item = existing[0]
            if item['sha256'] != fingerprint:
                raise ValueError('同类型同版本内容发生变化，使用新版本并重新确认')
            saved = root / item['archived_path']
            if not saved.is_file() or digest(saved) != fingerprint:
                raise ValueError('已归档副本缺失或损坏，停止覆盖')
            if manifest['work_id'] is None and ident is not None:
                manifest['work_id'] = ident
                atomic_text(folder / '00_归档记录.json', json.dumps(manifest, ensure_ascii=False, indent=2))
            refresh(root, folder, manifest)
            return dict(status='already_archived', asset=item)
        destination = folder / KINDS[spec['kind']] / f"{spec['kind']}_{spec['version']}_{fingerprint[:12]}{source.suffix}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if digest(destination) != fingerprint: raise ValueError('目标文件冲突')
        else:
            temporary = destination.with_name(destination.name + '.' + uuid4().hex + '.tmp')
            try:
                shutil.copyfile(source, temporary)
                if digest(temporary) != fingerprint: raise ValueError('复制期间源文件变化，拒绝归档')
                os.replace(temporary, destination)
            finally:
                if temporary.exists(): temporary.unlink()
        item = {k: spec[k] for k in required if k not in ('folder', 'source')}
        item.update(source_path=str(source), archived_path=destination.relative_to(root).as_posix(),
                    sha256=fingerprint, archived_at=datetime.now(timezone.utc).isoformat())
        manifest['work_id'] = ident
        manifest['assets'].append(item)
        atomic_text(folder / '00_归档记录.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        refresh(root, folder, manifest)
        return dict(status='archived', asset=item)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['archive', 'inspect', 'repair'])
    parser.add_argument('input', help='archive使用确认清单JSON路径；inspect/repair使用作品目录名')
    args = parser.parse_args()
    try:
        if args.action == 'archive':
            result = archive(ROOT, json.loads(Path(args.input).read_text(encoding='utf-8-sig')))
        else:
            folder = folder_path(ROOT, args.input)
            result = load_manifest(folder)
            if args.action == 'repair':
                with locked(ROOT):
                    if not (folder / '00_归档记录.json').is_file(): raise ValueError('没有可恢复的归档记录')
                    refresh(ROOT, folder, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(2, str(exc) + '\n')


if __name__ == '__main__': main()
