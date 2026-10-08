"""Narrow, backed-up removal of administrative stamp lines; dry run by default."""
import argparse
import datetime
from pathlib import Path
import sqlite3

try:
    from .public_text import strip_admin_lines
except ImportError:
    from public_text import strip_admin_lines


def clean(con):
    changes = []
    for rowid, case_id, old in con.execute(
        "SELECT rowid,case_id,text FROM chunks WHERE text LIKE '%LEGAL-HO%' "
        "OR text LIKE '%Legal(ED)(HO)%' OR text LIKE '%Generated from eOffice%'"
    ).fetchall():
        new = strip_admin_lines(old)
        if new == old:
            raise ValueError(f"Unrecognised stamp in chunk {rowid}; review required")
        if any(marker in new for marker in ("LEGAL-HO", "Legal(ED)(HO)", "Generated from eOffice")):
            raise ValueError(f"Residual stamp in chunk {rowid}")
        con.execute("INSERT INTO chunks_fts(chunks_fts,rowid,text) VALUES ('delete',?,?)", (rowid, old))
        con.execute("UPDATE chunks SET text=? WHERE rowid=? AND text=?", (new, rowid, old))
        con.execute("INSERT INTO chunks_fts(rowid,text) VALUES (?,?)", (rowid, new))
        changes.append((rowid, case_id))
    return changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.db.is_file():
        raise ValueError("Database does not exist")
    con = sqlite3.connect(args.db, timeout=60)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = args.db.with_name(args.db.name + ".pre-footer-clean-" + stamp)
    with sqlite3.connect(backup) as dst:
        con.backup(dst)
    print("BACKUP", backup)
    try:
        con.execute("BEGIN IMMEDIATE")
        changes = clean(con)
        con.execute("ATTACH DATABASE ? AS prior", (str(backup),))
        tables = con.execute("SELECT name FROM prior.sqlite_master WHERE type='table' AND name NOT LIKE 'chunks_fts%' AND name NOT LIKE 'sqlite_%'").fetchall()
        for (table,) in tables:
            if table == "chunks":
                continue
            for left, right in (("prior", "main"), ("main", "prior")):
                if con.execute(f'SELECT * FROM {left}."{table}" EXCEPT SELECT * FROM {right}."{table}" LIMIT 1').fetchone():
                    raise ValueError(f"Unrelated table changed: {table}")
        expected = {rowid for rowid, _ in changes}
        actual = {r[0] for r in con.execute("SELECT rowid FROM prior.chunks EXCEPT SELECT rowid FROM main.chunks WHERE text=(SELECT text FROM prior.chunks p WHERE p.rowid=main.chunks.rowid)")}
        if actual != expected:
            raise ValueError("Unexpected chunk changes")
        for rowid, _ in changes:
            old = con.execute("SELECT case_id,chunk_index,section_type,text FROM prior.chunks WHERE rowid=?", (rowid,)).fetchone()
            new = con.execute("SELECT case_id,chunk_index,section_type,text FROM main.chunks WHERE rowid=?", (rowid,)).fetchone()
            if new[:3] != old[:3] or new[3] != strip_admin_lines(old[3]):
                raise ValueError("Non-stamp content changed")
        if con.execute("SELECT count(*) FROM main.chunks").fetchone() != con.execute("SELECT count(*) FROM prior.chunks").fetchone():
            raise ValueError("Chunk count changed")
        con.execute("INSERT INTO chunks_fts(chunks_fts,rank) VALUES ('integrity-check',1)")
        if con.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Integrity failure")
        print("PRESERVATION_VERIFIED", len(changes), "chunks", sorted({c for _, c in changes}))
        if args.apply:
            con.commit()
            print("FOOTER_CLEANUP_APPLIED")
        else:
            con.rollback()
            print("DRY_RUN_NO_CHANGES")
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == "__main__":
    main()
