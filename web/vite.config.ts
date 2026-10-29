import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// In development the app's API is the local bi-api (python -m bi.main_api); built, the API serves this app itself (WEB_DIR).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { '/app/api': 'http://localhost:4000' } },
  build: { outDir: 'dist', sourcemap: true },
});
