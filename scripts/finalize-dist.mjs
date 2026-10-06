// Stamp each build folder with its module system.
//
// The package root is "type": "module", so the CommonJS build needs its own
// manifest for `require()` to keep working, and the ESM build gets an explicit
// one so it never depends on the root setting.
import { writeFile, access } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const targets = [
  ['dist/esm', { type: 'module' }],
  ['dist/cjs', { type: 'commonjs' }],
];

for (const [folder, manifest] of targets) {
  const absolute = path.join(root, folder);
  await access(absolute);
  await writeFile(
    path.join(absolute, 'package.json'),
    `${JSON.stringify(manifest, null, 2)}\n`,
    'utf8',
  );
  console.log(`wrote ${folder}/package.json (${manifest.type})`);
}
