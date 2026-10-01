import { build } from 'esbuild';
import { mkdir } from 'node:fs/promises';

await mkdir(new URL('./media/', import.meta.url), { recursive: true });

const common = {
  bundle: true,
  platform: 'browser',
  target: ['chrome120'],
  minify: true,
  sourcemap: false,
  legalComments: 'none'
};

await build({
  ...common,
  entryPoints: ['src/webview/brain-grid.js'],
  outfile: 'media/brain-grid.bundle.js'
});

await build({
  ...common,
  entryPoints: ['src/webview/radar.js'],
  outfile: 'media/radar.bundle.js'
});

console.log('JARVIS webviews compiled.');
