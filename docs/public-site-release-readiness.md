# Reusable public-site release readiness

This repository provides a **public-safe reusable GitHub Actions workflow** for the common mechanics proven by the SupraCraft VanillaCord and Bridge public-web pilots.

The reusable workflow deliberately does **not** own project-specific routes, release semantics, Maven coordinates, download/support behavior, branding, or accessibility claims. Consumers keep those assertions locally.

## Reusable workflow

Path:

```text
.github/workflows/public-site-readiness.yml
```

A consumer calls it from a thin local workflow:

```yaml
name: public-site-readiness

on:
  pull_request:
    branches: [main]
    paths:
      - 'docs/**'
      - 'scripts/build-public-site.py'
      - 'scripts/check-public-site.py'
      - 'package.json'
      - 'playwright.config.mjs'
      - 'lighthouserc.cjs'
      - 'tests/site/**'
      - '.github/workflows/public-site-readiness.yml'
  push:
    branches: [main]
    paths:
      - 'docs/**'
      - 'scripts/build-public-site.py'
      - 'scripts/check-public-site.py'
      - 'package.json'
      - 'playwright.config.mjs'
      - 'lighthouserc.cjs'
      - 'tests/site/**'
      - '.github/workflows/public-site-readiness.yml'

permissions:
  contents: read

jobs:
  readiness:
    uses: SupraShellScripts/github-ops-lab/.github/workflows/public-site-readiness.yml@<pinned-ref>
    with:
      build_command: >-
        python3 ./scripts/build-public-site.py
        --output build/public-site
        --base-url http://127.0.0.1:4173/
      validate_command: >-
        python3 ./scripts/check-public-site.py
        --site-dir build/public-site
        --navigation-base http://127.0.0.1:4173/
      lychee_args: >-
        --verbose
        --no-progress
        --max-retries 2
        --timeout 20
        --accept 200,204,206,429
        --exclude '^http://127\\.0\\.0\\.1(:[0-9]+)?/'
        './README.md'
        './docs/**/*.md'
        './build/public-site/**/*.html'
```

Pin the reusable workflow to a reviewed immutable commit SHA or a deliberately managed release tag. Do not consume a floating development branch in release-critical repositories.

## Consumer-owned contract

Each consumer remains responsible for:

- triggering the workflow on the correct branches and path filters;
- generating the exact candidate bytes that would be published;
- a deterministic candidate validator when the project has machine contracts;
- `package.json` with pinned web-QA dependencies;
- `playwright.config.*` with the intended browser/device matrix;
- local Playwright specs for required routes and critical user journeys;
- axe assertions and accessibility semantics relevant to that application;
- 320 CSS-pixel reflow/overflow checks where the profile requires them;
- theme assertions when Light/Dark/System behavior is part of the UI contract;
- `lighthouserc.*` routes and thresholds when Lighthouse is applicable;
- Lychee exclusions and paths appropriate to the repository;
- separate post-deployment smoke against the real production URL.

The common pilot baseline used desktop Chromium, Firefox, and WebKit plus Android-Chromium and iPhone-WebKit projects. A consumer may use a lighter profile only when its governing policy explicitly permits one.

## Shared mechanics

The reusable workflow provides:

1. SHA-pinned source checkout with persisted credentials disabled;
2. Node setup;
3. candidate build command;
4. optional deterministic candidate validation;
5. consumer dependency installation;
6. Playwright Chromium/Firefox/WebKit engine installation;
7. consumer Playwright/axe execution;
8. Chromium resolution for Lighthouse;
9. optional consumer Lighthouse execution;
10. SHA-pinned Lychee link validation;
11. uploaded Playwright/Lighthouse/Lychee evidence.

The workflow runs with `contents: read` and requires no private-repository credentials or organization-brand governance access.

## Important Pages lesson: base-path containment

GitHub Pages project sites live below a project base path, for example:

```text
https://example-org.github.io/project/
```

A same-origin browser assertion is insufficient: navigation can accidentally escape `/project/` to the organization root while remaining on the same origin. Project-local browser tests and deployed smoke must therefore assert both the expected origin **and** the expected project base path.

## Accessibility boundary

Automated axe and Lighthouse results are evidence, not accessibility certification. Projects targeting WCAG 2.2 AA / Revised Section 508 alignment still require appropriate manual review for keyboard behavior, zoom/reflow, semantics/screen-reader behavior, forced colors/high contrast, and other material interaction changes.

## Stable-tool boundary

This lab is an extraction and validation home. If the reusable workflow becomes a broadly consumed product with an independent lifecycle, graduate it to an appropriate durable public repository rather than turning `github-ops-lab` into a general-purpose product monorepo.
