import { test, expect } from '@playwright/test';

test('outside actions explain a missing key before any request can act', async ({ browser, baseURL }) => {
  test.skip(process.env.QA_NO_KEY !== '1', 'Run after restarting only the throwaway app with its fixture key removed');
  const context = await browser.newContext({ baseURL, storageState: 'e2e/.auth/admin.json' });
  const page = await context.newPage();
  await page.goto('/helpdesk/admin/email-accounts');
  await expect(page.getByRole('button', { name: 'Connect mailbox', exact: true })).toBeDisabled();
  await expect(page.getByText('Add PRAMAAN_API_KEY to .env', { exact: true })).toBeVisible();
  const development = await page.request.get('/api/method/helpdesk.www.helpdesk.index.get_context_for_dev');
  expect(development.status()).toBe(417);
  expect(await development.text()).not.toMatch(/Traceback|\/app\/|\/Users\//);
  const csrf = await page.evaluate(() => (window as any).csrf_token);
  const actions: Array<[string, Record<string, unknown>]> = [
    ['helpdesk.api.capabilities.draft_ticket_reply', { ticket: 'unused' }],
    ['helpdesk.api.capabilities.enrich_customer', { name: 'unused' }],
    ['helpdesk.api.capabilities.enrich_contact', { name: 'unused' }],
    ['helpdesk.api.capabilities.parse_attachment', { file_name: 'unused' }],
    ['helpdesk.api.capabilities.draft_article', { url: 'https://example.test' }],
    ['helpdesk.api.capabilities.start_callback', { ticket: 'unused', recipient: '+15555550100', request_id: 'unused' }],
    ['helpdesk.api.calling.session', {}],
    ['helpdesk.api.settings.email.create_email_account', { data: { email_id: 'support@example.test' } }],
    ['helpdesk.api.settings.email.provision_mailbox', { display_name: 'Fixture', request_id: 'unused' }],
    ['helpdesk.api.outcome_reviews.prepare', { kind: 'attachment', ticket: 'unused', file_name: 'unused' }],
    ['helpdesk.api.outcome_reviews.run', { review_id: 'unused' }],
  ];
  for (const [method, data] of actions) {
    const response = await page.request.post(`/api/method/${method}`, { data, headers: { 'X-Frappe-CSRF-Token': csrf } });
    expect(response.status(), method).toBe(422);
    expect((await response.json()).message, method).toBe('Add PRAMAAN_API_KEY to .env');
  }
  await context.close();
});
