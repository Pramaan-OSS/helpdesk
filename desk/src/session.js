export function loginLocation(path) {
  const destination = '/helpdesk' + (path === '/' ? '' : path);
  return '/login?' + new URLSearchParams({ 'redirect-to': destination });
}

export async function ensureSession(auth, path, redirect) {
  if (!auth.isLoggedIn) {
    redirect(loginLocation(path));
    return false;
  }
  try {
    await auth.init();
    return true;
  } catch (error) {
    if (error?.status !== 401) throw error;
    redirect(loginLocation(path));
    return false;
  }
}
