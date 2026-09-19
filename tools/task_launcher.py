"""Windowless scheduled entrypoint, preserving exit code in a local log."""
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from runtime import load_config, atomic_json


def main():
    config_path, work = sys.argv[1:3]
    config = load_config(config_path)
    command = [str(Path(sys.executable).with_name('python.exe')), str(Path(__file__).with_name('creator.py')), '--config', config_path, 'run', work]
    if len(sys.argv) > 3:
        command.extend(['--expected-node', sys.argv[3]])
    try:
        proc = subprocess.run(command, capture_output=True, timeout=900, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        report = {'exit_code': proc.returncode, 'completed_at': datetime.now().astimezone().isoformat(),
                  'result': json.loads(proc.stdout.decode('utf-8-sig'))}
    except Exception as error:
        report = {'exit_code': 1, 'error_type': type(error).__name__}
    atomic_json(Path(config['data_dir']) / 'task-results' / (work + '.json'), report)
    return report['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
