"""Durable reply guard. Records workflow; does not send platform messages."""
import hashlib
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


class ReplyLedger:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS replies (key TEXT PRIMARY KEY, payload TEXT NOT NULL, state TEXT NOT NULL, proof TEXT, updated TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS reply_events (id INTEGER PRIMARY KEY, key TEXT NOT NULL, previous TEXT, state TEXT NOT NULL, proof TEXT, created TEXT NOT NULL)')
        self.db.commit()

    def close(self):
        self.db.close()

    def prepare(self, work_id, target, original, reply):
        # target is a platform id when available, otherwise a verified page fingerprint.
        if not all(isinstance(v, str) and v.strip() for v in (work_id, target, original, reply)):
            raise ValueError('作品、目标标识、原评论、回复均不能为空')
        key = hashlib.sha256(json.dumps([work_id, target, original], ensure_ascii=False).encode()).hexdigest()
        payload = json.dumps(dict(work_id=work_id, target=target, original=original, reply=reply), ensure_ascii=False)
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO replies VALUES (?, ?, ?, ?, ?)',
                            (key, payload, 'draft', None, datetime.now(timezone.utc).isoformat()))
        row = self.get(key)
        if row['payload']['reply'] != reply:
            raise ValueError('该目标已有不同回复记录，先核对已有状态，禁止隐式覆盖')
        return row

    def get(self, key):
        row = self.db.execute('SELECT payload,state,proof,updated FROM replies WHERE key=?', (key,)).fetchone()
        if row is None:
            raise ValueError('回复记录不存在')
        return dict(key=key, payload=json.loads(row[0]), state=row[1], proof=row[2], updated=row[3])

    def list_work(self, work_id):
        rows = self.db.execute('SELECT key FROM replies ORDER BY updated DESC').fetchall()
        return [item for row in rows if (item := self.get(row[0]))['payload']['work_id'] == work_id]

    def transition(self, key, expected, state, proof):
        allowed = {('draft', 'approved'), ('approved', 'sending'),
                   ('sending', 'sent'), ('sending', 'uncertain'),
                   ('uncertain', 'sent'), ('uncertain', 'approved')}
        if (expected, state) not in allowed or not isinstance(proof, str) or not proof.strip():
            raise ValueError('非法状态转换或缺少授权/页面核对证据')
        # Persist sending BEFORE the UI click; a crash must never silently permit retry.
        with self.db:
            result = self.db.execute('UPDATE replies SET state=?,proof=?,updated=? WHERE key=? AND state=?',
                                     (state, proof, datetime.now(timezone.utc).isoformat(), key, expected))
            if result.rowcount != 1:
                raise ValueError('状态已变更或重复操作，停止发送并回读')
            self.db.execute('INSERT INTO reply_events(key,previous,state,proof,created) VALUES (?,?,?,?,?)',
                            (key, expected, state, proof, datetime.now(timezone.utc).isoformat()))
        return self.get(key)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / 'ops/creator-state/replies.sqlite'


def read_work(work_id, path=DEFAULT_DB):
    """Read-only connection: displaying the dashboard must not create/migrate records."""
    if not Path(path).is_file(): return []
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    try:
        rows = db.execute('SELECT key,payload,state,proof,updated FROM replies').fetchall()
        return [dict(key=k, payload=p, state=s, proof=e, updated=t)
                for k, raw, s, e, t in rows if (p := json.loads(raw))['work_id'] == work_id]
    finally:
        db.close()


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('comments_file')
    p.add_argument('comment_id')
    p = sub.add_parser('list')
    p.add_argument('work_id')
    p = sub.add_parser('transition')
    p.add_argument('key')
    p.add_argument('expected')
    p.add_argument('state')
    p.add_argument('--proof-file', required=True, help='包含真实授权或页面核对证据的UTF-8文件')
    args = parser.parse_args()
    ledger = None
    try:
        if args.action == 'list':
            result = read_work(args.work_id)
        else:
            ledger = ReplyLedger(DEFAULT_DB)
            if args.action == 'prepare':
                data = json.loads(Path(args.comments_file).read_text(encoding='utf-8-sig'))
                if data.get('demo') is not False: raise ValueError('正式回复记录只接受真实评论')
                matches = [c for c in data['comments'] if c['id'] == args.comment_id]
                if len(matches) != 1: raise ValueError('目标评论必须唯一')
                c = matches[0]
                target = c.get('platform_comment_id') or c['id']
                result = ledger.prepare(data['work_id'], target, c['text'], c['reply_draft'])
            else:
                file = Path(args.proof_file).resolve()
                proof = file.read_text(encoding='utf-8-sig').strip()
                if not proof: raise ValueError('证据文件为空')
                result = ledger.transition(args.key, args.expected, args.state, str(file) + '\n' + proof)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(2, str(exc) + '\n')
    finally:
        if ledger: ledger.close()


if __name__ == '__main__': main()
