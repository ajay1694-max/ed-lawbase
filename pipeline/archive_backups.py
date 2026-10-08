"""Archive immutable recovery copies for verified off-host storage.

Never includes live databases, secret files or code. Does not delete anything.
SHA256 values are calculated while streaming each file into the archive.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile
import time


class HashReader:
    def __init__(self, file):
        self.file = file
        self.digest = hashlib.sha256()

    def read(self, size=-1):
        data = self.file.read(size)
        self.digest.update(data)
        return data


def create(root, output):
    root = root.resolve()
    paths = sorted((root / 'data').glob('lawbase.sqlite.pre-*'))
    paths += sorted(p for p in (root / 'data/backups').rglob('*') if p.is_file())
    if not paths:
        raise ValueError('No recovery copies found')
    manifest = {'created_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'files': []}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as raw:
        output.chmod(0o600)
        with tarfile.open(fileobj=raw, mode='w:gz', compresslevel=1) as archive:
            for path in paths:
                if path.is_symlink() or not path.resolve().is_relative_to(root / 'data'):
                    raise ValueError('Unsafe recovery path')
                before = path.stat()
                name = path.relative_to(root).as_posix()
                info = archive.gettarinfo(str(path), arcname=name)
                info.mode = 0o600
                with path.open('rb') as file:
                    reader = HashReader(file)
                    archive.addfile(info, reader)
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError('Recovery file changed while archiving: ' + name)
                manifest['files'].append({'path': name, 'bytes': before.st_size,
                                          'mtime_ns': before.st_mtime_ns,
                                          'sha256': reader.digest.hexdigest()})
                print('ARCHIVED', name, before.st_size, flush=True)
            payload = json.dumps(manifest, indent=2).encode()
            info = tarfile.TarInfo('OFFVM-MANIFEST.json')
            info.size = len(payload)
            info.mode = 0o600
            archive.addfile(info, io.BytesIO(payload))
    output.with_suffix(output.suffix + '.manifest.json').write_text(json.dumps(manifest, indent=2))
    print('ARCHIVE_READY', output, output.stat().st_size, flush=True)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    create(args.root, args.output)
