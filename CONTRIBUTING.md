# Contributing to ED LawBase

Every contribution is a Markdown file with TOML front matter between `+++` lines. **Declare the tier first.** A pre-commit hook (`pipeline/guard.py`) blocks any commit that puts internal material in this public repository.

- **Public tier (this repo):** only judgments and statutes, plus your analysis of them.
- **Internal tier:** anything that draws on ED files, case numbers, manuals or strategy. It goes in the internal pack, never here.

## 1. Headnote on a judgment — `enrich/cases/<case_id>.md`

Find the `case_id` in the app; it appears in the case header.

```
+++
case_id = "2024_INSC_434"
tier = "public"
stance = "adverse"            # pro-ED | adverse | mixed | neutral
status = "good law"           # good law | overruled | stayed | under appeal | per incuriam
citation_extra = ""           # SCC / other reporter cite, if verified
issues = ["pmla.s44_cognizance", "pmla.s19_arrest"]
summary = "One or two sentences an officer can paste into a reply."
updated = "2026-09-14"
+++

Holding with paragraph numbers. Quote sparingly and exactly.
Later history: followed in / distinguished in / overruled by.
```

Issue keys are in `taxonomy/issues.toml`. To propose a new issue, add it there with a label and an auto-tag pattern.

## 2. Research brief — `enrich/briefs/<slug>.md`

```
+++
slug = "short-kebab-name"
title = "Question the brief answers"
tier = "public"
issues = ["pmla.pardon_approver"]
date = "2026-09-14"
author = "Unit / officer"
+++
```

In the body, give the answer first, then the authorities table, then the open points. Mark anything not read in full as *(as quoted)*.

## 3. Internal pack only

- `templates/<slug>.md`: court-reply paragraphs with `{placeholders}`.
- `orders/<order_id>.md`: metadata for an order obtained in a case, with the PDF in the same folder.

Both carry `tier = "internal"`. See the internal pack README.

## Review

- Every contribution is reviewed before merge: a legal-cell or nominated officer checks the holding against the certified copy.
- Merging triggers a rebuild, and officers pick up the new data with `app\update.py`.
