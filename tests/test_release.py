import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_tools', ROOT / 'tools/release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def metadata(self, root):
        (root / 'src/netpulse').mkdir(parents=True)
        (root / 'releases').mkdir()
        (root / 'pyproject.toml').write_text('version = "1.2.0"\n')
        (root / 'setup.py').write_text('    version="1.2.0",\n')
        (root / 'src/netpulse/__init__.py').write_text('__version__ = "1.2.0"\n')
        (root / 'releases/v1.2.0.md').write_text('Release notes\n')

    def test_tag_must_match_all_source_versions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.metadata(root)
            self.assertEqual(release.release_version(root, 'v1.2.0'), '1.2.0')
            with self.assertRaises(ValueError):
                release.release_version(root, 'v1.3.0')
            (root / 'setup.py').write_text('    version="1.1.0",\n')
            with self.assertRaises(ValueError):
                release.release_version(root)

    def test_release_requires_nonempty_curated_notes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.metadata(root)
            (root / 'releases/v1.2.0.md').write_text('  \n')
            with self.assertRaises(ValueError):
                release.release_version(root)

    def test_checksum_manifest_covers_artifacts_and_excludes_itself(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'package.whl').write_bytes(b'package')
            (root / 'SHA256SUMS').write_text('outdated')
            release.checksums(root)
            self.assertEqual((root / 'SHA256SUMS').read_text(),
                             hashlib.sha256(b'package').hexdigest() + '  package.whl\n')

    def test_repository_release_metadata_is_consistent(self):
        self.assertRegex(release.release_version(), r'^\d+\.\d+\.\d+$')
