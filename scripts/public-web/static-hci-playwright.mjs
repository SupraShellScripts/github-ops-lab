const defaultGenericStandaloneName = /^(?:click here|here|more|read more|learn more|link|button|open)$/i;

function requireSelector(selector, name) {
  if (typeof selector !== 'string' || selector.trim() === '') {
    throw new TypeError(`${name} must be a non-empty selector string`);
  }
  return selector;
}

export async function assertDocumentStructure({
  page,
  expect,
  label = 'page',
  titlePattern = null,
  standaloneActionSelector = 'a[href], button',
  genericStandaloneName = defaultGenericStandaloneName,
}) {
  const title = (await page.title()).trim();
  expect(title.length, `${label} needs a descriptive document title`).toBeGreaterThanOrEqual(4);
  if (titlePattern) expect(title, `${label} document title`).toMatch(titlePattern);

  const h1 = page.locator('h1');
  await expect(h1, `${label} should have one page-purpose heading`).toHaveCount(1);
  expect((await h1.textContent())?.trim().length || 0, `${label} H1 should not be empty`).toBeGreaterThanOrEqual(3);

  const headings = await page.locator('h1,h2,h3,h4,h5,h6').evaluateAll(nodes => nodes.map(node => Number(node.tagName.slice(1))));
  for (let index = 1; index < headings.length; index += 1) {
    expect(headings[index] - headings[index - 1], `${label} heading levels should not skip downward`).toBeLessThanOrEqual(1);
  }

  const standaloneActions = page.locator(standaloneActionSelector);
  for (let index = 0; index < await standaloneActions.count(); index += 1) {
    const name = await standaloneActions.nth(index).evaluate(node => {
      const explicit = node.getAttribute('aria-label')?.trim();
      return (explicit || node.textContent || '').replace(/\s+/g, ' ').trim();
    });
    expect(name.length, `${label} standalone action ${index} should not be unnamed`).toBeGreaterThan(0);
    expect(genericStandaloneName.test(name), `${label} standalone action ${index} should not use a context-free generic label: ${name}`).toBe(false);
  }
}

export async function assertPrimaryTargets({
  page,
  expect,
  selector,
  label = 'page',
  minimumCssPixels = 44,
}) {
  const primarySelector = requireSelector(selector, 'selector');
  const controls = page.locator(primarySelector);
  expect(await controls.count(), `${label} should expose declared primary controls`).toBeGreaterThan(0);

  for (let index = 0; index < await controls.count(); index += 1) {
    const control = controls.nth(index);
    await expect(control, `${label} primary control ${index}`).toBeVisible();
    const geometry = await control.evaluate(node => {
      const rect = node.getBoundingClientRect();
      return { width: rect.width, height: rect.height };
    });
    expect(geometry.width, `${label} primary control ${index} width`).toBeGreaterThanOrEqual(minimumCssPixels);
    expect(geometry.height, `${label} primary control ${index} height`).toBeGreaterThanOrEqual(minimumCssPixels);
  }
}

