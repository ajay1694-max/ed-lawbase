"""Privacy, file isolation, review integrity and account lifecycle tests."""
import base64
import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import auth
import research


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = self.temp.name
        self.a = {'username': 'alice', 'is_admin': False}
        self.b = {'username': 'bob', 'is_admin': False}
        self.admin = {'username': 'admin', 'is_admin': True}
        self.c = sqlite3.connect(':memory:')
        self.c.executescript("CREATE TABLE cases(case_id TEXT); INSERT INTO cases VALUES ('existing'); CREATE TABLE verified_sources(case_id TEXT); INSERT INTO verified_sources VALUES ('existing');")

    def tearDown(self):
        self.c.close()
        self.temp.cleanup()

    def request(self, **changes):
        return dict(title='Public judgment', citation='2026 TEST 1', contributor='Alice', public_judgment=True, **changes)

    def test_private_library_and_saved_searches(self):
        research.save_library(self.root, self.a, {'case_id': 'existing', 'note': 'Personal research', 'folder': 'Bail'})
        sid = research.save_search(self.root, self.a, {'title': 'Search', 'params': {'q': 'bail'}})['id']
        self.assertEqual(research.listing(self.root, self.b, 'library'), {'items': [], 'searches': []})
        research.save_library(self.root, self.b, {'case_id': 'existing', 'remove': True})
        research.save_search(self.root, self.b, {'id': sid, 'remove': True})
        self.assertEqual(len(research.listing(self.root, self.a, 'library')['items']), 1)
        self.assertEqual(len(research.listing(self.root, self.a, 'library')['searches']), 1)

    def test_attachment_isolation_duplicate_and_filename(self):
        raw = b'%PDF-1.4\nPublic test fixture\n%%EOF'
        body = self.request(pdf_base64=base64.b64encode(raw).decode(), filename='../../secret.pdf')
        result = research.submit(self.root, self.a, body)
        self.assertEqual(research.submit(self.root, self.a, body)['id'], result['id'])
        self.assertTrue(research.submit(self.root, self.a, body)['duplicate'])
        self.assertEqual(research.listing(self.root, self.b, 'submissions')['items'], [])
        with self.assertRaises(PermissionError):
            research.attachment(self.root, self.b, result['id'])
        f = research.attachment(self.root, self.admin, result['id'])
        self.assertEqual(f.read_bytes(), raw)
        self.assertEqual(f.parent, Path(self.root) / 'data' / 'member_uploads')
        item = research.listing(self.root, self.a, 'submissions')['items'][0]
        self.assertNotIn('file_name', item)
        self.assertEqual(item['original_name'], 'secret.pdf')
        self.assertEqual(item['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(self.c.execute('SELECT count(*) FROM cases').fetchone()[0], 1)

    def test_invalid_and_oversize_uploads_rejected(self):
        for raw in (b'<script>bad</script>', b'%PDF-' + b'0' * research.MAX_PDF):
            with self.assertRaises(ValueError):
                research.submit(self.root, self.a, self.request(pdf_base64=base64.b64encode(raw).decode()))
        with self.assertRaises(ValueError):
            research.submit(self.root, self.a, {**self.request(), 'public_judgment': False})
        self.assertEqual(research.listing(self.root, self.admin, 'submissions')['items'], [])

    def test_review_authority_verified_import_and_race(self):
        ident = research.submit(self.root, self.a, self.request())['id']
        item = research.listing(self.root, self.admin, 'submissions')['items'][0]
        body = {'id': ident, 'status': 'integrated', 'review_note': 'Verified', 'linked_case': 'existing', 'expected_updated': item['updated']}
        with self.assertRaises(PermissionError):
            research.review(self.root, self.a, body, self.c)
        self.c.execute('DELETE FROM verified_sources')
        with self.assertRaises(ValueError):
            research.review(self.root, self.admin, body, self.c)
        self.c.execute("INSERT INTO verified_sources VALUES ('existing')")
        research.review(self.root, self.admin, body, self.c)
        with self.assertRaises(ValueError):
            research.review(self.root, self.admin, body, self.c)
        with research.connection(self.root) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM review_events').fetchone()[0], 1)


class AccountTests(unittest.TestCase):
    def test_existing_account_migration_and_token_revocation(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, 'data').mkdir()
            with sqlite3.connect(auth.db_path(root)) as c:
                c.execute('CREATE TABLE users(username TEXT PRIMARY KEY,salt TEXT,hash TEXT,is_admin INTEGER,created TEXT)')
                salt, digest = auth._hash('fixture-password')
                c.execute('INSERT INTO users VALUES (?,?,?,?,?)', ('alice', salt, digest, 1, '2026-01-01'))
            c.close()
            payload = json.dumps({'u': 'alice', 'a': True, 'exp': time.time()+60}).encode()
            sig = hmac.new(auth._secret(root), payload, hashlib.sha256).digest()
            legacy = base64.urlsafe_b64encode(payload).decode()+'.'+base64.urlsafe_b64encode(sig).decode()
            self.assertTrue(auth.verify_session(root, legacy)['is_admin'])
            with self.assertRaises(ValueError):
                auth.create_user(root, 'alice', 'replacement', False)
            self.assertTrue(auth.verify_login(root, 'alice', 'fixture-password')['is_admin'])
            with auth.connection(root) as c:
                c.execute("UPDATE users SET is_admin=0 WHERE username='alice'")
            self.assertFalse(auth.verify_session(root, legacy)['is_admin'])
            auth.set_password(root, 'alice', 'changed-fixture')
            self.assertIsNone(auth.verify_session(root, legacy))
            token = auth.make_session(root, auth.verify_login(root, 'alice', 'changed-fixture'))
            auth.delete_user(root, 'alice')
            self.assertIsNone(auth.verify_session(root, token))
            auth.create_user(root, 'alice', 'new-fixture')
            self.assertIsNone(auth.verify_session(root, token))


if __name__ == '__main__':
    unittest.main()
