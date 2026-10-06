// Remove the previous build output so a stale file can never survive a rebuild.
import { rm } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
await rm(path.join(root, 'dist'), { recursive: true, force: true });
console.log('cleaned dist/');
