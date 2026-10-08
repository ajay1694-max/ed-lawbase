# Research and member contributions

The research upgrade adds complete paginated judgment search (25 or 50 results per page), date sorting, shareable judgment/passage links, find-in-judgment, citation/extract copying, font controls, saved folders and notes, saved searches, brief full-text search, comparison of up to three judgments, and an indexed DOCX authority bundle of up to twenty judgments.

The corpus contains extracted text. LawBase passage numbers are **not court paragraph numbers**. The original-source button distinguishes a linked PDF from a collection page; some records have no source link. The database snapshot and later verified additions do not establish comprehensive coverage through the latest displayed decision date. Existing statute section labels require checking against the source text.

## Team workspace

My research belongs to the signed-in account. People sharing one team login share its folders, notes, searches and submission history. Use individual officer accounts for separate workspaces. The export basket is stored per account on that browser; saved research persists on the server. Administrators can review submissions but the library API does not expose other accounts' personal notes.

## Contribute

Members provide their name, a case title, and a citation, source link or public judgment PDF. PDFs are limited to 8 MB; a citation or official link can be submitted for larger documents. Each account may make up to 25 submissions per UTC day. Exact duplicate uploads by the same account reuse the existing request. The attachment store is capped at 2 GB; citation requests remain available when full.

Uploads are review attachments, not automatically trusted corpus documents. They are stored under generated filenames, served as authenticated downloads, and never executed. Header/type/size checks do not replace PDF/source verification. Do not upload confidential investigation material. Reviewers verify identity, court, date, completeness, source and duplicate status before incremental import. Status and reviewer notes are visible to the submitting account. Integrated status requires an existing verified-source corpus record. Every review change is logged; stale updates are rejected.

## Storage and operations

- `data/lawbase.sqlite`: public judgments, provisions and reviewed annotations.
- `data/auth.sqlite`: accounts and session revocation versions.
- `data/research.sqlite`: account libraries, searches, submissions and review audit.
- `data/member_uploads/`: submitted PDFs, outside static hosting and git.

Back up the database files with SQLite's backup API and copy attachments before deployment. `python3 pipeline/backup_state.py` creates and validates these snapshots in `data/backups/`. It does not delete old snapshots. Preserve disk space and back up again before any corpus import. Never replace research/auth data with a public corpus release or reseed a live database. Keep all account data, notes, uploads and backups out of the public repository.

Use `pipeline/import_verified.py` to dry-run and apply reviewed public content bundles. It backs up before apply, checks duplicate IDs/source provenance, preserves existing annotations and verifies pre-existing rows. Updating research status alone does not publish a judgment. The member queue API lists up to 500 items, prioritising open requests; if volume exceeds this, process the oldest open items before completed history. Review-note history remains in `review_events`.

Search uses the complete compact FTS passage map, generates snippets only for the visible page, retains bounded response caches, and permits at most three concurrent uncached read workloads. No paid API or third-party JavaScript is required. AI answers, automatic treatment labels and comprehensive later-history coverage are not provided by this release.

## Validation

Run `python -m unittest discover -s tests -p 'test_*.py'`, `python tests/test_search_equivalence.py`, `python pipeline/guard.py`, and `node --check` on both app scripts. With the local server running, use `python tests/http_smoke.py` for gzip/cache and concurrent search validation. Browser-check reader, notes, contribution and reviewer paths before deployment.
