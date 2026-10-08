"""Account-scoped research and review queue, separate from the public corpus.

Uploads are attachments for review, never automatically published or executed.
This database and its files live under ignored data/, not in the public repository.
"""
import base64
import binascii
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid
from contextlib import contextmanager

MAX_PDF = 8 * 1024 * 1024
MAX_BODY = 12 * 1024 * 1024
STATES = ('submitted', 'reviewing', 'needs_info', 'duplicate', 'integrated', 'declined')


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


@contextmanager
def connection(root):
    c = connect(root)
    try:
        with c:
            yield c
    finally:
        c.close()


def connect(root):
    path = Path(root) / 'data' / 'research.sqlite'
    path.parent.mkdir(exist_ok=True, parents=True)
    c = sqlite3.connect(path, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.executescript('''
    CREATE TABLE IF NOT EXISTS library (
      owner TEXT, case_id TEXT, folder TEXT, note TEXT, quote TEXT, locator TEXT,
      updated TEXT, PRIMARY KEY(owner,case_id));
    CREATE TABLE IF NOT EXISTS saved_searches (
      id TEXT PRIMARY KEY, owner TEXT, title TEXT, params TEXT, created TEXT);
    CREATE INDEX IF NOT EXISTS saved_owner ON saved_searches(owner);
    CREATE TABLE IF NOT EXISTS submissions (
      id TEXT PRIMARY KEY, owner TEXT, contributor TEXT, title TEXT, citation TEXT,
      source_url TEXT, note TEXT, original_name TEXT, sha256 TEXT, file_name TEXT,
      status TEXT, review_note TEXT, linked_case TEXT, created TEXT, updated TEXT);
    CREATE INDEX IF NOT EXISTS submission_owner ON submissions(owner,created);
    CREATE INDEX IF NOT EXISTS submission_status ON submissions(status,created);
    CREATE TABLE IF NOT EXISTS review_events (
      id INTEGER PRIMARY KEY, submission_id TEXT, reviewer TEXT, old_status TEXT,
      new_status TEXT, note TEXT, linked_case TEXT, created TEXT);
    ''')
    return c


def text(body, name, limit, required=False):
    value = body.get(name, '')
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f'{name}: maximum {limit} characters')
    value = value.strip()
    if required and not value:
        raise ValueError(f'{name} is required')
    return value


def owner(session):
    return session.get('username') or 'local'


def listing(root, session, kind):
    with connection(root) as c:
        if kind == 'library':
            return {'items': [dict(r) for r in c.execute('SELECT * FROM library WHERE owner=? ORDER BY folder,updated DESC', (owner(session),))],
                    'searches': [dict(r) for r in c.execute('SELECT * FROM saved_searches WHERE owner=? ORDER BY created DESC', (owner(session),))]}
        if kind == 'submissions':
            where, args = ('', ()) if session.get('is_admin') else (' WHERE owner=?', (owner(session),))
            rows = [dict(r) for r in c.execute('SELECT * FROM submissions' + where + " ORDER BY status IN ('submitted','reviewing','needs_info') DESC, created ASC LIMIT 500", args)]
            for r in rows:
                r['has_file'] = bool(r.pop('file_name'))
            return {'items': rows, 'is_admin': bool(session.get('is_admin')),
                    'pending': c.execute("SELECT count(*) FROM submissions WHERE status IN ('submitted','reviewing','needs_info')" + (' AND owner=?' if not session.get('is_admin') else ''), args).fetchone()[0]}
    raise ValueError('Unknown collection')


def save_library(root, session, body):
    cid = text(body, 'case_id', 150, True)
    with connection(root) as c:
        if body.get('remove'):
            c.execute('DELETE FROM library WHERE owner=? AND case_id=?', (owner(session), cid))
        else:
            values = (owner(session), cid, text(body, 'folder', 100) or 'Saved judgments', text(body, 'note', 10000), text(body, 'quote', 10000), text(body, 'locator', 100), now())
            c.execute('INSERT INTO library VALUES (?,?,?,?,?,?,?) ON CONFLICT(owner,case_id) DO UPDATE SET folder=excluded.folder,note=excluded.note,quote=excluded.quote,locator=excluded.locator,updated=excluded.updated', values)
    return {'ok': True}


def save_search(root, session, body):
    with connection(root) as c:
        if body.get('remove'):
            c.execute('DELETE FROM saved_searches WHERE owner=? AND id=?', (owner(session), text(body, 'id', 50, True)))
            return {'ok': True}
        title = text(body, 'title', 150, True)
        params = body.get('params', {})
        allowed = ('q', 'court', 'act', 'issue', 'year_from', 'year_to', 'within', 'sort')
        if not isinstance(params, dict):
            raise ValueError('Search parameters must be an object')
        params = {k: str(v)[:300] for k, v in params.items() if k in allowed}
        if c.execute('SELECT count(*) FROM saved_searches WHERE owner=?', (owner(session),)).fetchone()[0] >= 200:
            raise ValueError('Keep at most 200 saved searches; remove an older search first')
        ident = uuid.uuid4().hex
        c.execute('INSERT INTO saved_searches VALUES (?,?,?,?,?)', (ident, owner(session), title, json.dumps(params), now()))
        return {'ok': True, 'id': ident}


