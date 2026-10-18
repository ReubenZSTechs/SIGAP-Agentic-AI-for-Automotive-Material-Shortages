import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // Proxy ke backend FastAPI -> request same-origin, tanpa masalah CORS saat development.
    // (Backend juga sudah mengaktifkan CORS untuk http://localhost:5173.)
    proxy: { '/api': 'http://localhost:8000' },
  },
});
