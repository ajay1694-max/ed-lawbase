#!/usr/bin/env python3
r"""package.py - assemble the portable LawBase folder that officers unzip and double-click.

  python pipeline\package.py --out dist\LawBase
  python pipeline\package.py --out dist\LawBase --python-embed python-3.12.10-embed-amd64.zip
  python pipeline\package.py --out dist\LawBase --internal internal\lawbase-internal.sqlite

Produces:
  dist\LawBase\                     Start LawBase.cmd, app\, data\, (python\ if --python-embed)
  dist\LawBase-app-<ver>.zip        the program, WITHOUT data - for the public release
  dist\lawbase-data-<snapshot>.zip  data\lawbase.sqlite zipped - release asset, fetched by app\update.py
  dist\SHA256SUMS.txt               hashes of both zips
The internal pack is copied ONLY with --internal, and never goes into either zip.

With --python-embed (the official "Windows embeddable package" zip from python.org) the folder carries
its own Python, so officers need nothing installed. python-docx is then installed into it from PyPI
(needs internet at package time only).
"""
import argparse, hashlib, os, shutil, sqlite3, subprocess, sys, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = "0.1.0"

LAUNCHER = r"""@echo off
title ED LawBase
cd /d "%~dp0"
if exist "python\python.exe" (
  "python\python.exe" app\server.py
) else (
  python app\server.py
)
if errorlevel 1 pause
"""


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def zip_dir(src, dest, skip=()):
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for base, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if os.path.relpath(os.path.join(base, d), src).split(os.sep)[0] not in skip and d != "__pycache__"]
            for f in files:
                full = os.path.join(base, f)
                z.write(full, os.path.join(os.path.basename(src), os.path.relpath(full, src)))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default=os.path.join(ROOT, "dist", "LawBase"))
    p.add_argument("--data", default=os.path.join(ROOT, "data", "lawbase.sqlite"))
    p.add_argument("--internal", help="internal pack sqlite to copy into THIS folder only (not zipped)")
    p.add_argument("--python-embed", help="python-3.12.x-embed-amd64.zip from python.org")
    a = p.parse_args()

    out = os.path.abspath(a.out)
    dist = os.path.dirname(out)
    if os.path.exists(out):
        shutil.rmtree(out)
    shutil.copytree(os.path.join(ROOT, "app"), os.path.join(out, "app"),
                    ignore=shutil.ignore_patterns("__pycache__", "Start LawBase.cmd"))
    open(os.path.join(out, "Start LawBase.cmd"), "w", newline="\r\n").write(LAUNCHER)
    os.makedirs(os.path.join(out, "data"), exist_ok=True)
    shutil.copy2(a.data, os.path.join(out, "data", "lawbase.sqlite"))
    snapshot = dict(sqlite3.connect(a.data).execute("SELECT key, value FROM meta").fetchall()).get("snapshot", "unknown")

    if a.python_embed:
        pydir = os.path.join(out, "python")
        zipfile.ZipFile(a.python_embed).extractall(pydir)
        pth = next(f for f in os.listdir(pydir) if f.endswith("._pth"))
        lines = open(os.path.join(pydir, pth)).read().splitlines()
        lines = [("import site" if ln.strip() == "#import site" else ln) for ln in lines] + ["Lib\\site-packages", "..\\app"]
        open(os.path.join(pydir, pth), "w").write("\n".join(lines) + "\n")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "--target", os.path.join(pydir, "Lib", "site-packages"),
                               "--platform", "win_amd64", "--python-version", "3.12", "--only-binary=:all:", "python-docx"])

    app_zip = os.path.join(dist, f"LawBase-app-{VERSION}.zip")
    data_zip = os.path.join(dist, f"lawbase-data-{snapshot}.zip")
    zip_dir(out, app_zip, skip=("data", "internal"))
    with zipfile.ZipFile(data_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.write(a.data, "lawbase.sqlite")
    with open(os.path.join(dist, "SHA256SUMS.txt"), "w") as f:
        for path in (app_zip, data_zip):
            f.write(f"{sha256(path)}  {os.path.basename(path)}\n")

    if a.internal:
        os.makedirs(os.path.join(out, "internal"), exist_ok=True)
        shutil.copy2(a.internal, os.path.join(out, "internal"))
        print("NOTE: internal pack copied into the local folder only - do not upload this folder.")
    for path in (app_zip, data_zip):
        print(f"{os.path.basename(path):40s} {os.path.getsize(path) / 1e6:8,.1f} MB")
    print(f"folder ready: {out}")


if __name__ == "__main__":
    main()
