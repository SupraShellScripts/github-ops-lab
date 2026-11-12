#!/usr/bin/env python3
"""Read-only owner-authenticated repo environment and secret-name inventory.

Run with an authorized local gh login. The resulting inventory is PRIVATE
operational metadata even though it contains no secret values. Do not publish
it in public Actions artifacts or log lines. PR CI uses synthetic fixtures.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote

REPO = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
NAME = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
SCHEMA = "github-service-env-census/v1"

class Inaccessible(Exception):
    pass

def pages_from_json(raw: str) -> list[dict]:
    if len(raw) > 1048576:
        raise Inaccessible("RESPONSE_TOO_LARGE")
    try:
        parsed = json.loads(raw)
    except ValueError:
        raise Inaccessible("RESPONSE_NOT_JSON")
    pages = parsed if isinstance(parsed, list) else [parsed]
    if not pages or any(not isinstance(x, dict) for x in pages):
        raise Inaccessible("RESPONSE_SHAPE_UNKNOWN")
    return pages

def gh_read(repo: str, endpoint: str) -> list[dict]:
    if not REPO.fullmatch(repo) or not endpoint.startswith("/repos/" + repo + "/"):
        raise Inaccessible("REQUEST_DENIED")
    args = ["gh", "api", "--method", "GET", "--paginate", "--slurp", endpoint]
    try:
        process = subprocess.run(args, input="", text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 timeout=35, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise Inaccessible("GITHUB_CLI_UNAVAILABLE")
    if process.returncode:
        raise Inaccessible("READ_PERMISSION_OR_ENDPOINT_UNKNOWN")
    return pages_from_json(process.stdout)

def names(pages: list[dict], key: str) -> list[str]:
    result=[]
    for page in pages:
        items = page.get(key)
        if not isinstance(items, list):
            raise Inaccessible("LIST_FIELD_UNKNOWN")
        for item in items:
            if not isinstance(item, dict):
                raise Inaccessible("LIST_ELEMENT_UNKNOWN")
            name = item.get("name")
            if not isinstance(name,str) or not NAME.fullmatch(name):
                raise Inaccessible("NAME_UNKNOWN")
            result.append(name)
    if len(result) != len(set(result)):
        raise Inaccessible("DUPLICATE_NAME_OR_PAGINATION_UNKNOWN")
    return sorted(result)

def survey(repo: str, api=gh_read) -> dict:
    if not REPO.fullmatch(repo):
        raise ValueError("REPOSITORY_NAME_INVALID")
    root = f"/repos/{repo}"
    out={"schema": SCHEMA, "repository":repo,
         "observed_utc":datetime.now(timezone.utc).isoformat(),
         "classification":"PRIVATE_ESTATE_METADATA",
         "observation_only": True}
    def read_names(endpoint, key):
        try:
            return {"state":"OBSERVED","names":names(api(repo,endpoint),key)}
        except (Inaccessible, ValueError):
            return {"state":"INACCESSIBLE_OR_UNKNOWN","names":None}
    out["repository_secrets"] = read_names(root+"/actions/secrets","secrets")
    env = read_names(root+"/environments","environments")
    out["environments"]=env
    out["environment_secrets"]={}
    if env["state"]=="OBSERVED":
        for name in env["names"]:
            out["environment_secrets"][name] = read_names(
                root+"/environments/"+quote(name,safe="")+"/secrets","secrets")
    return out

def write_exclusive(path: Path, content: dict):
    path.parent.mkdir(parents=True,exist_ok=True)
    data=(json.dumps(content,indent=2,sort_keys=True)+"\n").encode("utf-8")
    fd=os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,"wb") as out:
            out.write(data)
    except Exception:
        path.unlink(missing_ok=True)
        raise

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo",required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    try:
        result=survey(args.repo)
        write_exclusive(args.output,result)
        full=(result["repository_secrets"]["state"]=="OBSERVED"
            and result["environments"]["state"]=="OBSERVED"
            and all(x["state"]=="OBSERVED" for x in result["environment_secrets"].values()))
        print("GITHUB_ENV_CENSUS="+("OBSERVED" if full else "PARTIAL_UNKNOWN"))
        return 0 if full else 2
    except (OSError,ValueError,Inaccessible):
        print("GITHUB_ENV_CENSUS=BLOCKED",file=sys.stderr)
        return 2

if __name__=="__main__":
    raise SystemExit(main())
