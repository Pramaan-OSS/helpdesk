import { expect, test, uid, usePersona } from '../helpers/fixtures';
usePersona('admin');

test('callback and browser phone show a plain unavailable message', async ({ page, api, ticket }) => {
  const settings = await api.get('HD Settings', 'HD Settings');
  const user = await api.get('User', 'Administrator');
  try {
    await api.update('HD Settings', 'HD Settings', { pramaan_calling_number: '+15555550100' });
    await api.update('User', 'Administrator', { pramaan_callback_number: '+15555550101' });
    await page.goto(`/helpdesk/tickets/${ticket.name}`);
    await page.getByText('Pramaan assistance', { exact: true }).click();
    await page.getByLabel('Customer phone', { exact: true }).fill('+15555550102');
    await page.getByRole('button', { name: 'Request phone callback', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('not available yet');
    await page.getByRole('button', { name: 'Browser calling', exact: true }).click();
    const panel = page.getByText('Phone', { exact: true }).locator('../..');
    await expect(panel).toContainText('not available yet');
    await expect(page.locator('body')).not.toContainText(/Traceback|\/Users\//);
  } finally {
    await api.update('HD Settings', 'HD Settings', { pramaan_calling_number: settings.pramaan_calling_number || '' });
    await api.update('User', 'Administrator', { pramaan_callback_number: user.pramaan_callback_number || '' });
  }
});

test('customer and contact suggestions require review and never overwrite saved details', async ({ page, api }) => {
  const customer = await api.insert('HD Customer', { customer_name: `Review ${uid()}`, domain: 'example.test' });
  const contact = await api.insert('Contact', { first_name: `Review ${uid()}`, email_ids: [{ email_id: `${uid()}@example.test`, is_primary: 1 }] });
  for (const [route, record, found] of [['customers', customer, 'Local fixture company'], ['contacts', contact, 'Local fixture contact']] as const) {
    await page.goto(`/helpdesk/${route}/${encodeURIComponent(record.name)}`);
    await page.getByRole('button', { name: 'Suggest details', exact: true }).click();
    await expect(page.getByText(found, { exact: true })).toBeVisible();
    await expect(page.getByText(/Your saved details have not changed/)).toBeVisible();
  }
  expect((await api.get('HD Customer', customer.name)).customer_name).toBe(customer.customer_name);
  expect((await api.get('Contact', contact.name)).first_name).toBe(contact.first_name);
});

test('a documentation draft stays in the editor until saved', async ({ page, api }) => {
  const category = await api.insert('HD Article Category', { category_name: `Draft ${uid()}` });
  const before = (await api.list('HD Article', { filters: { category: category.name } })).length;
  await page.goto(`/helpdesk/articles/new/${category.name}`);
  await page.getByText('Draft from documentation', { exact: true }).click();
  await page.getByLabel('Public documentation page', { exact: true }).fill('https://example.test/docs');
  await page.getByRole('button', { name: 'Suggest article', exact: true }).click();
  await expect(page.locator('.ProseMirror')).toContainText('Suggested support text for review.');
  expect((await api.list('HD Article', { filters: { category: category.name } })).length).toBe(before);
});
