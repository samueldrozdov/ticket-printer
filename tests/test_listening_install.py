import hashlib
import io
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from install_listening_models import checksum, install_bundle


class ModelInstallerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.archive = self.root / 'source.tar.bz2'

    def bundle(self, values):
        with tarfile.open(self.archive, 'w:bz2') as archive:
            for name, value in values.items():
                info = tarfile.TarInfo(name)
                info.size = len(value)
                archive.addfile(info, io.BytesIO(value))

    def download(self, relative, destination, expected):
        shutil.copyfile(self.archive, destination)

    def test_only_verified_required_assets_are_installed_and_reused_offline(self):
        files = {'model/weights.onnx': b'weights'}
        self.bundle({**files, '../../outside.txt': b'unwanted'})
        expected = {name: hashlib.sha256(value).hexdigest() for name,value in files.items()}
        with patch('install_listening_models.download', side_effect=self.download) as download:
            install_bundle(self.root, 'bundle.tar.bz2', 'archive-hash', expected)
            install_bundle(self.root, 'bundle.tar.bz2', 'archive-hash', expected)
        self.assertEqual((self.root / 'model/weights.onnx').read_bytes(), b'weights')
        self.assertEqual(download.call_count, 1)
        self.assertFalse((self.root / 'outside.txt').exists())

    def test_bad_asset_does_not_replace_any_existing_weight(self):
        (self.root / 'first').write_bytes(b'old')
        self.bundle({'first': b'new', 'second': b'bad'})
        with patch('install_listening_models.download', side_effect=self.download):
            with self.assertRaisesRegex(RuntimeError, 'checksum'):
                install_bundle(self.root, 'bundle.tar.bz2', 'archive-hash', {
                    'first': hashlib.sha256(b'new').hexdigest(),
                    'second': hashlib.sha256(b'expected').hexdigest(),
                })
        self.assertEqual((self.root / 'first').read_bytes(), b'old')
        self.assertFalse((self.root / 'second').exists())

    def test_symlink_cannot_be_installed_as_model_weights(self):
        with tarfile.open(self.archive, 'w:bz2') as archive:
            member = tarfile.TarInfo('model.onnx')
            member.type = tarfile.SYMTYPE
            member.linkname = '/etc/passwd'
            archive.addfile(member)
        with patch('install_listening_models.download', side_effect=self.download):
            with self.assertRaisesRegex(RuntimeError, 'Unexpected'):
                install_bundle(self.root, 'bundle.tar.bz2', 'archive-hash', {'model.onnx':'missing'})
        self.assertIsNone(checksum(self.root / 'model.onnx'))


if __name__ == '__main__':
    unittest.main()
