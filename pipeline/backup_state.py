"""Consistent SQLite snapshots plus submitted attachments before a deployment.

Run on the existing host: python3 pipeline/backup_state.py
Writes only to ignored data/backups/. Never prints account data or credentials.
"""
import datetime
import json
from pathlib import Path
import shutil
import sqlite3


def main():
    root = Path(__file__).resolve().parents[1]
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out = root / 'data' / 'backups' / ('research-upgrade-' + stamp)
    out.mkdir(parents=True)
    report = {'created_utc': stamp, 'databases': {}, 'uploads': 0}
    for name in ('lawbase.sqlite', 'auth.sqlite', 'research.sqlite'):
        source = root / 'data' / name
        if not source.exists():
            continue
        src = sqlite3.connect('file:' + str(source) + '?mode=ro', uri=True)
        dst = sqlite3.connect(out / name)
        try:
            src.backup(dst)
            if dst.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise RuntimeError('Snapshot validation failed: ' + name)
            report['databases'][name] = (out / name).stat().st_size
        finally:
            dst.close()
            src.close()
    uploads = root / 'data' / 'member_uploads'
    if uploads.exists():
        shutil.copytree(uploads, out / 'member_uploads')
        report['uploads'] = len(list((out / 'member_uploads').glob('*.pdf')))
    (out / 'manifest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('BACKUP_VERIFIED', out, json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
