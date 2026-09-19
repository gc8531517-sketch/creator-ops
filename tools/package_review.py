"""Build a deterministic allowlisted review ZIP. Never uploads or runs git."""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path
from release_check import ROOT, inspect


def build(output):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('OUTPUT_EXISTS_NOT_OVERWRITTEN')
    if output.is_relative_to(ROOT):
        raise ValueError('REVIEW_ARCHIVE_MUST_BE_OUTSIDE_SOURCE_TREE')
    report = inspect(ROOT)
    if not report['scan_ok']:
        raise ValueError('RELEASE_SCAN_FAILED:' + json.dumps(report['failures'], ensure_ascii=True))
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for item in report['files']:
            payload = (ROOT / item['file']).read_bytes()
            if hashlib.sha256(payload).hexdigest() != item['sha256']:
                raise ValueError('FILE_CHANGED_DURING_PACKAGING')
            info = zipfile.ZipInfo(item['file'], date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, payload)
    with zipfile.ZipFile(output) as archive:
        if archive.namelist() != [item['file'] for item in report['files']] or archive.testzip() is not None:
            raise ValueError('ARCHIVE_READBACK_FAILED')
        for item in report['files']:
            if hashlib.sha256(archive.read(item['file'])).hexdigest() != item['sha256']:
                raise ValueError('ARCHIVE_HASH_MISMATCH')
    return {'ok': True, 'files': len(report['files']), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
            'archive': str(output), 'uploaded': False, 'manifest': report['files']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = build(args.output)
    from runtime import atomic_json
    atomic_json(Path(args.output).with_suffix('.manifest.json'), result)
    print(json.dumps({k: v for k, v in result.items() if k != 'manifest'}, ensure_ascii=True, indent=2))
