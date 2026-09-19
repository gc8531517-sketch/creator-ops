import tempfile
import unittest
from pathlib import Path
from creator_reply_ledger import ReplyLedger, read_work


class ReplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'test.sqlite'
        self.ledger = ReplyLedger(self.path)
        self.addCleanup(lambda: self.ledger.close())
        self.row = self.ledger.prepare('1234567890123456789', 'verified-target', '[赞][赞][赞]', '谢谢支持')

    def test_idempotent(self):
        self.assertEqual(self.row['key'], self.ledger.prepare('1234567890123456789', 'verified-target', '[赞][赞][赞]', '谢谢支持')['key'])

    def test_requires_approval(self):
        with self.assertRaises(ValueError):
            self.ledger.transition(self.row['key'], 'draft', 'sending', 'test')

    def test_crash_preserves_sending(self):
        key = self.row['key']
        self.ledger.transition(key, 'draft', 'approved', 'test-only permission')
        self.ledger.transition(key, 'approved', 'sending', 'test-only target checked')
        self.ledger.close()
        self.ledger = ReplyLedger(self.path)
        self.assertEqual(self.ledger.get(key)['state'], 'sending')
        with self.assertRaises(ValueError):
            self.ledger.transition(key, 'approved', 'sending', 'retry prohibited')

    def test_uncertain_requires_evidence(self):
        key = self.row['key']
        self.ledger.transition(key, 'draft', 'approved', 'test permission')
        self.ledger.transition(key, 'approved', 'sending', 'test target')
        self.ledger.transition(key, 'sending', 'uncertain', 'test timeout')
        with self.assertRaises(ValueError):
            self.ledger.transition(key, 'uncertain', 'approved', '')

    def test_cannot_replace_reply(self):
        with self.assertRaises(ValueError):
            self.ledger.prepare('1234567890123456789', 'verified-target', '[赞][赞][赞]', '另一条')

    def test_readonly_display_and_events(self):
        key = self.row['key']
        self.ledger.transition(key, 'draft', 'approved', 'test authorization')
        self.assertEqual(read_work('1234567890123456789', self.path)[0]['state'], 'approved')
        self.assertEqual(read_work('9999999999', self.path), [])
        events = self.ledger.db.execute('SELECT previous,state,proof FROM reply_events WHERE key=?', (key,)).fetchall()
        self.assertEqual(events, [('draft', 'approved', 'test authorization')])

    def test_read_missing_does_not_create_database(self):
        missing = Path(self.tmp.name) / 'not-created.sqlite'
        self.assertEqual(read_work('1234567890123456789', missing), [])
        self.assertFalse(missing.exists())


if __name__ == '__main__':
    unittest.main()
