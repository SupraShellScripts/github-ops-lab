# Public-surface model and discovery conformance

`validate-surface-contract.py` is a public-safe, dependency-free validator for the cheap deterministic portion of `GOV-WEB-001` public-surface conformance.

It does **not** replace Playwright, axe, Lighthouse, Lychee, or project-specific journey tests. Its job is to reject structurally inconsistent candidate surfaces before expensive browser execution.

## Separation of responsibility

The consumer repository owns:

- route/state identities;
- critical flow transitions;
- global/utility navigation actions;
- approved external handoffs;
- indexability decisions;
- canonical production base URL;
- generated candidate bytes;
- browser-executed JS transitions and critical user journeys.

This reusable validator owns only generic checks over those declared inputs.

The intended ordering is:

```text
consumer contract + generated candidate bytes
        -> static/model/discovery validator
        -> Playwright/axe
        -> Lighthouse/Lychee as applicable
        -> deployment
        -> deployed smoke
```

## Contract schema

Current schema:

```text
public-surface-contract/1
```

Minimal example:

```json
{
  "schema": "public-surface-contract/1",
  "production_base_url": "https://example.org/project/",
  "entry_states": ["home"],
  "routes": [
    {
      "id": "home",
      "path": "/",
      "title": "Example Project",
      "indexable": true,
      "required": true,
      "terminal": false
    },
    {
      "id": "guide",
      "path": "/guide/",
      "title": "Example Project Guide",
      "indexable": true,
      "required": true,
      "terminal": false
    }
  ],
  "transitions": [
    {
      "from": "home",
      "action": "open-guide",
      "to": "guide",
      "required_rendered": true
    }
  ],
  "navigation": [
    {
      "action": "nav-home",
      "class": "global",
      "to": "home"
    }
  ],
  "handoffs": [
    {
      "action": "view-source",
      "handoff": "source",
      "url_prefix": "https://github.com/example/"
    }
  ],
  "discovery": {
    "sitemap": "sitemap.xml",
    "robots": "robots.txt",
    "machine_description": "surface.json"
  }
}
```

### Route paths

`routes[].path` is relative to the declared project-site root even though it starts with `/`.

For:

```text
production_base_url = https://example.org/project/
path                = /guide/
```

the canonical production URL is:

```text
https://example.org/project/guide/
```

This avoids treating GitHub Pages project sites as origin-root sites.

### Rendered state/action identifiers

The rendered page declares its route/state identity:

```html
<main data-surface-state="home">
```

Rendered interactive links/actions receive a stable identifier:

```html
<a href="guide/" data-surface-action="open-guide">Guide</a>
```

These attributes are **supplemental machine identifiers**. They do not replace native HTML elements, accessible names, ARIA semantics, visible labels, or keyboard behavior.

Every rendered anchor with an `href` and every rendered button is expected to have a `data-surface-action` classification when this validator is applied.

### Action classes

A rendered action must resolve to exactly one class:

- `transitions` — a declared flow edge from one route/state to another;
- `navigation` with class `global` or `utility`;
- `handoffs` — approved external exits/references;
- `exceptions` — narrow documented exceptions with a reason.

A link/action that is rendered but unclassified fails validation.

### Browser-required actions

A JS-only action can be declared:

```json
{
  "from": "home",
  "action": "open-dialog",
  "to": "dialog",
  "browser_required": true
}
```

The static validator records the action as requiring browser evidence rather than pretending to execute JavaScript. The consumer's Playwright suite remains authoritative for the actual transition.

## Discovery checks

For each declared indexable route, the validator requires:

- candidate HTML exists;
- exactly one matching `data-surface-state`;
- exact expected `<title>`;
- exactly one canonical link matching the production URL;
- no accidental `noindex`;
- inclusion in `sitemap.xml`.

The sitemap must contain exactly the declared indexable canonical routes.

### `lastmod`

`lastmod` is optional.

When a route declares:

```json
"lastmod": "2026-08-30"
```

the sitemap must contain that exact value.

When the route does **not** declare `lastmod`, the sitemap must not invent one. This prevents build-wall-clock timestamps from masquerading as content modification history.

### robots.txt

The validator requires `robots.txt` to advertise the canonical sitemap URL and rejects a `User-agent: *` rule that blocks the entire origin or declared project base path.

This is intentionally conservative. Crawler-specific policies remain project-owned data and should come only from authoritative provider documentation.

### machine-description discovery

When `discovery.machine_description` is declared, each rendered route must advertise it with a `describedby` relation, for example:

```html
<link rel="describedby" href="../surface.json">
```

The validator resolves the link against the route canonical URL.

## External handoffs

A handoff may require an exact URL:

```json
{
  "action": "download-release",
  "handoff": "artifact-download",
  "url": "https://example.net/exact-artifact.jar"
}
```

or a prefix:

```json
{
  "action": "view-source",
  "handoff": "source",
  "url_prefix": "https://github.com/example/project"
}
```

When `handoff` is declared, rendered HTML must also expose the matching `data-surface-handoff` value.

The validator rejects a declared internal action that exits the site and a declared external handoff that unexpectedly stays on the same origin.

## Usage

```bash
python3 scripts/public-web/validate-surface-contract.py \
  --contract ./PUBLIC_SURFACE.json \
  --site-dir ./build/public-site \
  --evidence ./build/public-surface-conformance.json
```

Exit status is nonzero on failure. Evidence is deterministic for unchanged contract/candidate inputs except for external run metadata supplied separately by a caller.

A consumer using `.github/workflows/public-site-readiness.yml` can invoke this from its existing deterministic `validate_command`, or pin/download the script as a separate read-only step. Project browser tests remain local.

## Evidence format

Current evidence schema:

```text
public-surface-conformance-evidence/1
```

It records:

- contract schema;
- production base URL;
- route and expected-transition counts;
- observed classified edges;
- browser-required actions;
- approved observed external handoffs;
- sitemap route inventory;
- warnings/errors;
- overall verdict.

Consumers should bind the evidence to their exact source revision and the immutable validator revision in their surrounding CI/provenance record.

## R4 properties

The validator is:

- **reproducible** — exact candidate + exact contract + exact validator revision determine the verdict;
- **repeatable** — it can be rerun by a fresh actor without chat/session state;
- **reversible** — read-only, so no rollback is required;
- **idempotent** — unchanged inputs yield the same state assessment/verdict.

Any later production mutation such as IndexNow notification should remain a separate `Discover -> Plan -> Act -> Verify` mechanism with deduplication, receipts, and post-action verification.

## Non-goals

This validator does not:

- decide project routes or critical journeys;
- infer actions from CSS/pixel position/visible copy;
- execute JavaScript;
- certify WCAG compliance;
- replace accessibility review;
- replace Lychee resource integrity;
- publish IndexNow notifications;
- maintain a central route registry;
- depend on private brand governance;
- implement crawler-specific cloaking or speculative bot lists.
