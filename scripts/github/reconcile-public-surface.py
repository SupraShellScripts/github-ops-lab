#!/usr/bin/env python3
"""Reconcile GitHub-native interaction settings for public deployment surfaces.

Estate-specific target policy is supplied at runtime. This tool deliberately owns
only repository-setting drift. It does not own work intake, planning, scheduling,
executor/provider selection, assignments, dependencies, attempts, or acceptance.
Those orchestration semantics belong outside this reconciler.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

API = "https://api.github.com"
API_VERSION = "2026-03-10"
VALID_MODES = {"deploy", "runner"}
TOP_LEVEL_KEYS = {"schema", "targets"}
TARGET_KEYS = {"repository", "mode", "enabled"}


class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class Target:
    repository: str
    mode: str
    enabled: bool


def desired_for_mode(mode: str) -> dict[str, Any]:
    if mode not in VALID_MODES:
        raise PolicyError(f"unsupported mode: {mode}")
    common: dict[str, Any] = {
        "has_issues": False,
        "has_projects": False,
        "has_wiki": False,
        "has_discussions": False,
    }
    if mode == "deploy":
        return {**common, "has_pull_requests": False}
    return {
        **common,
        "has_pull_requests": True,
        "pull_request_creation_policy": "collaborators_only",
    }


def parse_policy(raw: str) -> list[Target]:
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PolicyError(f"invalid JSON: {exc}") from exc
    if not isinstance(doc, dict) or doc.get("schema") != "public-surface-policy/1":
        raise PolicyError("policy schema must be public-surface-policy/1")
    unknown_top = set(doc) - TOP_LEVEL_KEYS
    if unknown_top:
        raise PolicyError("unsupported top-level policy field(s)")
    items = doc.get("targets")
    if not isinstance(items, list):
        raise PolicyError("targets must be an array")
    result: list[Target] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise PolicyError(f"target {index} must be an object")
        unknown_target = set(item) - TARGET_KEYS
        if unknown_target:
            raise PolicyError(f"target {index} contains unsupported field(s)")
        repo = item.get("repository")
        mode = item.get("mode")
        enabled = item.get("enabled", False)
        if not isinstance(repo, str) or repo.count("/") != 1 or not all(repo.split("/")):
            raise PolicyError(f"target {index} has invalid repository")
        if mode not in VALID_MODES:
            raise PolicyError(f"target {index} has invalid mode")
        if not isinstance(enabled, bool):
            raise PolicyError(f"target {index} enabled must be boolean")
        if repo in seen:
            raise PolicyError(f"duplicate repository at target {index}")
        seen.add(repo)
        result.append(Target(repo, mode, enabled))
    return result


def request_json(repository: str, token: str, method: str = "GET", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        f"{API}/repos/{repository}",
        data=body,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "github-ops-lab-public-surface-reconciler/1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            value = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GitHub API returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("GitHub API request failed") from exc
    if not isinstance(value, dict):
        raise RuntimeError("GitHub API returned a non-object response")
    return value


def drift(current: dict[str, Any], desired: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in desired.items() if current.get(key) != value}


def main() -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--policy", help="path to policy JSON")
    source.add_argument("--policy-env", default=None, help="environment variable containing policy JSON")
    parser.add_argument("--apply", action="store_true", help="apply drift; otherwise observe only")
    parser.add_argument("--validate-only", action="store_true", help="validate policy without GitHub API access")
    args = parser.parse_args()

    if args.policy:
        raw = open(args.policy, encoding="utf-8").read()
    else:
        raw = os.environ.get(args.policy_env or "", "")
        if not raw:
            raise PolicyError("policy environment variable is empty")

    targets = parse_policy(raw)
    enabled = [target for target in targets if target.enabled]
    if args.validate_only:
        print(f"PASS: policy valid; {len(enabled)} enabled target(s)")
        return 0

    token = os.environ.get("GH_TOKEN") or os.environ.get("PUBLIC_SURFACE_ADMIN_TOKEN")
    if not token:
        raise RuntimeError("GH_TOKEN or PUBLIC_SURFACE_ADMIN_TOKEN is required")

    changed = 0
    clean = 0
    for index, target in enumerate(enabled, start=1):
        try:
            current = request_json(target.repository, token)
            desired = desired_for_mode(target.mode)
            delta = drift(current, desired)
            if not delta:
                clean += 1
                print(f"target {index}: conformant")
                continue
            if not args.apply:
                print(f"target {index}: drift detected")
                continue
            request_json(target.repository, token, method="PATCH", payload=delta)
            observed = request_json(target.repository, token)
            residual = drift(observed, desired)
            if residual:
                raise RuntimeError("post-apply verification found residual drift")
            changed += 1
            print(f"target {index}: corrected and verified")
        except Exception as exc:
            print(f"target {index}: FAIL: {exc}", file=sys.stderr)
            return 1

    print(f"PASS: enabled={len(enabled)} conformant={clean} corrected={changed} apply={args.apply}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PolicyError, RuntimeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(2)
