import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/me': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
      '/brokers': 'http://localhost:8000',
      '/audit': {
        target: 'http://localhost:8000',
        bypass(req) {
          // Let browser navigation (HTML requests) fall through to the SPA
          if (req.headers.accept?.includes('text/html')) {
            return req.url;
          }
        },
      },
      '/fetch': 'http://localhost:8000',
      '/logout': 'http://localhost:8000',
      '/login': {
        target: 'http://localhost:8000',
        bypass(req) {
          if (req.headers.accept?.includes('text/html')) {
            return req.url;
          }
        },
      },
      '/signup': {
        target: 'http://localhost:8000',
        bypass(req) {
          if (req.headers.accept?.includes('text/html')) {
            return req.url;
          }
        },
      },
    },
  },
})