export async function assertKeyboardFocusPath({
  page,
  expect,
  selector,
  label = 'page',
  minimumTabBudget = 24,
  tabBudgetMultiplier = 3,
  convergenceTimeoutMs = 5000,
}) {
  const keyboardPrimarySelector = requireSelector(selector, 'selector');
  const expected = await page.locator(keyboardPrimarySelector).count();
  expect(expected, `${label} should expose keyboard-primary controls`).toBeGreaterThan(0);

  await page.evaluate(() => {
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    window.scrollTo(0, 0);
  });

  const seen = new Set();
  const maxTabs = Math.max(minimumTabBudget, expected * tabBudgetMultiplier);
  for (let tabIndex = 0; tabIndex < maxTabs && seen.size < expected; tabIndex += 1) {
    await page.keyboard.press('Tab');

    const focused = await page.evaluate(selectorValue => {
      const nodes = [...document.querySelectorAll(selectorValue)];
      const ordinal = nodes.indexOf(document.activeElement);
      if (ordinal < 0) return { primary: false, ordinal: -1, description: '' };
      const node = nodes[ordinal];
      const text = (node.getAttribute('aria-label') || node.textContent || '').replace(/\s+/g, ' ').trim();
      return {
        primary: true,
        ordinal,
        description: [node.tagName, node.getAttribute('href') || '', node.getAttribute('name') || '', node.getAttribute('value') || '', text].join('|'),
      };
    }, keyboardPrimarySelector);

    if (!focused.primary) continue;

    await expect.poll(async () => page.evaluate(({ selectorValue, ordinal }) => {
      const nodes = [...document.querySelectorAll(selectorValue)];
      const node = nodes[ordinal];
      if (!(node instanceof HTMLElement) || document.activeElement !== node) return false;

      const rect = node.getBoundingClientRect();
      const left = Math.max(rect.left, 0);
      const right = Math.min(rect.right, innerWidth);
      const top = Math.max(rect.top, 0);
      const bottom = Math.min(rect.bottom, innerHeight);
      return right > left && bottom > top;
    }, { selectorValue: keyboardPrimarySelector, ordinal: focused.ordinal }), {
      message: `${label} keyboard-focused ${focused.description} must become visible through browser-owned focus/scroll handling`,
      timeout: convergenceTimeoutMs,
    }).toBe(true);

    const obscured = await page.evaluate(({ selectorValue, ordinal }) => {
      const nodes = [...document.querySelectorAll(selectorValue)];
      const node = nodes[ordinal];
      if (!(node instanceof HTMLElement) || document.activeElement !== node) return true;

      const rect = node.getBoundingClientRect();
      const left = Math.max(rect.left, 0);
      const right = Math.min(rect.right, innerWidth);
      const top = Math.max(rect.top, 0);
      const bottom = Math.min(rect.bottom, innerHeight);
      if (right <= left || bottom <= top) return true;

      const x = (left + right) / 2;
      const y = (top + bottom) / 2;
      const topElement = document.elementFromPoint(x, y);
      return Boolean(topElement && topElement !== node && !node.contains(topElement) && !topElement.contains(node));
    }, { selectorValue: keyboardPrimarySelector, ordinal: focused.ordinal });

    expect(obscured, `${label} keyboard-focused ${focused.description} must not be obscured at its visible center`).toBe(false);
    seen.add(focused.ordinal);
  }

  expect(seen.size, `${label} keyboard traversal should reach every declared primary tab stop`).toBe(expected);
}

export async function assertSvgGeometry({
  page,
  expect,
  selector,
  label = 'page',
  expectedViewBox = null,
  intendedAspectRatio = 1,
  aspectTolerance = 0.05,
}) {
  const svgSelector = requireSelector(selector, 'selector');
  const icons = page.locator(svgSelector);
  expect(await icons.count(), `${label} should expose declared SVG graphics`).toBeGreaterThan(0);

  for (let index = 0; index < await icons.count(); index += 1) {
    const icon = icons.nth(index);
    if (expectedViewBox !== null) {
      await expect(icon, `${label} SVG ${index} viewBox`).toHaveAttribute('viewBox', expectedViewBox);
    } else {
      const viewBox = await icon.getAttribute('viewBox');
      expect(Boolean(viewBox?.trim()), `${label} SVG ${index} needs a usable viewBox`).toBe(true);
    }

    const geometry = await icon.evaluate(node => {
      const rect = node.getBoundingClientRect();
      return { width: rect.width, height: rect.height };
    });
    expect(geometry.width, `${label} SVG ${index} rendered width`).toBeGreaterThan(0);
    expect(geometry.height, `${label} SVG ${index} rendered height`).toBeGreaterThan(0);
    expect(
      Math.abs(geometry.width / geometry.height - intendedAspectRatio),
      `${label} SVG ${index} should preserve its intended aspect ratio`,
    ).toBeLessThan(aspectTolerance);
  }
}
