// Real prod frontend via Funnel, e2e session. Requests are unmodified by default.
// PROBE_ABORT_STATUS=1 reproduces the historical audit workaround only.
const { chromium } = require(process.env.PW_PATH);
const fs = require('fs');
const BASE = process.env.BASE, COOKIE = process.env.DA_COOKIE;
const fixture = process.env.PROBE_FIXTURE ? JSON.parse(fs.readFileSync(process.env.PROBE_FIXTURE)) : null;
const STATUS_RE = /\/api\/v1\/media\/[^/]+\/status$/;
const init = () => {
  window.__marks = {};
  performance.setResourceTimingBufferSize(5000);
  const mark = (k) => { if (!(k in window.__marks)) window.__marks[k] = Math.round(performance.now()); };
  new MutationObserver(() => {
    if (document.querySelector('[data-thumbhash="ready"]')) requestAnimationFrame(() => requestAnimationFrame(() => mark('first_color')));
    for (const img of document.querySelectorAll('img[src*="/media/cache/"]')) {
      mark('first_poster_in_dom');
      if (img.complete && img.naturalWidth) mark('first_poster_loaded');
      else img.addEventListener('load', () => mark('first_poster_loaded'), { once: true });
    }
    if (document.querySelector('video[src*="/media/cache/"]')) mark('first_video_tile_in_dom');
    if (document.querySelector('[data-testid], main button img, main button video') ) mark('first_tile_media_in_dom');
  }).observe(document, { subtree: true, childList: true, attributes: true });
  try { new PerformanceObserver(l => { for (const e of l.getEntries()) window.__marks.lcp = Math.round(e.startTime); }).observe({ type: 'largest-contentful-paint', buffered: true }); } catch {}
};
async function run(browser, label, viewport, warm) {
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: viewport.width < 500 ? 3 : 2, ignoreHTTPSErrors: true });
  if (COOKIE) await ctx.addCookies([{ name: 'da_session', value: COOKIE, domain: new URL(BASE).hostname, path: '/', secure: true, httpOnly: true, sameSite: 'Strict' }]);
  await ctx.addInitScript(init);
  if (fixture) {
    await ctx.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname;
      const file = fixture.files[path];
      if (file) {
        await new Promise(r => setTimeout(r, Number(process.env.MEDIA_DELAY_MS || 1080)));
        return route.fulfill({ body: fs.readFileSync(file.path), contentType: file.type });
      }
      const before = process.env.PROBE_VARIANT === 'before';
      const clean = row => { const copy = {...row}; if (before) { delete copy.thumbhash; delete copy.thumb_url; } return copy; };
      let body = [];
      if (path.endsWith('/auth/me')) body = {user_id: 1, email:'synthetic@example.invalid', display_name:'Synthetic', role:'owner', divers:[{diver_id:1,access_kind:'owner'}]};
      else if (path.endsWith('/dives/library')) body = {items:fixture.items.map(clean),next_cursor:null};
      else if (path.endsWith('/divers')) body = [{id:1,display_name:'Synthetic',is_primary_user:true}];
      else if (path.endsWith('/status/batch')) body = Object.fromEntries(Object.entries(fixture.batch).map(([k,v])=>[k,clean(v)]));
      else if (path.endsWith('/unread-count')) body = {count:0};
      else if (path.endsWith('/updates')) body = {notes:[]};
      return route.fulfill({json:body});
    });
  } else if (process.env.PROBE_ABORT_STATUS === '1') await ctx.route(STATUS_RE, r => r.abort());
  const page = await ctx.newPage();
  const results = [];
  for (const phase of warm ? ['cold', 'warm'] : ['cold']) {
    const reqs = [];
    const onFin = async (req) => { const t = req.timing(); let size = 0; try { size = (await req.sizes()).responseBodySize; } catch {} reqs.push({ url: req.url(), t, size, type: req.resourceType() }); };
    const onFail = (req) => reqs.push({ url: req.url(), failed: req.failure()?.errorText, type: req.resourceType() });
    page.on('requestfinished', onFin); page.on('requestfailed', onFail);
    const t0 = Date.now();
    await page.goto(BASE + '/dives', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(Number(process.env.PROBE_WAIT_MS || 8000));
    const marks = await page.evaluate(() => window.__marks);
    page.off('requestfinished', onFin); page.off('requestfailed', onFail);
    if (!marks.first_color && marks.first_poster_loaded) marks.first_color = marks.first_poster_loaded;
    const nav = await page.evaluate(() => { const n = performance.getEntriesByType('navigation')[0]; return { ttfb: Math.round(n.responseStart), dcl: Math.round(n.domContentLoadedEventEnd) }; });
    const ent = await page.evaluate(() => performance.getEntriesByType('resource').map(e => ({ n: e.name, s: Math.round(e.startTime), e: Math.round(e.responseEnd), b: e.encodedBodySize, tr: e.transferSize })));
    const pick = (re) => ent.filter(e => re.test(e.n)).sort((a, b) => a.s - b.s)[0];
    const key = { me: pick(/auth\/me/), library: pick(/dives\/library/), divers: pick(/\/divers$/), batch: pick(/status\/batch/), js: pick(/assets\/index-.*\.js/) };
    const posters = ent.filter(e => /media\/cache\/(signed\/|\d+\/(play|thumb))/.test(e.n));
    const visibleUrls = await page.evaluate(() => [...document.querySelectorAll('img[src*="/media/cache/"]')].filter(img => {
      const r = img.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth;
    }).map(img => img.currentSrc || img.src));
    const visiblePosters = posters.filter(e => visibleUrls.includes(e.n));
    const first5s = ent.filter(e => e.s < 5000);
    const norm = u => u.replace(BASE, '').replace(/[0-9a-f-]{36}/gi, '{uuid}').replace(/\/\d+(\/|$|\?)/g, '/{id}$1').replace(/\?.*/, '');
    results.push({ label, phase, viewport: `${viewport.width}x${viewport.height}`, nav, marks,
      key: Object.fromEntries(Object.entries(key).map(([k, v]) => [k, v ? { start: v.s, end: v.e, dur: v.e - v.s, bytes: v.tr } : null])),
      visible_media_count: new Set(visibleUrls).size, visible_media_bytes: visiblePosters.reduce((s,e)=>s+(e.tr || 0),0),
      media_cache_requests: posters.length, media_cache_bytes: posters.reduce((s, e) => s + (e.tr || 0), 0),
      media_cache_first_end: posters.length ? Math.min(...posters.map(e => e.e)) : null,
      media_cache_last_end_before_8s: posters.length ? Math.max(...posters.map(e => e.e)) : null,
      requests_first_5s: first5s.length, bytes_first_5s: first5s.reduce((s, e) => s + (e.tr || 0), 0),
      aborted_status_calls: reqs.filter(r => r.failed && STATUS_RE.test(r.url)).length,
      api_paths: [...new Set(ent.filter(e => e.n.includes('/api/')).map(e => norm(e.n)))].sort() });
  }
  await ctx.close();
  return results;
}
(async () => {
  const browser = await chromium.launch({ channel: 'chrome' });
  const out = [];
  out.push(...await run(browser, 'desktop', { width: 1280, height: 800 }, true));
  out.push(...await run(browser, 'desktop', { width: 1280, height: 800 }, true));
  out.push(...await run(browser, 'phone', { width: 390, height: 844 }, true));
  console.log(JSON.stringify(out, null, 1));
  await browser.close();
})();
