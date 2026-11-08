/// <reference types="vitest/config" />
import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
      '@shared': path.resolve(import.meta.dirname, '../../packages/shared-types'),
    },
  },
  server: {
    // changeOrigin stays false so the API sees the browser Host and Origin.
    proxy: {
      '/api/': {
        target: 'http://localhost:8000',
        rewrite: (p) => p.replace(/^\/api/, ''),
        // Runs before Vite's error logger, which prints req.url; drop the query so OAuth codes never reach logs.
        configure: (proxy) => proxy.on('error', (_err, req) => (req.url = req.url?.split('?')[0])),
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
  },
})
