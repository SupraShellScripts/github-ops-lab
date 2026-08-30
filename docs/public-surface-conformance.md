# Public-surface model and discovery conformance

`validate-surface-contract.py` is a public-safe, dependency-free validator for the cheap deterministic portion of `GOV-WEB-001` public-surface conformance.

It does **not** replace Playwright, axe, Lighthouse, Lychee, deployed smoke, or project-specific journey tests. Its job is to reject structurally inconsistent candidate surfaces before expensive browser execution.

## Separation of responsibility

The consumer repository owns:

- route/state identities;
- critical flow transitions;
- global/utility navigation actions;
- same-site machine/resource endpoints exposed as links;
- approved external handoffs;
- indexability decisions;
- canonical production identity;
- crawler-policy applicability/authority;
- generated candidate bytes;
- browser-executed JavaScript transitions and critical user journeys.

The reusable validator owns generic checks over those declared inputs.

The intended order is:

```text
consumer contract + generated candidate bytes
        -> static/model/discovery validator
        -> Playwright/axe
        -> Lighthouse/Lychee as applicable
        -> deployment
        -> deployed smoke/live authority checks
```

## Contract schema

Current schema:

```text
public-surface-contract/1
```

A subpath-hosted example:

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
    "robots": {
      "mode": "origin-external",
      "url": "https://example.org/robots.txt"
    },
    "machine_description": "surface.json"
  }
}
```

## Route identity

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

This prevents GitHub Pages project sites from being accidentally treated as origin-root sites.

## Production identity versus candidate navigation identity

`production_base_url` is the canonical/indexing identity. It is not assumed to be the address used by the local candidate server.

For example, candidate bytes may carry canonical URLs under:

```text
https://supracraft.github.io/Bridge/
```

while qualification serves those exact bytes at:

```text
http://127.0.0.1:4173/
```

Pass the candidate navigation identity explicitly:

```bash
--navigation-base http://127.0.0.1:4173/
```

The validator uses:

- the **production base** for canonical URLs and Sitemap entries;
- the **candidate navigation base** for rendered internal navigation, same-site resources, and candidate `describedby` resolution.

This ensures pre-deployment qualification validates the candidate rather than yesterday's deployed surface.

## Rendered state/action identifiers

A rendered human page declares its state identity:

```html
<main data-surface-state="home">
```

Rendered interactive links/actions use stable supplemental identifiers:

```html
<a href="guide/" data-surface-action="open-guide">Guide</a>
```

These attributes do not replace native HTML, visible labels, accessible names, ARIA semantics, or keyboard behavior. They exist to make the same interface understandable to deterministic automation and agents without reverse-engineering CSS or position.

When this validator is applied, every rendered anchor with `href` and every rendered button must be classified by `data-surface-action`.

## Action classes

A rendered action resolves to exactly one class:

- `transitions` — declared human-flow edges;
- `navigation` — global or utility human navigation;
- `resources` — linked same-site machine/resource endpoints;
- `handoffs` — approved external exits/references;
- `exceptions` — narrow documented exceptions with a reason.

Rendered-but-unclassified actions fail validation.

### Navigation and `$self`

By default, declared navigation is expected on all required routes. `required_on` may narrow the set, or `false` may make a declaration classification-only.

Same-page utility actions such as a skip link use `$self`:

```json
{
  "action": "skip-main",
  "class": "utility",
  "to": "$self"
}
```

A `$self` action proves that utility behavior exists but does not satisfy the recovery requirement for a non-terminal state. A required non-terminal route must expose a valid continuation/recovery edge to another route/state.

### Same-site machine resources

Machine endpoints remain distinct from human-flow states. Declare an exact project-relative path:

```json
{
  "action": "machine-project",
  "path": "/project.json"
}
```

or prefix:

```json
{
  "action": "machine-release-data",
  "path_prefix": "/releases/"
}
```

Resources are classification-only by default. `required_on` makes exposure from specific human routes part of the contract.

### Browser-required actions

A transition that cannot be proven statically can declare:

```json
{
  "from": "home",
  "action": "open-dialog",
  "to": "dialog",
  "browser_required": true
}
```

The validator records that browser evidence is required; consumer-owned Playwright remains authoritative for execution.

## Discovery checks

For each declared indexable human route, the validator requires:

- candidate HTML exists;
- exactly one matching `data-surface-state`;
- exact expected `<title>`;
- exactly one canonical URL matching the production identity;
- no accidental `noindex`;
- presence in `sitemap.xml`.

The Sitemap must contain exactly the declared indexable canonical routes.

### Truthful `lastmod`

`lastmod` is optional. If a route declares an authoritative value, the Sitemap must contain that exact value. If the route does not declare one, the Sitemap must not invent one from build time.

This keeps source/content history separate from CI wall-clock time.

## robots.txt authority

Robots Exclusion Protocol authority is origin-scoped, so the contract makes ownership explicit instead of assuming every project can generate a meaningful project-local file.

### Origin-root surface: `local`

A site that owns the origin root may validate its candidate `/robots.txt`:

```json
"robots": {
  "mode": "local",
  "path": "robots.txt"
}
```

`local` is valid only when `production_base_url` is the origin root, such as:

```text
https://example.org/
```

The validator checks that candidate `robots.txt` advertises the canonical Sitemap and does not globally disallow `User-agent: *`.

### Shared-origin/subpath surface: `origin-external`

A project site such as:

```text
https://supracraft.github.io/Bridge/
```

does not own:

```text
https://supracraft.github.io/robots.txt
```

It must therefore declare origin-level authority explicitly:

```json
"robots": {
  "mode": "origin-external",
  "url": "https://supracraft.github.io/robots.txt"
}
```

Candidate validation verifies that the declared URL is exactly the production origin's `/robots.txt`, then records robots verification as `deferred-live`. The actual origin policy belongs in deployed/live verification or in the repository that owns the origin-root site.

Do **not** generate `/Bridge/robots.txt` and call it the site's REP authority; a tidy but non-authoritative file is worse than an explicit applicability boundary.

Crawler-specific policy remains project-owned data and should use identities published by authoritative providers rather than speculative bot lists.

## Machine-description discovery

When `discovery.machine_description` is declared, the candidate must contain it and every rendered human route must advertise it with a `describedby` relation:

```html
<link rel="describedby" href="../surface.json">
```

During candidate qualification this resolves against the candidate page/navigation base, proving the candidate's own machine description. In production the same relative relation resolves under the production project base.

## External handoffs

A handoff can require an exact URL or a URL prefix. When a handoff identity is declared, rendered HTML must expose the matching `data-surface-handoff` value.

The validator rejects internal transitions/resources that escape the candidate site and external handoffs that unexpectedly remain inside it.

## Usage

```bash
python3 scripts/public-web/validate-surface-contract.py \
  --contract ./PUBLIC_SURFACE.json \
  --site-dir ./build/public-site \
  --navigation-base http://127.0.0.1:4173/ \
  --evidence ./build/public-surface-conformance.json
