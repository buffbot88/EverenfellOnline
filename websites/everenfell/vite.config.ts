import { defineConfig } from 'vite';

export default defineConfig({
  base: '/websites/everenfell/',
  publicDir: false,
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
