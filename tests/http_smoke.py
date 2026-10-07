"""HTTP smoke test for a running LawBase (local mode, no login): gzip, response cache and concurrent requests.

Run: python app/server.py --no-browser   (then)   python tests/http_smoke.py [base_url]
"""
import concurrent.futures, gzip, json, sys, time, urllib.parse, urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"


def get(path, gz=True):
    req = urllib.request.Request(BASE + path, headers={"Accept-Encoding": "gzip"} if gz else {})
    t = time.perf_counter()
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
        enc, xc = r.headers.get("Content-Encoding"), r.headers.get("X-Cache")
    raw = gzip.decompress(body) if enc == "gzip" else body
    return time.perf_counter() - t, len(body), len(raw), enc, xc, raw


def main():
    ok = True
    for path in ["/", "/api/meta", "/api/briefs", "/api/brief?slug=ibc-00-overview-start-here",
                 "/api/case?id=DLHC010126002021", "/api/search?q=" + urllib.parse.quote("section 32A moratorium")]:
        t1, wire1, raw1, enc1, _, body1 = get(path)
        t2, wire2, raw2, enc2, xc2, body2 = get(path)
        _, _, _, enc3, _, body3 = get(path, gz=False)
        same = body1 == body2 == body3
        ok &= same and (enc1 == "gzip" or raw1 <= 1024) and enc3 is None
        print(f"{path[:55]:55s} first {t1*1000:6.0f} ms  repeat {t2*1000:5.0f} ms ({xc2 or 'no cache'})  "
              f"{raw1/1024:7.1f} KB -> {wire1/1024:6.1f} KB on the wire  identical={same}")
    if json.loads(body1)["total"] != 8:
        ok = False; print("unexpected search result")
    qs = ["bail", "money laundering", "attachment", "proceeds of crime", "tender of pardon", "moratorium",
          "resolution professional", "liquidator", "s.45", "arrest"] * 4
    with concurrent.futures.ThreadPoolExecutor(12) as ex:
        res = list(ex.map(lambda q: get("/api/search?q=" + urllib.parse.quote(q) + "&limit=20"), qs))
    errs = [r for r in res if b'"error"' in r[5][:40]]
    totals = {}
    for q, r in zip(qs, res):
        totals.setdefault(q, set()).add(json.loads(r[5])["total"])
    consistent = all(len(v) == 1 for v in totals.values())
    ok &= not errs and consistent
    print(f"40 concurrent searches: errors={len(errs)}, consistent totals={consistent}")
    print("SMOKE OK" if ok else "SMOKE FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
