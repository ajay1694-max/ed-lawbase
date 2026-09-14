#!/usr/bin/env python3
r"""ingest_ed_portal.py - turn the 45 judgments in PMLA_Judgments_and_Compendiums\01_ED_Official_Portal_Judgments
into a *_chunks.parquet that drops straight into pipeline\build.py's --corpus folder alongside the
openindialaw.py sweep output. These are individually downloaded from ED's own public portal
(enforcementdirectorate.gov.in/acts-and-rules/important-judgements/) and fill the gap after the Open
India Law snapshot (~Nov 2025) up to the download date - public tier, same character as any other
court judgment already in the corpus.

  python pipeline\ingest_ed_portal.py

17 of the 45 files carry a repeating ED eOffice banner (page/file-number + "Generated from eOffice by
<name>, ... ED Head Quarter on <date>") stamped by ED's internal e-filing system when the bundle was
prepared. That banner is stripped here - the underlying judgment text is a public court ruling either
way, but the banner is an internal administrative artefact and does not belong in a public dataset.
"""
import glob, os, re, sys

import fitz  # PyMuPDF
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = r"C:\Users\Admin\Documents\PMLA_Judgments_and_Compendiums\01_ED_Official_Portal_Judgments"
INDEX_MD = os.path.join(ROOT, "INDEX_OF_ED_JUDGMENTS.md")
# Merged straight into the existing per-court sweep files (<slug>_pmla_chunks.parquet), so these land
# under the SAME court_slug as the openindialaw.py sweep output - one "supreme-court" bucket, not a
# separate "ed-portal-2026" pseudo-court. New bodies not in Open India Law's court set (the SAFEMA
# Appellate Tribunal, NCLAT) get their own new file/slug, which is correct - they ARE different bodies.
CORPUS_DIR = r"C:\Users\Admin\OpenIndiaLaw\ed-corpus-v2026.08.1"
COLUMNS = ["case_id", "chunk_index", "section_type", "text", "court", "title", "case_number", "citation",
           "decision_date", "year", "disposition", "judges", "source_url"]
SOURCE_URL = "https://enforcementdirectorate.gov.in/acts-and-rules/important-judgements/"  # listing page, not per-file

# sr 5 and 27: Word->PDF export with a broken font ToUnicode map - the page LOOKS like normal digital
# text (verified visually) but PyMuPDF's text layer comes back as just the header/footer stamps.
# ocrfast.py --force on these two (91s: `python .claude\tools\ocrfast.py <pdf1> <pdf2> --force
# --out-dir pipeline\ocr_cache`) fixed it; the .txt output is checked into ocr_cache/ so this script
# doesn't depend on a session scratchpad. Re-run that command if either source PDF changes.
_OCR_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ocr_cache")
OCR_OVERRIDE = {
    5: os.path.join(_OCR_CACHE, "05_2026-07-20_Calcutta_High_Court_All_India_Trinamool_Congress_&_Anr._v._Union.txt"),
    27: os.path.join(_OCR_CACHE, "27_2026-04-28_High_Court_of_Bombay_at_G_Rohan_Rangnathan_Harmalkar_vs_Directorate_of.txt"),
}

# ED's internal eOffice banner: 4 lines repeated at the foot of nearly every page. Strip as a block,
# and also catch any of the three most distinctive lines occurring alone (a page break can split the block).
BANNER_BLOCK = re.compile(
    r"\n?\d{5,7}/\d{4}/Legal\(ED\)\(HO\)\n\d{1,4}\nFile No\. Leg/\d+/\d{4}-LEGAL-HO \(Computer No\. \d+\)\n"
    r"Generated from eOffice by [^\n]+\n?")
BANNER_LINE = re.compile(r"(?im)^(?:\d{5,7}/\d{4}/Legal\(ED\)\(HO\)|"
                         r"File No\. Leg/\d+/\d{4}-LEGAL-HO \(Computer No\. \d+\)|"
                         r"Generated from eOffice by .*ED Head Quarter on \d{2}/\d{2}/\d{4}.*)\s*$\n?")

COURT_SLUG = {  # ED's index labels -> the slug already used by openindialaw.py, where one exists
    "supreme court of india": "supreme-court",
    "high court of delhi": "delhi",
    "high court at calcutta": "calcutta", "calcutta high court": "calcutta",
    "madras high court": "madras", "high court of judicature at madras": "madras",
    "high court of karnataka": "karnataka", "high court for karnataka": "karnataka",
    "high court of kerala at ernakulam": "kerala", "the high court of kerala": "kerala",
    "jharkhand high court": "jharkhand", "high court of jharkhand at ranchi": "jharkhand",
    "patna high court": "patna",
    "telangana high court": "telangana", "high court for the state of telangana at hyderabad": "telangana",
    "high court of bombay at goa": "bombay",
    "high court of punjab and haryana at chandigarh": "punjab-and-haryana",
    "high court of chhattisgarh, bilaspur": "chhattisgarh", "high court of chhattisgarh at bilaspur": "chhattisgarh",
    "high court of chhattisgarh": "chhattisgarh",
    "high court of allahabad, lucknow": "allahabad",  # Lucknow bench - same court_slug as the main seat
    # bodies with no existing slug in the Open India Law corpus (tribunals, not High Courts)
    "appellate tribunal under safema at new delhi.": "atfp-safema", "appellate tribunal under safema, new delhi": "atfp-safema",
    "appellate tribunal under safema": "atfp-safema",
    "national company law appellate tribunal principal bench, new delhi": "nclat",
}

