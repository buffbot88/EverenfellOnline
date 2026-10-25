import { defineConfig } from 'vite';

// Map 0 tiles ship with the client under public/maps/map0/ and are
// referenced by relative URLs (src/assets/map0.json), so dev and
// production resolve identical paths. No dev-only asset routes remain.
export default defineConfig({
  base: '/websites/everenfell/',
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
