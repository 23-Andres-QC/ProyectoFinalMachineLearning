import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// En desarrollo (npm run dev) /api va al nginx del docker compose, que lo pasa al backend.
export default defineConfig({
  plugins: [vue()],
  server: { proxy: { '/api': 'http://localhost:8080' } },
})
