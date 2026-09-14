#!/usr/bin/env python3
"""guard.py - keeps internal material out of the public tier.

  python pipeline/guard.py            scan this repo; exit 1 if anything internal is found
  (build.py also calls check_tier() on every record it loads)

Two checks:
  1. every enrichment file declares tier = "public" | "internal"; a public repo may hold only public
  2. public files must not carry ED-internal markers (ECIR numbers, PAO/OC numbers, "internal pack")
"""
import os, re, sys, tomllib

INTERNAL_MARKERS = re.compile(
    r"ECIR/[A-Z]{2,6}/\d+/\d{4}|\bPAO[- ]?(No\.?)?\s*\d+/\d{4}|\bO\.?C\.?\s*No\.?\s*\d+/\d{4}"
    r"|internal pack|case-library|RESTRICTED|CONFIDENTIAL", re.I)


def read_md(path):
    text = open(path, encoding="utf-8").read()
    if text.startswith("+++"):
        _, front, body = text.split("+++", 2)
        return tomllib.loads(front), body
    return {}, text


def check_tier(meta, building, path):
    tier = str(meta.get("tier", "")).lower()
    if tier not in ("public", "internal"):
        raise SystemExit(f"{path}: tier must be declared as \"public\" or \"internal\"")
    if building == "public" and tier != "public":
        raise SystemExit(f"REFUSED: {path} is tier={tier} - internal material never enters the public build")
    return tier


def scan(root):
    problems = []
    for base, _, files in os.walk(os.path.join(root, "enrich")):
        for f in files:
            if not f.endswith(".md"):
                continue
            path = os.path.join(base, f)
            meta, body = read_md(path)
            tier = str(meta.get("tier", "")).lower()
            if tier != "public":
                problems.append(f"{path}: tier={tier or 'missing'} (public repo holds public only)")
            for m in INTERNAL_MARKERS.finditer(body):
                problems.append(f"{path}: internal marker '{m.group(0)}'")
    return problems


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    found = scan(root)
    print("\n".join(found) if found else "guard: clean - nothing internal in the public tier")
    sys.exit(1 if found else 0)
