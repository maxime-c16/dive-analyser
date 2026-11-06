import fs from 'node:fs'
import https from 'node:https'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

const devProxyTarget = new URL(process.env.PROXY_TARGET || 'http://localhost:8000')
// Keep the browser Host for session Origin checks, but route TLS using the
// upstream hostname. Otherwise Node may derive SNI from the localhost Host.
const devProxyAgent = devProxyTarget.protocol === 'https:'
  ? new https.Agent({ servername: devProxyTarget.hostname })
  : undefined

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
        target: devProxyTarget.href,
        ws: true,
        changeOrigin: false,
        agent: devProxyAgent,
        secure: false,
      },
      // Signed media paths must reach the same front door as the API.
      // Vite's SPA fallback cannot serve thumbnails or byte-range video.
      '/media': {
        target: devProxyTarget.href,
        changeOrigin: false,
        agent: devProxyAgent,
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
      '/media': {
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
