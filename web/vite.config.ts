import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev proxies /api to the FastAPI server; production builds into dist/,
// which the server mounts as static files.
export default defineConfig({
  plugins: [react()],
  build: { outDir: 'dist' },
  server: {
    proxy: {
      '/api': { target: 'http://127.0.0.1:8900', changeOrigin: true },
    },
  },
})
