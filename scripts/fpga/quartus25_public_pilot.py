#!/usr/bin/env python3
"""Public-safe Cyclone IV toolchain pilot. No network, license acceptance or hardware IO."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile

PART = 'EP4CE115F29C7'
FAMILY = 'Cyclone IV E'
TOP = 'synthetic_top'
PROJECT = 'synthetic'
FILES = ('synthetic.qpf', 'synthetic.qsf', 'synthetic.sdc', 'synthetic_top.v', 'synthetic_top_tb.v')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _active_lines(content):
    lines = []
    for line in content.splitlines():
        active = line.split('#', 1)[0].strip()
        if active:
            lines.append(active)
    return lines


def check(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('fixture root must be a real directory')
    files = {}
    for name in FILES:
        candidate = root / name
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError(f'missing or symlinked fixture: {name}')
        files[name] = sha256(candidate)
    qsf = _active_lines((root / 'synthetic.qsf').read_text(encoding='utf-8'))
    qpf = _active_lines((root / 'synthetic.qpf').read_text(encoding='utf-8'))
    sdc = _active_lines((root / 'synthetic.sdc').read_text(encoding='utf-8'))
    required_qsf = [
        f'set_global_assignment -name FAMILY "{FAMILY}"',
        f'set_global_assignment -name DEVICE {PART}',
        f'set_global_assignment -name TOP_LEVEL_ENTITY {TOP}',
        'set_global_assignment -name VERILOG_FILE synthetic_top.v',
        'set_global_assignment -name SDC_FILE synthetic.sdc',
    ]
    if sorted(qsf) != sorted(required_qsf):
        raise ValueError('unexpected/missing QSF assignment, device or source')
    if qpf != [f'PROJECT_REVISION = "{PROJECT}"']:
        raise ValueError('wrong revision')
    # This is only a synthetic *primary clock presence* test, not a STA-coverage proof.
    if not any(re.fullmatch(r'create_clock\s+-period\s+20(?:\.0+)?\s+\[get_ports\s+\{?clk\}?\]', s) for s in sdc):
        raise ValueError('active primary clock constraint missing')
    if not any(re.search(r'\bmodule\s+synthetic_top\b', s) for s in (root / 'synthetic_top.v').read_text().splitlines()):
        raise ValueError('top module missing')
    return {'schema': 'quartus25-public-pilot/v1', 'stage': 'SOURCE_CONTRACT_PASS',
            'target_part': PART, 'target_family': FAMILY, 'project': PROJECT,
            'source_sha256': files, 'quartus_executed': False, 'timing_qualified': False,
            'hardware_observed': False, 'private_inputs': False}


def tool_version(command):
    p = shutil.which(command)
    if p is None:
        return {'present': False}
    try:
        r = subprocess.run([p, '--version'], text=True, capture_output=True, timeout=15, check=False)
        return {'present': True, 'path': p, 'returncode': r.returncode,
                'version_excerpt': (r.stdout + r.stderr)[:500]}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {'present': True, 'error': type(e).__name__}


def probe(root):
    out = check(root)
    disk = shutil.disk_usage(tempfile.gettempdir())
    out.update({'stage': 'RUNNER_OBSERVED', 'os': platform.platform(), 'machine': platform.machine(),
                'python': sys.version.split()[0], 'cpus': os.cpu_count(),
                'scratch_disk_total_bytes': disk.total, 'scratch_disk_free_bytes': disk.free,
                'quartus_sh': tool_version('quartus_sh'), 'iverilog': tool_version('iverilog'),
                'quartus_compile': 'NOT_RUN', 'fpga_fit': 'NOT_RUN', 'timequest': 'NOT_RUN'})
    return out


def compile_quartus(root, outdir, timeout):
    source = check(root)
    tool = shutil.which('quartus_sh')
    if tool is None:
        return {'schema': source['schema'], 'stage': 'ENVIRONMENT_BLOCKED',
                'reason': 'quartus_sh not installed (no installer acquisition/EULA operation in pilot)',
                'quartus_executed': False, 'timing_qualified': False, 'hardware_observed': False}, 3
    if not 1 <= timeout <= 3600:
        raise ValueError('timeout must be 1..3600 seconds')
    outdir = Path(outdir)
    if outdir.exists() or outdir.is_symlink():
        raise ValueError('output directory must not yet exist')
    outdir.mkdir(parents=False)
    with tempfile.TemporaryDirectory(prefix='quartus25-pilot-') as tmp:
        scratch = Path(tmp)
        for n in FILES:
            shutil.copyfile(Path(root) / n, scratch / n)
        try:
            p = subprocess.run([tool, '--flow', 'compile', PROJECT], cwd=scratch,
                               capture_output=True, text=True, timeout=timeout, check=False)
            (outdir / 'quartus-stdout.txt').write_text(p.stdout[-100000:], encoding='utf-8')
            (outdir / 'quartus-stderr.txt').write_text(p.stderr[-100000:], encoding='utf-8')
        except subprocess.TimeoutExpired:
            return {'schema': source['schema'], 'stage': 'ENVIRONMENT_FAILURE',
                    'reason': 'quartus compile timeout', 'quartus_executed': True,
                    'timing_qualified': False, 'hardware_observed': False}, 4
        outputs = sorted(x for x in scratch.rglob('*') if x.is_file() and
                         (x.suffix.lower() in ('.sof', '.rpt') or x.name.endswith('.smsg')))
        for pth in outputs:
            relative = pth.relative_to(scratch)
            output_path = outdir / relative
            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(pth, output_path)
        produced = {str(p.relative_to(outdir)): sha256(p) for p in outdir.rglob('*') if p.is_file()}
        has_sof = any(p.endswith('.sof') for p in produced)
        reports = sorted(p for p in produced if p.endswith('.rpt'))
        verdict = 'COMPILE_ARTIFACT_OBSERVED' if p.returncode == 0 and has_sof else 'COMPILE_FAILED'
        result = {'schema': source['schema'], 'stage': verdict, 'quartus_executed': True,
                  'quartus_exit_code': p.returncode, 'sof_observed': has_sof,
                  'report_paths': reports, 'generated_sha256': produced,
                  'source_sha256': source['source_sha256'],
                  # Never infer complete STA coverage from a success code or an .sta.rpt file.
                  'timequest_coverage': 'NOT_VERIFIED', 'timing_qualified': False,
                  'hardware_observed': False}
        (outdir / 'receipt.json').write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
        return result, (0 if verdict == 'COMPILE_ARTIFACT_OBSERVED' else 4)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['check', 'probe', 'compile'])
    p.add_argument('--root', required=True)
    p.add_argument('--out-dir')
    p.add_argument('--timeout', type=int, default=900)
    a = p.parse_args(argv)
    try:
        if a.command == 'compile':
            if not a.out_dir:
                raise ValueError('--out-dir required for compile')
            out, rc = compile_quartus(a.root, a.out_dir, a.timeout)
        else:
            out, rc = (check(a.root) if a.command == 'check' else probe(a.root)), 0
        print(json.dumps(out, sort_keys=True, indent=2))
        return rc
    except (ValueError, OSError, UnicodeError) as e:
        print(json.dumps({'stage': 'INPUT_BLOCKED', 'reason': str(e)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
