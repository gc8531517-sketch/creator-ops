"""Opt-in temporary Windows Task Scheduler test; never starts capture."""
import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from runtime import PACKAGE, atomic_json, executable
from bootstrap import NODES


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--register-and-remove-test-tasks', action='store_true', required=True)
    parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='CreatorOps scheduler ') as folder:
        root = Path(folder)
        config = root / 'config.json'
        plan = root / 'plan.json'
        atomic_json(config, {'schema_version': 1, 'data_dir': str(root / 'data')})
        atomic_json(plan, {'work_id': '1234567890000000001', 'registration_complete': True,
            'nodes': [{'node': n, 'planned_at': (datetime.now(timezone.utc) + timedelta(days=10 + i)).isoformat(), 'status': 'pending'} for i, n in enumerate(NODES)]})
        command = [executable('', 'pwsh'), '-NoProfile', '-File', str(PACKAGE / 'scripts/schedule.ps1'), '-ConfigPath', str(config), '-PlanPath', str(plan), '-PythonPath', sys.executable]
        preview = subprocess.run(command, capture_output=True, check=True)
        expected = json.loads(preview.stdout.decode('utf-8-sig'))
        names = [item['task_name'] for item in expected['tasks']] + [expected['recovery_task']]
        # Names include a hash of a brand new temporary config directory.
        target_file = root / 'tasks.json'
        atomic_json(target_file, names)
        try:
            proc = subprocess.run(command + ['-Apply'], capture_output=True, check=True)
            actual = json.loads(proc.stdout.decode('utf-8-sig'))
            assert actual['applied'] is True and len(actual['tasks']) == 5
            print(json.dumps({'ok': True, 'five_exact_and_recovery_registered_and_read_back': True, 'capture_started': False}))
        finally:
            cleanup = subprocess.run([executable('', 'pwsh'), '-NoProfile', '-File', str(PACKAGE / 'tests/cleanup_test_tasks.ps1'), '-NamesFile', str(target_file)], capture_output=True)
            if cleanup.returncode:
                raise RuntimeError('TEST_TASK_CLEANUP_FAILED: inspect temporary CreatorOps tasks')


if __name__ == '__main__': main()