def submit(root, session, body):
    title = text(body, 'title', 300, True)
    contributor = text(body, 'contributor', 120, True)
    citation = text(body, 'citation', 300)
    url = text(body, 'source_url', 1500)
    if url and not re.match(r'^https?://[^\s]+$', url):
        raise ValueError('Use a complete http/https source link')
    note = text(body, 'note', 4000)
    if body.get('public_judgment') is not True:
        raise ValueError('Confirm this is a public judgment or a request for one')
    raw, digest, name = b'', '', ''
    encoded = body.get('pdf_base64', '')
    if encoded:
        if not isinstance(encoded, str) or len(encoded) > (MAX_PDF * 4 // 3 + 8):
            raise ValueError('PDF must be 8 MB or smaller')
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError('Invalid PDF upload') from None
        if len(raw) > MAX_PDF or not raw.startswith(b'%PDF-'):
            raise ValueError('Upload a PDF of 8 MB or less')
        digest = hashlib.sha256(raw).hexdigest()
        name = os.path.basename(text(body, 'filename', 250).replace('\\', '/')) or 'judgment.pdf'
    if not raw and not (citation or url):
        raise ValueError('Add a PDF, citation or source link')
    ident = uuid.uuid4().hex
    stored = ident + '.pdf' if raw else ''
    path = Path(root) / 'data' / 'member_uploads' / stored
    c = connect(root)
    try:
        c.execute('BEGIN IMMEDIATE')
        if c.execute("SELECT count(*) FROM submissions WHERE owner=? AND created>=?", (owner(session), now()[:10])).fetchone()[0] >= 25:
            raise ValueError('Daily limit reached: 25 submissions per account')
        # Exact own-file duplicates return the existing request, with no new file.
        if digest:
            old = c.execute('SELECT id FROM submissions WHERE owner=? AND sha256=?', (owner(session), digest)).fetchone()
            if old:
                return {'ok': True, 'id': old[0], 'duplicate': True}
        elif citation or url:
            old = c.execute("SELECT id FROM submissions WHERE owner=? AND citation=? AND source_url=? AND title=? AND status NOT IN ('declined')", (owner(session), citation, url, title)).fetchone()
            if old:
                return {'ok': True, 'id': old[0], 'duplicate': True}
        if raw:
            path.parent.mkdir(exist_ok=True, parents=True)
            if sum(f.stat().st_size for f in path.parent.glob('*.pdf')) + len(raw) > 2 * 1024**3:
                raise ValueError('Upload storage is full; submit a citation/link for now')
            with path.open('xb') as f:
                f.write(raw)
            try:
                path.chmod(0o600)
            except OSError:
                pass
        c.execute('INSERT INTO submissions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (ident, owner(session), contributor, title, citation, url, note, name, digest, stored, 'submitted', '', '', now(), now()))
        c.commit()
    except Exception:
        c.rollback()
        if raw and path.is_file():
            path.unlink()  # only this request's uncommitted file, never user paths
        raise
    finally:
        c.close()
    return {'ok': True, 'id': ident, 'duplicate': False}


def attachment(root, session, ident):
    with connection(root) as c:
        r = c.execute('SELECT * FROM submissions WHERE id=?', (ident,)).fetchone()
    if not r or not r['file_name'] or (r['owner'] != owner(session) and not session.get('is_admin')):
        raise PermissionError('Attachment not available')
    return Path(root) / 'data' / 'member_uploads' / r['file_name']


def review(root, session, body, corpus):
    if not session.get('is_admin'):
        raise PermissionError('Administrator review required')
    ident = text(body, 'id', 50, True)
    status = text(body, 'status', 30, True)
    note = text(body, 'review_note', 4000, True)
    linked = text(body, 'linked_case', 150)
    if status not in STATES:
        raise ValueError('Unknown review status')
    if status in ('integrated', 'duplicate'):
        if not linked or not corpus.execute('SELECT 1 FROM cases WHERE case_id=?', (linked,)).fetchone():
            raise ValueError('Select the existing LawBase case before completing this review')
    if status == 'integrated':
        verified = corpus.execute("SELECT 1 FROM sqlite_master WHERE name='verified_sources'").fetchone()
        if not verified or not corpus.execute('SELECT 1 FROM verified_sources WHERE case_id=?', (linked,)).fetchone():
            raise ValueError('Complete the verified-source import before marking integrated')
    with connection(root) as c:
        c.execute('BEGIN IMMEDIATE')
        r = c.execute('SELECT status,updated FROM submissions WHERE id=?', (ident,)).fetchone()
        if not r:
            raise ValueError('Submission not found')
        if body.get('expected_updated') != r['updated']:
            raise ValueError('This review changed; reload the queue before saving')
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='microseconds')
        c.execute('UPDATE submissions SET status=?,review_note=?,linked_case=?,updated=? WHERE id=?', (status, note, linked, stamp, ident))
        c.execute('INSERT INTO review_events(submission_id,reviewer,old_status,new_status,note,linked_case,created) VALUES (?,?,?,?,?,?,?)', (ident, owner(session), r['status'], status, note, linked, stamp))
    return {'ok': True}
