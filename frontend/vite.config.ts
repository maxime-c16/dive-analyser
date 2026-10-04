import fs from 'node:fs'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

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
  plugins: [react()],
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
    // HMR configuration - DISABLED in Docker
    // The frontend app connects to backend via PROXY_TARGET
    // For local development: remove DOCKER_ENV variable
    hmr: false,
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
