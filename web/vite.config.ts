/// <reference types="vitest/config" />
import { readFileSync, existsSync } from 'node:fs';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// в worktree к портам прибавляется число из .wt-offset: API 3100 + n, Vite 5173 + n
const offsetFile = new URL('../.wt-offset', import.meta.url);
const offset = existsSync(offsetFile) ? Number(readFileSync(offsetFile, 'utf8').trim()) || 0 : 0;

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173 + offset,
    strictPort: true,
    proxy: { '/api': `http://127.0.0.1:${3100 + offset}` },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
    setupFiles: ['src/test/setup.ts'],
  },
});
