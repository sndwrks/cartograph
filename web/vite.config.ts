import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    proxy: {
      // dev-only: the nginx image handles /api in production compose.
      // In-compose dev reaches the api service by name; host-side dev can
      // override with VITE_API_PROXY=http://localhost:8000
      '/api': process.env.VITE_API_PROXY ?? 'http://api:8000',
    },
  },
})
