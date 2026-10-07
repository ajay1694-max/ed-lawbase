#!/usr/bin/env python3
r"""bench_search.py - time a fixed set of LawBase searches directly against the database (no HTTP, no login).

    python pipeline/bench_search.py                 # uses data/lawbase.sqlite
    python pipeline/bench_search.py --repeat 2      # second pass shows warm-cache timings

Reports, per query: seconds, results, and MB read from disk by this process (where the OS reports it).
On Linux, drop the page cache first for a cold run:  sync; echo 3 | sudo tee /proc/sys/vm/drop_caches
"""
import argparse, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "app"))
import server  # noqa: E402

QUERIES = [
    ({"q": "bail"}, "one common word"),
    ({"q": "money laundering"}, "two very common words"),
    ({"q": "Pankaj Bansal"}, "party name"),
    ({"q": "section 32A moratorium"}, "three words, case level"),
    ({"q": '"proceeds of crime" attachment'}, "phrase plus word"),
    ({"q": "resolution plan", "issue": "ibc.s32a_immunity"}, "issue filter"),
    ({"q": "tender of pardon", "within": "chunk"}, "same-passage match"),
]


def read_bytes():
    try:
        with open(f"/proc/{os.getpid()}/io") as f:
            for line in f:
                if line.startswith("read_bytes:"):
                    return int(line.split()[1])
    except OSError:
        pass
    try:
        import psutil
        return psutil.Process().io_counters().read_bytes
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=1)
    a = ap.parse_args()
    for rnd in range(a.repeat):
        print(f"--- pass {rnd + 1} ---")
        total = 0.0
        for params, label in QUERIES:
            server._CACHE.clear() if hasattr(server, "_CACHE") else None
            b0, t0 = read_bytes(), time.perf_counter()
            c = server.connect()
            try:
                res = server.api_search(c, dict(params))
            finally:
                server.release(c) if hasattr(server, "release") else c.close()
            dt = time.perf_counter() - t0
            b1 = read_bytes()
            total += dt
            mb = f"{(b1 - b0) / 1e6:7.1f} MB" if b0 is not None and b1 is not None else "      ?"
            first = res["results"][0]["title"][:45] if res["results"] else "-"
            print(f"{dt:7.2f}s {mb} {res['total']:6d} hits  {label:26s} {params.get('q')!r:34s} -> {first}")
        print(f"total {total:.2f}s")


if __name__ == "__main__":
    main()