```

A consumer of `.github/workflows/public-site-readiness.yml` may invoke this from its deterministic `validate_command` or as a separate pinned read-only step. Project browser tests remain local.

## Evidence

Current schema:

```text
public-surface-conformance-evidence/1
```

Evidence includes:

- contract schema;
- production base and candidate navigation base;
- route and expected-transition counts;
- observed classified human edges;
- observed same-site machine resources;
- browser-required actions;
- approved external handoffs;
- Sitemap inventory;
- robots authority mode, URL, and whether verification is candidate or deferred-live;
- warnings/errors;
- overall deterministic verdict.

Consumers should bind this evidence to exact consumer source and immutable validator identities in surrounding CI/provenance.

## R4 properties

The validator is:

- **reproducible** — exact candidate + contract + validator revision determine the verdict;
- **repeatable** — a fresh actor can rerun it without session state;
- **reversible** — it is read-only, so no rollback is required;
- **idempotent** — unchanged inputs produce the same assessment/verdict.

Future production mutations such as IndexNow remain separate `Discover -> Plan -> Act -> Verify` mechanisms with deduplication, receipts, and post-action verification.

## Non-goals

This validator does not:

- decide project routes or critical journeys;
- turn every machine endpoint into a human state;
- infer actions from CSS, pixels, or visible copy;
- execute JavaScript;
- certify WCAG conformance;
- replace accessibility review;
- replace Lychee resource integrity;
- publish IndexNow notifications;
- maintain a central route registry;
- depend on private brand governance;
- implement crawler-specific cloaking or speculative bot lists.
