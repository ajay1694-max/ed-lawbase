"""Hosted HTTP authorization with isolated account and research databases."""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import auth
import server


class HostedHTTPTests(unittest.TestCase):
    def test_auth_origin_and_owner_boundaries(self):
        with tempfile.TemporaryDirectory() as root:
            for user in ('alice', 'bob'):
                auth.create_user(root, user, 'local-fixture-only')
            alice = auth.make_session(root, {'username': 'alice', 'is_admin': False})
            bob = auth.make_session(root, {'username': 'bob', 'is_admin': False})
            with patch.object(server, 'ROOT', root), patch.object(server, 'HOSTED', True):
                httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
                worker = threading.Thread(target=httpd.serve_forever, daemon=True)
                worker.start()
                def request(path, body=None, token=None, headers=None):
                    conn = http.client.HTTPConnection('127.0.0.1', httpd.server_port, timeout=10)
                    hdr = {'Content-Type': 'application/json'}
                    if token:
                        hdr['Cookie'] = 'lawbase_session=' + token
                    hdr.update(headers or {})
                    conn.request('POST' if body is not None else 'GET', path, json.dumps(body) if body is not None else None, hdr)
                    response = conn.getresponse()
                    code, data, cache = response.status, response.read(), response.getheader('Cache-Control')
                    conn.close()
                    return code, json.loads(data), cache
                try:
                    self.assertEqual(request('/api/submissions')[0], 401)
                    form = {'title': 'Public test request', 'citation': 'TEST 1', 'contributor': 'Alice', 'public_judgment': True}
                    self.assertEqual(request('/api/submissions/create', form, alice, {'Origin': 'https://other.invalid'})[0], 403)
                    code, created, cache = request('/api/submissions/create', form, alice)
                    self.assertEqual(code, 200)
                    self.assertEqual(cache, 'no-store')
                    self.assertEqual(len(request('/api/submissions', token=alice)[1]['items']), 1)
                    self.assertEqual(request('/api/submissions', token=bob)[1]['items'], [])
                    self.assertEqual(request('/api/submissions/review', {'id': created['id']}, bob)[0], 403)
                    self.assertEqual(request('/api/logout', {}, alice)[0], 200)
                    auth.delete_user(root, 'alice')
                    self.assertEqual(request('/api/submissions', token=alice)[0], 401)
                finally:
                    httpd.shutdown()
                    httpd.server_close()
                    worker.join()


if __name__ == '__main__':
    unittest.main()
