import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { skipGettingStarted } from './helpers/fixtures';

test.use({ headless: true });

test('private attachment summary requires estimate approval, copies text and never writes a note', async ({ page, context, baseURL }) => {
  const login = JSON.parse(readFileSync('.runtime/outcomes-browser-user.json', 'utf8'));
  const ticket = { name: login.ticket };
  const commentCount = () => Number(execFileSync(resolve('.venv/bin/python'),
    ['-m', 'frappe.utils.bench_helper', 'frappe', '--site', 'pramaan.localhost', 'execute', 'helpdesk.test_utils.outcome_browser_comment_count'],
    { cwd: resolve('.runtime/bench/sites'), env: { ...process.env, FRAPPE_PRELOAD_DATABASE_DRIVERS: 'none' }, encoding: 'utf8' }).trim());
  const commentsBefore = commentCount();
  const socket = new URL(baseURL!);
  socket.port = String(JSON.parse(readFileSync('.runtime/bench/sites/common_site_config.json', 'utf8')).socketio_port);
  const ownedOrigins = new Set([new URL(baseURL!).origin, socket.origin]);
  const outside: string[] = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (!ownedOrigins.has(url.origin) && ['http:', 'https:'].includes(url.protocol)) outside.push(url.origin);
  });
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.request.post('/api/method/login', { form: { usr: login.user, pwd: login.password } });
  await skipGettingStarted(page, login.user);
  await page.addInitScript(() => localStorage.setItem('helpdesk_persona_captured', '1'));
  await page.goto(`/helpdesk/tickets/${ticket.name}`);
  await page.getByText('Pramaan assistance', { exact: true }).click();
  await page.getByLabel('Attachment', { exact: true }).selectOption(login.file_name);
  await page.getByRole('button', { name: 'Summarise attachment', exact: true }).click();
  await expect(page.getByText('Worst-case Pramaan outcome cost: $0.012345', { exact: true })).toBeVisible();
  await expect(page.getByText('Read the attachment text', { exact: true })).toBeVisible();
  await page.screenshot({ path: '.runtime/outcomes-attachment-estimate.png', fullPage: true });
  const events = () => JSON.parse(readFileSync('.runtime/outcomes-browser-requests.json', 'utf8'));
  expect(events().filter((event: any) => event.method === 'POST' && event.path === '/v1/outcomes/document.summarize')).toHaveLength(0);
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await page.getByRole('button', { name: 'Summarise attachment', exact: true }).click();
  await page.getByRole('button', { name: 'Approve and summarise', exact: true }).click();
  await expect(page.getByLabel('Attachment summary', { exact: true })).toHaveValue(/The private attachment describes the support request/);
  await page.getByRole('button', { name: 'Copy summary', exact: true }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain('Check the supplied details.');
  expect(events().filter((event: any) => event.method === 'POST' && event.path === '/v1/outcomes/document.summarize')).toHaveLength(1);
  expect(commentCount()).toBe(commentsBefore);
  expect(outside).toEqual([]);
  await page.screenshot({ path: '.runtime/outcomes-attachment.png', fullPage: true });
});
