import { fileURLToPath } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// In production the app is served from the same host as the core, so `/api` is same-origin.
// In dev with VITE_API_MODE=live, VITE_API_PROXY (shell or .env file) points `/api` at a running core.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  const apiProxy = env.VITE_API_PROXY
  return {
    plugins: [react(), tailwindcss()],
    build: {
      // Two pages: the module (index.html) and the demo frame (demo.html, #325). The frame has its
      // own entry, so none of its code is in the module's bundle.
      rolldownOptions: {
        input: {
          main: fileURLToPath(new URL('./index.html', import.meta.url)),
          demo: fileURLToPath(new URL('./demo.html', import.meta.url)),
        },
      },
    },
    server: {
      port: 5173,
      proxy: apiProxy ? { '/api': { target: apiProxy, changeOrigin: true } } : undefined,
    },
  }
})
