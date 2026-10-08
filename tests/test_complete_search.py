"""An independent FTS fixture proves no hidden passage/result truncation."""
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import server


class CompleteSearchTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(':memory:')
        self.c.row_factory = sqlite3.Row
        self.c.executescript('''
        CREATE TABLE cases(case_id TEXT PRIMARY KEY,title TEXT,citation TEXT,case_number TEXT,decision_date TEXT,court_slug TEXT,year INTEGER,acts TEXT);
        CREATE TABLE chunks(case_id TEXT,chunk_index INTEGER,text TEXT);
        CREATE TABLE chunk_case(case_id TEXT);
        CREATE VIRTUAL TABLE chunks_fts USING fts5(text,content=chunks,content_rowid=rowid);
        CREATE TABLE enrich_cases(case_id TEXT,citation_extra TEXT);
        CREATE TABLE issues(issue TEXT,label TEXT);
        CREATE TABLE case_issues(case_id TEXT,issue TEXT,source TEXT,hits INTEGER);
        ''')
        for i in range(63):
            self.c.execute('INSERT INTO cases VALUES (?,?,?,?,?,?,?,?)', (f'case-{i:03}', f'Judgment {i}', '', '', f'2026-01-{i%28+1:02}', 'court', 2026, 'PMLA'))
            # The first case alone has more than the old 3,000-passage cutoff.
            for j in range(3001 if i == 0 else 1):
                self.c.execute('INSERT INTO chunks VALUES (?,?,?)', (f'case-{i:03}', j, 'bail'))
                self.c.execute('INSERT INTO chunk_case VALUES (?)', (f'case-{i:03}',))
        self.c.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
        self.patch = patch.object(server, '_HAS_CHUNK_CASE', True)
        self.patch.start()
        self.internal_patch = patch.object(server, 'INTERNAL_DBS', [])
        self.internal_patch.start()

    def tearDown(self):
        self.patch.stop()
        self.internal_patch.stop()
        self.c.close()

    def test_all_matches_paging_and_hits(self):
        pages = [server.api_search(self.c, {'q': 'bail', 'offset': n}) for n in (0,25,50)]
        self.assertEqual([p['total'] for p in pages], [63]*3)
        ids = [r['case_id'] for p in pages for r in p['results']]
        self.assertEqual(len(set(ids)), 63)
        self.assertEqual(len(ids), 63)
        self.assertEqual(pages[0]['results'][0]['hits'], 3001)
        self.assertFalse(pages[-1]['has_more'])
        self.assertTrue(pages[0]['has_more'])

    def test_date_sort_and_filter_only_are_complete(self):
        res = server.api_search(self.c, {'court': 'court', 'limit': 50, 'sort': 'oldest'})
        self.assertEqual(res['total'], 63)
        dates = [x['decision_date'] for x in res['results']]
        self.assertEqual(dates, sorted(dates))


if __name__ == '__main__':
    unittest.main()
