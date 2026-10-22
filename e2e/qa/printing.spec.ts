import { writeFileSync } from 'node:fs';
import { expect, test, usePersona } from '../helpers/fixtures';

usePersona('admin');

test('a ticket prints to PDF using the installed browser', async ({ page, ticket }) => {
  await page.goto(`/helpdesk/tickets/${ticket.name}`);
  const response = await page.request.get('/api/method/frappe.utils.print_format.download_pdf', {
    params: { doctype: 'HD Ticket', name: ticket.name, no_letterhead: '1' },
  });
  expect(response.status()).toBe(200);
  expect(response.headers()['content-type']).toContain('application/pdf');
  const bytes = await response.body();
  expect(bytes.subarray(0, 5).toString()).toBe('%PDF-');
  expect(bytes.length).toBeGreaterThan(1000);
  writeFileSync('.scratch/qa/ticket.pdf', bytes);
});
