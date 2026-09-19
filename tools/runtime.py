"""Portable configuration and crash-safe local primitives (no credentials)."""
import json
import os
import shutil
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

PACKAGE = Path(__file__).resolve().parents[1]


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        with temp.open('w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def executable(value, name):
    found = shutil.which(value or name)
    if not found:
        raise ValueError('DEPENDENCY_MISSING:' + name)
    return str(Path(found).resolve())


def load_config(path):
    path = Path(path).resolve()
    config = read_json(path)
    if config.get('schema_version') != 1:
        raise ValueError('CONFIG_SCHEMA_UNSUPPORTED')
    if any(k in config for k in ('app_secret', 'access_token', 'cookie', 'password')):
        raise ValueError('DO_NOT_STORE_CREDENTIALS_IN_PROJECT_CONFIG')
    config['_path'] = str(path)
    config['data_dir'] = str((path.parent / config.get('data_dir', 'runtime')).resolve())
    config['download_dir'] = str(Path(config.get('download_dir') or Path.home() / 'Downloads').resolve())
    if config.get('identity', 'bot') not in ('bot', 'user'):
        raise ValueError('INVALID_FEISHU_IDENTITY')
    return config


@contextmanager
def exclusive(path, timeout=0):
    """OS-held lock: released even after crash. Never unlink another owner's lock."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open('a+b')
    stream.seek(0, 2)
    if stream.tell() == 0:
        stream.write(b'0')
        stream.flush()
    deadline = time.monotonic() + timeout
    held = False
    try:
        while True:
            try:
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('BUSY_RETRY_LATER') from None
                time.sleep(0.2)
        yield
    finally:
        if held:
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_UN)
        stream.close()


def chrome_path(config):
    if config.get('chrome_path'):
        return executable(config['chrome_path'], 'chrome')
    for root in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA'):
        path = Path(os.environ.get(root, '.')) / 'Google/Chrome/Application/chrome.exe'
        if path.is_file():
            return str(path.resolve())
    return executable('', 'chrome')


def lark_command(config):
    # Run Node's entrypoint directly: avoids cmd.exe quoting of untrusted text.
    entry = config.get('lark_entry')
    if not entry:
        entry = Path(os.environ.get('APPDATA', Path.home())) / 'npm/node_modules/@larksuite/cli/scripts/run.js'
    if not Path(entry).is_file():
        raise ValueError('LARK_ENTRY_MISSING: set lark_entry to the installed CLI scripts/run.js')
    return [executable(config.get('node_path'), 'node'), str(Path(entry).resolve())]
