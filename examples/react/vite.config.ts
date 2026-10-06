import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

/**
 * The browser never talks to the facade directly.
 *
 * It calls `/api/bookroom/...` on this dev server, Vite forwards that to the
 * Node proxy in `server.mjs`, and that proxy is the only process that holds
 * `BOOKROOM_FACADE_TOKEN`. Point `BOOKROOM_PROXY_URL` somewhere else if the
 * proxy is not on the default port.
 */
const PROXY_TARGET = process.env.BOOKROOM_PROXY_URL ?? 'http://127.0.0.1:8788';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api/bookroom': {
        target: PROXY_TARGET,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
});