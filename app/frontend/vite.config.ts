import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import { defineConfig } from 'vite';

export default defineConfig(({ command, mode }) => ({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, '.'),
    },
  },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
  build: {
    target: 'es2019',
    sourcemap: false,
    minify: 'esbuild',
    cssCodeSplit: true,
    brotliSize: false,
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      treeshake: true,
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            return id.toString().split('node_modules/')[1].split('/')[0].toString();
          }
        },
      },
    },
  },
  esbuild: {
    // Drop console/debugger only for production builds
    drop: mode === 'production' ? ['console', 'debugger'] : [],
  },
}));
