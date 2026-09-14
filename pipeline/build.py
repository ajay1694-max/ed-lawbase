#!/usr/bin/env python3
r"""build.py - assemble the LawBase SQLite file that the officer app reads.

PUBLIC build (judgments + statutes + public enrichment):
  python pipeline\build.py public --corpus C:\Users\Admin\OpenIndiaLaw\ed-corpus-v2026.08.1 ^
      --statutes C:\Users\Admin\OpenIndiaLaw\v2026.08.1\in_central_legislation.parquet ^
      --out data\lawbase.sqlite

INTERNAL build (enrichment, briefs, templates and order metadata from the internal pack only):
  python pipeline\build.py internal --pack C:\Users\Admin\Projects\ed-lawbase-internal ^
      --out internal\lawbase-internal.sqlite

--corpus is the output folder of `openindialaw.py sweep` (<court>_pmla_chunks.parquet files).
Issue tags and Act flags are computed with FTS5 queries AFTER the index is built (taxonomy/issues.toml),
which takes seconds instead of running Python regexes over every chunk.
Needs duckdb on the BUILD machine only; the app uses nothing beyond the Python stdlib.
"""
import argparse, collections, datetime, glob, os, re, sqlite3, sys, time, tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from guard import check_tier, read_md  # noqa: E402

SNAPSHOT = "v2026.08.1"
ATTRIBUTION = ("Judgments and statutes: Open India Law by Vaquill AI (github.com/Vaquill-AI/open-india-law), "
               "snapshot v2026.08.1, licensed CC BY 4.0. Headnotes, tags and briefs: ED LawBase.")

# statutes carried into the app (act_id -> short name)
STATUTE_ACTS = {
    "IND_central_2036": "PMLA 2002", "IND_central_1988": "FEMA 1999", "IND_central_4035": "FEOA 2018",
    "IND_central_20099": "BNSS 2023", "IND_central_20062": "BNS 2023", "IND_central_20063": "BSA 2023",
    "IND_REP_659_1860": "IPC 1860 (repealed)", "IND_REP_971_1872": "Evidence Act 1872 (repealed)",
    "IND_central_1558": "PC Act 1988", "IND_central_1791": "NDPS 1985", "IND_central_1470": "UAPA 1967",
    "IND_central_1840": "Benami Act 1988", "IND_central_2147": "Black Money Act 2015",
    "IND_central_2114": "Companies Act 2013", "IND_central_2435": "Income-tax Act 1961",
    "IND_central_2475": "Customs Act 1962 (partial)", "IND_central_1618": "COFEPOSA 1974",
    "IND_central_1490": "SAFEMA 1976",
}

ACT_FTS = {
    "PMLA": '"money laundering" OR pmla',
    "FEMA": '"foreign exchange management" OR fema',
    "FERA": '"foreign exchange regulation" OR fera',
    "FEOA": '"fugitive economic" OR feoa',
}
BANNER = re.compile(r"^\s*Case:[^\n]*\n(?:Court:[^\n]*\n)?Section:[^\n]*\n")
# relevance filter (DuckDB RE2 syntax): text names one of ED's statutes, or the title names the Directorate
ED_TEXT_RX = (r"(?i)prevention of money[- ]?laundering|\bPMLA\b|foreign exchange management|\bFEMA\b"
              r"|foreign exchange regulation|\bFERA\b|fugitive economic offender|\bFEOA\b")
ED_TITLE_RX = r"(?i)directorate\s*of\s*enforcement|enforcement\s*directorate|director\s*of\s*enforcement"

PUBLIC_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE cases (case_id TEXT PRIMARY KEY, court_slug TEXT, court TEXT, title TEXT, case_number TEXT,
  citation TEXT, decision_date TEXT, year INTEGER, disposition TEXT, judges TEXT, source_url TEXT,
  n_chunks INTEGER, acts TEXT);
