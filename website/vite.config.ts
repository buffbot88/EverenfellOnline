import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const here = fileURLToPath(new URL('.', import.meta.url));

// Multi-page build: preserves the existing / and /servers/ URLs so deep
// links keep working on static hosts without rewrite rules. public/
// (access.js) is copied to dist/ verbatim for the game client.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    rollupOptions: {
      input: {
        main: resolve(here, 'index.html'),
        servers: resolve(here, 'servers/index.html'),
      },
    },
  },
});
