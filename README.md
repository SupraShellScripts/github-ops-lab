# github-ops-lab

Public-safe GitHub Actions execution laboratory for repository-operations tooling.

## Purpose

This repository provides disposable, reproducible GitHub-hosted execution for tooling that can be evaluated entirely with public inputs and public-safe outputs. It is an execution and validation surface, not an authority for private engineering data or promotion decisions.

## Hard boundary

Allowed here:

- public repository metadata and source;
- public-safe PowerShell and `gh` tooling;
- syntax, parser, unit, smoke, and compatibility validation;
- synthetic/public fixtures;
- sanitized logs, hashes, and test evidence.

Not allowed here:

- credentials that can read private repositories;
- private source, corpora, evaluator logic, failure knowledge, or internal prompts;
- organization-wide or broadly scoped mutation credentials;
- secrets copied from private environments;
- treating a successful public workflow as approval to promote or publish elsewhere.

## Execution posture

Pull-request and push validation is non-mutating and uses minimal `GITHUB_TOKEN` permissions. Any future workflow capable of modifying another public repository must be separately designed, manually dispatched, narrowly scoped, and reviewed before it is enabled.

Stable reusable tooling should graduate to its durable public home rather than turning this lab into a product repository.
