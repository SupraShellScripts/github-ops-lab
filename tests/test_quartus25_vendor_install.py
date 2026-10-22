import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/fpga/quartus25_vendor_install.py"
SPEC = importlib.util.spec_from_file_location("quartus_vendor_admission", SCRIPT)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class ArchiveGate(unittest.TestCase):
    def setUp(self):
        self.space = tempfile.TemporaryDirectory()
        self.addCleanup(self.space.cleanup)
        self.root = Path(self.space.name)
        self.source = self.root / "in"
        self.source.mkdir()
        self.dest = self.root / "out"

    def fake_files(self):
        for name, sha1, min_size in m.FILES:
            with (self.source / name).open("wb") as f:
                f.truncate(min_size + 1)

    @staticmethod
    def matching_hashes(path):
        for name, expected, _ in m.FILES:
            if path.name == name:
                return expected, "a" * 64
        raise AssertionError("unexpected input")

    def test_missing_first_file(self):
        result, rc = m.observe(self.source, self.dest)
        self.assertEqual(rc, 3)
        self.assertEqual(result["stage"], "ARCHIVE_MISSING")

    def test_missing_second_file(self):
        name, _, min_size = m.FILES[0]
        with (self.source / name).open("wb") as f:
            f.truncate(min_size + 1)
        result, rc = m.observe(self.source, self.dest, self.matching_hashes)
        self.assertEqual(rc, 3)
        self.assertEqual(result["stage"], "ARCHIVE_MISSING")

    def test_hash_mismatch_rejected(self):
        self.fake_files()
        result, rc = m.observe(self.source, self.dest, lambda path: ("0" * 40, "1" * 64))
        self.assertEqual(rc, 3)
        self.assertEqual(result["stage"], "ARCHIVE_REJECTED")
        self.assertIn("SHA1", result["reason"])

    def test_regular_archives_produce_digest_receipt(self):
        self.fake_files()
        result, rc = m.observe(self.source, self.dest, self.matching_hashes)
        self.assertEqual(rc, 0)
        self.assertEqual(result["stage"], "ARCHIVES_VERIFIED_EULA_PENDING")
        self.assertEqual(len(result["archives"]), 2)
        self.assertFalse(result["compiler_executed"])
        self.assertFalse(result["eula_accepted_by_tool"])

    def test_symlink_archive_rejected(self):
        self.fake_files()
        (self.source / m.FILES[1][0]).unlink()
        (self.source / m.FILES[1][0]).symlink_to(self.source / m.FILES[0][0])
        result, rc = m.observe(self.source, self.dest, self.matching_hashes)
        self.assertEqual(rc, 3)
        self.assertEqual(result["stage"], "ARCHIVE_REJECTED")

    def test_symlink_source_directory_rejected(self):
        other = self.root / "other"
        other.mkdir()
        self.source.rmdir()
        self.source.symlink_to(other, target_is_directory=True)
        result, rc = m.observe(self.source, self.dest)
        self.assertEqual(rc, 2)
        self.assertEqual(result["stage"], "INPUT_BLOCKED")

    def test_existing_destination_rejected(self):
        self.dest.mkdir()
        result, rc = m.observe(self.source, self.dest)
        self.assertEqual(rc, 2)
        self.assertEqual(result["stage"], "INPUT_BLOCKED")

    def test_disk_shortage_rejected(self):
        self.fake_files()
        result, rc = m.observe(self.source, self.dest, self.matching_hashes,
                               disk_fn=lambda _: mock.Mock(free=1))
        self.assertEqual(rc, 3)
        self.assertEqual(result["stage"], "CAPACITY_BLOCKED")

    def test_no_explicit_eula_never_invokes_installer(self):
        approved = {"stage": "ARCHIVES_VERIFIED_EULA_PENDING", "eula_accepted_by_tool": False,
                    "compiler_executed": False, "fit": "NOT_RUN",
                    "timequest": "NOT_RUN", "hil": "NOT_RUN"}
        with mock.patch.object(m, "observe", return_value=(approved, 0)):
            with mock.patch.object(m.subprocess, "run") as runner:
                result, rc = m.install(self.source, self.dest, approve=False)
        self.assertEqual(rc, 3)
        self.assertEqual(result["stage"], "EULA_APPROVAL_REQUIRED")
        runner.assert_not_called()

    def test_failed_installer_is_not_success(self):
        approved = {"stage": "ARCHIVES_VERIFIED_EULA_PENDING", "eula_accepted_by_tool": False,
                    "compiler_executed": False, "fit": "NOT_RUN",
                    "timequest": "NOT_RUN", "hil": "NOT_RUN"}
        with mock.patch.object(m, "observe", return_value=(approved, 0)):
            with mock.patch.object(m.subprocess, "run", return_value=mock.Mock(returncode=5, stdout="", stderr="failure")) as run:
                result, rc = m.install(self.source, self.dest, approve=True)
        self.assertEqual(rc, 4)
        self.assertEqual(result["stage"], "INSTALL_FAILED_UNCERTAIN_RESIDUE")
        self.assertTrue(result["eula_accepted_by_tool"])
        self.assertEqual(run.call_args.args[0][0], str((self.source / m.FILES[0][0]).resolve()))

    def test_mocked_install_wrong_edition_fails(self):
        approved = {"stage": "ARCHIVES_VERIFIED_EULA_PENDING", "eula_accepted_by_tool": False,
                    "compiler_executed": False, "fit": "NOT_RUN",
                    "timequest": "NOT_RUN", "hil": "NOT_RUN"}
        tool = self.dest / "quartus" / "bin" / "quartus_sh"
        def fake_run(command, **kwargs):
            if "--installdir" in command:
                tool.parent.mkdir(parents=True)
                tool.write_text("synthetic unit-test marker, not a compiler")
                return mock.Mock(returncode=0, stdout="", stderr="")
            return mock.Mock(returncode=0, stdout="Version 24.1std.0 Build 1077 Lite Edition", stderr="")
        with mock.patch.object(m, "observe", return_value=(approved, 0)):
            with mock.patch.object(m.subprocess, "run", side_effect=fake_run):
                result, rc = m.install(self.source, self.dest, approve=True)
        self.assertEqual(rc, 4)
        self.assertEqual(result["stage"], "INSTALL_UNQUALIFIED")
        self.assertFalse(result["compiler_executed"])


if __name__ == "__main__":
    unittest.main()
