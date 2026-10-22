import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/fpga/quartus25_public_pilot.py'
FIXTURE = ROOT / 'fixtures/fpga/quartus25-minimal'
spec = importlib.util.spec_from_file_location('quartus_pilot', SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Contract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'f'
        shutil.copytree(FIXTURE, self.root)

    def test_valid_original_fixture(self):
        result = m.check(self.root)
        self.assertEqual(result['target_part'], 'EP4CE115F29C7')
        self.assertFalse(result['quartus_executed'])
        self.assertFalse(result['timing_qualified'])

    def test_deterministic_digest(self):
        self.assertEqual(m.check(self.root), m.check(self.root))
        self.assertEqual(set(m.check(self.root)['source_sha256']), set(m.FILES))

    def test_wrong_part_rejected(self):
        q = self.root / 'synthetic.qsf'
        q.write_text(q.read_text().replace('EP4CE115F29C7', 'AUTO'))
        with self.assertRaisesRegex(ValueError, 'QSF'):
            m.check(self.root)

    def test_wrong_family_rejected(self):
        q = self.root / 'synthetic.qsf'
        q.write_text(q.read_text().replace('Cyclone IV E', 'Cyclone V'))
        with self.assertRaisesRegex(ValueError, 'QSF'):
            m.check(self.root)

    def test_missing_sdc_rejected(self):
        (self.root / 'synthetic.sdc').unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            m.check(self.root)

    def test_commented_sdc_rejected(self):
        (self.root / 'synthetic.sdc').write_text('# create_clock -period 20 [get_ports clk]\n')
        with self.assertRaisesRegex(ValueError, 'primary clock'):
            m.check(self.root)

    def test_sdc_wrong_clock_rejected(self):
        (self.root / 'synthetic.sdc').write_text('create_clock -period 20 [get_ports wrong]\n')
        with self.assertRaisesRegex(ValueError, 'primary clock'):
            m.check(self.root)

    def test_symlink_file_rejected(self):
        q = self.root / 'synthetic.sdc'
        q.unlink()
        q.symlink_to(self.root / 'synthetic.qsf')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            m.check(self.root)

    def test_uninstalled_quartus_explicit_not_run(self):
        with mock.patch.object(m.shutil, 'which', return_value=None):
            result, rc = m.compile_quartus(self.root, Path(self.tmp.name) / 'out', 1)
        self.assertEqual(rc, 3)
        self.assertEqual(result['stage'], 'ENVIRONMENT_BLOCKED')
        self.assertFalse(result['quartus_executed'])

    def test_wrong_quartus_build_rejected_without_compiling(self):
        observed = mock.Mock(returncode=0, stdout='Version 24.1std.0 Build 1077 Lite Edition',
                             stderr='')
        with mock.patch.object(m.shutil, 'which', return_value='/opt/q/quartus_sh'):
            with mock.patch.object(m.subprocess, 'run', return_value=observed) as invoked:
                result, rc = m.compile_quartus(self.root, Path(self.tmp.name) / 'wrong-build', 15)
        self.assertEqual(rc, 3)
        self.assertEqual(result['stage'], 'TOOL_IDENTITY_BLOCKED')
        self.assertFalse(result['quartus_executed'])
        self.assertEqual(invoked.call_count, 1)
        self.assertFalse((Path(self.tmp.name) / 'wrong-build').exists())

    def test_standard_edition_rejected_without_compiling(self):
        observed = mock.Mock(returncode=0, stdout='Version 25.1std.0 Build 1129 Standard Edition',
                             stderr='')
        with mock.patch.object(m.shutil, 'which', return_value='/opt/q/quartus_sh'):
            with mock.patch.object(m.subprocess, 'run', return_value=observed) as invoked:
                result, rc = m.compile_quartus(self.root, Path(self.tmp.name) / 'wrong-edition', 15)
        self.assertEqual(rc, 3)
        self.assertEqual(result['stage'], 'TOOL_IDENTITY_BLOCKED')
        self.assertFalse(result['quartus_executed'])
        self.assertEqual(invoked.call_count, 1)

    def test_matching_identity_compiles_but_missing_sof_fails(self):
        identity = mock.Mock(returncode=0, stdout='Quartus Prime Shell\nVersion 25.1std.0 Build 1129 Lite Edition',
                             stderr='')
        compile_without_outputs = mock.Mock(returncode=0, stdout='no output generated', stderr='')
        with mock.patch.object(m.shutil, 'which', return_value='/opt/q/quartus_sh'):
            with mock.patch.object(m.subprocess, 'run', side_effect=[identity, compile_without_outputs]) as invoked:
                result, rc = m.compile_quartus(self.root, Path(self.tmp.name) / 'empty-build', 15)
        self.assertEqual(rc, 4)
        self.assertEqual(result['stage'], 'COMPILE_FAILED')
        self.assertTrue(result['quartus_executed'])
        self.assertFalse(result['sof_observed'])
        self.assertFalse(result['timing_qualified'])
        self.assertEqual(invoked.call_count, 2)

    def test_probe_never_claims_build(self):
        with mock.patch.object(m.shutil, 'which', return_value=None):
            result = m.probe(self.root)
        self.assertEqual(result['quartus_compile'], 'NOT_RUN')
        self.assertEqual(result['timequest'], 'NOT_RUN')


if __name__ == '__main__':
    unittest.main()
