import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const packages = ['react', 'react-dom', 'scheduler', '3dmol', 'iobuffer', 'netcdfjs', 'pako', 'upng-js'];
const sections = ['CalcLens bundled browser dependency notices\nGenerated from locked npm packages.'];
for (const name of packages) {
  const folder = path.join(root, 'node_modules', name);
  const manifest = JSON.parse(await readFile(path.join(folder, 'package.json'), 'utf8'));
  const license = await readFile(path.join(folder, 'LICENSE'), 'utf8');
  sections.push(`${name} ${manifest.version}\n${'='.repeat(72)}\n${license}`);
}
sections.push('Additional notices retained from the upstream 3Dmol browser bundle\n' +
  await readFile(path.join(root, 'node_modules/3dmol/build/3Dmol-min.js.LICENSE.txt'), 'utf8'));
await mkdir(path.join(root, 'public'), { recursive: true });
await writeFile(path.join(root, 'public/THIRD_PARTY_LICENSES.txt'), sections.join('\n\n'));
