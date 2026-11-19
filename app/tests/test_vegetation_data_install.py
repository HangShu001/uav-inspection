"""Offline installer checks using tiny temporary fixtures only."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "install_vegetation_data.py"
spec = importlib.util.spec_from_file_location("install_vegetation_data", SCRIPT)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class VegetationInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.bundle = self.base / "bundle"
        self.root = self.base / "runtime"
        self.files = {"measurement_data/task/scene.json": b'{"points":42}',
                      "models/test/model.json": b'{"model":"fixture"}'}
        self.entries = []
        for name, content in self.files.items():
            source = self.bundle / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(content)
            self.entries.append({"path": name, "bytes": len(content),
                                 "sha256": hashlib.sha256(content).hexdigest()})
        self.write_manifest()

    def write_manifest(self):
        (self.bundle / "manifest.json").write_text(json.dumps({
            "version": 1, "files": self.entries,
            "total_bytes": sum(entry["bytes"] for entry in self.entries),
        }), encoding="utf-8")

    def test_install_is_offline_and_idempotent(self):
        self.assertEqual(installer.install(self.root, self.bundle),
                         {"installed": 2, "skipped": 0, "files": 2})
        for name, content in self.files.items():
            self.assertEqual((self.root / name).read_bytes(), content)
        self.assertEqual(installer.install(self.root, self.bundle),
                         {"installed": 0, "skipped": 2, "files": 2})

    def test_corrupt_bundle_does_not_write_destination(self):
        (self.bundle / self.entries[-1]["path"]).write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            installer.install(self.root, self.bundle)
        self.assertFalse(self.root.exists())

    def test_conflict_is_preflighted_and_requires_explicit_overwrite(self):
        conflict = self.root / self.entries[-1]["path"]
        conflict.parent.mkdir(parents=True)
        conflict.write_bytes(b"existing upload")
        with self.assertRaisesRegex(ValueError, "--overwrite"):
            installer.install(self.root, self.bundle)
        self.assertFalse((self.root / self.entries[0]["path"]).exists())
        self.assertEqual(conflict.read_bytes(), b"existing upload")
        installer.install(self.root, self.bundle, overwrite=True)
        self.assertEqual(conflict.read_bytes(), self.files[self.entries[-1]["path"]])

    def test_manifest_path_cannot_escape_bundle_or_runtime(self):
        for name in ("../outside", "/models/file", "models/../outside", "models\\outside",
                     "models/C:file", "models//file", "models/file.", "other/file"):
            with self.subTest(path=name), self.assertRaises(ValueError):
                installer.safe_path(self.root, name)

    def test_duplicate_paths_and_wrong_total_are_rejected(self):
        self.entries.append(dict(self.entries[0]))
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            installer.verify_bundle(self.bundle)
        self.entries.pop()
        self.write_manifest()
        manifest = json.loads((self.bundle / "manifest.json").read_text())
        manifest["total_bytes"] += 1
        (self.bundle / "manifest.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "total"):
            installer.verify_bundle(self.bundle)

    def test_linked_destination_is_rejected(self):
        outside = self.base / "outside"
        outside.mkdir()
        self.root.mkdir()
        try:
            (self.root / "models").symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("Creating symlinks requires OS support/permission")
        with self.assertRaisesRegex(ValueError, "linked"):
            installer.install(self.root, self.bundle, overwrite=True)
        self.assertEqual(list(outside.iterdir()), [])

    def test_file_created_after_preflight_is_never_overwritten(self):
        original_link = os.link

        def concurrent_upload(source, target):
            Path(target).write_bytes(b"concurrent upload")
            return original_link(source, target)

        with patch.object(installer.os, "link", side_effect=concurrent_upload):
            with self.assertRaises(FileExistsError):
                installer.install(self.root, self.bundle)
        self.assertEqual((self.root / self.entries[0]["path"]).read_bytes(), b"concurrent upload")
        self.assertFalse(list(self.root.rglob(".vegetation-*.tmp")))

    def test_data_root_follows_server_configuration(self):
        app = self.base / "app"
        app.mkdir()
        with patch.object(installer, "APP_ROOT", app), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(installer.data_root(), app)
            (app / "deployment-layout.json").write_text('{"data_directory":"../02-data"}')
            self.assertEqual(installer.data_root(), self.base / "02-data")
            with patch.dict(os.environ, {"UAV_DATA_DIR": str(self.base / "environment")}):
                self.assertEqual(installer.data_root(), self.base / "environment")
                self.assertEqual(installer.data_root(str(self.base / "explicit")), self.base / "explicit")


if __name__ == "__main__":
    unittest.main()
