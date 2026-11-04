"""Source-only TAR inspection tests. No Altera bytes and no license acceptance."""
import importlib.util
import io
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest
from unittest import mock

MODPATH = Path(__file__).resolve().parents[1] / "scripts/fpga/quartus25_complete_tar_probe.py"
SPEC = importlib.util.spec_from_file_location("quartus25_complete_tar_probe", MODPATH)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class TarAdmission(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)
        self.tar = self.root / m.TAR_NAME
        self.qdz = self.root / m.QDZ_NAME

    def fixtures(self, member="setup.sh", member_type=tarfile.REGTYPE, contents=b"#!/bin/sh\n"):
        with tarfile.open(self.tar, "w") as out:
            meta = tarfile.TarInfo(member)
            meta.size = len(contents) if member_type == tarfile.REGTYPE else 0
            meta.type = member_type
            out.addfile(meta, io.BytesIO(contents) if member_type == tarfile.REGTYPE else None)
        with self.qdz.open("wb") as out:
            out.truncate(m.QDZ_MIN_BYTES)

    def digest_ok(self, path):
        return (m.TAR_SHA1 if path.name == m.TAR_NAME else m.QDZ_SHA1, "b"*64)

    def run_observe(self, **kwargs):
        return m.observe(self.root, hash_fn=self.digest_ok, min_tar_size=0, **kwargs)

    def test_valid_minimal_tar_contract(self):
        self.fixtures()
        result, rc = self.run_observe()
        self.assertEqual(rc, 0)
        self.assertEqual(result["stage"], "TAR_AND_QDZ_VERIFIED_EULA_PENDING")
        self.assertFalse(result["archive_extracted"])
        self.assertFalse(result["installer_executed"])
        self.assertEqual(result["quartus_compile"], "NOT_RUN")
        self.assertEqual(result["tar_metadata"]["member_count"], 1)

    def test_missing_tar(self):
        result, rc = self.run_observe()
        self.assertEqual(rc, 3)
        self.assertEqual(result["expected_file"], m.TAR_NAME)

    def test_missing_qdz(self):
        self.fixtures()
        self.qdz.unlink()
        result, rc = self.run_observe()
        self.assertEqual(rc, 3)
        self.assertEqual(result["expected_file"], m.QDZ_NAME)

    def test_wrong_hash(self):
        self.fixtures()
        result, rc = m.observe(self.root, hash_fn=lambda p: ("0"*40, "1"*64), min_tar_size=0)
        self.assertEqual(rc, 3)
        self.assertEqual(result["stage"], "ARCHIVE_REJECTED")

    def test_symlink_rejected(self):
        self.fixtures()
        self.qdz.unlink()
        self.qdz.symlink_to(self.tar)
        result, rc = self.run_observe()
        self.assertEqual(rc, 3)
        self.assertEqual(result["stage"], "ARCHIVE_REJECTED")

    def test_no_setup_script(self):
        self.fixtures(member="irrelevant-file.txt")
        result, rc = self.run_observe()
        self.assertEqual(rc, 3)
        self.assertEqual(result["stage"], "TAR_METADATA_REJECTED")

    def test_path_traversal_not_admitted(self):
        self.fixtures(member="../setup.sh")
        result, rc = self.run_observe()
        self.assertEqual(rc, 3)
        self.assertEqual(result["manifest"]["unsafe_member_count"], 1)

    def test_symlink_tar_member_not_admitted(self):
        self.fixtures(member="setup.sh", member_type=tarfile.SYMTYPE)
        result, rc = self.run_observe()
        self.assertEqual(rc, 3)
        self.assertEqual(result["stage"], "TAR_METADATA_REJECTED")

    def test_insufficient_disk(self):
        self.fixtures()
        result, rc = self.run_observe(disk_fn=lambda _: mock.Mock(free=42))
        self.assertEqual(rc, 3)
        self.assertEqual(result["stage"], "CAPACITY_BLOCKED")


if __name__ == "__main__":
    unittest.main()
