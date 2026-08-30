# Public-surface model and discovery conformance

`validate-surface-contract.py` is a public-safe, dependency-free validator for the cheap deterministic portion of `GOV-WEB-001` public-surface conformance.

It does **not** replace Playwright, axe, Lighthouse, Lychee, or project-specific journey tests. Its job is to reject structurally inconsistent candidate surfaces before expensive browser execution.

## Separation of responsibility

The consumer repository owns:

- route/state identities;
- critical flow transitions;
- global/utility navigation actions;
- same-site machine/resource endpoints exposed as links;
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
    },
    {
      "action": "skip-main",
      "class": "utility",
      "to": "$self"
    }
  ],
  "resources": [
    {
      "action": "machine-project",
      "path": "/surface.json",
      "required_on": ["home"]
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

### Production identity versus candidate navigation identity

`production_base_url` is the canonical/indexing identity. It is **not** assumed to be the URL used by the local candidate server.

For example, Bridge can be generated with canonical URLs under:

```text
https://supracraft.github.io/Bridge/
```

while browser qualification serves the exact candidate at:

```text
http://127.0.0.1:4173/
```

Pass that ephemeral candidate identity with:

```text
--navigation-base http://127.0.0.1:4173/
```

The validator uses the production base for canonical/Sitemap/robots checks and the navigation base for rendered internal-link/resource containment and route resolution. This separation prevents a correct candidate from being rejected merely because it is being tested before publication.

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
- `navigation` — global or utility human navigation;
- `resources` — same-site machine/resource endpoints such as `project.json`, `stable.json`, or other linked deterministic interfaces;
- `handoffs` — approved external exits/references;
- `exceptions` — narrow documented exceptions with a reason.

A link/action that is rendered but unclassified fails validation.

#### Navigation and `$self`

By default, each declared `navigation` action is required on every required route. A project can narrow that requirement:

```json
{
  "action": "nav-releases",
  "class": "global",
  "to": "releases",
  "required_on": ["home", "guide", "releases"]
}
```

or mark the navigation declaration as classification-only:

```json
"required_on": false
```

Utility links that remain on the current route, such as a skip link, use the special target `$self`:

```json
{
  "action": "skip-main",
  "class": "utility",
  "to": "$self"
}
```

A `$self` utility link proves the utility action exists, but it does **not** satisfy the recovery requirement for a non-terminal route. Required non-terminal routes must render at least one valid internal transition/navigation edge to another route/state.

#### Same-site machine resources

Machine/resource links are intentionally not modeled as human route states merely because they are clickable. Declare an exact project-relative path:

```json
{
  "action": "machine-project",
  "path": "/project.json"
}
```

or a project-relative prefix:

```json
{
  "action": "machine-release-data",
  "path_prefix": "/releases/"
}
```

`resources` are classification-only by default. Use `required_on` when a particular human route is contractually required to expose that machine interface.

This distinction prevents ordinary machine endpoints from being mislabeled as exceptions and keeps the human flow graph focused on human states and journeys.

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

When `discovery.machine_description` is declared, the candidate must contain that machine-description resource and each rendered human route must advertise it with a `describedby` relation, for example:

```html
<link rel="describedby" href="../surface.json">
```

The validator resolves the relation against the route's production canonical URL.

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

The validator rejects a declared internal action/resource that exits the candidate site and a declared external handoff that unexpectedly stays on the candidate origin.

## Usage

```bash
python3 scripts/public-web/validate-surface-contract.py \
  --contract ./PUBLIC_SURFACE.json \
  --site-dir ./build/public-site \
  --navigation-base http://127.0.0.1:4173/ \
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
- production canonical base URL and candidate navigation base URL;
- route and expected-transition counts;
- observed classified human edges;
- observed same-site machine/resources;
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
- turn every linked machine endpoint into a human flow state;
- infer actions from CSS/pixel position/visible copy;
- execute JavaScript;
- certify WCAG compliance;
- replace accessibility review;
- replace Lychee resource integrity;
- publish IndexNow notifications;
- maintain a central route registry;
- depend on private brand governance;
- implement crawler-specific cloaking or speculative bot lists.