CREATE TABLE chunks (rowid INTEGER PRIMARY KEY, case_id TEXT, chunk_index INTEGER, section_type TEXT, text TEXT);
CREATE VIRTUAL TABLE chunks_fts USING fts5(text, content='chunks', content_rowid='rowid',
  tokenize='unicode61 remove_diacritics 2');
CREATE TABLE issues (issue TEXT PRIMARY KEY, label TEXT, act TEXT, fts TEXT);
CREATE TABLE case_issues (case_id TEXT, issue TEXT, hits INTEGER, source TEXT, PRIMARY KEY (case_id, issue));
CREATE TABLE statutes (rowid INTEGER PRIMARY KEY, act_id TEXT, act_short TEXT, act_title TEXT, chapter TEXT,
  section_number TEXT, section_title TEXT, text TEXT, source_url TEXT);
CREATE VIRTUAL TABLE statutes_fts USING fts5(text, section_title, content='statutes', content_rowid='rowid',
  tokenize='unicode61 remove_diacritics 2');
"""
ENRICH_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE enrich_cases (case_id TEXT PRIMARY KEY, tier TEXT, stance TEXT, status TEXT, citation_extra TEXT,
  issues TEXT, summary TEXT, body TEXT, updated TEXT);
CREATE TABLE briefs (rowid INTEGER PRIMARY KEY, slug TEXT UNIQUE, title TEXT, tier TEXT, issues TEXT, date TEXT,
  author TEXT, body TEXT);
CREATE VIRTUAL TABLE briefs_fts USING fts5(title, body, content='briefs', content_rowid='rowid');
CREATE TABLE templates (rowid INTEGER PRIMARY KEY, slug TEXT UNIQUE, title TEXT, tier TEXT, issues TEXT, body TEXT);
CREATE TABLE orders (order_id TEXT PRIMARY KEY, tier TEXT, court TEXT, case_ref TEXT, date TEXT, issues TEXT,
  summary TEXT, file TEXT);
"""


def load_taxonomy():
    data = tomllib.load(open(os.path.join(ROOT, "taxonomy", "issues.toml"), "rb"))
    return [(f"{act}.{name}", rule["label"], act, rule["fts"]) for act, sub in data.items() for name, rule in sub.items()]


def fresh(path, schema):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".building"
    for leftover in (tmp, tmp + "-journal"):
        if os.path.exists(leftover):
            os.remove(leftover)
    con = sqlite3.connect(tmp)
    con.executescript(schema)
    return con, tmp


def finish(con, tmp, path, meta):
    con.executemany("INSERT OR REPLACE INTO meta VALUES (?,?)", [(k, str(v)) for k, v in meta.items()])
    con.commit()
    con.execute("ANALYZE")
    con.execute("VACUUM")
    con.close()
    os.replace(tmp, path)
    print(f"-> {path}  ({os.path.getsize(path) / 1e6:,.0f} MB)")


