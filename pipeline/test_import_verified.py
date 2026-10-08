"""Transaction/idempotence tests using the production table definitions."""
import copy
import json
from pathlib import Path
import sqlite3
import unittest
from import_verified import apply_bundle

ROOT = Path(__file__).resolve().parents[1]


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.bundle = json.loads((ROOT / 'pipeline/verified/2026-10-08.json').read_text(encoding='utf-8'))
        self.con = sqlite3.connect(':memory:')
        source = sqlite3.connect(f'file:{ROOT / "data/lawbase.sqlite"}?mode=ro', uri=True)
        for table in ('cases', 'chunks', 'chunk_case', 'issues', 'case_issues', 'enrich_cases'):
            self.con.execute(source.execute('SELECT sql FROM sqlite_master WHERE name=?', (table,)).fetchone()[0])
        self.con.execute("CREATE VIRTUAL TABLE chunks_fts USING fts5(text,content='chunks',content_rowid='rowid')")
        row = source.execute("SELECT * FROM cases WHERE case_id='EDPORTAL_03_2026-08-10'").fetchone()
        self.con.execute('INSERT INTO cases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', row)
        for record in self.bundle['records']:
            for issue in record['note']['issues']:
                self.con.execute('INSERT OR IGNORE INTO issues VALUES (?,?,?,?)', source.execute('SELECT * FROM issues WHERE issue=?', (issue,)).fetchone())
        source.close()
        self.con.commit()

    def tearDown(self):
        self.con.close()

    def test_repeated_intake_preserves_notes_and_search(self):
        sentinel = ('EDPORTAL_03_2026-08-10', 'public', 'mixed', 'reviewed', '', '', 'Existing officer note', 'Keep this exactly', '2026-10-08')
        self.con.execute('INSERT INTO enrich_cases VALUES (?,?,?,?,?,?,?,?,?)', sentinel)
        first = apply_bundle(self.con, self.bundle)
        self.assertEqual(first['cases_added'], 1)
        second = apply_bundle(self.con, self.bundle)
        self.assertEqual(second, dict(cases_added=0, metadata_fixed=0, notes_added=0, chunks_added=0))
        self.assertEqual(self.con.execute('SELECT * FROM enrich_cases WHERE case_id=?', (sentinel[0],)).fetchone(), sentinel)
        self.assertGreater(self.con.execute("SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH 'Salgaocar'").fetchone()[0], 0)
        self.assertEqual(self.con.execute('SELECT count(*) FROM chunk_case').fetchone()[0], 26)

    def test_late_failure_rolls_back_earlier_corrections(self):
        bundle = copy.deepcopy(self.bundle)
        bundle['records'][1]['note']['issues'] = ['unknown.issue']
        before = self.con.execute('SELECT * FROM cases').fetchall()
        with self.assertRaises(ValueError), self.con:
            self.con.execute('BEGIN')
            apply_bundle(self.con, bundle)
        self.assertEqual(self.con.execute('SELECT * FROM cases').fetchall(), before)
        self.assertEqual(self.con.execute('SELECT count(*) FROM chunks').fetchone()[0], 0)

    def test_conflicting_metadata_is_not_overwritten(self):
        self.con.execute("UPDATE cases SET citation='Concurrent verified correction'")
        self.con.commit()
        with self.assertRaisesRegex(ValueError, 'Concurrent metadata conflict'), self.con:
            self.con.execute('BEGIN')
            apply_bundle(self.con, self.bundle)
        self.assertEqual(self.con.execute('SELECT citation FROM cases').fetchone()[0], 'Concurrent verified correction')


if __name__ == '__main__':
    unittest.main()
