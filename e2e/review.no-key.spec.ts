import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { skipGettingStarted } from './helpers/fixtures';

const login = JSON.parse(readFileSync('.runtime/outcomes-browser-user.json', 'utf8'));
const message = 'This needs a Pramaan key. Ask your administrator to set PRAMAAN_API_KEY.';
test.use({ headless: true });

test.beforeEach(async ({ page }) => {
  const response = await page.request.post('/api/method/login', { form: { usr: login.user, pwd: login.password } });
  expect(response.ok()).toBeTruthy();
  await skipGettingStarted(page, login.user);
  await page.addInitScript(() => { if (!sessionStorage.getItem('review-fixture-initialised')) { localStorage.setItem('helpdesk_persona_captured', '1'); sessionStorage.setItem('review-fixture-initialised', '1'); } });
});

const settings = [
  ['profile', 'Profile'], ['preferences', 'Preferences'], ['email-accounts', 'Email Accounts'],
  ['email-notifications', 'Email notifications'], ['general', 'General'], ['agents', 'Agents'],
  ['invite-agents', 'Invite Agents'], ['teams', 'Teams'], ['sla-policies', 'Service Level Agreements (SLAs)'],
  ['business-holidays', 'Business Holidays'], ['assignment-rules', 'Assignment Rules'],
  ['field-dependencies', 'Field Dependencies'], ['saved-replies', 'Saved Replies'],
  ['telephony', 'Calling'], ['signin', 'Sign-in'], ['erpnext', 'local customer app'],
];
for (const [slug, title] of settings) {
  test(`settings ${slug} opens on hard load and reload`, async ({ page }) => {
    const failed: string[] = [];
    page.on('response', response => {
      if (response.status() >= 400 && !response.url().includes('socket.io')) failed.push(`${response.status()} ${new URL(response.url()).pathname}`);
    });
    for (const load of [() => page.goto(`/helpdesk/admin/${slug}`), () => page.reload()]) {
      const response = await load();
      expect(response?.status()).toBe(200);
      await expect(page.locator('#app')).toContainText(title, { ignoreCase: true });
      await expect(page.locator('body')).not.toContainText(/Traceback|Not Permitted|Could not load sign-in settings|\/Users\//);
    }
    expect(failed).toEqual([]);
  });
}

test('ticket outside actions explain missing key and cannot run', async ({ page }) => {
  await page.goto(`/helpdesk/tickets/${login.ticket}`);
  await page.getByText('Pramaan assistance', { exact: true }).click();
  await expect(page.getByText(message, { exact: true }).first()).toBeVisible();
  for (const name of ['Draft a reply', 'Request phone callback', 'Read attachment text', 'Summarise attachment']) {
    await expect(page.getByRole('button', { name, exact: true })).toBeDisabled();
  }
  await page.getByLabel('Attachment', { exact: true }).selectOption(login.file_name);
  await expect(page.getByRole('button', { name: 'Read attachment text', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Summarise attachment', exact: true })).toBeDisabled();
});

test('mailbox connect and rental explain missing key', async ({ page }) => {
  await page.goto('/helpdesk/admin/email-accounts');
  await expect(page.getByText(message, { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Connect mailbox', exact: true })).toBeDisabled();
  await page.getByText('Need a new inbox?', { exact: true }).click();
  await expect(page.getByRole('button', { name: 'Create rented inbox', exact: true })).toBeDisabled();
});

test('recorded call review explains missing key', async ({ page }) => {
  await page.goto('/helpdesk/call-logs');
  const buttons = page.getByRole('button', { name: 'Review call', exact: true });
  await expect(buttons.first()).toBeVisible();
  for (const button of await buttons.all()) await expect(button).toBeDisabled();
  await expect(page.getByText(message, { exact: true }).first()).toBeVisible();
});

test('browser phone explains missing key without asking for microphone access', async ({ page }) => {
  let opened = false;
  page.on('request', request => { if (request.url().endsWith('/helpdesk.api.calling.session')) opened = true; });
  await page.goto(`/helpdesk/tickets/${login.ticket}`);
  await page.getByRole('button', { name: 'Browser calling', exact: true }).click();
  await expect(page.getByText(message, { exact: true }).first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Call', exact: true })).toBeDisabled();
  expect(opened).toBe(false);
});

test('customer create has no permission toast and enrichment explains missing key', async ({ page }) => {
  const failed: string[] = [];
  page.on('response', response => { if (response.status() >= 400 && !response.url().includes('socket.io')) failed.push(new URL(response.url()).pathname); });
  await page.goto('/helpdesk/customers');
  await page.getByRole('button', { name: 'Create', exact: true }).click();
  const dialog = page.getByRole('dialog');
  const name = `Browser review customer ${Date.now()}`;
  await dialog.getByRole('textbox', { name: 'Name (required)', exact: true }).fill(name);
  await dialog.getByLabel('Domain', { exact: true }).fill('example.com');
  await dialog.getByRole('button', { name: 'Create', exact: true }).click();
  await expect(page).toHaveURL(/\/helpdesk\/customers\//);
  await expect(page.getByText(name, { exact: true }).first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Suggest details', exact: true })).toBeDisabled();
  await expect(page.getByText(message, { exact: true }).first()).toBeVisible();
  await page.reload();
  await expect(page.getByRole('button', { name: 'Suggest details', exact: true })).toBeVisible();
  await expect(page.locator('body')).not.toContainText('You do not have permission');
  expect(failed).toEqual([]);
});

test('direct outside actions reject missing key with safe 4xx', async ({ page }) => {
  await page.goto(`/helpdesk/tickets/${login.ticket}`);
  const csrf = await page.evaluate(() => (window as any).csrf_token);
  for (const [method, args] of [
    ['capabilities.draft_ticket_reply', { ticket: login.ticket }],
    ['capabilities.start_callback', { ticket: login.ticket, recipient: '+441234567890', request_id: 'a6c27099-4083-410b-9e66-9676609ea976' }],
    ['capabilities.enrich_customer', { name: 'missing' }],
    ['capabilities.parse_attachment', { file_name: login.file_name }],
    ['settings.email.create_email_account', { data: { email_id: 'support@example.com' } }],
    ['outcome_reviews.prepare', { kind: 'Summary', ticket: login.ticket, file_name: login.file_name }],
    ['outcome_reviews.prepare', { kind: 'Call', ticket: login.ticket, call_name: login.call_name }],
    ['calling.session', {}],
  ] as const) {
    const response = await page.request.post(`/api/method/helpdesk.api.${method}`, { data: args, headers: { "X-Frappe-CSRF-Token": csrf } });
    expect(response.status()).toBe(422);
    expect((await response.json()).message).toBe(message);
    expect(await response.text()).not.toMatch(/Traceback|\/Users\/|\.py/);
  }
});

test('signed-in and anonymous error pages have no scripts or diagnostics', async ({ page, browser, baseURL }) => {
  for (const anonymous of [false, true]) {
    const context = anonymous ? await browser.newContext({ baseURL, extraHTTPHeaders: { 'X-Frappe-Site-Name': 'pramaan.localhost' } }) : null;
    const request = context?.request ?? page.request;
    for (const [path, status] of [['/api/method/telephony.call', 403], ['/missing-review-page', 404]] as const) {
      const response = await request.get(path, { headers: { Accept: 'text/html' } });
      expect(response.status()).toBe(status);
      expect(await response.text()).toContain('Return to Helpdesk');
      expect(await response.text()).not.toMatch(/Traceback|\/Users\/|frappe|<script|bundle/);
    }
    await context?.close();
  }
});

test('Skip for now preserves a deep link across reloads', async ({ page }) => {
  await page.addInitScript(() => { if (!sessionStorage.getItem('review-first-onboarding')) { localStorage.removeItem('helpdesk_persona_captured'); sessionStorage.setItem('review-first-onboarding', '1'); } });
  await page.route('**/api/method/helpdesk.api.auth.get_user', async route => {
    const response = await route.fetch();
    const body = await response.json();
    body.message.persona_captured = false;
    await route.fulfill({ response, json: body });
  });
  await page.goto('/helpdesk/admin/telephony');
  await page.getByRole('button', { name: 'Skip for now', exact: true }).click();
  await expect(page).toHaveURL(/\/helpdesk\/admin\/telephony$/);
  // Keep the server flag uncaptured so reloads prove the saved skip choice works.
  expect(await page.evaluate(() => localStorage.getItem('helpdesk_persona_captured'))).toBe('1');
  await page.goto('/helpdesk/admin/signin');
  await expect(page.locator('#app')).toContainText('Sign-in');
  await page.reload();
  await expect(page.locator('#app')).toContainText('Sign-in');
  await expect(page.getByRole('button', { name: 'Skip for now', exact: true })).not.toBeVisible();
});

test('Sign-in settings read and save accept the screen request method', async ({ page }) => {
  await page.goto('/helpdesk/admin/signin');
  await expect(page.locator('#app')).toContainText('Sign-in');
  const csrf = await page.evaluate(() => (window as any).csrf_token);
  const headers = { 'X-Frappe-CSRF-Token': csrf };
  const original = await page.request.post('/api/method/helpdesk.api.settings.signin.get_data', { headers });
  expect(original.status()).toBe(200);
  const data = (await original.json()).message;
  const saved = await page.request.post('/api/method/helpdesk.api.settings.signin.update_data', { data, headers });
  expect(saved.status()).toBe(200);
  await page.reload();
  await expect(page.locator('body')).not.toContainText('Could not load sign-in settings.');
});

test('specific server messages survive in the callback control', async ({ page }) => {
  await page.route('**/api/method/helpdesk.api.auth.get_user', async route => {
    const response = await route.fetch();
    const body = await response.json();
    body.message.pramaan_configured = true;
    await route.fulfill({ response, json: body });
  });
  const specific = 'Set the calling number and your callback number in Calling settings.';
  await page.route('**/api/method/helpdesk.api.capabilities.start_callback', route => route.fulfill({
    status: 417, contentType: 'application/json',
    body: JSON.stringify({ _server_messages: JSON.stringify([JSON.stringify({ message: specific })]) }),
  }));
  await page.goto(`/helpdesk/tickets/${login.ticket}`);
  await page.getByText('Pramaan assistance', { exact: true }).click();
  await page.getByRole('button', { name: 'Request phone callback', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: specific })).toBeVisible();
});


test('automatic email controls match the supported contract', async ({ page }) => {
  const failed: string[] = [];
  page.on('response', response => { if (response.status() >= 400 && !response.url().includes('socket.io')) failed.push(new URL(response.url()).pathname); });
  await page.goto('/helpdesk/admin/email-notifications');
  await expect(page.locator('#app')).toContainText('They are off by default');
  await page.getByRole('button', { name: 'Acknowledgement', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Email Content (required)', exact: true })).toBeVisible();
  await expect(page.getByRole('switch', { name: 'Enabled', exact: true })).toBeVisible();
  expect(failed).toEqual([]);
});
