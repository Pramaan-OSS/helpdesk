import { expect, test, usePersona } from '../helpers/fixtures';
usePersona('admin');

test('the page opens one same-origin live-update connection after setup', async ({ page, baseURL }) => {
  const starts: string[] = [];
  let setupComplete = false;
  const earlyRequests: string[] = [];
  page.on('response', response => { if (response.url().endsWith('get_context_for_dev') && response.ok()) setupComplete = true; });
  page.on('request', request => {
    const url = new URL(request.url());
    if (process.env.QA_MODE === 'development' && /get_user$|get_translations$/.test(url.pathname) && !setupComplete) earlyRequests.push(url.pathname);
    if (url.pathname === '/socket.io/' && url.searchParams.get('transport') === 'polling' && !url.searchParams.has('sid')) starts.push(url.origin);
  });
  await page.goto('/helpdesk/tickets');
  await expect.poll(() => page.locator('#app').evaluate((element: any) => element.__vue_app__?.config.globalProperties.$socket?.connected)).toBe(true);
  expect(starts).toEqual([new URL(baseURL!).origin]);
  expect(earlyRequests).toEqual([]);
});

test('a foreign origin cannot open live updates', async ({ page }) => {
  const headers = { Origin: 'https://foreign.example.test', 'Content-Type': 'text/plain;charset=UTF-8' };
  const path = '/socket.io/?EIO=4&transport=polling';
  const opened = await page.request.get(path, { headers });
  const packet = await opened.text();
  expect(packet[0]).toBe('0');
  const sid = JSON.parse(packet.slice(1)).sid;
  const session = `${path}&sid=${encodeURIComponent(sid)}`;
  try {
    await page.request.post(session, { headers, data: '40/qa-helpdesk.localhost,' });
    const response = await page.request.get(session, { headers });
    expect(await response.text()).toContain('Invalid origin');
  } finally {
    await page.request.post(session, { headers, data: '1' });
  }
});
