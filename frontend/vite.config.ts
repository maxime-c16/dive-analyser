import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    strictPort: false,
    // HMR configuration for development
    // Browser connects through nginx proxy at 192.168.1.57:6090
    // Nginx proxies HMR WebSocket connections to the Vite dev server
    hmr: {
      host: process.env.VITE_HMR_HOST || 'localhost',
      port: process.env.VITE_HMR_PORT ? parseInt(process.env.VITE_HMR_PORT) : 6090,
      protocol: process.env.VITE_HMR_PROTOCOL || 'ws',
      // Specify the path for WebSocket connections - Nginx will proxy this
      path: '/@vite/ws',
    },
    watch: {
      usePolling: true,
    },
    // Proxy API requests to the backend during development
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
    port: 3000,
  },
  optimizeDeps: {
    exclude: ['lucide-react'],
    esbuildOptions: {
      target: 'esnext',
    },
  },
})
