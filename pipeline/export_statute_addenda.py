#!/usr/bin/env python3
r"""export_statute_addenda.py - write statute rows for acts added to STATUTE_ACTS after a build, so that
apply_enrich.py can load them into an existing database on a machine without the Open India Law mirror.

    python pipeline\export_statute_addenda.py C:\Users\Admin\OpenIndiaLaw\v2026.08.1\in_central_legislation.parquet ^
        IND_central_2154 IND_central_2006
writes pipeline/statute_addenda.jsonl (one JSON object per provision; same columns as the statutes table).
"""
import json, os, sys

import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build import STATUTE_ACTS  # noqa: E402

parquet, ids = sys.argv[1], sys.argv[2:]
missing = [i for i in ids if i not in STATUTE_ACTS]
if missing:
    sys.exit(f"add these to STATUTE_ACTS in build.py first: {missing}")
rows = duckdb.sql(f"""SELECT act_id, title, chapter, section_number, section_title, text, source_url
    FROM read_parquet('{parquet.replace(chr(92), '/')}') WHERE act_id IN ({",".join(f"'{i}'" for i in ids)})
    ORDER BY act_id, chunk_id""").fetchall()
out = os.path.join(HERE, "statute_addenda.jsonl")
with open(out, "w", encoding="utf-8", newline="\n") as f:
    for r in rows:
        f.write(json.dumps(dict(zip(("act_id", "act_title", "chapter", "section_number", "section_title", "text",
                                     "source_url"), r)), ensure_ascii=False) + "\n")
print(f"{len(rows)} provisions -> {out}")
