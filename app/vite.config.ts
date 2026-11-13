import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// In production the app is served from the same host as the core, so `/api` is same-origin.
// In dev with VITE_API_MODE=live, VITE_API_PROXY points `/api` at a running core.
const apiProxy = process.env.VITE_API_PROXY

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: apiProxy ? { '/api': { target: apiProxy, changeOrigin: true } } : undefined,
  },
})
