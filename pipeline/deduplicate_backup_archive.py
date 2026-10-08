"""Repackage immutable recovery archives without losing any historical bytes.

Each 64 KiB block is stored once. Restore validates block hashes, every original
file hash/size and SQLite integrity before issuing the standard off-host receipt.
No live files are read or removed. Python standard library only.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import tarfile
import zipfile

BLOCK = 65536


def safe_path(name):
    parts = PurePosixPath(name).parts
    if name.startswith('/') or '..' in parts or '\\' in name or ':' in name:
        raise ValueError('Unsafe recovery path')
    if not (name.startswith('data/lawbase.sqlite.pre-') or name.startswith('data/backups/')):
        raise ValueError('Unexpected recovery path')
    return parts


def pack(source, destination):
    seen, files, observed, manifest = set(), [], {}, None
    with tarfile.open(source, 'r|gz') as archive, zipfile.ZipFile(destination, 'x', zipfile.ZIP_DEFLATED, compresslevel=1) as out:
        for member in archive:
            if not member.isfile():
                raise ValueError('Nonregular archive member')
            if member.name == 'OFFVM-MANIFEST.json':
                if manifest is not None or member.size > 1024 * 1024:
                    raise ValueError('Invalid manifest')
                manifest = json.loads(archive.extractfile(member).read())
                continue
            safe_path(member.name)
            if member.name in observed:
                raise ValueError('Duplicate path')
            digest, size, blocks = hashlib.sha256(), 0, []
            with archive.extractfile(member) as incoming:
                while block := incoming.read(BLOCK):
                    sha = hashlib.sha256(block).hexdigest()
                    if sha not in seen:
                        out.writestr('blocks/' + sha, block)
                        seen.add(sha)
                    blocks.append(sha)
                    digest.update(block)
                    size += len(block)
            observed[member.name] = {'bytes': size, 'sha256': digest.hexdigest()}
            files.append({'path': member.name, 'blocks': blocks})
            print('PACKED', member.name, size, flush=True)
        if not manifest or len(manifest['files']) != len(observed):
            raise ValueError('Manifest/member mismatch')
        for item in manifest['files']:
            if observed.get(item['path']) != {'bytes': item['bytes'], 'sha256': item['sha256']}:
                raise ValueError('Original checksum mismatch')
        out.writestr('BACKUP-INDEX.json', json.dumps({'version': 1, 'block_bytes': BLOCK, 'manifest': manifest, 'files': files}))
    print('DEDUPLICATED_ARCHIVE_READY', destination.stat().st_size, 'UNIQUE_BLOCKS', len(seen), flush=True)


def verify(source, destination):
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(source) as archive:
        index_info = archive.getinfo('BACKUP-INDEX.json')
        if index_info.file_size > 32 * 1024 * 1024:
            raise ValueError('Oversized index')
        index = json.loads(archive.read(index_info))
        if index.get('version') != 1 or index.get('block_bytes') != BLOCK:
            raise ValueError('Unknown format')
        manifest = index['manifest']
        records = {r['path']: r for r in manifest['files']}
        mappings = {r['path']: r for r in index['files']}
        if len(records) != len(manifest['files']) or len(mappings) != len(index['files']) or records.keys() != mappings.keys():
            raise ValueError('Manifest/index mismatch')
        blocks = {b for r in index['files'] for b in r['blocks']}
        if any(not isinstance(b, str) or not re.fullmatch('[0-9a-f]{64}', b) for b in blocks):
            raise ValueError('Invalid block name')
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != {'BACKUP-INDEX.json'} | {'blocks/' + b for b in blocks}:
            raise ValueError('Unexpected archive member')
        for name, record in records.items():
            parts = safe_path(name)
            target = destination.joinpath(*parts)
            if not target.resolve().is_relative_to(destination):
                raise ValueError('Path outside destination')
            target.parent.mkdir(parents=True, exist_ok=True)
            digest, size = hashlib.sha256(), 0
            with target.open('xb') as out:
                for sha in mappings[name]['blocks']:
                    info = archive.getinfo('blocks/' + sha)
                    if not 0 < info.file_size <= BLOCK:
                        raise ValueError('Oversized block')
                    block = archive.read(info)
                    if hashlib.sha256(block).hexdigest() != sha:
                        raise ValueError('Block checksum mismatch')
                    out.write(block)
                    digest.update(block)
                    size += len(block)
            if size != record['bytes'] or digest.hexdigest() != record['sha256']:
                raise ValueError('Restored file checksum mismatch')
            if '.sqlite' in target.name:
                c = sqlite3.connect(target.as_uri() + '?mode=ro', uri=True)
                try:
                    if c.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                        raise ValueError('SQLite recovery copy invalid')
                finally:
                    c.close()
            print('RESTORE_COPY_VERIFIED', name, size, flush=True)
    (destination / 'OFFVM-MANIFEST.json').write_text(json.dumps(manifest, indent=2))
    receipt = {'verified': True, 'files': len(records), 'bytes': sum(r['bytes'] for r in records.values()),
               'manifest': manifest, 'archive': str(source.resolve()), 'destination': str(destination)}
    (destination / 'VERIFIED-RECEIPT.json').write_text(json.dumps(receipt, indent=2))
    print('OFFVM_BACKUPS_VERIFIED', receipt['files'], receipt['bytes'], flush=True)
    return receipt


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['pack', 'verify'])
    p.add_argument('source', type=Path)
    p.add_argument('destination', type=Path)
    args = p.parse_args()
    (pack if args.mode == 'pack' else verify)(args.source, args.destination)
