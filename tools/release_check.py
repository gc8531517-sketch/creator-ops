"""Fail-closed public-file allowlist. Never prints matched sensitive contents."""
import hashlib
import json
import re
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {
    'README.md', '.gitignore', 'docs/RELEASE_REVIEW.md', 'AGENTS.md',
    'LICENSE', 'SECURITY.md', 'CONTRIBUTING.md', 'CHANGELOG.md',
    'requirements.txt', 'config.example.json', '.github/workflows/tests.yml',
    'docs/INSTALL.md', 'docs/TROUBLESHOOTING.md', 'docs/PROVENANCE.md',
    'docs/ACCEPTANCE.md',
    'examples/metadata.example.json', 'examples/review.example.json',
    'examples/comments.example.json', 'examples/asset.example.json',
    'extension/manifest.json', 'extension/background.js', 'extension/content.js', 'extension/export_core.js',
    'scripts/setup.ps1', 'scripts/schedule.ps1', 'scripts/trigger-export.ps1',
    'tests/extension/export_core.test.js', 'tests/extension/background.test.js',
    'tests/test_pipeline.py', 'tests/test_feishu.py', 'tests/test_release.py', 'tests/test_runtime.py',
    'tests/live_smoke.py', 'tests/scheduler_smoke.py', 'tests/cleanup_test_tasks.ps1',
    'tools/runtime.py', 'tools/feishu.py', 'tools/bootstrap.py', 'tools/pipeline.py',
    'tools/creator.py', 'tools/task_launcher.py', 'tools/parse_creator_export.py', 'tools/package_review.py',
    'tools/creator_ops.py', 'tools/creator_assets.py', 'tools/creator_reply_ledger.py',
    'tools/test_creator_ops.py', 'tools/test_creator_assets.py',
    'tools/test_creator_reply_ledger.py', 'tools/release_check.py',
}
PATTERNS = {
    'private_key': re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
    'personal_windows_path': re.compile(r'[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s]+', re.I),
    'platform_work_id': re.compile(r'(?<!\d)7\d{18}(?!\d)'),
    'feishu_base_url': re.compile(r'https://[^\s/]+\.feishu\.cn/base/\w+'),
    'thread_id': re.compile(r'\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b'),
    'credential_assignment': re.compile(r'(?i)(?:appSecret|accessToken|api_key|password)\s*[=:]\s*[\"\x27][A-Za-z0-9_+/=-]{16,}'),
}
EXCLUDED_DIRS = {'.git', '.venv', '__pycache__', 'runtime', '.tmp'}
EXCLUDED_FILES = {'config.local.json'}

def inspect(root=ROOT):
    failures, files = [], []
    paths = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in dirs:
            p = Path(directory) / name
            if p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()):
                failures.append({'file': p.relative_to(root).as_posix(), 'reason': 'linked_directory'})
        dirs[:] = [n for n in dirs if n not in EXCLUDED_DIRS]
        paths.extend(Path(directory) / name for name in names)
    for path in sorted(paths):
        relative = path.relative_to(root)
        if relative.as_posix() in EXCLUDED_FILES:
            continue
        name = relative.as_posix()
        if path.is_symlink() or name not in ALLOWED:
            failures.append({'file': name, 'reason': 'not_allowlisted_or_symlink'})
            continue
        raw = path.read_bytes()
        try:
            content = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            failures.append({'file': name, 'reason': 'non_text'})
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(content):
                failures.append({'file': name, 'reason': label})
        files.append({'file': name, 'sha256': hashlib.sha256(raw).hexdigest()})
    present = {entry['file'] for entry in files}
    for missing in sorted(ALLOWED - present):
        failures.append({'file': missing, 'reason': 'missing_required_public_file'})
    return {'scan_ok': not failures, 'publication_approved': False,
            'scope': 'working tree only; manual review and Git-history audit still required',
            'failures': failures, 'files': files}

if __name__ == '__main__':
    result = inspect()
    print(json.dumps(result, ensure_ascii=True, indent=2))
    raise SystemExit(0 if result['scan_ok'] else 1)
