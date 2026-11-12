# Read-only GitHub service environment census

This is a **generic public-source** tool for owner-authenticated GitHub repository
settings discovery. It does not create repositories, secrets, environments, tokens,
deployments, runners, workflows, or scheduled jobs.

## Security boundary

- Do not run against private estate data on public GitHub-hosted CI. Public
  PR workflow uses synthetic fixtures only.
- Use an existing **locally authorized** GitHub CLI session with the *narrow
  read access necessary* to list environment names and secret **names** (never
  values), and save output to a private local directory.
- A GitHub 403 or unsupported endpoint is `INACCESSIBLE_OR_UNKNOWN`, **not**
  `OBSERVED names=[]`. Do not request new admin scopes merely to make the
  inventory green. Record unknown in the owning private DLE.
- The output is operationally sensitive even without secret values. It is
  written as a brand-new 0600 file, never overwritten or automatically uploaded.
- No checkout/write permissions are required for public CI. No long-running
  runner or privileged host agent is created.

## Read-only invocation

```bash
python3 scripts/github/read_only_service_env_census.py \
  --repo example-org/example-repo \
  --output /tmp/example-repo-env-census-local.json
```

Expected output contains normalized environment names and per-environment
secret **names** with `OBSERVED` or `INACCESSIBLE_OR_UNKNOWN` state. It
does not contain API tokens, encrypted secret blobs, or environment variable
values. The command emits only `GITHUB_ENV_CENSUS=OBSERVED`,
`GITHUB_ENV_CENSUS=PARTIAL_UNKNOWN` or `GITHUB_ENV_CENSUS=BLOCKED`.

## Research portfolio use

Run the actual private repo/organization census only through the owning
GitHub Ops private workstream; report **capability presence by authorized
repository/environment**, not provider credentials. Match known service
requirements (Kaggle, Colab, Google Drive, Apps Script, Cloudflare, OpenRouter,
OpenAI API, OCI and artifact registries) to the explicit consumer project.
Do not store account-wide provider keys or propagate all organization secrets
to consumer repositories.

## Qualification

`python3 -m unittest discover -s tests -p 'test_read_only_service_env_census.py' -v`

Offline tests validate pagination, permission refusal, GET-only gh invocation,
safe repository names, file permissions, no overwrite, and synthetic secret
name parsing. Provider admin API access remains unqualified until an authorized
local execution produces private readback evidence.
