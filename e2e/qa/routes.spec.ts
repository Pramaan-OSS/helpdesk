import { writeFileSync } from 'node:fs';
import { test, expect } from '@playwright/test';

const routes = ['/home', '/tickets', '/tickets/new', '/customers', '/contacts', '/kb', '/search', '/dashboard', '/call-logs', '/notifications', '/guide', '/my-tickets', '/my-tickets/new', '/kb-public',
  ...['profile','preferences','email-accounts','email-notifications','general','agents','invite-agents','teams','sla-policies','business-holidays','assignment-rules','field-dependencies','saved-replies','telephony','signin','erpnext'].map(tab => `/admin/${tab}`)];

test('each screen loads and reloads without errors, with route timings', async ({ browser, baseURL }) => {
  test.setTimeout(900000);
  const rows: unknown[] = [];
  for (const route of routes) {
    const context = await browser.newContext({ baseURL, storageState: 'e2e/.auth/admin.json', extraHTTPHeaders: { 'X-Frappe-Site-Name': 'qa-helpdesk.localhost' } });
    await context.addInitScript(() => localStorage.setItem('isOnboardingStepsCompletedhelpdeskAdministrator', 'true'));
    await context.route('**/*', r => ['localhost','127.0.0.1'].includes(new URL(r.request().url()).hostname) ? r.continue() : r.abort());
    const page = await context.newPage(); const errors: string[] = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('response', r => { if (r.status() >= 400 && !r.url().includes('socket.io')) errors.push(`${r.status()} ${new URL(r.url()).pathname}`); });
    const times: number[] = [];
    for (let visit = 0; visit < 2; visit++) {
      const start = Date.now();
      const response = visit ? await page.reload() : await page.goto(`/helpdesk${route}`);
      expect(response?.status(), route).toBe(200);
      await expect(page.locator('#app')).not.toBeEmpty();
      await page.waitForLoadState('networkidle');
      times.push(Date.now() - start);
      await expect(page.locator('body')).not.toContainText(/Traceback|Not Permitted|Could not load sign-in settings|\/Users\//);
    }
    if (['/home', '/tickets', '/guide'].includes(route)) await page.screenshot({ path: `.scratch/qa/${process.env.QA_MODE || 'production'}-${route.slice(1)}.png`, fullPage: true });
    rows.push({ route, firstMs: times[0], repeatMs: times[1], errors });
    writeFileSync(`.scratch/qa/${process.env.QA_MODE || 'production'}-timings.json`, JSON.stringify(rows, null, 2));
    await context.close();
    expect(errors, route).toEqual([]);
  }
});
