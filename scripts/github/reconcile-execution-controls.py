#!/usr/bin/env python3
"""GitHub Ops: read-only estate census and bounded native-settings reconciliation.

This is NOT a scheduler, dispatch actor, PR reviewer, or general admin shell.
It uses the operator's existing gh CLI identity; tokens and raw API errors
never appear in output. Private estate reports remain outside Git worktrees.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

SCHEMA = "github-execution-controls/v1"
POLICY_SCHEMA = "github-execution-control-policy/v1"
REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
REPO_FIELDS = {"repository", "allow_auto_merge"}
ENV_FIELDS = {"repository", "name", "remove_required_reviewers", "expected_reviewers"}
TARGET_LIMIT = 1000


class PolicyError(ValueError):
    pass


class ApiError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def api_class(stderr: str) -> str:
    match = re.search(r"\b(401|403|404|409|422|429)\b", stderr)
    return "HTTP_" + match.group(1) if match else "API_UNAVAILABLE"


class Gh:
    def call(self, args: list[str], payload: dict | None = None):
        proc = subprocess.run(
            ["gh", *args], input=None if payload is None else json.dumps(payload),
            text=True, capture_output=True, timeout=65, check=False)
        if proc.returncode:
            raise ApiError(api_class(proc.stderr))
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise ApiError("INVALID_PROVIDER_JSON") from exc

    def get(self, path: str):
        return self.call(["api", path])

    def change(self, method: str, path: str, payload: dict):
        if method not in ("PATCH", "PUT"):
            raise PolicyError("unsupported mutation")
        return self.call(["api", "--method", method, path, "--input", "-"], payload)

    def repos(self, owner: str):
        if not NAME_PATTERN.fullmatch(owner):
            raise PolicyError("invalid account")
        data = self.call(["repo", "list", owner, "--limit", str(TARGET_LIMIT),
                          "--json", "nameWithOwner,isArchived,visibility,defaultBranchRef"])
        if not isinstance(data, list) or len(data) >= TARGET_LIMIT:
            raise ApiError("REPOSITORY_CENSUS_INCOMPLETE")
        return data


def validate_policy(data: dict):
    if not isinstance(data, dict) or data.get("schema") != POLICY_SCHEMA:
        raise PolicyError("unknown policy schema")
    if set(data) != {"schema", "repositories", "environments"}:
        raise PolicyError("policy keys differ from allowlist")
    seen = set()
    for entry in data["repositories"]:
        if not isinstance(entry, dict) or set(entry) != REPO_FIELDS:
            raise PolicyError("unexpected repository policy keys")
        name = entry.get("repository")
        if not isinstance(name, str) or not REPO_PATTERN.fullmatch(name):
            raise PolicyError("invalid repository")
        if entry.get("allow_auto_merge") is not True:
            raise PolicyError("only enable-auto-merge is supported")
        if name.lower() in seen:
            raise PolicyError("duplicate repository")
        seen.add(name.lower())
    for entry in data["environments"]:
        if not isinstance(entry, dict) or set(entry) != ENV_FIELDS:
            raise PolicyError("unexpected environment policy keys")
        repo, env = entry.get("repository"), entry.get("name")
        if not isinstance(repo, str) or not REPO_PATTERN.fullmatch(repo):
            raise PolicyError("invalid environment repository")
        if not isinstance(env, str) or not NAME_PATTERN.fullmatch(env):
            raise PolicyError("invalid environment name")
        if entry["remove_required_reviewers"] is not True:
            raise PolicyError("only bounded reviewer removal supported")
        expected = entry["expected_reviewers"]
        if not isinstance(expected, list) or not expected or not all(
            isinstance(s, str) and NAME_PATTERN.fullmatch(s) for s in expected):
            raise PolicyError("expected reviewer identities required")
        if len(set(s.lower() for s in expected)) != len(expected):
            raise PolicyError("duplicate expected reviewer")
        key = (repo + ":" + env).lower()
        if key in seen:
            raise PolicyError("duplicate environment")
        seen.add(key)
    return data


def get_safe(gh: Gh, path: str):
    try:
        return {"state": "READABLE", "data": gh.get(path)}
    except ApiError as exc:
        # A permissions/subscription failure is not an empty policy.
        return {"state": exc.code, "data": None}


def safe_sample(repo: str, gh: Gh) -> dict:
    snapshot = {"repository": repo}
    core = get_safe(gh, "repos/" + repo)
    if core["state"] != "READABLE":
        return {"repository": repo, "repository_state": core["state"]}
    data = core["data"]
    branch = data.get("default_branch")
    snapshot.update(
        visibility=data.get("visibility"), archived=bool(data.get("archived")),
        default_branch=branch, allow_auto_merge=data.get("allow_auto_merge"),
        merge_methods={
            "squash": data.get("allow_squash_merge"),
            "merge": data.get("allow_merge_commit"),
            "rebase": data.get("allow_rebase_merge")},
        )
    checks = {
        "branch_protection": f"repos/{repo}/branches/{branch}/protection",
        "branch": f"repos/{repo}/branches/{branch}",
        "rulesets": f"repos/{repo}/rulesets",
        "environments": f"repos/{repo}/environments?per_page=100",
        "actions": f"repos/{repo}/actions/permissions",
        "workflow_token": f"repos/{repo}/actions/permissions/workflow",
        "runners": f"repos/{repo}/actions/runners?per_page=1",
    }
    for key, path in checks.items():
        item = get_safe(gh, path)
        if item["state"] != "READABLE":
            snapshot[key] = {"state": item["state"]}
            continue
        d = item["data"]
        if key == "branch_protection":
            summary = {
                "required_approvals": (d.get("required_pull_request_reviews") or {}).get("required_approving_review_count"),
                "status_checks": (d.get("required_status_checks") or {}).get("contexts"),
                "conversation_resolution": (d.get("required_conversation_resolution") or {}).get("enabled"),
                "enforce_admins": (d.get("enforce_admins") or {}).get("enabled")}
        elif key == "branch":
            summary = {"protected": d.get("protected")}
        elif key == "rulesets":
            summary = [{"name": x.get("name"), "enforcement": x.get("enforcement")}
                       for x in d] if isinstance(d, list) else None
        elif key == "environments":
            summary = [
                {"name": x.get("name"), "protection_types": sorted(
                    (y.get("type", "unknown") for y in x.get("protection_rules", [])))}
                for x in d.get("environments", [])]
        elif key == "runners":
            # Never return runner names, labels, IPs or sovereign host metadata.
            summary = {"total_count": d.get("total_count")}
        else:
            summary = {k: d.get(k) for k in (
                ["enabled", "allowed_actions", "sha_pinning_required"]
                if key == "actions" else
                ["default_workflow_permissions", "can_approve_pull_request_reviews"])}
        snapshot[key] = {"state": "READABLE", "summary": summary}
    return snapshot


def app_summary(owner: str, gh: Gh) -> dict:
    path = "user/installations?per_page=100" if owner == "__user__" else \
        f"orgs/{owner}/installations?per_page=100"
    response = get_safe(gh, path)
    if response["state"] != "READABLE":
        return {"state": response["state"]}
    data = response["data"]
    items = data.get("installations", [])
    if data.get("total_count", 0) > len(items):
        return {"state": "PAGINATION_REQUIRED", "count": len(items)}
    return {"state": "READABLE", "apps": [
        {"slug": x.get("app_slug"), "repository_selection": x.get("repository_selection"),
         "permissions": x.get("permissions", {})} for x in items]}


def reviewer_update(current: dict, expected: list[str], branch_protected: bool):
    """Return safe minimal update or fail closed. Never invent branch protection."""
    if branch_protected is not True:
        raise PolicyError("DEFAULT_BRANCH_NOT_PROTECTED")
    branch = current.get("deployment_branch_policy")
    if branch != {"protected_branches": True, "custom_branch_policies": False}:
        raise PolicyError("ENVIRONMENT_BRANCH_POLICY_MISMATCH")
    rules = current.get("protection_rules")
    if not isinstance(rules, list):
        raise PolicyError("ENVIRONMENT_RULES_UNREADABLE")
    types = [r.get("type") for r in rules]
    if any(x not in ("required_reviewers",) for x in types):
        raise PolicyError("UNEXPECTED_ENVIRONMENT_PROTECTION_RULE")
    if types.count("required_reviewers") > 1:
        raise PolicyError("MULTIPLE_REVIEWER_RULES")
    if not rules:
        return None
    actual = []
    for item in rules[0].get("reviewers", []):
        login = (item.get("reviewer") or {}).get("login")
        if not login:
            raise PolicyError("REVIEWER_IDENTITY_UNVERIFIED")
        actual.append(login.lower())
    if sorted(actual) != sorted(x.lower() for x in expected):
        raise PolicyError("REVIEWER_SET_DRIFT")
    return {"wait_timer": 0, "reviewers": [],
            "deployment_branch_policy": {"protected_branches": True,
                                         "custom_branch_policies": False}}


def reconcile(gh: Gh, policy: dict, apply: bool) -> list[dict]:
    # Read ALL preconditions and stage EVERY operation before any mutation.
    # An inaccessible environment or drifted reviewer list cannot cause a
    # partial application that already changed unrelated repository settings.
    staged = []
    outcomes = []
    for target in policy["repositories"]:
        repo = target["repository"]
        before = gh.get("repos/" + repo)
        if before.get("archived") or before.get("disabled"):
            raise PolicyError("TARGET_REPOSITORY_NOT_ACTIVE")
        drift = before.get("allow_auto_merge") is not True
        outcomes.append({"target": repo, "type": "auto_merge",
                         "state": "CHANGE_REQUIRED" if drift else "CONFORMANT"})
        if drift:
            staged.append(("PATCH", "repos/" + repo, {"allow_auto_merge": True}, len(outcomes)-1))
    for target in policy["environments"]:
        repo, name = target["repository"], target["name"]
        base = "repos/" + repo
        r = gh.get(base)
        default = r.get("default_branch")
        if r.get("archived") or not default:
            raise PolicyError("TARGET_REPOSITORY_NOT_ACTIVE")
        current_branch = gh.get(f"{base}/branches/{default}")
        env_path = f"{base}/environments/{name}"
        current = gh.get(env_path)  # nonexistent environment never auto-created
        proposed = reviewer_update(current, target["expected_reviewers"],
                                   current_branch.get("protected"))
        outcomes.append({"target": repo + ":" + name, "type": "remove_reviewers",
                         "state": "CHANGE_REQUIRED" if proposed else "CONFORMANT"})
        if proposed is not None:
            staged.append(("PUT", env_path, proposed, len(outcomes)-1))
    if not apply:
        return outcomes

    # The operator's explicit apply applies only this preflighted desired
    # state. We re-read immediately before each write (race is denied).
    for verb, path, payload, index in staged:
        if verb == "PATCH":
            before = gh.get(path)
            if before.get("allow_auto_merge") is not False:
                raise PolicyError("AUTO_MERGE_CONCURRENT_DRIFT")
        else:
            before = gh.get(path)
            target = next(x for x in policy["environments"]
                          if path.endswith("/environments/" + x["name"])
                          and x["repository"] in path)
            branch = gh.get("repos/" + target["repository"] + "/branches/" +
                            gh.get("repos/" + target["repository"])["default_branch"])
            recalculated = reviewer_update(before, target["expected_reviewers"],
                                           branch.get("protected"))
            if recalculated != payload:
                raise PolicyError("ENVIRONMENT_CONCURRENT_DRIFT")
        gh.change(verb, path, payload)
        after = gh.get(path)
        if verb == "PATCH":
            if after.get("allow_auto_merge") is not True:
                raise PolicyError("AUTO_MERGE_VERIFY_FAILED")
        else:
            if reviewer_update(after, target["expected_reviewers"], True) is not None:
                raise PolicyError("ENVIRONMENT_VERIFY_FAILED")
        outcomes[index]["state"] = "VERIFIED"
    return outcomes


def output_path(path: str) -> Path:
    dest = Path(path).expanduser().resolve()
    if dest == Path.cwd().resolve() or Path.cwd().resolve() in dest.parents:
        raise PolicyError("PRIVATE_CENSUS_OUTPUT_WITHIN_WORKTREE")
    dest.mkdir(mode=0o700, parents=True, exist_ok=True)
    return dest / "github-execution-controls.json"


def main(argv: list[str] | None = None, gh: Gh | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--owners", nargs="*", default=[], help="owner accounts (never guessed)")
    p.add_argument("--policy", help="private manifest path")
    p.add_argument("--output", default=str(
        Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "github-ops-execution-census"))
    p.add_argument("--all-repositories", action="store_true",
                   help="deep-inspect all discovered repos, not only policy targets")
    p.add_argument("--apply", action="store_true",
                   help="apply only exact policy changes after live preconditions")
    args = p.parse_args(argv)
    if args.apply and not args.policy:
        raise PolicyError("APPLY_REQUIRES_POLICY")
    if not args.owners and not args.policy:
        raise PolicyError("PROVIDE_OWNERS_OR_POLICY")
    gh = gh or Gh()
    policy = None
    if args.policy:
        policy = validate_policy(json.loads(Path(args.policy).read_text(encoding="utf-8")))
    owners = {}
    names = set()
    for owner in args.owners:
        discovered = gh.repos(owner)
        owners[owner] = {"discovered_count": len(discovered),
                         "archived_count": sum(bool(x.get("isArchived")) for x in discovered)}
        if args.all_repositories:
            names.update(x["nameWithOwner"] for x in discovered)
    if policy:
        names.update(x["repository"] for x in policy["repositories"])
        names.update(x["repository"] for x in policy["environments"])
    census = {name: safe_sample(name, gh) for name in sorted(names)}
    current_user = get_safe(gh, "user")
    account_login = (current_user["data"] or {}).get("login") if current_user["state"] == "READABLE" else None
    accounts = {owner: app_summary("__user__" if owner == account_login else owner, gh)
                for owner in args.owners}
    # Mutation happens only after a full current-state scan. Reconcile re-reads.
    changes = reconcile(gh, policy, apply=args.apply) if policy else []
    report = {"schema": SCHEMA, "accounts": owners,
              "app_installations": accounts, "repositories": census,
              "policy_changes": changes, "applied": bool(args.apply)}
    destination = output_path(args.output)
    temp = destination.with_suffix(".tmp")
    temp.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, destination)
    print(json.dumps({"schema": SCHEMA, "account_count": len(owners),
                      "deep_inspected_repos": len(census),
                      "changes": changes, "applied": bool(args.apply),
                      "local_report": str(destination)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PolicyError, ApiError, OSError, ValueError) as error:
        # No raw provider stderr or policy/source content is printed.
        print(f"GITHUB_OPS_BLOCKED={str(error)}", file=sys.stderr)
        raise SystemExit(2)