def load_enrichment(con, root, building):
    n = collections.Counter()
    for path in sorted(glob.glob(os.path.join(root, "enrich", "cases", "*.md"))):
        meta, body = read_md(path)
        tier = check_tier(meta, building, path)
        issues = meta.get("issues", [])
        con.execute("INSERT OR REPLACE INTO enrich_cases VALUES (?,?,?,?,?,?,?,?,?)",
                    (meta["case_id"], tier, meta.get("stance", ""), meta.get("status", ""),
                     meta.get("citation_extra", ""), ",".join(issues), meta.get("summary", ""), body.strip(),
                     str(meta.get("updated", ""))))
        if building == "public":
            for iss in issues:
                con.execute("INSERT OR REPLACE INTO case_issues VALUES (?,?,?,?)", (meta["case_id"], iss, 999, "curated"))
        n["cases"] += 1
    for path in sorted(glob.glob(os.path.join(root, "enrich", "briefs", "*.md"))):
        meta, body = read_md(path)
        tier = check_tier(meta, building, path)
        con.execute("INSERT OR REPLACE INTO briefs (slug,title,tier,issues,date,author,body) VALUES (?,?,?,?,?,?,?)",
                    (meta["slug"], meta["title"], tier, ",".join(meta.get("issues", [])), str(meta.get("date", "")),
                     meta.get("author", ""), body.strip()))
        n["briefs"] += 1
    for path in sorted(glob.glob(os.path.join(root, "templates", "*.md"))):
        meta, body = read_md(path)
        tier = check_tier(meta, building, path)
        con.execute("INSERT OR REPLACE INTO templates (slug,title,tier,issues,body) VALUES (?,?,?,?,?)",
                    (meta["slug"], meta["title"], tier, ",".join(meta.get("issues", [])), body.strip()))
        n["templates"] += 1
    for path in sorted(glob.glob(os.path.join(root, "orders", "*.md"))):
        meta, body = read_md(path)
        tier = check_tier(meta, building, path)
        con.execute("INSERT OR REPLACE INTO orders VALUES (?,?,?,?,?,?,?,?)",
                    (meta["order_id"], tier, meta.get("court", ""), meta.get("case_ref", ""), str(meta.get("date", "")),
                     ",".join(meta.get("issues", [])), meta.get("summary", "") or body.strip()[:2000],
                     meta.get("file", "")))
        n["orders"] += 1
    con.execute("INSERT INTO briefs_fts(briefs_fts) VALUES('rebuild')")
    return n


def tag(con, rules):
    """Issue tags and Act flags from FTS5 queries over the finished index."""
    t = time.time()
    for issue, _, _, q in rules:
        con.execute("""INSERT OR IGNORE INTO case_issues
            SELECT k.case_id, ?, count(*), 'auto' FROM chunks_fts JOIN chunks k ON k.rowid = chunks_fts.rowid
            WHERE chunks_fts MATCH ? GROUP BY k.case_id""", (issue, q))
    con.execute("CREATE TEMP TABLE case_acts (case_id TEXT, act TEXT)")
    for act, q in ACT_FTS.items():
        con.execute("""INSERT INTO case_acts SELECT DISTINCT k.case_id, ? FROM chunks_fts
            JOIN chunks k ON k.rowid = chunks_fts.rowid WHERE chunks_fts MATCH ?""", (act, q))
    con.execute("""UPDATE cases SET acts = (SELECT group_concat(act, ',') FROM
        (SELECT DISTINCT act FROM case_acts a WHERE a.case_id = cases.case_id ORDER BY act))""")
    con.commit()
    print(f"tagged {len(rules)} issues + {len(ACT_FTS)} Acts in {time.time() - t:.0f}s", flush=True)


