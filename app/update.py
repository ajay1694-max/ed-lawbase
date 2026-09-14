#!/usr/bin/env python3
r"""update.py - fetch the latest LawBase data file from the shared repository's Releases.

  python app\update.py            (or "Update LawBase.cmd")

Reads app\config.json for the repository. Downloads lawbase-data-*.zip and SHA256SUMS.txt from the
latest release, verifies the hash, and swaps data\lawbase.sqlite only after verification passes.
Public data only - the internal pack is never fetched from the internet.
"""
import hashlib, json, os, sys, tempfile, urllib.request, zipfile

APP = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(APP)
CONFIG = os.path.join(APP, "config.json")
UA = {"User-Agent": "ED-LawBase-updater", "Accept": "application/vnd.github+json"}


def get(url, dest=None):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        if dest is None:
            return r.read()
        total, done = int(r.headers.get("Content-Length", 0)), 0
        with open(dest, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  {done / 1e6:,.0f} / {total / 1e6:,.0f} MB", end="", flush=True)
        print()


def main():
    cfg = json.load(open(CONFIG))
    repo = cfg.get("repo", "")
    if not repo or "/" not in repo:
        sys.exit("app\\config.json has no repository set yet ({\"repo\": \"owner/name\"}).")
    rel = json.loads(get(f"https://api.github.com/repos/{repo}/releases/latest"))
    assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
    data_name = next((n for n in assets if n.startswith("lawbase-data-") and n.endswith(".zip")), None)
    if not data_name or "SHA256SUMS.txt" not in assets:
        sys.exit(f"release {rel.get('tag_name')} has no data zip / SHA256SUMS.txt")
    sums = dict(line.split()[::-1] for line in get(assets["SHA256SUMS.txt"]).decode().splitlines() if line.strip())
    current = os.path.join(ROOT, "data", "installed-release.txt")
    if os.path.exists(current) and open(current).read().strip() == rel["tag_name"]:
        print(f"Already up to date ({rel['tag_name']}).")
        return
    print(f"Downloading {data_name} from release {rel['tag_name']} ...")
    tmp = tempfile.mkdtemp(prefix="lawbase-")
    zpath = os.path.join(tmp, data_name)
    get(assets[data_name], zpath)
    h = hashlib.sha256(open(zpath, "rb").read()).hexdigest()
    if h != sums.get(data_name):
        sys.exit("Checksum mismatch - download discarded. Try again.")
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    zipfile.ZipFile(zpath).extract("lawbase.sqlite", tmp)
    os.replace(os.path.join(tmp, "lawbase.sqlite"), os.path.join(ROOT, "data", "lawbase.sqlite"))
    open(current, "w").write(rel["tag_name"])
    print(f"Updated to {rel['tag_name']}. Restart LawBase if it is open.")


if __name__ == "__main__":
    main()
