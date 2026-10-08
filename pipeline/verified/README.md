# Verified incremental intake

These bundles contain public judgment text and independently written headnotes, with primary-source URL and SHA256. Private collection provenance belongs outside this repository.

Run `python pipeline/import_verified.py data/lawbase.sqlite pipeline/verified/2026-10-08.json` for a dry run; add `--apply` to commit. Each invocation retains a consistent SQLite backup. It verifies preservation of existing rows, refuses conflicting metadata and duplicate identities, appends FTS entries, and preserves existing headnotes. Restart the application after a successful apply to refresh process caches.

The 08.10.2026 bundle adds the 26-page Salgaocar FEMA order and corrects the existing Rohit Vij record. No missing attachment or secondary mirror is represented as an original. Later history is explicitly unverified.

After any future full corpus rebuild, reapply the verified bundles before serving the database. They are separate from the upstream parquet corpus. Do not replace a live database with a rebuild that omits existing annotations.
