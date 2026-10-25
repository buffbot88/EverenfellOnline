import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      // Python web API (AccountHandler.php / gamesession.php) during dev.
      '/legacy-api': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/legacy-api/, ''),
      },
    },
  },
  build: {
    target: 'es2022',
    outDir: 'dist',
  },
});
