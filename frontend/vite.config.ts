import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Proxy /api to local FastAPI so the browser stays same-origin in demo.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
