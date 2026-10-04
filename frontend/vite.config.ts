/// <reference types="vitest/config" />
import { fileURLToPath, URL } from 'node:url';

import react from '@vitejs/plugin-react';
import { defineConfig, type Plugin } from 'vite';

/**
 * The two faces the first screen is set in (frontend-plan §12.3): Instrument Serif
 * regular (titles) and Instrument Sans (everything else), latin only. Preloaded so
 * the text does not swap faces after it first paints; every other weight and subset
 * still loads on demand through its `unicode-range`.
 */
const PRELOADED_FONTS = [
  /instrument-serif-latin-400-normal-[^/]*\.woff2$/,
  /instrument-sans-latin-wght-normal-[^/]*\.woff2$/,
];

function preloadFonts(): Plugin {
  return {
    name: 'preload-fonts',
    apply: 'build',
    transformIndexHtml: {
      order: 'post',
      handler(_html, context) {
        const files = Object.keys(context.bundle ?? {}).filter((file) =>
          PRELOADED_FONTS.some((pattern) => pattern.test(file)),
        );
        return files.map((file) => ({
          tag: 'link',
          attrs: { rel: 'preload', as: 'font', type: 'font/woff2', href: `/${file}`, crossorigin: '' },
          injectTo: 'head' as const,
        }));
      },
    },
  };
}

// Backend runs on :8000 (see ../backend/RUNNING.md); the dev server proxies
// /api so the browser only ever talks to one origin and cookies/CORS never
// become a dev-only problem that doesn't reproduce against the real deploy.
export default defineConfig({
  plugins: [react(), preloadFonts()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
  },
});
