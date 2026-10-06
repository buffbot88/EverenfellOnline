import { defineConfig } from 'vite';

// Dev proxy: the browser talks same-origin to Vite (:5173), and Vite forwards
// `/api/*` to the legacy Apache/PHP stack on :80 (ESSamp). This avoids CORS
// entirely and keeps the PHP session cookie working, since from the browser's
// point of view everything comes from one origin.
export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:80',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
});
