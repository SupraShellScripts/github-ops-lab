import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const routes = ['/', '/accessibility/'];

async function assertNoHorizontalOverflow(page, label) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, `${label} must not overflow horizontally`).toBeLessThanOrEqual(1);
}

async function assertA11y(page, label) {
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22a', 'wcag22aa'])
    .analyze();
  expect(results.violations, `${label} axe violations: ${results.violations.map(v => v.id).join(', ')}`).toEqual([]);
}

for (const route of routes) {
  test(`${route} is a complete accessible candidate route`, async ({ page }, testInfo) => {
    const consoleErrors = [];
    const pageErrors = [];
    page.on('console', message => {
      if (message.type() === 'error') consoleErrors.push(message.text());
    });
    page.on('pageerror', error => pageErrors.push(String(error)));

    const response = await page.goto(route, { waitUntil: 'networkidle' });
    expect(response?.status()).toBeLessThan(400);
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await expect(page.locator('h1')).toHaveCount(1);
    await expect(page.locator('nav[aria-label="Primary"]')).toHaveCount(1);
    await expect(page.locator('main#main-content')).toHaveCount(1);
    await expect(page.locator('[aria-current="page"]')).toHaveCount(1);
    await expect(page.locator('#theme-select')).toHaveCount(1);
    await expect(page.locator('a.skip[href="#main-content"]')).toHaveCount(1);
    await assertNoHorizontalOverflow(page, `${testInfo.project.name} ${route}`);
    await assertA11y(page, `${testInfo.project.name} ${route}`);
    expect(pageErrors).toEqual([]);
    expect(consoleErrors).toEqual([]);
  });
}

test('consumer-owned primary journey works', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('link', { name: 'Review accessibility notes' }).click();
  await expect(page).toHaveURL(/\/accessibility\/$/);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Accessibility');
});

test('consumer-owned theme contract persists explicit choices', async ({ page }) => {
  await page.goto('/');
  await page.evaluate(() => localStorage.removeItem('selftest-theme'));
  await page.emulateMedia({ colorScheme: 'light' });
  await page.reload();

  const selector = page.locator('#theme-select');
  await expect(selector).toHaveValue('system');
  await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute('data-effective-theme', 'light');

  await selector.selectOption('dark');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.reload();
  await expect(selector).toHaveValue('dark');

  await selector.selectOption('system');
  await expect(page.locator('html')).not.toHaveAttribute('data-theme', /.+/);
  await page.emulateMedia({ colorScheme: 'dark' });
  await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute('data-effective-theme', 'dark');
});

test('320px reflow remains usable', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  for (const route of routes) {
    await page.goto(route, { waitUntil: 'networkidle' });
    await assertNoHorizontalOverflow(page, `320px ${route}`);
    for (const locator of [page.getByRole('link', { name: 'Home' }), page.getByRole('link', { name: 'Accessibility' }), page.locator('#theme-select')]) {
      await expect(locator).toBeVisible();
    }
  }
});

test('desktop keyboard users can skip directly to main content', async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith('desktop-'), 'desktop keyboard check');
  await page.goto('/');
  await page.evaluate(() => document.activeElement?.blur());
  await page.keyboard.press('Tab');
  await expect(page.locator('.skip')).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('#main-content')).toBeFocused();
});
