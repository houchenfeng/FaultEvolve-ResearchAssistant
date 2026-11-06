import { defineConfig } from 'vite';

// Relative base: the same bundle is served by FastAPI under /edge-tablet/ and
// loaded from the APK's local web root.
export default defineConfig({
  base: './',
  build: { target: 'es2020', chunkSizeWarningLimit: 1500 },
  server: { port: 5190 },
});
