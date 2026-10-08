#!/usr/bin/env python3
"""Add reviewed public judgments without rebuilding the corpus or replacing notes.

Dry run by default. --apply makes a SQLite backup before the transaction.
The bundle supplies primary-source provenance, explicit IDs, and guarded fixes.
"""
import argparse
import datetime
import json
from pathlib import Path
import sqlite3
try:
    from .public_text import strip_admin_lines
except ImportError:
    from public_text import strip_admin_lines


def apply_bundle(con, bundle):
    changed = {"cases_added": 0, "metadata_fixed": 0, "notes_added": 0, "chunks_added": 0}
    con.execute("CREATE TABLE IF NOT EXISTS verified_sources (case_id TEXT, sha256 TEXT, source_url TEXT, verified_on TEXT, PRIMARY KEY(case_id, sha256))")
    for item in bundle["records"]:
        cid = item["case_id"]
        source = item["source"]
        if len(source["sha256"]) != 64 or not source["url"].startswith("https://"):
            raise ValueError("Invalid source provenance")
        row = con.execute("SELECT * FROM cases WHERE case_id=?", (cid,)).fetchone()
        if item["mode"] == "existing":
            if row is None:
                raise ValueError(f"Required existing case missing: {cid}")
            for col, fix in item["fixes"].items():
                if col not in ("case_number", "citation", "judges", "decision_date", "year", "disposition"):
                    raise ValueError("Unapproved metadata column")
                value = con.execute(f"SELECT {col} FROM cases WHERE case_id=?", (cid,)).fetchone()[0]
                if value == fix["new"]:
                    continue
                if value != fix["old"]:
                    raise ValueError(f"Concurrent metadata conflict: {cid}.{col}")
                con.execute(f"UPDATE cases SET {col}=? WHERE case_id=?", (fix["new"], cid))
                changed["metadata_fixed"] += 1
        elif item["mode"] == "new":
            meta = item["case"]
            if row is None:
                candidates = con.execute("SELECT case_id FROM cases WHERE source_url=? OR (court_slug=? AND decision_date=? AND (case_number=? OR title=?))", (source["url"], meta["court_slug"], meta["decision_date"], meta["case_number"], meta["title"])).fetchall()
                if candidates:
                    raise ValueError(f"Possible duplicate under another ID: {candidates}")
                columns = ("court_slug", "court", "title", "case_number", "citation", "decision_date", "year", "disposition", "judges")
                con.execute("INSERT INTO cases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (cid, *(meta[k] for k in columns), source["url"], len(item["chunks"]), meta["acts"]))
                for index, chunk in enumerate(item["chunks"]):
                    if strip_admin_lines(chunk) != chunk:
                        raise ValueError("Administrative stamp in public intake")
                    cur = con.execute("INSERT INTO chunks(case_id,chunk_index,section_type,text) VALUES (?,?,?,?)", (cid, index, "judgment", chunk))
                    con.execute("INSERT INTO chunks_fts(rowid,text) VALUES (?,?)", (cur.lastrowid, chunk))
                    con.execute("INSERT INTO chunk_case VALUES (?,?)", (cur.lastrowid, cid))
                changed["cases_added"] += 1
                changed["chunks_added"] += len(item["chunks"])
            else:
                recorded = con.execute("SELECT 1 FROM verified_sources WHERE case_id=? AND sha256=?", (cid, source["sha256"])).fetchone()
                if not recorded:
                    raise ValueError(f"ID already exists without matching source: {cid}")
        else:
            raise ValueError("Invalid intake mode")
        note = item.get("note")
        old_note = con.execute("SELECT 1 FROM enrich_cases WHERE case_id=?", (cid,)).fetchone()
        if note and not old_note:
            con.execute("INSERT INTO enrich_cases VALUES (?,?,?,?,?,?,?,?,?)", (cid, "public", note["stance"], "later history not verified", "", ",".join(note["issues"]), note["summary"], note["body"], bundle["verified_on"]))
            changed["notes_added"] += 1
        elif old_note:
            print(f"Preserved existing headnote: {cid}")
        for issue in note["issues"] if note else []:
            if not con.execute("SELECT 1 FROM issues WHERE issue=?", (issue,)).fetchone():
                raise ValueError(f"Unknown issue: {issue}")
            con.execute("INSERT OR IGNORE INTO case_issues VALUES (?,?,999,'curated')", (cid, issue))
        con.execute("INSERT OR IGNORE INTO verified_sources VALUES (?,?,?,?)", (cid, source["sha256"], source["url"], bundle["verified_on"]))
    return changed


def verify_preservation(con, baseline, bundle):
    con.execute("ATTACH DATABASE ? AS prior", (str(baseline),))
    # Every pre-existing row must survive. Only the explicitly guarded metadata
    # columns on listed existing cases may differ; all their other fields survive.
    fixed = [r["case_id"] for r in bundle["records"] if r["mode"] == "existing"]
    tables = ("meta", "chunks", "issues", "case_issues", "statutes", "enrich_cases", "briefs", "templates", "orders", "chunk_case")
    for table in tables:
        if con.execute(f"SELECT * FROM prior.{table} EXCEPT SELECT * FROM main.{table} LIMIT 1").fetchone():
            raise ValueError(f"Existing row changed: {table}")
    slots = ",".join("?" for _ in fixed) or "NULL"
    if con.execute(f"SELECT * FROM prior.cases WHERE case_id NOT IN ({slots}) EXCEPT SELECT * FROM main.cases LIMIT 1", fixed).fetchone():
        raise ValueError("Unrelated case changed")
    columns = [r[1] for r in con.execute("PRAGMA main.table_info(cases)")]
    for item in bundle["records"]:
        if item["mode"] != "existing":
            continue
        keep = ",".join(c for c in columns if c not in item["fixes"])
        if con.execute(f"SELECT {keep} FROM prior.cases WHERE case_id=? EXCEPT SELECT {keep} FROM main.cases WHERE case_id=?", (item["case_id"], item["case_id"])).fetchone():
            raise ValueError("Unapproved field changed")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("db", type=Path)
    p.add_argument("bundle", type=Path)
    p.add_argument("--apply", action="store_true")
    a = p.parse_args()
    bundle = json.loads(a.bundle.read_text(encoding="utf-8"))
    if not a.db.is_file():
        raise ValueError("Database does not exist")
    con = sqlite3.connect(a.db, timeout=60)
    # A consistent baseline is retained for both dry run and apply. No file copy
    # of a possibly live WAL database is used.
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = a.db.with_name(a.db.name + ".pre-verified-" + stamp)
    with sqlite3.connect(backup) as dst:
        con.backup(dst)
    print("BACKUP", backup)
    try:
        con.execute("BEGIN IMMEDIATE")
        changed = apply_bundle(con, bundle)
        verify_preservation(con, backup, bundle)
        con.execute("INSERT INTO chunks_fts(chunks_fts, rank) VALUES ('integrity-check', 1)")
        if con.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Integrity failure")
        print("PRESERVATION_VERIFIED", json.dumps(changed, sort_keys=True))
        if a.apply:
            con.commit()
            print("VERIFIED_INTAKE_APPLIED")
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
