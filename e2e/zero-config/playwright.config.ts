import { defineConfig } from '@playwright/test';
export default defineConfig({ testDir: '.', testMatch: '*.spec.ts', workers: 1, timeout: 60000,
  outputDir: '../../.runtime/zero-browser-results', reporter: 'list',
  use: { headless: true, baseURL: process.env.ZERO_TEST_URL || 'http://localhost:18008', trace: 'off' } });
