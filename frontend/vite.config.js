import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  server: {
    proxy: {
      '/analyze': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
      '/sample-questions': 'http://localhost:8000',
      '/dataset-info': 'http://localhost:8000',
    }
  }
})