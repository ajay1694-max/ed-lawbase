# ED LawBase — Usage Guide

An offline search tool for PMLA, FEMA and FEOA case law and statutes. It runs on your own machine — nothing you search or export leaves your computer.

## 1. Starting it

Open the `LawBase` folder and double-click **`Start LawBase.cmd`**. A black window opens (leave it running) and your browser opens to the search page. If it doesn't open automatically, go to the address it prints — normally **http://127.0.0.1:8765/**.

To stop it, close the black window.

## 2. The three tabs

### Judgments

This is the main tab. At the top:

| Field | What it does |
|---|---|
| Search box | Type your words. Every word must appear in the judgment (not necessarily the same paragraph — see below). |
| **Court** | Restrict to one court, or leave on "All courts". |
| **Act** | Restrict to PMLA, FEMA, FERA or FEOA. |
| **Issue** | A ready-made list of legal points — bail (s.45), arrest (s.19), pardon/approver, cognizance (s.44), and more. Pick one **with no search words** to list every case tagged with it. |
| **from yr / to yr** | Restrict by decision year. |
| **same passage only** | Off by default: your words can appear anywhere in the judgment. Tick it to require them in the same paragraph — stricter, fewer results. |

**Search tips:**
- Plain words: `pardon special court` — finds judgments where both appear somewhere.
- A phrase: put it in quotes — `"twin conditions"`.
- Several phrases: `"tender of pardon" "special court"` — both must appear.
- Alternatives: `pardon OR approver`.

Click any result to open the full judgment on the right. There you'll see the court, citation, date, disposition and coram, the issue tags, and — where we've written one — a headnote summarising the holding and marking whether it helps or hurts the ED's position.

### Statutes

Search PMLA, FEMA, FEOA and related Acts (BNSS, BNS, BSA, PC Act, NDPS, and others) section by section. Pick an Act from the dropdown, or search across all of them by keyword — e.g. searching "burden of proof" under PMLA finds s.24.

*Section numbers in the source can be off by one; the section text itself is reliable.*

### Briefs

Saved research notes that answer a specific question with citations already assembled — for example, the pardon-and-cognizance brief. Open one and export it straight to Word.

## 3. Getting results out

- **One judgment → Word:** open the case, click **Export judgment (DOCX)**.
- **A brief → Word:** open the brief, click **Export (DOCX)**.
- **Several cases → one citation table:** on any judgment, click **+ export list** to add it to your list (bottom of the screen shows the count). When ready, click **Export citation table (DOCX)** at the bottom of the page. This gives you a formatted table — case, court, citation, date, disposition, issues — ready to paste into a note or a court reply.

Every export carries a footer: *"Research lead only — cite from the certified copy / SCR / SCC and check later history"* plus the source attribution. Keep that footer if you paste the content elsewhere.

## 4. What's in it, and what isn't

- **13,411 judgments** — Supreme Court and all 25 High Courts, 1950 to about November 2025 — where the text names PMLA, FEMA, FERA or FEOA, or the title names the Directorate of Enforcement.
- **7,279 statutory provisions** — PMLA, FEMA, FEOA and the related Acts (BNSS/BNS/BSA, PC Act, NDPS, UAPA, Benami, Black Money, Companies, Income-tax, Customs (partial), COFEPOSA, SAFEMA).
- **Not included:** anything after the snapshot date, Special Court or district court orders, tribunal order text, and SCC citations (only SCR, where reported).

## 5. Keeping it current

From the same folder, run:
```
python app\update.py
```
This checks the shared repository for a newer data file and, if you're behind, downloads and verifies it before replacing your local copy. It only touches the judgments/statutes database — nothing else changes.

## 6. A rule to remember

Everything here is a **research lead**. Before you rely on a case or cite it, check the certified copy or SCR/SCC, and confirm it hasn't since been appealed, stayed or overruled.
