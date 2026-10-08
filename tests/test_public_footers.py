import sqlite3
import unittest
from pipeline.public_text import strip_admin_lines
from pipeline.clean_public_footers import clean


class PublicFootersTest(unittest.TestCase):
    def test_exact_stamp_only(self):
        legal = "Section 14: reasons must be recorded.\nFile No. LEGAL-HO quoted by the Court.\n"
        for stamp in (
            "File No. Leg-13/91/2026-LEGAL-HO (Computer No. 19673)\n",
            "File No. Leg/91/2026-LEGAL-HO (Computer No. 19673)\n",
            "123456/2026/Legal(ED)(HO)\n",
        ):
            self.assertEqual(strip_admin_lines(legal + stamp + "Appeal dismissed.\n"), legal + "Appeal dismissed.\n")

    def test_cleanup_fts_and_rollback(self):
        con = sqlite3.connect(":memory:")
        con.executescript("CREATE TABLE chunks(rowid INTEGER PRIMARY KEY,case_id TEXT,text TEXT); CREATE VIRTUAL TABLE chunks_fts USING fts5(text,content='chunks',content_rowid='rowid');")
        old = "Mandatory hearing preserved.\nFile No. Leg-13/91/2026-LEGAL-HO (Computer No. 19673)\nAppeal dismissed."
        con.execute("INSERT INTO chunks VALUES(1,'CASE',?)", (old,))
        con.execute("INSERT INTO chunks_fts(rowid,text) VALUES(1,?)", (old,))
        con.commit()
        con.execute("BEGIN")
        self.assertEqual(clean(con), [(1, "CASE")])
        self.assertEqual(con.execute("SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'Mandatory'").fetchall(), [(1,)])
        self.assertEqual(con.execute("SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH '19673'").fetchall(), [])
        con.execute("INSERT INTO chunks_fts(chunks_fts,rank) VALUES('integrity-check',1)")
        con.rollback()
        self.assertEqual(con.execute("SELECT text FROM chunks").fetchone()[0], old)
        self.assertEqual(con.execute("SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH '19673'").fetchall(), [(1,)])


if __name__ == '__main__':
    unittest.main()
