import { defineConfig } from 'vite';
import { resolve, join, extname } from 'node:path';
import { createReadStream, statSync } from 'node:fs';

// The legacy Flash tree (1.7 GB, gitignored) — served as /res/* in dev so
// Ruffle can boot the ORIGINAL Main.swf with zero copied assets.
const LEGACY_RES = resolve(__dirname, '../TonNgoKhong/server/ESSamp/wwwroot/res');

const MIME = {
  '.swf': 'application/x-shockwave-flash',
  '.xml': 'text/xml',
  '.dat': 'application/octet-stream',
  '.jat': 'application/octet-stream',
  '.mm': 'application/octet-stream',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.mp3': 'audio/mpeg',
  '.flv': 'video/x-flv',
  '.txt': 'text/plain',
  '.js': 'text/javascript',
};

// Dev-only static mount: /res/* -> legacy tree. Keeps the 1.7 GB of Flash
// assets out of git AND out of the Vite bundle; Ruffle fetches them live.
function resPlugin() {
  return {
    name: 'legacy-res',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (!req.url || !req.url.startsWith('/res/')) return next();
        const rel = decodeURIComponent(req.url.slice('/res/'.length).split('?')[0]);
        // Block path traversal — stay inside the legacy tree.
        const file = resolve(join(LEGACY_RES, rel));
        if (!file.startsWith(LEGACY_RES)) {
          res.statusCode = 403;
          res.end('forbidden');
          return;
        }
        try {
          const st = statSync(file);
          if (!st.isFile()) throw new Error('not a file');
          res.setHeader('Content-Type', MIME[extname(file).toLowerCase()] || 'application/octet-stream');
          res.setHeader('Content-Length', st.size);
          // The game loads cross-subpath assets; same-origin here, but be lenient.
          res.setHeader('Access-Control-Allow-Origin', '*');
          createReadStream(file).pipe(res);
        } catch {
          res.statusCode = 404;
          res.end('not found');
        }
      });
    },
  };
}

// Dev proxy: the browser talks same-origin to Vite (:5173), and Vite forwards
// `/api/*` to the legacy Apache/PHP stack on :80 (ESSamp). This avoids CORS
// entirely and keeps the PHP session cookie working, since from the browser's
// point of view everything comes from one origin.
export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      '/api': {
        // Default: legacy ESSamp Apache on :80. Point at the Python server
        // with API_TARGET=http://127.0.0.1:8080 (see server/py/).
        target: process.env.API_TARGET || 'http://127.0.0.1:80',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  plugins: [resPlugin()],
  build: {
    rollupOptions: {
      // Two pages: the Phaser login scaffold (index.html) and the Ruffle
      // player that runs the original Flash client (player.html).
      input: {
        main: resolve(__dirname, 'index.html'),
        player: resolve(__dirname, 'player.html'),
      },
    },
  },
});
