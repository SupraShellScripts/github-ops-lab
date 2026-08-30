# Reusable static-HCI Playwright assertions

`scripts/public-web/static-hci-playwright.mjs` contains the small automation-only HCI subset proven across two independent SupraCraft public-site consumers.

It is intentionally a helper for a consumer's existing Playwright suite, not a second browser harness and not a product design system. Routes, selectors, critical journeys, tooltip behavior, branding, and application semantics remain consumer-owned.

## Proven common assertions

The helper exports:

- `assertDocumentStructure` — descriptive title, one non-empty page-purpose H1, non-skipping downward heading hierarchy, and a narrow check against empty/context-free standalone action names;
- `assertPrimaryTargets` — rendered target-box checks for consumer-declared primary controls, with 44 CSS pixels as the current default project target;
- `assertKeyboardFocusPath` — actual `Tab` traversal across consumer-declared critical controls, viewport convergence through browser-owned focus/scroll behavior, then visible-center obstruction checking;
- `assertSvgGeometry` — usable `viewBox`, non-zero rendered dimensions, and intended aspect-ratio checking for consumer-declared SVG graphics.

Consumers choose applicability explicitly. Do not point the target-size assertion at every inline prose link, and do not invent an SVG requirement for a surface that has no applicable scalable control graphics.

## Keyboard/focus invariant

The keyboard helper preserves the input modality it claims to test. It sends real Playwright keyboard `Tab` input and never calls `focus()`, `scrollIntoView()`, or synthetic scrolling to make a control pass.

A real focus transfer can trigger asynchronous browser-owned scrolling, especially when a surface uses `scroll-behavior: smooth`. Chromium and WebKit may therefore report the newly focused control before its normal focus scroll has converged. The helper waits for the **same still-focused declared control** to intersect the viewport, then checks that its visible center is not obscured. This is a state-convergence wait, not a substitute interaction.

The helper deliberately does not treat mobile device emulation as proof of OS-level external-keyboard scrolling. Consumers should invoke keyboard-path checks only in browser profiles that actually model the keyboard behavior being claimed; a narrow desktop viewport is appropriate when the requirement is keyboard behavior under responsive layout.

## Consumer pattern

Pin the helper to a reviewed immutable `github-ops-lab` revision, place that exact file in a repository-local CI/helper location, and import it from the consumer's existing Playwright spec. For example:

```js
import { test, expect } from '@playwright/test';
import {
  assertDocumentStructure,
  assertKeyboardFocusPath,
  assertPrimaryTargets,
  assertSvgGeometry,
} from '../.ci/static-hci-playwright.mjs';

test('homepage satisfies shared static HCI invariants', async ({ page }, testInfo) => {
  await page.goto('/');

  await assertDocumentStructure({
    page,
    expect,
    label: `${testInfo.project.name} homepage`,
  });

  await assertPrimaryTargets({
    page,
    expect,
    selector: '.declared-primary-control',
    label: `${testInfo.project.name} homepage`,
  });
});
```

Keyboard evidence remains a separate applicability decision:

```js
test('narrow desktop keyboard path remains reachable', async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith('desktop-'));
  await page.setViewportSize({ width: 320, height: 800 });
  await page.goto('/');

  await assertKeyboardFocusPath({
    page,
    expect,
    selector: '.declared-keyboard-primary',
    label: `${testInfo.project.name} 320px homepage`,
  });
});
```

The fetched helper revision is part of release-readiness evidence and should be visible in the consumer workflow or repository-local pin so later runs can be reproduced.

## Two-consumer provenance

### SupraCraft/Bridge

- pilot PR `#51`;
- qualified head `47246d3f9f61ca82d5bc5608fffaa2def375cd85`;
- merged production revision `6ab755cda7a4b4cc03f132f1c2b6345c72ea9afd`;
- production Pages run `33299901550`;
- validator lesson tracked in Bridge issue `#52`.

Bridge established that programmatic focus/mobile emulation must not be substituted for actual keyboard-modality evidence.

### SupraCraft/VanillaCord

- pilot PR `#61`;
- first rebased candidate `0356046a3c0478e0b386524b64aea3d72dbb7efe`;
- readiness run `33306063467` exposed the same-turn smooth focus-scroll timing assumption in Chromium/WebKit;
- corrected qualified head `8e77e4e8782c406231cc15fc68c4069715760b59`;
- merged production revision `c4b4c5c6aace99b936d9b68576b49c32d9775338`;
- post-merge readiness run `33307252201`;
- production Pages run `33307252171`.

VanillaCord independently reproduced the shared invariants and refined the keyboard helper to wait for native focus-scroll convergence before geometry measurement.

## Self-test

The existing public-site-readiness self-test imports this helper directly. Its synthetic fixture deliberately uses smooth scrolling and places a declared keyboard target below the initial 320px desktop viewport. The Playwright matrix therefore regression-tests the timing boundary that the second consumer exposed rather than merely testing a page where every focus target is already visible.

Keep product-specific selectors and behavior out of this helper. Add a new generic assertion only after it has objective semantics and independent consumer evidence.
