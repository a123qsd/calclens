import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: './',
  build: { outDir: '../src/slab_preflight/web_assets', emptyOutDir: true },
});