def build_public(a):
    import duckdb
    t0 = time.time()
    rules = load_taxonomy()
    con, tmp = fresh(a.out, PUBLIC_SCHEMA + ENRICH_SCHEMA)
    con.executemany("INSERT INTO issues VALUES (?,?,?,?)", rules)
    dk = duckdb.connect()
    files = sorted(glob.glob(os.path.join(a.corpus, "*_chunks.parquet")))
    if not files:
        sys.exit(f"no *_chunks.parquet in {a.corpus}")
    n_chunks = 0
    for f in files:
        slug = re.sub(r"_(pmla|ed)?_?chunks\.parquet$", "", os.path.basename(f))
        fp = f.replace("\\", "/")
        try:
            meta_rows = dk.execute(f"""SELECT case_id, any_value(court), any_value(title), any_value(case_number),
                any_value(citation), left(CAST(any_value(decision_date) AS VARCHAR), 10), any_value(year),
                any_value(disposition), array_to_string(any_value(judges), '; '), any_value(source_url), count(*)
                FROM read_parquet('{fp}') GROUP BY case_id""").fetchall()
        except duckdb.Error as e:  # e.g. a half-written file from an interrupted sweep
            print(f"{slug:20s} SKIPPED - unreadable: {str(e).splitlines()[0]}", flush=True)
            continue
        # Relevance filter. The sweep matches ED in petitioner/respondent fields, but in HC metadata those fields
        # often hold CITED case names ("... v. Directorate of Enforcement (2019) 9 SCC 24" in ordinary bail
        # orders) or other departments' enforcement wings. Keep a case only if its text names PMLA/FEMA/FERA/FEOA
        # or its title names the Directorate of Enforcement.
        keep = {r[0] for r in dk.execute(f"""SELECT case_id FROM read_parquet('{fp}')
            GROUP BY case_id HAVING bool_or(regexp_matches(text, '{ED_TEXT_RX}'))
                OR bool_or(regexp_matches(coalesce(title, ''), '{ED_TITLE_RX}'))""").fetchall()}
        dropped = len(meta_rows) - len(keep)
        meta_rows = [r for r in meta_rows if r[0] in keep]
        con.executemany("INSERT OR REPLACE INTO cases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'')",
                        [(r[0], slug, *r[1:]) for r in meta_rows])
        cur = dk.execute(f"SELECT case_id, chunk_index, section_type, text FROM read_parquet('{fp}') ORDER BY case_id, chunk_index")
        while batch := cur.fetchmany(20000):
            con.executemany("INSERT INTO chunks (case_id, chunk_index, section_type, text) VALUES (?,?,?,?)",
                            [(cid, idx, st, BANNER.sub("", txt or "", count=1)) for cid, idx, st, txt in batch])
            n_chunks += len(batch)
        con.commit()
        print(f"{slug:20s} {len(meta_rows):6d} cases kept, {dropped:5d} dropped (no ED statute in text, no ED in title)  "
              f"{n_chunks:9,d} chunks so far  {time.time() - t0:5.0f}s", flush=True)
    con.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
    print(f"judgment index built  {time.time() - t0:.0f}s", flush=True)
    tag(con, rules)

    ids = ",".join(f"'{k}'" for k in STATUTE_ACTS)
    srows = dk.execute(f"""SELECT act_id, title, chapter, section_number, section_title, text, source_url
        FROM read_parquet('{a.statutes.replace(chr(92), '/')}') WHERE act_id IN ({ids}) ORDER BY act_id, chunk_id""").fetchall()
    con.executemany("INSERT INTO statutes (act_id, act_short, act_title, chapter, section_number, section_title, text, source_url) "
                    "VALUES (?,?,?,?,?,?,?,?)", [(r[0], STATUTE_ACTS[r[0]], *r[1:]) for r in srows])
    con.execute("INSERT INTO statutes_fts(statutes_fts) VALUES('rebuild')")

    n = load_enrichment(con, a.enrich or ROOT, "public")
    total_cases = con.execute("SELECT count(*) FROM cases").fetchone()[0]
    finish(con, tmp, a.out, {"tier": "public", "snapshot": SNAPSHOT, "built": datetime.datetime.now().isoformat(timespec="minutes"),
                             "cases": total_cases, "chunks": n_chunks, "provisions": len(srows), "attribution": ATTRIBUTION,
                             "curated_cases": n["cases"], "briefs": n["briefs"]})
    print(f"done in {time.time() - t0:.0f}s: {total_cases:,} cases, {n_chunks:,} chunks, {len(srows):,} provisions, {dict(n)}")


def build_internal(a):
    con, tmp = fresh(a.out, ENRICH_SCHEMA)
    n = load_enrichment(con, a.pack, "internal")
    finish(con, tmp, a.out, {"tier": "internal", "built": datetime.datetime.now().isoformat(timespec="minutes"), **n})
    print(f"internal pack: {dict(n)}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)
    x = s.add_parser("public")
    x.add_argument("--corpus", required=True); x.add_argument("--statutes", required=True)
    x.add_argument("--enrich", help="repo root holding enrich/ (default: this repo)"); x.add_argument("--out", required=True)
    x.set_defaults(fn=build_public)
    x = s.add_parser("internal")
    x.add_argument("--pack", required=True); x.add_argument("--out", required=True)
    x.set_defaults(fn=build_internal)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
