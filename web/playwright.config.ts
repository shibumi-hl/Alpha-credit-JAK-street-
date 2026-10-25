import { defineConfig, devices } from '@playwright/test';

// BASE_URL — живой адрес (после деплоя) или локальный Vite; локально API и Vite должны быть подняты
export default defineConfig({
  testDir: 'e2e',
  timeout: 60_000,
  use: { baseURL: process.env.BASE_URL ?? 'http://localhost:5183', trace: 'retain-on-failure' },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1000 } } },
    { name: 'mobile', use: { ...devices['Pixel 7'], viewport: { width: 375, height: 812 } } },
  ],
});
