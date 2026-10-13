import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // In dev the API runs on :8000; proxying avoids CORS and keeps API URLs relative.
    proxy: { '/api': 'http://localhost:8000' },
  },
})
