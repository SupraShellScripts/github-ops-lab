import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve('build/public-site');
const required = [
  'index.html',
  path.join('accessibility', 'index.html')
];

for (const relative of required) {
  const file = path.join(root, relative);
  if (!fs.existsSync(file)) throw new Error(`missing candidate route: ${relative}`);
  const html = fs.readFileSync(file, 'utf8');
  for (const token of ['<html lang="en">', 'id="main-content"', 'aria-label="Primary"', 'id="theme-select"']) {
    if (!html.includes(token)) throw new Error(`${relative} missing required token ${token}`);
  }
}

console.log(`validated ${required.length} generated candidate routes`);
