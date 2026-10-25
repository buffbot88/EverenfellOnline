import { createReadStream, existsSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig, type Plugin } from 'vite';

const here = path.dirname(fileURLToPath(import.meta.url));
// Original legacy map tiles, dev-only. Never copied into dist/ or public/.
const MAP0_DIR = path.resolve(here, '../../MKO_Client/Assets/res/tw/r/m/0');

/** Serves /dev-assets/map0/<file>.jpg from the local original client folder. */
function devMapTiles(): Plugin {
  return {
    name: 'everenfell-dev-map-tiles',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use('/dev-assets/map0/', (req, res, next) => {
        const name = decodeURIComponent((req.url ?? '/').split('?')[0].replace(/^\//, ''));
        // Only the flat tile names of map 0 are served; no traversal.
        if (!/^\d{6}\.jpg$/.test(name)) {
          next();
          return;
        }
        const file = path.join(MAP0_DIR, name);
        if (!existsSync(file) || !statSync(file).isFile()) {
          res.statusCode = 404;
          res.end('not found');
          return;
        }
        res.setHeader('Content-Type', 'image/jpeg');
        res.setHeader('Cache-Control', 'no-cache');
        createReadStream(file).pipe(res);
      });
    },
  };
}

export default defineConfig({
  plugins: [devMapTiles()],
  server: {
    port: 5173,
    proxy: {
      // Python web API (AccountHandler.php / gamesession.php) during dev.
      '/legacy-api': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/legacy-api/, ''),
      },
    },
  },
  build: {
    target: 'es2022',
    outDir: 'dist',
  },
});
