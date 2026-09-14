# ED LawBase

An offline, searchable corpus of judgments and statutes under the **PMLA, FEMA and FEOA**, built for Enforcement Directorate officers. It is meant for investigation and for drafting court replies. Officers run it on their own machines, it updates from a shared repository, and the output comes in citable formats.

## Two tiers — read this first

| Tier | What it holds | Where it lives |
|---|---|---|
| **Public** (`tier = "public"`) | SC and HC judgments, statutes, our headnotes and issue tags on those public judgments, and research briefs that rely only on public law | This GitHub repository and its Releases |
| **Internal** (`tier = "internal"`) | Special Court, AA and ATFP orders obtained in our cases; court-reply templates; notes that draw on ED files | An internal pack, **never pushed to GitHub**, distributed through official channels |

The app merges both tiers when an internal pack is present. The build refuses to publish any record marked `tier = "internal"` (see `pipeline/guard.py`).

## Layout

```
pipeline/        build scripts: sweep the source corpus, tag issues, build lawbase.sqlite
taxonomy/        issues.toml - issue tags (PMLA/FEMA/FEOA) and their auto-tag patterns
enrich/
  cases/         <case_id>.md - headnote, issues, stance, status (TOML front matter)
  briefs/        <slug>.md - research briefs (e.g. special court pardon)
app/             portable browser app (stdlib Python server + static UI + DOCX export)
dist/            built portable folder for officers (not committed)
```

The internal pack uses the same `enrich/` layout, plus `orders/` for PDFs with metadata and `templates/` for court-reply paragraphs.

## Data sources

- Judgments and statutes: **Open India Law** by Vaquill AI, snapshot v2026.08.1, licensed CC BY 4.0. **Attribution is mandatory.** Coverage is the SC and 25 HCs up to about Nov 2025. There are no district courts and no tribunal text.
- Known source gaps: the CrPC 1973 text is absent (BNSS is present); the Customs Act 1962 is partial (30 provisions); SCC citations are not included.

## Coverage (build of 14.09.2026, evening)

| | |
|---|---|
| Judgments | **13,456** cases (147,357 text chunks): SC, 25 HCs, the SAFEMA Appellate Tribunal and NCLAT, 1950 to **September 2026** |
| By statute named in the text | PMLA 6,630+ · FERA 2,413+ · FEMA 1,946+ · none named, but ED in the title: ~1,500 |
| Statutes | 7,279 provisions: PMLA, FEMA, FEOA, BNSS, BNS, BSA, IPC, Evidence Act, PC Act, NDPS, UAPA, Benami, Black Money, Companies, Income-tax, Customs (partial), COFEPOSA, SAFEMA |
| Issue tags | 28 (`taxonomy/issues.toml`), auto-tagged by FTS5 query |
| Database file | 867 MB SQLite |

**Two sources feed the public tier**, both handled by `pipeline/build.py public`:
1. Open India Law (CC BY 4.0) via `openindialaw.py sweep`, up to its ~Nov 2025 snapshot.
2. `pipeline/ingest_ed_portal.py` - 45 judgments downloaded individually from `enforcementdirectorate.gov.in`'s own "important judgements" page, filling the gap to September 2026. Merged straight into the matching court's file (`<slug>_pmla_chunks.parquet`), not kept as a separate bucket. Two brand-new bodies came in this way: the **SAFEMA Appellate Tribunal** and **NCLAT**, absent from Open India Law entirely. 17 of the 45 carried an ED eOffice administrative stamp (page/file-number footer) that is stripped before ingestion; 2 had a broken PDF font layer and were OCR'd instead (`pipeline/ocr_cache/`).

**A third source is internal-tier only, and stays that way.** `pipeline/ingest_compendiums.py` ingests ED counsel's own compiled judgment binders (Coram Compilation, the AA Judgment Binder, the Chhavi Ranjan and Alamgir Alam compilations, delay/arrest notes, the SG's PMLA overview note) as full-text-searchable briefs in the **internal pack** - never this repo. Several are confirmed to carry SCC Online / Eastern Book Company "TruePrint" copyrighted formatting; Open India Law's own policy is to exclude commercial law reporter material for exactly this reason, and this project follows the same rule. Each binder is ingested whole (with page markers) rather than split into its individually-cited authorities - see the docstring in `ingest_compendiums.py` for why that split is valuable future work, not done yet.

**Relevance rule.** A judgment is included when its text names PMLA, FEMA, FERA or FEOA, **or** its title names the Directorate of Enforcement. Matching ED in the petitioner and respondent fields alone is not enough. In High Court metadata those fields often hold cited case names or other departments' enforcement wings, and 1,727 such cases were excluded.

## Rule of use

The corpus gives research leads. Before relying on anything, cite from the certified copy or SCR/SCC and check later history.
