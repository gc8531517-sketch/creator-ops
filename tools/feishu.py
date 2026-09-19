"""Lark CLI adapter with dynamic fields and explicit write/readback validation."""
import json
import math
import os
import subprocess
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from runtime import atomic_json, lark_command


class LarkError(RuntimeError):
    pass


def equivalent(actual, expected):
    if isinstance(actual, list) and len(actual) == 1 and not isinstance(expected, list):
        actual = actual[0]
    if expected is None:
        return actual is None or actual == []
    if type(expected) in (int, float):
        return type(actual) in (int, float) and math.isfinite(actual) and abs(actual - expected) < 1e-7
    return actual == expected


class Feishu:
    def __init__(self, config):
        self.config = config
        self.base = config.get('base_token', '')
        self.fields_cache = {}

    def call(self, action, **flags):
        cmd = lark_command(self.config) + ['base', action, '--format', 'json', '--as', self.config.get('identity', 'bot')]
        if self.base and 'base_token' not in flags:
            flags['base_token'] = self.base
        for key, value in flags.items():
            if value is None:
                continue
            cmd.extend(['--' + key.replace('_', '-'), json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)])
        env = {**os.environ, 'LARKSUITE_CLI_NO_UPDATE_NOTIFIER': '1', 'LARKSUITE_CLI_NO_SKILLS_NOTIFIER': '1'}
        try:
            proc = subprocess.run(cmd, cwd=self.config['data_dir'], capture_output=True, timeout=90, env=env)
        except subprocess.TimeoutExpired:
            raise LarkError('LARK_TIMEOUT: outcome may be uncertain; do not blindly repeat create') from None
        try:
            body = json.loads((proc.stdout if proc.returncode == 0 else proc.stderr).decode('utf-8-sig'))
        except (ValueError, UnicodeError):
            raise LarkError('LARK_INVALID_RESPONSE') from None
        if proc.returncode or body.get('ok') is not True:
            error = body.get('error', {})
            # Do not echo payloads, credentials, URLs or raw stderr.
            raise LarkError('LARK_ERROR:' + str(error.get('type', 'unknown')) + ':' + str(error.get('code', proc.returncode)))
        return body.get('data', {})

    def fields(self, table):
        if table not in self.fields_cache:
            data = self.call('+field-list', table_id=table)
            items = data.get('fields', data.get('items', []))
            if not items:
                raise LarkError('FIELD_SCHEMA_EMPTY')
            if data.get('has_more'):
                raise LarkError('FIELD_SCHEMA_INCOMPLETE')
            self.fields_cache[table] = {f['name']: f['id'] for f in items}
        return self.fields_cache[table]

    def rows(self, table, **flags):
        data = self.call('+record-list', table_id=table, limit=2, **flags)
        ids, matrix, fields = data.get('record_id_list', []), data.get('data', []), data.get('field_id_list', [])
        if len(ids) != len(matrix):
            raise LarkError('RECORD_MATRIX_INVALID')
        if any(len(row) != len(fields) for row in matrix) or (len(ids) < 2 and data.get('has_more')):
            raise LarkError('RECORD_MATRIX_INCOMPLETE')
        reverse = {v: k for k, v in self.fields(table).items()}
        return [(ident, {reverse.get(field, field): val for field, val in zip(fields, row)}) for ident, row in zip(ids, matrix)]

    def find(self, table, key_field, key):
        rows = self.rows(table, filter_json={'logic': 'and', 'conditions': [[key_field, '==', key]]})
        if len(rows) > 1:
            raise LarkError('DUPLICATE_BUSINESS_KEY')
        return rows[0] if rows else None

    def get(self, table, ident):
        data = self.call('+record-get', table_id=table, record_id=ident)
        if data.get('record_id_list') != [ident] or len(data.get('data', [])) != 1:
            raise LarkError('READBACK_RECORD_MISMATCH')
        if len(data['data'][0]) != len(data.get('field_id_list', [])):
            raise LarkError('READBACK_MATRIX_INCOMPLETE')
        reverse = {v: k for k, v in self.fields(table).items()}
        return {reverse.get(k, k): v for k, v in zip(data['field_id_list'], data['data'][0])}

    def write(self, table, ident, values):
        fields = self.fields(table)
        if set(values) - set(fields):
            raise LarkError('UNKNOWN_WRITE_FIELDS')
        self.call('+record-upsert', table_id=table, record_id=ident, json={fields[k]: v for k, v in values.items()})
        for attempt in range(4):
            actual = self.get(table, ident)
            if all(equivalent(actual.get(k), v) for k, v in values.items()):
                return ident
            if attempt < 3:
                time.sleep(1)
        raise LarkError('READBACK_VALUE_MISMATCH')

    def ensure(self, table, key_field, key, initial):
        """Create once, stop on ambiguity; never overwrite existing snapshot data."""
        existing = self.find(table, key_field, key)
        if existing:
            return existing[0]
        marker = Path(self.config['data_dir']) / 'uncertain-creates.json'
        pending = json.loads(marker.read_text(encoding='utf-8')) if marker.exists() else []
        token = [table, key_field, key]
        if token in pending:
            raise LarkError('CREATE_OUTCOME_UNCERTAIN: inspect remote and reconcile before retry')
        fields = self.fields(table)
        if set(initial) - set(fields):
            raise LarkError('UNKNOWN_CREATE_FIELDS')
        pending.append(token)
        atomic_json(marker, pending)
        self.call('+record-upsert', table_id=table, json={fields[k]: v for k, v in initial.items()})
        for attempt in range(4):
            row = self.find(table, key_field, key)
            if row and all(equivalent(row[1].get(k), v) for k, v in initial.items()):
                pending.remove(token)
                atomic_json(marker, pending)
                return row[0]
            if attempt < 3:
                time.sleep(1)
        raise LarkError('CREATE_READBACK_UNCERTAIN')
