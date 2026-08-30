import { test, expect } from '@playwright/test';
import {
  assertDocumentStructure,
  assertKeyboardFocusPath,
  assertPrimaryTargets,
  assertSvgGeometry,
} from '../../../../../scripts/public-web/static-hci-playwright.mjs';

for (const route of ['/', '/accessibility/']) {
  test(`${route} satisfies shared static-HCI structure and target invariants`, async ({ page }, testInfo) => {
    const response = await page.goto(route, { waitUntil: 'networkidle' });
    expect(response?.status()).toBeLessThan(400);

    await assertDocumentStructure({
      page,
      expect,
      label: `${testInfo.project.name} ${route}`,
      titlePattern: /(?:self-test|Accessibility)/i,
    });

    await assertPrimaryTargets({
      page,
      expect,
      selector: 'nav a, #theme-select',
      label: `${testInfo.project.name} ${route}`,
    });
  });
}

test('shared SVG geometry helper validates scalable control graphics', async ({ page }) => {
  await page.goto('/');
  await assertSvgGeometry({
    page,
    expect,
    selector: '.hci-icon',
    label: 'self-test homepage',
    expectedViewBox: '0 0 24 24',
  });
});

test('shared keyboard helper waits for browser-owned smooth focus scrolling at 320px', async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith('desktop-'), 'keyboard behavior requires a keyboard-capable browser profile');
  await page.setViewportSize({ width: 320, height: 800 });
  await page.goto('/', { waitUntil: 'networkidle' });

  await assertKeyboardFocusPath({
    page,
    expect,
    selector: 'nav a, #theme-select, a.hci-primary',
    label: `${testInfo.project.name} 320px smooth-focus fixture`,
  });
});
