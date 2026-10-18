import fs from 'node:fs'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// Optional HTTPS for the production preview so browser credentials stored
// with the Secure attribute (real session auth) work exactly as in
// production. Enabled by setting PREVIEW_HTTPS_KEY / PREVIEW_HTTPS_CERT.
const previewHttps =
  process.env.PREVIEW_HTTPS_KEY && process.env.PREVIEW_HTTPS_CERT
    ? {
        key: fs.readFileSync(process.env.PREVIEW_HTTPS_KEY),
        cert: fs.readFileSync(process.env.PREVIEW_HTTPS_CERT),
      }
    : undefined

export default defineConfig({
  plugins: [
    react(),
    {
      name: 'calendar-local-private-adapter',
      apply: 'serve',
      configureServer(server) {
        server.middlewares.use('/__calendar_local/training', (_req, res) => {
          res.setHeader('Cache-Control', 'no-store');
          res.setHeader('Content-Type', 'application/json');
          try {
            const bundle = JSON.parse(fs.readFileSync(new URL('../reports/calendar/kcpm-2026-2027/import-bundle.json', import.meta.url), 'utf8'));
            // Only exact schedule fields; never attachments, provenance paths or resource URLs.
            const fields = ['source_key', 'local_date', 'start_local', 'end_local', 'timezone', 'venue_code', 'group_key'];
            res.end(JSON.stringify(bundle.training_occurrences.map((row: Record<string, unknown>) => Object.fromEntries(fields.map(key => [key, row[key]])))));
          } catch { res.statusCode = 404; res.end('{}'); }
        });
      },
    },
    // Push-only service worker (PR3 notifications-push). `injectManifest`
    // builds dist/sw-push.js from src/sw-push.ts. Workbox requires its
    // `self.__WB_MANIFEST` placeholder at build time, but the worker never
    // consumes it (no precacheAndRoute, no fetch handler, no runtime
    // caching) — caching/offline behaviour is unchanged by design.
    // `injectRegister: false` because registration is manual and lazy (see
    // pushSubscription.ts): the SW registers only when the user opens
    // notification settings, and permission is requested only on explicit
    // opt-in click — never at login or first render. The existing
    // public/manifest.webmanifest is kept as-is (`manifest: false`).
    VitePWA({
      strategies: 'injectManifest',
      srcDir: 'src',
      filename: 'sw-push.ts',
      injectRegister: false,
      manifest: false,
      devOptions: { enabled: false },
    }),
  ],
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    restoreMocks: true,
    include: ['src/**/*.test.{ts,tsx}', 'tests/**/*.test.{ts,tsx}'],
    exclude: ['e2e/**', 'node_modules/**', 'dist/**'],
  },
  server: {
    host: '0.0.0.0',
    port: 3000,
    strictPort: false,
    // Use Vite's default HMR in development, including Docker.
    watch: {
      usePolling: true,
    },
    // Proxy API requests to the backend during development
    // In Docker: uses PROXY_TARGET from docker-compose.yml (http://backend:8000)
    proxy: {
      '/api': {
        target: process.env.PROXY_TARGET || 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
  preview: {
    host: '0.0.0.0',
    port: 4173,
    https: previewHttps,
    // Production preview (`vite preview`) proxies API calls to the live
    // backend so the deployed-style bundle can be validated end-to-end
    // before an authorized production deployment.
    proxy: {
      '/api': {
        target: process.env.PREVIEW_PROXY_TARGET || 'http://127.0.0.1:6002',
        changeOrigin: true,
        secure: false,
      },
    },
  },
  // Optimize dependencies - exclude problematic packages
  optimizeDeps: {
    exclude: ['lucide-react'],
    esbuildOptions: {
      target: 'esnext',
    },
  },
})
