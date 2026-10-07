// Run from the repository root with ADMIN_STORAGE_STATE pointing to a temporary
// authenticated Playwright state. Only display names/emails are anonymized;
// requests run against the real backend without artificial delays.
const { chromium } = require('../../../frontend/node_modules/playwright');
const fs = require('node:fs');
(async () => {
  const browser = await chromium.launch({ headless: true });
  const state = JSON.parse(fs.readFileSync(process.env.ADMIN_STORAGE_STATE));
  delete state.session_id;
  const baseURL = process.env.ADMIN_BASE_URL || 'https://192.168.1.57:6443/admin';
  const host = new URL(baseURL);
  for (const cookie of state.cookies) { cookie.domain = host.hostname; cookie.secure = host.protocol === 'https:'; }
  const label = process.env.ADMIN_RECORD_LABEL || 'before';
  const context = await browser.newContext({ storageState: state, ignoreHTTPSErrors: true,
    viewport: { width: 393, height: 852 }, recordVideo: { dir: `/tmp/admin-${label}-video` } });
  const page = await context.newPage();
  await page.route('**/api/v1/**', async route => {
    const response = await route.fetch();
    let body;
    try { body = await response.json(); } catch { return route.fulfill({ response }); }
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/v1/auth/me') {
      body.email = 'admin@example.test'; body.display_name = 'Admin';
      await page.evaluate(id => localStorage.setItem(`dive-analyser:updates:v1:${id}`,
        JSON.stringify({ seen: [], lastShown: Date.now() })), body.user_id);
    }
    if (path === '/api/v1/admin/users') body.users = body.users.map((u, i) => ({ ...u,
      email: `user${i + 1}@example.test`, display_name: `User ${i + 1}` }));
    if (path === '/api/v1/admin/divers') body.divers = body.divers.map((d, i) => ({ ...d,
      display_name: `Diver ${i + 1}`, canonical_name: `diver-${i + 1}` }));
    // These header menus remain closed throughout the recording.
    await route.fulfill({ response, json: body });
  });
  await page.addInitScript(label => {
    addEventListener('DOMContentLoaded', () => {
      const badge = document.createElement('div');
      badge.style.cssText = 'position:fixed;bottom:12px;left:12px;z-index:99999;background:#102c29;color:white;padding:8px;font:14px monospace;border:1px solid #56b8a5';
      document.body.appendChild(badge);
      const start = performance.now();
      const interval = setInterval(() => {
        const ready = !!document.querySelector('button[aria-label^="Manage"]') || [...document.querySelectorAll('button')].some(b => b.textContent.trim() === 'Manage');
        badge.textContent = `${label.toUpperCase()} · ${((performance.now() - start) / 1000).toFixed(2)}s · ${ready ? 'users ready' : 'loading'}`;
        if (ready) clearInterval(interval);
      }, 20);
    });
  }, label);
  const start = Date.now();
  await page.goto(baseURL);
  await page.getByRole('button', { name: 'Manage', exact: true }).first().waitFor({ timeout: 120000 });
  console.log(JSON.stringify({ label, readyMs: Date.now() - start }));
  await page.waitForTimeout(2000);
  const video = page.video();
  await context.close();
  await video.saveAs(`/tmp/admin-${label}.webm`);
  await browser.close();
})();
