import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { Api } from '../helpers/api';

test('fresh installation accepts its generated login and shows the capability screen', async ({ page, context, baseURL }) => {
  await context.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.continue() : route.abort());
  const noKey = process.env.ZERO_TEST_NO_KEY === '1';
  const password = readFileSync(process.env.ZERO_CREDENTIAL_FILE!, 'utf8').trim();
  const response = await page.goto('/login');
  expect(response?.status()).toBe(200);
  if (noKey) await expect(page.getByText('Add PRAMAAN_API_KEY to .env', { exact: true })).toBeVisible();
  await page.getByLabel('Email or username').fill('Administrator');
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/helpdesk/);
  // Normal first-user setup is optional; use its own explicit skip action.
  const skip = page.getByText('Skip for now', { exact: true });
  if (await skip.isVisible({ timeout: 5000 }).catch(() => false)) await skip.click();
  await expect(page.locator('#app')).toBeVisible();
  const api = await Api.login(baseURL!, 'Administrator', password);
  await api.call('helpdesk.api.onboarding.mark_persona_captured');
  const customer = await api.call('helpdesk.api.customer.create_customer', { customer: { customer_name: `First-run fixture ${Date.now()}`, domain: 'example.test' } });
  await page.goto(`/helpdesk/customers/${encodeURIComponent(customer.name)}`);
  const suggest = page.getByRole('button', { name: 'Suggest details', exact: true });
  await expect(suggest).toBeVisible();
  if (noKey) {
    await expect(suggest).toBeDisabled();
    await expect(page.getByText('Add PRAMAAN_API_KEY to .env', { exact: true }).first()).toBeVisible();
  } else {
    await suggest.click();
    await expect(page.getByText('Local fixture company', { exact: true })).toBeVisible();
  }
  await expect(page.locator('body')).not.toContainText(/Traceback|Not Permitted|Could not load/);
});
