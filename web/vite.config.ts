import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { fileURLToPath } from 'node:url';

// base './': every path stays relative (the page runs under any sub-path, or from `midi2motion serve`).
// The bundle goes to dist/app/ so it never collides with public/assets/ (the android GLB).
export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  build: { outDir: 'dist', assetsDir: 'app', emptyOutDir: true, chunkSizeWarningLimit: 900,
    rollupOptions: { output: { manualChunks: { three: ['three'], react: ['react', 'react-dom'] } } } },
  server: { host: '127.0.0.1', port: 8814 },
  preview: { host: '127.0.0.1', port: 8814 },
});
