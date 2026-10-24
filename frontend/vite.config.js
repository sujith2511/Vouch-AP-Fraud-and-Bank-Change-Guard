import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // The FastAPI backend does not send CORS headers, so the browser can't call
    // http://127.0.0.1:8000 directly from this page. Instead the browser calls
    // /api/... on the Vite server, and Vite forwards it to the backend:
    //   /api/items  ->  http://127.0.0.1:8000/items
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
