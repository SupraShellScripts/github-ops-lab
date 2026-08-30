import fs from 'node:fs';
import path from 'node:path';

const out = path.resolve('build/public-site');
fs.rmSync(out, { recursive: true, force: true });
fs.mkdirSync(path.join(out, 'accessibility'), { recursive: true });

const shell = ({ title, heading, body, current }) => `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#ffffff" data-effective-theme="light">
  <title>${title}</title>
  <style>
    :root { color-scheme: light dark; font-family: system-ui, sans-serif; }
    body { margin: 0; line-height: 1.5; }
    .skip { position: absolute; left: .5rem; top: -4rem; padding: .75rem; background: Canvas; color: CanvasText; }
    .skip:focus { top: .5rem; }
    header, main, footer { max-width: 60rem; margin: auto; padding: 1rem; }
    nav { display: flex; flex-wrap: wrap; gap: .75rem; align-items: center; }
    a, select { min-height: 2rem; }
    main:focus { outline: 2px solid currentColor; outline-offset: 2px; }
    pre { overflow-x: auto; }
  </style>
</head>
<body>
  <a class="skip" href="#main-content">Skip to main content</a>
  <header>
    <nav aria-label="Primary">
      <a href="${current === 'home' ? './' : '../'}"${current === 'home' ? ' aria-current="page"' : ''}>Home</a>
      <a href="${current === 'home' ? './accessibility/' : './'}"${current === 'accessibility' ? ' aria-current="page"' : ''}>Accessibility</a>
      <label>Theme
        <select id="theme-select">
          <option value="system">System</option>
          <option value="light">Light</option>
          <option value="dark">Dark</option>
        </select>
      </label>
    </nav>
  </header>
  <main id="main-content" tabindex="-1">
    <h1>${heading}</h1>
    ${body}
  </main>
  <footer>Reusable workflow self-test fixture.</footer>
  <script>
    const select = document.querySelector('#theme-select');
    const media = matchMedia('(prefers-color-scheme: dark)');
    const meta = document.querySelector('meta[name="theme-color"]');
    const apply = value => {
      document.documentElement.removeAttribute('data-theme');
      if (value === 'light' || value === 'dark') document.documentElement.dataset.theme = value;
      const effective = value === 'system' ? (media.matches ? 'dark' : 'light') : value;
      meta.dataset.effectiveTheme = effective;
      meta.content = effective === 'dark' ? '#111111' : '#ffffff';
    };
    const stored = localStorage.getItem('selftest-theme') || 'system';
    select.value = stored;
    apply(stored);
    select.addEventListener('change', () => { localStorage.setItem('selftest-theme', select.value); apply(select.value); });
    media.addEventListener('change', () => { if (select.value === 'system') apply('system'); });
  </script>
</body>
</html>`;

fs.writeFileSync(path.join(out, 'index.html'), shell({
  title: 'Public-site readiness self-test',
  heading: 'Public-site readiness self-test',
  current: 'home',
  body: '<p>This synthetic candidate proves the reusable release-readiness workflow without project-specific product behavior.</p><p><a href="./accessibility/">Review accessibility notes</a></p>'
}));

fs.writeFileSync(path.join(out, 'accessibility', 'index.html'), shell({
  title: 'Accessibility - public-site readiness self-test',
  heading: 'Accessibility',
  current: 'accessibility',
  body: '<p>Automated checks are evidence, not certification. Manual accessibility review remains a consumer responsibility.</p>'
}));
