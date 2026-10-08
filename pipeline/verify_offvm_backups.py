"""Stream-extract an off-host recovery archive; verify hashes and SQLite copies.

Writes to a new local destination. Never restores the running application.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sqlite3
import tarfile


def verify(archive_path, destination):
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    observed = {}
    manifest = None
    with tarfile.open(archive_path, 'r|gz') as archive:
        for item in archive:
            parts = PurePosixPath(item.name).parts
            if not item.isfile() or item.name.startswith('/') or '..' in parts or '\\' in item.name:
                raise ValueError('Unsafe archive member')
            if item.name == 'OFFVM-MANIFEST.json':
                manifest = json.loads(archive.extractfile(item).read())
                continue
            if not (item.name.startswith('data/lawbase.sqlite.pre-') or item.name.startswith('data/backups/')):
                raise ValueError('Unexpected archive path')
            target = destination.joinpath(*parts)
            if not target.resolve().is_relative_to(destination):
                raise ValueError('Path outside destination')
            target.parent.mkdir(parents=True, exist_ok=True)
            digest, length = hashlib.sha256(), 0
            with target.open('xb') as out, archive.extractfile(item) as source:
                while chunk := source.read(1024 * 1024):
                    out.write(chunk)
                    digest.update(chunk)
                    length += len(chunk)
            observed[item.name] = {'sha256': digest.hexdigest(), 'bytes': length}
            print('EXTRACTED', item.name, length, flush=True)
    if not manifest or len(manifest['files']) != len(observed):
        raise ValueError('Manifest/member mismatch')
    for record in manifest['files']:
        result = observed.get(record['path'])
        if result != {'sha256': record['sha256'], 'bytes': record['bytes']}:
            raise ValueError('Checksum mismatch: ' + record['path'])
        path = destination / record['path']
        if '.sqlite' in path.name:
            con = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
            try:
                if con.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise ValueError('SQLite recovery copy invalid')
            finally:
                con.close()
            print('RESTORE_COPY_VERIFIED', record['path'], flush=True)
    (destination / 'OFFVM-MANIFEST.json').write_text(json.dumps(manifest, indent=2))
    receipt = {'verified': True, 'files': len(observed), 'bytes': sum(v['bytes'] for v in observed.values()),
               'manifest': manifest, 'archive': str(archive_path.resolve()), 'destination': str(destination)}
    (destination / 'VERIFIED-RECEIPT.json').write_text(json.dumps(receipt, indent=2))
    print('OFFVM_BACKUPS_VERIFIED', len(observed), receipt['bytes'], flush=True)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    verify(args.archive, args.destination)
