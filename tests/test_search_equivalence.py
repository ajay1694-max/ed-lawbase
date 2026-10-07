"""The two-phase search (compact chunk_case map, snippets built only for returned cases) must return exactly
what the original single-query search returned: same cases, same order, same hit counts, same snippets.

Run: python tests/test_search_equivalence.py   (needs data/lawbase.sqlite and git history for the old version)
"""
import importlib.util, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))
import server as new  # noqa: E402

OLD_REV = "7a51c76"  # last commit before the two-phase search
QUERIES = [{"q": "bail"}, {"q": "money laundering"}, {"q": "Pankaj Bansal"}, {"q": "section 32A moratorium"},
           {"q": '"proceeds of crime" attachment'}, {"q": "resolution plan", "issue": "ibc.s32a_immunity"},
           {"q": "tender of pardon", "within": "chunk"}, {"q": "attachment", "court": "delhi"},
           {"q": "provisional attach*"}, {"q": "2022 INSC 757"}, {"q": "s.45 twin conditions", "limit": "100"},
           {"court": "delhi", "year_from": "2024"}, {"q": "money laundering bail", "court": "bombay", "year_from": "2020"}]


def load_old():
    src = subprocess.run(["git", "-C", ROOT, "show", f"{OLD_REV}:app/server.py"], capture_output=True, text=True,
                         encoding="utf-8", check=True).stdout
    path = os.path.join(tempfile.mkdtemp(), "server_old.py")
    open(path, "w", encoding="utf-8").write(src.replace('os.path.dirname(os.path.abspath(__file__))',
                                                        repr(os.path.join(ROOT, "app"))))
    spec = importlib.util.spec_from_file_location("server_old", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def key(res):
    return [(r["case_id"], r["hits"], tuple(r["snips"])) for r in res["results"]], res["total"]


def main():
    old = load_old()
    bad = 0
    for p in QUERIES:
        co, cn = old.connect(), new.connect()
        try:
            a, b = key(old.api_search(co, dict(p))), key(new.api_search(cn, dict(p)))
        finally:
            co.close(); new.release(cn)
        if a == b:
            print(f"same  {p}  ({b[1]} hits, {len(b[0])} shown)")
        else:
            bad += 1
            print(f"DIFF  {p}: totals {a[1]} vs {b[1]}")
            for i, (x, y) in enumerate(zip(a[0], b[0])):
                if x != y:
                    print("   first difference at", i, "\n   old:", x, "\n   new:", y)
                    break
    print("ALL SAME" if not bad else f"{bad} queries differ")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
