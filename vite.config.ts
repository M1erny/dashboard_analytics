import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          // Split heavy vendor libraries into separate cacheable chunks
          'vendor-recharts': ['recharts'],
          'vendor-maps': ['react-simple-maps'],
          'vendor-icons': ['lucide-react'],
        },
      },
    },
    // Increase chunk size warning limit (recharts is inherently large)
    chunkSizeWarningLimit: 600,
  },
  server: {
    port: 5176,
    strictPort: true,
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
