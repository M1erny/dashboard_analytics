import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 2137,
    host: '0.0.0.0', // Listen on all addresses
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        secure: false,
      }
    },
    allowedHosts: true,
  }
})
