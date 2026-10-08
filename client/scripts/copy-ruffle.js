// Stages the Ruffle selfhosted runtime (ruffle.js + core + wasm, ~30MB)
// from node_modules into public/ruffle/ so it is served verbatim.
// The @ruffle-rs/ruffle package resolves its core/wasm relative to the
// <script> tag (document.currentScript) — bundling it with Vite breaks
// that lookup, hence plain <script src="/ruffle/ruffle.js"> in player.html.
// Runs automatically via predev/prebuild; public/ruffle/ is gitignored.
import { copyFileSync, mkdirSync, readdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const src = join(root, 'node_modules', '@ruffle-rs', 'ruffle');
const dst = join(root, 'public', 'ruffle');
mkdirSync(dst, { recursive: true });

let n = 0;
for (const f of readdirSync(src)) {
  if (/\.(js|wasm)$/.test(f)) {
    copyFileSync(join(src, f), join(dst, f));
    n++;
  }
}
console.log(`[sync:ruffle] staged ${n} files -> public/ruffle/`);
