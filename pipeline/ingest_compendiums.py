#!/usr/bin/env python3
r"""ingest_compendiums.py - the compilation binders and notes in PMLA_Judgments_and_Compendiums\
02_Local_Compendiums_and_Binders, as full-text-searchable INTERNAL-tier briefs.

  python pipeline\ingest_compendiums.py --pack C:\Users\Admin\Projects\ed-lawbase-internal

INTERNAL TIER ONLY - never promote these to the public repo without checking each one first. Three
were confirmed carrying "TruePrint" / Eastern Book Company marks in their first 30 pages (Coram
Compilation Vol 1, the AA Judgment Binder, the Chhavi Ranjan compilation) - that is SCC Online's
copyrighted formatting, not the public-domain judgment text underneath it. The others were not
positively cleared either (a source stamp deeper in a 500-page PDF is easy to miss on a sample), and
Open India Law's own stated policy is to exclude commercial law reporter material entirely. Treat
every one of these as ED counsel's litigation work product: internal reference material, not something
this project redistributes.

Every one of these PDFs carries its own embedded index (Sr./S./SI. No. | case citation | page range) -
see pipeline\ingest_ed_portal.py's sibling note. This script does NOT parse those indexes into separate
per-case entries yet; it ingests each PDF as one long searchable document with page markers, which is
enough to find things via the app's search and then jump to the right page in the original PDF. Splitting
by the embedded index into individually-citable entries (recovering real SCC/SCC OnLine citations we are
currently missing for several PMLA landmarks) is valuable future work - flagged, not done here.
"""
import argparse, os, re

import fitz  # PyMuPDF

SRC = r"C:\Users\Admin\Documents\PMLA_Judgments_and_Compendiums\02_Local_Compendiums_and_Binders"

DOCS = [  # (filename, slug, title)
    ("10. AA-Judgment Binder-09012025.pdf", "aa-judgment-binder",
     "Adjudicating Authority judgment binder (compiled 09.01.2025)"),
    ("CHHAVI RANJAN 1044 VOL 3 FINAL COMPILATION WITH INDEX 19.11.2025.pdf", "chhavi-ranjan-compilation-vol3",
     "Compilation of judgments, Chhavi Ranjan v. UoI (Jharkhand HC W.P.(Cr) 1044/2024), Vol 3 (19.11.2025)"),
    ("Coram Compilation Volume 1.pdf", "coram-compilation-vol1",
     "Compilation of judgments on Coram composition of the Adjudicating Authority, Vol 1"),
    ("FINAL COMPILATION.pdf", "final-compilation-vol2",
     "Judgment compilation on behalf of the Directorate of Enforcement, Vol 2"),
    ("Judgement - PMLA.pdf", "jk-hc-niket-kansal-discharge-predicate",
     "J&K HC, Niket Kansal - PMLA independent of predicate offence discharge (CRM(M) 140/2025, 22.05.2025)"),
    ("Note on arrest prior to kejriwal 2025.pdf", "note-arrest-prior-to-kejriwal-2025",
     "ED note on arrests made prior to the Kejriwal v. ED judgment of 12.07.2024, with compiled authorities"),
    ("Note-2-Overview-of-the-PMLA TUSHAR MEHTA.pdf", "note-overview-pmla-tushar-mehta",
     "Overview of the PMLA / defining money laundering - Note by Tushar Mehta, Solicitor General of India"),
    ("Revised alamgir compilation .pdf", "alamgir-alam-compilation-revised",
     "Revised compilation of judgments, Alamgir Alam v. ED (Jharkhand HC B.A. 9548/2024)"),
    ("Updated-2 Delay Compilation.pdf", "delay-compilation-updated2",
     "Compilation on delay/prolonged incarceration as a ground for bail, on behalf of ED"),
    ("vijay-madanlal-case-compressed.pdf", "vijay-madanlal-full-report",
     "Vijay Madanlal Choudhary v. Union of India, 2022 SCC OnLine SC 929 - full compiled report"),
]


def extract(path):
    d = fitz.open(path)
    parts = [f"--- page {i + 1} of {len(d)} ---\n{p.get_text()}" for i, p in enumerate(d)]
    return "\n\n".join(parts), len(d)


def write_brief(pack_root, slug, title, body, source_file, pages):
    out_dir = os.path.join(pack_root, "enrich", "briefs")
    os.makedirs(out_dir, exist_ok=True)
    front = (f'+++\nslug = "{slug}"\ntitle = "{title}"\ntier = "internal"\nissues = []\n'
             f'date = "2026-09-14"\nauthor = "Ingested from PMLA_Judgments_and_Compendiums ({pages} pages, '
             f'source file: {source_file})"\n+++\n\n')
    note = (f"**Full text of `{source_file}`** ({pages} pages), ingested verbatim for search only. "
            "This binder carries its own index of the individual authorities it compiles with page "
            "ranges for each - see the `--- page N ---` markers below to find one, then open the "
            "original PDF at that page for the certified text. Internal tier: possible SCC Online / "
            "Eastern Book Company copyrighted formatting - never push this brief to the public repo.\n\n")
    open(os.path.join(out_dir, f"{slug}.md"), "w", encoding="utf-8").write(front + note + body)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pack", required=True, help="ed-lawbase-internal repo root")
    a = ap.parse_args()
    for fname, slug, title in DOCS:
        path = os.path.join(SRC, fname)
        if not os.path.exists(path):
            print("MISSING, skipped:", fname); continue
        body, pages = extract(path)
        write_brief(a.pack, slug, title, body, fname, pages)
        print(f"{slug:38s} {pages:4d}pg  {len(body):9,d} chars  <- {fname}")

    # table of judgements.docx: already plain text (an LLM-drafted summary table, not a PDF export), and
    # short enough to store simply
    import zipfile, html
    docx = os.path.join(SRC, "table of judgements.docx")
    if os.path.exists(docx):
        x = zipfile.ZipFile(docx).read("word/document.xml").decode("utf-8")
        paras = [html.unescape(re.sub(r"<[^>]+>", "", s)) for s in re.findall(r"<w:p[ >].*?</w:p>", x, flags=re.S)]
        text = "\n\n".join(t for t in paras if t.strip())
        write_brief(a.pack, "table-of-judgements-summary", "Table of PMLA judgments and questions of law (summary)",
                   text, "table of judgements.docx", 1)
        print(f"{'table-of-judgements-summary':38s} {'1':>4}pg  {len(text):9,d} chars  <- table of judgements.docx")


if __name__ == "__main__":
    main()
