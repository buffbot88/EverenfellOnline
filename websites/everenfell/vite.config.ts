import { createReadStream, existsSync, statSync } from 'node:fs';
import { extname, resolve } from 'node:path';
import { defineConfig, type Plugin } from 'vite';

/** Dev-only static mapping: ./assets served at /assets/ (never in dist/). */
function devAssetsPlugin(): Plugin {
  const root = resolve(__dirname, 'assets');
  const types: Record<string, string> = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.mp3': 'audio/mpeg',
    '.json': 'application/json',
  };
  return {
    name: 'everenfell-dev-assets',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = (req.url ?? '').split('?')[0];
        if (!url.startsWith('/assets/')) return next();
        const file = resolve(root, url.slice('/assets/'.length));
        if (!file.startsWith(root) || !existsSync(file) || !statSync(file).isFile()) {
          return next();
        }
        res.setHeader('Content-Type', types[extname(file).toLowerCase()] ?? 'application/octet-stream');
        res.setHeader('Cache-Control', 'no-store');
        createReadStream(file).pipe(res);
      });
    },
  };
}

export default defineConfig({
  base: '/websites/everenfell/',
  publicDir: false,
  plugins: [devAssetsPlugin()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8080',
      '/everenfell': { target: 'ws://127.0.0.1:8091', ws: true },
    },
  },
  build: {
    target: 'es2022',
    outDir: 'dist',
    copyPublicDir: false,
  },
});
