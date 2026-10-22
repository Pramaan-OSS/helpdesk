import path from 'node:path';
import { defineConfig, devices } from '@playwright/test';
export default defineConfig({
  testDir: '..', workers: 1, fullyParallel: false, retries: 0, timeout: 45000,
  outputDir: process.env.QA_OUTPUT_DIR || '../../.scratch/qa/browser-results',
  reporter: [['list'], ['json', { outputFile: path.resolve(process.cwd(), process.env.QA_REPORT_FILE || '.scratch/qa/browser-report.json') }]],
  use: { ...devices['Desktop Chrome'], headless: true, baseURL: process.env.BASE_URL || 'http://localhost:18173',
    extraHTTPHeaders: { 'X-Frappe-Site-Name': 'qa-helpdesk.localhost' },
    screenshot: 'only-on-failure', trace: 'retain-on-failure', viewport: { width: 1440, height: 900 }, timezoneId: 'UTC' },
  projects: [
    { name: 'setup', testMatch: /global.setup.ts/ },
    { name: 'chromium', testMatch: process.env.QA_NO_KEY === '1' ? /qa\/no-key\.spec\.ts/ : /(?:tests\/.*|qa\/(?:routes|outcomes|printing|realtime|integrations))\.spec\.ts/, dependencies: ['setup'] },
  ],
});
