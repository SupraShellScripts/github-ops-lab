"""Offline tests: no GitHub token or estate settings are read/mutated."""
import importlib.util
import json
import tempfile
from types import SimpleNamespace
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "scripts/github/reconcile-execution-controls.py"
spec = importlib.util.spec_from_file_location("github_execution_controls", MODULE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def policy():
    return {"schema":m.POLICY_SCHEMA,
            "repositories":[{"repository":"ExampleOrg/execution-control","allow_auto_merge":True}],
            "environments":[{"repository":"ExampleOrg/execution-control",
                             "name":"test-rdte",
                             "remove_required_reviewers":True,
                             "expected_reviewers":["reviewer"]}]}


def env(reviewers=("reviewer",), protection=None):
    if protection is None:
        protection = ([{"type":"required_reviewers",
                        "reviewers":[{"type":"User","reviewer":{"login":x,"id":i+101}} for i,x in enumerate(reviewers)]}]
                      if reviewers else [])
    return {"deployment_branch_policy":{"protected_branches":True,
                                        "custom_branch_policies":False},
            "protection_rules":protection}


class FakeGh:
    def __init__(self):
        self.changed=[]
        self.repo={"default_branch":"main","allow_auto_merge":False,"archived":False}
        self.branch={"protected":True}
        self.environment=env()
    def get(self, path):
        if path=="repos/ExampleOrg/execution-control":
            return dict(self.repo)
        if path=="repos/ExampleOrg/execution-control/branches/main":
            return dict(self.branch)
        if path=="repos/ExampleOrg/execution-control/environments/test-rdte":
            return dict(self.environment)
        raise AssertionError("unexpected API GET: "+path)
    def change(self, verb, path, payload):
        self.changed.append((verb,path,payload))
        if verb=="PATCH":
            self.repo.update(payload)
        elif verb=="PUT":
            self.environment["protection_rules"]=[]
        else:
            raise AssertionError("unexpected verb")
        return {}


class ExecutionPolicyTests(unittest.TestCase):
    def test_valid_policy(self):
        self.assertEqual(len(m.validate_policy(policy())["environments"]),1)
    def test_unknown_policy_keys_fail_closed(self):
        p=policy()
        p["environments"][0]["run_command"]="echo secret"
        with self.assertRaises(m.PolicyError):
            m.validate_policy(p)
    def test_no_disabling_auto_merge(self):
        p=policy()
        p["repositories"][0]["allow_auto_merge"]=False
        with self.assertRaises(m.PolicyError):
            m.validate_policy(p)
    def test_expected_reviewer_mandatory(self):
        p=policy()
        p["environments"][0]["expected_reviewers"]=[]
        with self.assertRaises(m.PolicyError):
            m.validate_policy(p)
    def test_env_preserves_default_branch_protection(self):
        with self.assertRaisesRegex(m.PolicyError,"DEFAULT_BRANCH_NOT_PROTECTED"):
            m.reviewer_update(env(),["reviewer"],False)
        with self.assertRaisesRegex(m.PolicyError,"ENVIRONMENT_BRANCH_POLICY_MISMATCH"):
            d=env()
            d["deployment_branch_policy"]["protected_branches"]=False
            m.reviewer_update(d,["reviewer"],True)
    def test_unknown_environment_rules_block(self):
        with self.assertRaisesRegex(m.PolicyError,"UNEXPECTED_ENVIRONMENT_PROTECTION_RULE"):
            m.reviewer_update(env(protection=[{"type":"wait_timer"}]),["reviewer"],True)
    def test_review_drift_blocks(self):
        with self.assertRaisesRegex(m.PolicyError,"REVIEWER_SET_DRIFT"):
            m.reviewer_update(env(["someone-else"]),["reviewer"],True)
    def test_compliant_env_is_noop(self):
        self.assertIsNone(m.reviewer_update(env([]),["reviewer"],True))
    def test_read_only_plan_no_writes(self):
        fake=FakeGh()
        result=m.reconcile(fake,policy(),apply=False)
        self.assertEqual([x["state"] for x in result],["CHANGE_REQUIRED","CHANGE_REQUIRED"])
        self.assertFalse(fake.changed)
    def test_apply_verified(self):
        fake=FakeGh()
        checkpoints=[]
        def save(outcomes, phase, recovery):
            checkpoints.append((phase,json.loads(json.dumps(outcomes)),
                                json.loads(json.dumps(recovery))))
        result=m.reconcile(fake,policy(),apply=True,checkpoint=save)
        self.assertEqual([x["state"] for x in result],["VERIFIED","VERIFIED"])
        self.assertEqual([x[0] for x in fake.changed],["PATCH","PUT"])
        self.assertEqual(fake.environment["deployment_branch_policy"]["protected_branches"],True)
        self.assertEqual(checkpoints[0][0],"PREFLIGHTED")
        self.assertEqual(checkpoints[-1][0],"VERIFIED")
        self.assertEqual(checkpoints[0][2][0]["previous"]["allow_auto_merge"],False)
        self.assertEqual(checkpoints[0][2][1]["previous"]["reviewers"],
                         [{"type":"User","id":101}])
        self.assertTrue(any(x[1][0]["state"]=="APPLIED_UNVERIFIED" for x in checkpoints))

    def test_repeat_apply_idempotent(self):
        fake=FakeGh()
        m.reconcile(fake,policy(),apply=True,checkpoint=lambda *args: None)
        fake.changed=[]
        result=m.reconcile(fake,policy(),apply=True,checkpoint=lambda *args: None)
        self.assertEqual([x["state"] for x in result],["CONFORMANT","CONFORMANT"])
        self.assertFalse(fake.changed)

    def test_no_apply_without_checkpoint(self):
        fake=FakeGh()
        with self.assertRaisesRegex(m.PolicyError,"APPLY_REQUIRES_DURABLE_CHECKPOINT"):
            m.reconcile(fake,policy(),apply=True)
        self.assertFalse(fake.changed)

    def test_preflight_checkpoint_failure_causes_zero_mutation(self):
        fake=FakeGh()
        def failed(*args):
            raise OSError("disk-full")
        with self.assertRaises(OSError):
            m.reconcile(fake,policy(),apply=True,checkpoint=failed)
        self.assertFalse(fake.changed)

    def test_partial_settings_update_retains_prechange_recovery(self):
        class FailSecond(FakeGh):
            def change(self, verb, path, payload):
                if verb=="PUT":
                    raise m.ApiError("HTTP_403")
                return super().change(verb,path,payload)
        fake=FailSecond()
        checkpoints=[]
        def save(outcomes,phase,recovery):
            checkpoints.append((phase,json.loads(json.dumps(outcomes)),
                                json.loads(json.dumps(recovery))))
        with self.assertRaises(m.ApiError):
            m.reconcile(fake,policy(),apply=True,checkpoint=save)
        self.assertEqual(fake.repo["allow_auto_merge"],True)
        self.assertEqual([x[0] for x in fake.changed],["PATCH"])
        self.assertEqual(checkpoints[-1][1][0]["state"],"VERIFIED")
        self.assertEqual(checkpoints[-1][1][1]["state"],"CHANGE_REQUIRED")
        self.assertEqual(checkpoints[-1][2][1]["previous"]["reviewers"][0]["id"],101)

    def test_reviewer_restore_id_must_be_observed(self):
        fake=FakeGh()
        fake.environment["protection_rules"][0]["reviewers"][0]["reviewer"].pop("id")
        with self.assertRaisesRegex(m.PolicyError,"REVIEWER_ROLLBACK_IDENTITY_UNVERIFIED"):
            m.reconcile(fake,policy(),apply=True,checkpoint=lambda *args: None)
        self.assertFalse(fake.changed)

    def test_self_review_rule_is_preserved(self):
        current=env()
        current["prevent_self_review"]=True
        payload=m.reviewer_update(current,["reviewer"],True)
        self.assertTrue(payload["prevent_self_review"])
        self.assertTrue(m.environment_restore_payload(current)["prevent_self_review"])

    def test_safe_default_home_directory_not_assumed_git_worktree(self):
        with tempfile.TemporaryDirectory() as base:
            dest=Path(base)/"AppData"/"Local"/"GitHubOps"
            with patch.object(m.subprocess,"run",
                              return_value=SimpleNamespace(returncode=128,stdout="")), \
                 patch.object(m.Path,"cwd",return_value=Path(base)):
                result=m.output_path(str(dest))
            self.assertTrue(result.parent.is_dir())

    def test_real_git_worktree_report_location_denied(self):
        with tempfile.TemporaryDirectory() as base:
            with patch.object(m.subprocess,"run",
                              return_value=SimpleNamespace(returncode=0,stdout=base+"\n")):
                with self.assertRaisesRegex(m.PolicyError,"PRIVATE_CENSUS_OUTPUT_WITHIN_WORKTREE"):
                    m.output_path(str(Path(base)/"child"))

    def test_api_errors_classified_without_sensitive_text(self):
        self.assertEqual(m.api_class("HTTP 403 SECRET_ABC123"),"HTTP_403")
        self.assertEqual(m.api_class("private bearer abc"),"API_UNAVAILABLE")
    def test_runner_names_not_returned(self):
        class Partial:
            def get(self,path):
                if path=="repos/Org/repo":
                    return {"default_branch":"main","visibility":"private",
                            "allow_auto_merge":False,"archived":False}
                if path.endswith("/actions/runners?per_page=1"):
                    return {"total_count":4,"runners":[{"name":"sensitive-machine-name"}]}
                if "/branches/main" in path:
                    return {"protected":True}
                if path.endswith("/rulesets"):
                    return []
                if path.endswith("/environments?per_page=100"):
                    return {"environments":[]}
                return {}
        sample=m.safe_sample("Org/repo",Partial())
        self.assertEqual(sample["runners"]["summary"],{"total_count":4})
        self.assertNotIn("sensitive-machine-name",json.dumps(sample))


if __name__=="__main__":
    unittest.main()
