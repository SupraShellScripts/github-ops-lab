"""Synthetic no-credential tests for private-state GitHub environment census."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.github import read_only_service_env_census as census

class ReadOnlyCensusTests(unittest.TestCase):
    def test_complete_synthetic_observation(self):
        calls=[]
        def fake_api(repo, endpoint):
            calls.append(endpoint)
            if endpoint.endswith("/actions/secrets"):
                return [{"secrets":[{"name":"KAGGLE_API_TOKEN"}]}]
            if endpoint.endswith("/environments"):
                return [{"environments":[{"name":"kaggle-research"},{"name":"colab-research"}]}]
            if endpoint.endswith("/kaggle-research/secrets"):
                return [{"secrets":[{"name":"KAGGLE_API_TOKEN"}]}]
            if endpoint.endswith("/colab-research/secrets"):
                return [{"secrets":[]}]
            raise AssertionError(endpoint)
        result=census.survey("owner/example",api=fake_api)
        self.assertEqual(result["repository_secrets"]["state"],"OBSERVED")
        self.assertEqual(result["environments"]["names"],["colab-research","kaggle-research"])
        self.assertEqual(result["environment_secrets"]["kaggle-research"]["names"],["KAGGLE_API_TOKEN"])
        self.assertEqual(result["environment_secrets"]["colab-research"]["names"],[])
        self.assertEqual(len(calls),4)
        self.assertNotIn("value",json.dumps(result))

    def test_missing_scope_is_not_empty(self):
        def fake_api(repo, endpoint):
            if endpoint.endswith("/actions/secrets"):
                raise census.Inaccessible("403")
            return [{"environments":[]}]
        x=census.survey("owner/example",api=fake_api)
        self.assertEqual(x["repository_secrets"]["state"],"INACCESSIBLE_OR_UNKNOWN")
        self.assertIsNone(x["repository_secrets"]["names"])

    def test_inaccessible_environment_does_not_imply_none(self):
        def fake_api(repo, endpoint):
            if endpoint.endswith("/environments"):
                raise census.Inaccessible("403")
            return [{"secrets":[]}]
        x=census.survey("owner/example",api=fake_api)
        self.assertEqual(x["environments"]["state"],"INACCESSIBLE_OR_UNKNOWN")
        self.assertEqual(x["environment_secrets"],{})
        self.assertIsNone(x["environments"]["names"])

    def test_invalid_repo_injection_denied(self):
        for repo in ("owner/repo; rm -rf /","owner/../../foo","onlyone","owner/foo bar"):
            with self.subTest(repo=repo):
                with self.assertRaises(ValueError):
                    census.survey(repo,api=lambda *args: [])

    def test_duplicate_page_content_is_unknown(self):
        with self.assertRaises(census.Inaccessible):
            census.names([{"secrets":[{"name":"SOME_NAME"}]},
                          {"secrets":[{"name":"SOME_NAME"}]}],"secrets")

    def test_multi_page_gh_json_contract(self):
        content=json.dumps([{"secrets":[{"name":"A"}]},{"secrets":[{"name":"B"}]}])
        self.assertEqual(census.names(census.pages_from_json(content),"secrets"),["A","B"])
        with self.assertRaises(census.Inaccessible):
            census.pages_from_json("<html>403</html>")

    def test_gh_uses_get_without_shell_and_no_secret_logging(self):
        from types import SimpleNamespace
        with patch.object(census.subprocess,"run",
                          return_value=SimpleNamespace(returncode=0,stdout='[{"secrets":[]}]')
                         ) as run:
            result=census.gh_read("owner/repo","/repos/owner/repo/actions/secrets")
        self.assertEqual(result,[{"secrets":[]}])
        argv=run.call_args.args[0]
        self.assertEqual(argv[0:5],["gh","api","--method","GET","--paginate"])
        self.assertEqual(argv[5],"--slurp")
        self.assertIs(run.call_args.kwargs["stderr"],census.subprocess.DEVNULL)
        self.assertNotIn("shell",run.call_args.kwargs)

    def test_private_file_exclusive_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"private"/"census.json"
            census.write_exclusive(path,{"names":["X"]})
            self.assertEqual(json.loads(path.read_text()),{"names":["X"]})
            if os.name=="posix":
                self.assertEqual(path.stat().st_mode & 0o777,0o600)
            with self.assertRaises(FileExistsError):
                census.write_exclusive(path,{"names":["Y"]})
            self.assertEqual(json.loads(path.read_text()),{"names":["X"]})

if __name__=="__main__":
    unittest.main()
