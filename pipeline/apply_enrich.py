#!/usr/bin/env python3
r"""apply_enrich.py - apply taxonomy and enrich/ changes to an EXISTING lawbase.sqlite, in place.

Use this when only headnotes, briefs or issue tags have changed: it avoids a full rebuild (which needs the
whole Open India Law corpus) and works on the live server's copy.

    python pipeline/apply_enrich.py data/lawbase.sqlite            # dry run: reports what would change
    python pipeline/apply_enrich.py data/lawbase.sqlite --apply    # backs up to <db>.pre-enrich-<stamp>, then writes

What it does, all in one transaction:
  1. issues table  <- taxonomy/issues.toml (new issues inserted, labels/queries of existing ones refreshed);
  2. auto tags     <- FTS5 query run for each issue that had no 'auto' rows (new issues only);
  3. statutes      <- pipeline/statute_addenda.jsonl, for acts in STATUTE_ACTS not yet in the database;
  4. cases         <- metadata corrections in pipeline/case_fixes.json;
  5. enrich_cases, briefs, curated case_issues <- enrich/ (public tier only, via build.load_enrichment).
It never touches chunks, and touches cases only for the listed metadata fixes in pipeline/case_fixes.json. Safe to re-run: a second run changes nothing.
Restart the app afterwards - it caches case metadata (citation_extra) per process.
"""
import argparse, collections, datetime, json, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build import ROOT, STATUTE_ACTS, load_enrichment, load_taxonomy  # noqa: E402


def counts(con):
    q = lambda s: con.execute(s).fetchone()[0]
    return {"issues": q("SELECT count(*) FROM issues"), "case_issues": q("SELECT count(*) FROM case_issues"),
            "enrich_cases": q("SELECT count(*) FROM enrich_cases"), "briefs": q("SELECT count(*) FROM briefs"),
            "statutes": q("SELECT count(*) FROM statutes")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if not os.path.exists(a.db):
        sys.exit(f"no such database: {a.db}")
    if a.apply:
        stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
        bak = f"{a.db}.pre-enrich-{stamp}"
        src = sqlite3.connect(a.db)
        dst = sqlite3.connect(bak)
        src.backup(dst)
        dst.close(); src.close()
        print(f"backup -> {bak}")
    con = sqlite3.connect(a.db)
    before = counts(con)
    con.execute("BEGIN")
    have_auto = {r[0] for r in con.execute("SELECT DISTINCT issue FROM case_issues WHERE source = 'auto'")}
    rules = load_taxonomy()
    for rule in rules:
        con.execute("INSERT OR REPLACE INTO issues VALUES (?,?,?,?)", rule)
    new = [r for r in rules if r[0] not in have_auto]
    for issue, _, _, q in new:
        con.execute("""INSERT OR IGNORE INTO case_issues
            SELECT k.case_id, ?, count(*), 'auto' FROM chunks_fts JOIN chunks k ON k.rowid = chunks_fts.rowid
            JOIN cases c ON c.case_id = k.case_id
            WHERE chunks_fts MATCH ? GROUP BY k.case_id""", (issue, q))
    addenda = os.path.join(HERE, "statute_addenda.jsonl")
    added_acts = collections.Counter()
    if os.path.exists(addenda):
        present = {r[0] for r in con.execute("SELECT DISTINCT act_id FROM statutes")}
        for line in open(addenda, encoding="utf-8"):
            r = json.loads(line)
            if r["act_id"] in present or r["act_id"] not in STATUTE_ACTS:
                continue
            con.execute("INSERT INTO statutes (act_id, act_short, act_title, chapter, section_number, section_title, "
                        "text, source_url) VALUES (?,?,?,?,?,?,?,?)",
                        (r["act_id"], STATUTE_ACTS[r["act_id"]], r["act_title"], r["chapter"], r["section_number"],
                         r["section_title"], r["text"], r["source_url"]))
            added_acts[STATUTE_ACTS[r["act_id"]]] += 1
        if added_acts:
            con.execute("INSERT INTO statutes_fts(statutes_fts) VALUES('rebuild')")
    print("statute provisions added:", dict(added_acts) or "none")
    fixes = os.path.join(HERE, "case_fixes.json")
    if os.path.exists(fixes):
        for cid, cols in json.load(open(fixes, encoding="utf-8")).items():
            if cid.startswith("_"):
                continue
            for col, val in cols.items():
                if col.startswith("_") or col not in ("citation", "decision_date", "title", "case_number", "court"):
                    continue
                cur = con.execute(f"SELECT {col} FROM cases WHERE case_id=?", (cid,)).fetchone()
                if cur and cur[0] != val:
                    con.execute(f"UPDATE cases SET {col}=? WHERE case_id=?", (val, cid))
                    print(f"case fix: {cid}.{col}: {cur[0]!r} -> {val!r}")
    n = load_enrichment(con, ROOT, "public")
    con.execute("INSERT OR REPLACE INTO meta VALUES ('enriched', ?)", (datetime.date.today().isoformat(),))
    after = counts(con)
    print("auto-tagged new issues:", ", ".join(r[0] for r in new) or "none")
    print("enrichment files loaded:", dict(n))
    for k in before:
        print(f"  {k:13} {before[k]:>7} -> {after[k]:>7}")
    if a.apply:
        con.commit()
        print("APPLIED")
    else:
        con.rollback()
        print("DRY RUN - nothing written (add --apply)")
    con.close()


if __name__ == "__main__":
    main()
