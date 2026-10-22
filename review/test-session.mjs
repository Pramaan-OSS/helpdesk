import test from 'node:test';
import assert from 'node:assert/strict';
import { ensureSession, loginLocation } from '../desk/src/session.js';

test('guest root and deep links preserve one local return destination', async () => {
  for (const path of ['/', '/tickets/0075?view=activity&tab=comments']) {
    const redirects = [];
    const auth = { isLoggedIn: false, init: () => assert.fail('Guest must not fetch a profile') };
    assert.equal(await ensureSession(auth, path, url => redirects.push(url)), false);
    const url = new URL(redirects[0], 'http://localhost');
    assert.equal(url.pathname, '/login');
    assert.equal(url.searchParams.get('redirect-to'), '/helpdesk' + (path === '/' ? '' : path));
    assert.equal([...url.searchParams].length, 1);
  }
});

test('expired server session redirects even when the user cookie remains', async () => {
  const redirects = [];
  const auth = { isLoggedIn: true, init: async () => { throw { status: 401 }; } };
  assert.equal(await ensureSession(auth, '/admin/telephony', url => redirects.push(url)), false);
  assert.deepEqual(redirects, [loginLocation('/admin/telephony')]);
});

test('valid session continues and a server outage is not mistaken for sign-out', async () => {
  assert.equal(await ensureSession({ isLoggedIn: true, init: async () => {} }, '/', () => assert.fail()), true);
  const error = { status: 503 };
  await assert.rejects(ensureSession({ isLoggedIn: true, init: async () => { throw error; } }, '/', () => assert.fail()), value => value === error);
});
