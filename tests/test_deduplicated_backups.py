import hashlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import tarfile
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline'))
import deduplicate_backup_archive as tool


class BackupTests(unittest.TestCase):
    def fixture(self, root):
        db = root / 'fixture.sqlite'
        c = sqlite3.connect(db)
        c.execute('CREATE TABLE evidence(value)')
        c.execute('INSERT INTO evidence VALUES (?)', ('original preserved',))
        c.commit(); c.close()
        data = db.read_bytes()
        files = ['data/lawbase.sqlite.pre-first', 'data/backups/old/lawbase.sqlite']
        manifest = {'files': [{'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'mtime_ns': 1} for name in files]}
        source = root / 'original.tar.gz'
        with tarfile.open(source, 'w:gz') as archive:
            for name, content in [(n, data) for n in files] + [('OFFVM-MANIFEST.json', json.dumps(manifest).encode())]:
                member = tarfile.TarInfo(name); member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
        return source, data, manifest

    def test_roundtrip_deduplicates_and_verifies_all_original_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source, data, manifest = self.fixture(root)
            packed = root / 'packed.zip'; tool.pack(source, packed)
            with zipfile.ZipFile(packed) as archive:
                self.assertEqual(len([n for n in archive.namelist() if n.startswith('blocks/')]), 1)
            receipt = tool.verify(packed, root / 'restored')
            self.assertTrue(receipt['verified'])
            self.assertEqual(receipt['manifest'], manifest)
            for record in manifest['files']:
                self.assertEqual((root / 'restored' / record['path']).read_bytes(), data)
            with self.assertRaises(FileExistsError): tool.verify(packed, root / 'restored')

    def test_corrupt_block_fails_without_verified_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source, _, _ = self.fixture(root)
            packed = root / 'packed.zip'; tool.pack(source, packed)
            with zipfile.ZipFile(packed) as src, zipfile.ZipFile(root / 'corrupt.zip', 'w') as dst:
                for name in src.namelist():
                    dst.writestr(name, b'corrupt' if name.startswith('blocks/') else src.read(name))
            with self.assertRaises(ValueError): tool.verify(root / 'corrupt.zip', root / 'bad')
            self.assertFalse((root / 'bad/VERIFIED-RECEIPT.json').exists())

    def test_unsafe_paths_rejected(self):
        for path in ['data/backups/../../escape', '/data/backups/x', 'data/backups/C:/x', 'data/backups/x\\y', 'data/auth.sqlite']:
            with self.assertRaises(ValueError): tool.safe_path(path)


if __name__ == '__main__': unittest.main()