CASE_NO_RX = re.compile(r"\b((?:SLP|W\.?P\.?|Crl\.?A\.?|B\.A\.|MCRC|C\.M\.S\.A\.|CRM\(M\)|CRL\s*OP|Cr\.A\(DB\))"
                        r"[\.\s\(\)A-Za-z]{0,15}No\.?\s*\d+[\/\s]*(?:of\s*)?\d{4})", re.I)
CITATION_RX = re.compile(r"\(?\b20\d\d\)?\s*(?:INSC\s*\d+|SCC\s*OnLine\s*[A-Za-z]+\s*\d+|\d+\s*SCC\s*\d+)")
DISPOSITION_RX = re.compile(r"(?i)\b(dismissed|allowed|disposed\s+of|quashed|rejected|set\s+aside)\b")


def parse_index():
    rows = []
    for line in open(INDEX_MD, encoding="utf-8"):
        m = re.match(r"\|\s*(\d+)\s*\|\s*([\d-]+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|", line)
        if m:
            sr, date, court, title, fname = m.groups()
            rows.append({"sr": int(sr), "date": date, "court": court.strip(), "title": title.strip(), "file": fname})
    return rows


def clean_text(t):
    t = BANNER_BLOCK.sub("\n", t)
    t = BANNER_LINE.sub("", t)
    t = re.sub(r"(?m)^--- page \d+ ---\s*$", "", t)  # ocrfast.py page markers
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def chunk(text, size=1400):
    paras = re.split(r"\n\s*\n", text)
    out, buf = [], ""
    for p in paras:
        if len(buf) + len(p) > size and buf:
            out.append(buf.strip()); buf = ""
        buf += p + "\n\n"
    if buf.strip():
        out.append(buf.strip())
    return out or [text]


def main():
    rows = parse_index()
    print(f"{len(rows)} rows in index")
    by_slug = {}
    for r in rows:
        path = os.path.join(ROOT, r["file"])
        if not os.path.exists(path):
            print("MISSING FILE, skipped:", r["file"]); continue
        if r["sr"] in OCR_OVERRIDE:
            raw = open(OCR_OVERRIDE[r["sr"]], encoding="utf-8").read()
        else:
            raw = "".join(p.get_text() for p in fitz.open(path))
        full = clean_text(raw)
        flat = re.sub(r"\s+", " ", full)  # metadata regexes only - a PDF line-break can split a case number mid-token
        court_key = r["court"].strip().lower()
        slug = COURT_SLUG.get(court_key)
        if not slug:
            print(f"no slug mapping for court '{r['court']}' (sr {r['sr']}) - using a slugified fallback")
            slug = re.sub(r"[^a-z0-9]+", "-", court_key).strip("-")[:40]
        case_no = re.sub(r"\s+", " ", next(iter(CASE_NO_RX.findall(flat)), ""))
        citation = next(iter(CITATION_RX.findall(flat)), "")
        disp_matches = DISPOSITION_RX.findall(flat[-3000:])  # look near the end, where operative orders sit
        disposition = disp_matches[-1].title() if disp_matches else ""
        case_id = f"EDPORTAL_{r['sr']:02d}_{r['date']}"
        for i, ch in enumerate(chunk(full)):
            by_slug.setdefault(slug, []).append({
                "case_id": case_id, "chunk_index": i, "section_type": "body", "text": ch,
                "court": r["court"], "title": r["title"], "case_number": case_no, "citation": citation,
                "decision_date": r["date"], "year": int(r["date"][:4]), "disposition": disposition,
                "judges": [], "source_url": SOURCE_URL,
            })
        print(f"  sr{r['sr']:02d}  {slug:16s} {len(full):7,d} chars  case_no={case_no or '-':28s} disp={disposition or '-'}  {r['title'][:55]}")

    schema = pa.schema([
        ("case_id", pa.string()), ("chunk_index", pa.int64()), ("section_type", pa.string()), ("text", pa.string()),
        ("court", pa.string()), ("title", pa.string()), ("case_number", pa.string()), ("citation", pa.string()),
        ("decision_date", pa.string()), ("year", pa.int64()), ("disposition", pa.string()),
        ("judges", pa.list_(pa.string())), ("source_url", pa.string()),
    ])
    os.makedirs(CORPUS_DIR, exist_ok=True)
    total_chunks = total_cases = 0
    for slug, new_recs in sorted(by_slug.items()):
        new_table = pa.Table.from_pylist(new_recs, schema=schema)
        target = os.path.join(CORPUS_DIR, f"{slug}_pmla_chunks.parquet")
        new_ids = {r["case_id"] for r in new_recs}
        if os.path.exists(target):
            existing = pq.read_table(target, columns=COLUMNS)  # project down - the sweep file carries many more columns
            # idempotent: drop any prior run's rows for these same case_ids before re-adding (case_id, not chunk
            # rowid, is the identity - a re-run with different chunking would otherwise leave orphaned old chunks)
            keep = pc.invert(pc.is_in(existing["case_id"], value_set=pa.array(sorted(new_ids))))
            existing = existing.filter(keep)
            combined = pa.concat_tables([existing, new_table])
            action = f"merged into existing {os.path.basename(target)} ({existing.num_rows:,} kept + {new_table.num_rows:,} new = {combined.num_rows:,} rows)"
        else:
            combined = new_table
            action = f"new file {os.path.basename(target)}"
        pq.write_table(combined, target)
        n_cases = len({r["case_id"] for r in new_recs})
        total_chunks += len(new_recs); total_cases += n_cases
        print(f"  {slug:16s} +{len(new_recs):4d} chunks, {n_cases:2d} case(s) - {action}")
    print(f"\nDone: {total_chunks} new chunks across {total_cases} cases, {len(by_slug)} court file(s) touched in {CORPUS_DIR}")


if __name__ == "__main__":
    sys.exit(main())
