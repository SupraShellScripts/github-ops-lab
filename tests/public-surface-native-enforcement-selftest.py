#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts" / "github" / "reconcile-public-surface.py"
spec = importlib.util.spec_from_file_location("reconciler", MODULE)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

policy = mod.parse_policy('{"schema":"public-surface-policy/1","targets":[{"repository":"example/deploy","mode":"deploy","enabled":true},{"repository":"example/runner","mode":"runner","enabled":false}]}')
assert len(policy) == 2
assert policy[0].enabled is True
assert policy[1].enabled is False

assert mod.desired_for_mode("deploy") == {
    "has_issues": False,
    "has_projects": False,
    "has_wiki": False,
    "has_discussions": False,
    "has_pull_requests": False,
}
runner = mod.desired_for_mode("runner")
assert runner["has_pull_requests"] is True
assert runner["pull_request_creation_policy"] == "collaborators_only"

for bad in [
    '{}',
    '{"schema":"public-surface-policy/1","targets":{}}',
    '{"schema":"public-surface-policy/1","targets":[{"repository":"bad","mode":"deploy","enabled":true}]}',
    '{"schema":"public-surface-policy/1","targets":[{"repository":"a/b","mode":"other","enabled":true}]}',
]:
    try:
        mod.parse_policy(bad)
    except mod.PolicyError:
        pass
    else:
        raise AssertionError(f"expected PolicyError for {bad}")

print("PASS: public-surface native enforcement self-test")
