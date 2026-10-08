"""Remove exported recovery copies only after off-host restore verification.

Requires the exact manifest digest from a verified off-host receipt. Keeps the
specified complete state snapshot and never touches live application databases.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


def prune(root, manifest_path, verified_digest, keep, apply=False):
    root = root.resolve()
    manifest = json.loads(manifest_path.read_text())
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    if digest != verified_digest:
        raise ValueError('Off-host verified manifest digest mismatch')
    keep_path = (root / 'data/backups' / keep).resolve()
    backup_root = (root / 'data/backups').resolve()
    if keep_path.parent != backup_root or not (keep_path / 'manifest.json').is_file():
        raise ValueError('Retained complete state snapshot missing')
    for name in ['lawbase.sqlite', 'auth.sqlite', 'research.sqlite']:
        if not (keep_path / name).is_file():
            raise ValueError('Retained database missing')
    candidates = []
    for item in manifest['files']:
        name = item['path']
        parts = PurePosixPath(name).parts
        if name.startswith('/') or '..' in parts or '\\' in name:
            raise ValueError('Unsafe manifest path')
        path = root.joinpath(*parts)
        if path.is_symlink() or not path.resolve().is_relative_to(root / 'data'):
            raise ValueError('Unsafe recovery path')
        if path.resolve().is_relative_to(keep_path):
            continue
        if not (name.startswith('data/lawbase.sqlite.pre-') or name.startswith('data/backups/')):
            raise ValueError('Live or unexpected file in manifest')
        stat = path.stat()
        if (stat.st_size, stat.st_mtime_ns) != (item['bytes'], item['mtime_ns']):
            raise ValueError('Recovery copy changed since export')
        candidates.append(path)
    total = sum(p.stat().st_size for p in candidates)
    print('PRUNE_PLAN', len(candidates), total, 'KEEP', keep, flush=True)
    if apply:
        for path in candidates:
            path.unlink()
        # Remove empty exported state directories, with no recursive deletion.
        directories = sorted((p for p in backup_root.rglob('*') if p.is_dir()),
                             key=lambda p: len(p.parts), reverse=True)
        for path in directories:
            if not path.resolve().is_relative_to(keep_path) and not any(path.iterdir()):
                path.rmdir()
        print('EXPORTED_COPIES_REMOVED', len(candidates), total, flush=True)
    return {'files': len(candidates), 'bytes': total, 'keep': keep, 'applied': apply}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--verified-manifest-sha', required=True)
    parser.add_argument('--keep', required=True)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    prune(args.root, args.manifest, args.verified_manifest_sha, args.keep, args.apply)
