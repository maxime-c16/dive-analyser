#!/usr/bin/env node
/*
 * UI council capture bundle.
 *
 * Captures every hill-climb journey at the five contract viewports against the
 * running candidate (Vite dev server of this worktree + real API proxy), then
 * writes a self-contained bundle council reviewers read directly from disk:
 *
 *   <out>/<sha>/
 *     MANIFEST.md          reviewer entry point: SHA, identity, coverage table
 *     manifest.json        machine-readable: every capture, metrics, failures
 *     shots/<scenario>/<WxH>.png        settled full-viewport captures
 *     shots/<scenario>/<WxH>.full.png   full-page captures (scrolling views)
 *     sheets/<scenario>.png             all five sizes side by side
 *
 * Reviewers no longer drive a browser: they read MANIFEST.md and the images.
 * Audio is impossible by construction (--mute-audio, media never played).
 *
 * Usage (from frontend/):
 *   node scripts/ui-council-capture.mjs login                # one-time, headed
 *   node scripts/ui-council-capture.mjs capture [--only a,b] [--sizes 390x844]
 *
 * Env: UI_COUNCIL_BASE (default http://localhost:4317)
 *      UI_COUNCIL_AUTH (default ~/.config/dive-analyser/ui-council-auth.json)
 *      UI_COUNCIL_OUT  (default <repo>/.ui-council)
 *
 * The auth file is a Playwright storage state for the owner's own session. It
 * stays outside the repository with mode 0600 and is never copied into the
 * bundle. No write API is called by `capture`.
 */
import { chromium } from '@playwright/test'
import { createHash } from 'node:crypto'
import { execSync, spawn } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const repo = path.resolve(here, '..', '..')
let BASE = process.env.UI_COUNCIL_BASE || 'http://localhost:4317'
const AUTH = process.env.UI_COUNCIL_AUTH || path.join(os.homedir(), '.config/dive-analyser/ui-council-auth.json')
const OUT = process.env.UI_COUNCIL_OUT || path.join(repo, '.ui-council')

export const SIZES = [[390, 844], [844, 390], [768, 1024], [1024, 768], [1440, 900]]

/*
 * Scenario steps run in a fresh page per size. `discover` resolves a dynamic
 * child URL (first conversation, first member, first code...) from the real
 * data, so the bundle never hard-codes private identifiers.
 */
const firstHref = (prefix, exclude, prefer) => async page => {
  await page.locator(`a[href^="${prefix}"]`).first().waitFor({ state: 'attached', timeout: 12000 }).catch(() => {})
  const hrefs = await page.locator(`a[href^="${prefix}"]`).evaluateAll(
    (nodes, ex) => nodes.map(n => n.getAttribute('href')).filter(h => h && !(ex && h.startsWith(ex))), exclude || null)
  return (prefer && hrefs.find(h => h.startsWith(prefix + prefer))) || hrefs[0] || null
}

export const SCENARIOS = [
  // Library
  { id: 'library-grid', family: 'Library', path: '/dives' },
  { id: 'library-player', family: 'Library', path: '/dives', discover: async page => {
    const r = await page.request.get(`${BASE}/api/v1/dives?limit=1`)
    if (!r.ok()) return null
    const body = await r.json()
    const first = (Array.isArray(body) ? body : body.items || body.dives || [])[0]
    return first ? `/dives?clip=${first.id}` : null
  }, settle: '[role="dialog"], .clip-viewer' },
  { id: 'library-by-code', family: 'Library', path: '/dives?view=codes' },
  { id: 'library-progress', family: 'Library', path: '/dives?view=progress' },
  // 201C is the baseline audit's reference code (409 attempts, 91 sessions).
  { id: 'code-analysis', family: 'Library', path: '/dives/analysis/201C', slow: true },
  { id: 'code-analysis-details', family: 'Library', path: '/dives/analysis/201C/details', slow: true },
  // Messages
  { id: 'messages-inbox', family: 'Messages', path: '/messages', private: true },
  { id: 'messages-thread', family: 'Messages', path: '/messages', discover: firstHref('/messages/'), private: true },
  // Community
  { id: 'community', family: 'Community', path: '/community' },
  ...['dives', 'codes', 'activity', 'achievements'].map(tab => ({
    id: `profile-${tab}`, family: 'Community', path: '/community',
    discover: async page => { const h = await firstHref('/users/')(page); return h ? `${h}?tab=${tab}` : null },
  })),
  // Calendar
  { id: 'calendar', family: 'Calendar', path: '/calendar' },
  { id: 'calendar-month', family: 'Calendar', path: '/calendar?view=month' },
  { id: 'calendar-detail', family: 'Calendar', path: '/calendar', discover: firstHref('/calendar/o/') },
  { id: 'calendar-new', family: 'Calendar', path: '/calendar/new' },
  // Evaluations
  { id: 'evaluations-my-dives', family: 'Evaluations', path: '/evaluations?tab=dives' },
  { id: 'evaluations-history', family: 'Evaluations', path: '/evaluations?tab=history' },
  { id: 'evaluations-judge', family: 'Evaluations', path: '/evaluations?tab=judge' },
  // Judge Room (lobby; live phases need a room and are captured by `room`)
  { id: 'room-lobby', family: 'Judge Room', path: '/room', settle: '.gm-home' },
]

function sha() {
  const head = execSync('git rev-parse HEAD', { cwd: repo }).toString().trim()
  const dirty = execSync('git status --porcelain -- frontend/src', { cwd: repo }).toString().trim()
  return dirty ? `${head.slice(0, 12)}-dirty` : head.slice(0, 12)
}

/*
 * --serve: production build of this worktree served by `vite preview` (which
 * reuses the dev /api and /media proxy). Pages load in about a second instead
 * of recompiling modules per navigation in dev mode. PREVIEW_PROXY_TARGET (or
 * PROXY_TARGET) must point at the real API, exactly as for the dev candidate.
 */
async function serve(port) {
  const outDir = path.join(os.tmpdir(), `ui-council-dist-${process.pid}`)
  console.log(`building worktree source into ${outDir}…`)
  execSync(`npx vite build --outDir ${outDir} --emptyOutDir --logLevel warn`, { cwd: path.join(repo, 'frontend'), stdio: 'inherit' })
  const child = spawn('npx', ['vite', 'preview', '--outDir', outDir, '--port', String(port), '--strictPort'], { cwd: path.join(repo, 'frontend'), stdio: 'ignore',
    // The preview proxy reads PREVIEW_PROXY_TARGET; capture only issues GETs.
    env: { ...process.env, PREVIEW_PROXY_TARGET: process.env.PREVIEW_PROXY_TARGET || process.env.PROXY_TARGET || 'https://localhost:6002' } })
  const url = `http://localhost:${port}`
  for (let i = 0; i < 60; i++) {
    const ok = await fetch(url).then(r => r.ok).catch(() => false)
    if (ok) return { url, stop: () => { child.kill(); fs.rmSync(outDir, { recursive: true, force: true }) } }
    await new Promise(r => setTimeout(r, 500))
  }
  child.kill(); throw new Error('vite preview did not start')
}

async function launch(headless = true) {
  // System Chrome: bundled Chromium lacks H.264, so footage would not render.
  return chromium.launch({ channel: 'chrome', headless, args: ['--mute-audio', '--autoplay-policy=user-gesture-required'] })
}

async function login() {
  const browser = await launch(false)
  const context = await browser.newContext({ viewport: { width: 1024, height: 768 } })
  const page = await context.newPage()
  await page.goto(`${BASE}/login`)
  console.log('Sign in with your own account in the opened window…')
  for (;;) {
    const r = await page.request.get(`${BASE}/api/v1/auth/me`).catch(() => null)
    if (r && r.ok()) { const me = await r.json(); console.log(`Signed in as ${me.display_name}`); break }
    await page.waitForTimeout(1500)
  }
  fs.mkdirSync(path.dirname(AUTH), { recursive: true })
  await context.storageState({ path: AUTH })
  fs.chmodSync(AUTH, 0o600)
  console.log(`Session saved to ${AUTH} (0600, outside the repository).`)
  await browser.close()
}

/*
 * Settled = API quiet for 600 ms (the app polls and keeps sockets open, so
 * Playwright's networkidle never fires), fonts loaded, no visible loader,
 * then one more frame. Media byte ranges and dev-server modules are ignored.
 */
function trackRequests(page) {
  const inflight = new Set()
  let last = Date.now()
  const relevant = r => { const u = r.url(); return !u.includes('/media/') && !u.includes('/@') && !u.includes('/node_modules/') && !/\.(mp4|webm|m4s|mov)(\?|$)/.test(u) && r.resourceType() !== 'websocket' && r.resourceType() !== 'media' }
  page.on('request', r => { if (relevant(r)) { inflight.add(r); last = Date.now() } })
  const done = r => { if (inflight.delete(r)) last = Date.now() }
  page.on('requestfinished', done); page.on('requestfailed', done)
  page.quiet = async (ms = 600, cap = 10000) => {
    const start = Date.now()
    while (Date.now() - start < cap) { if (!inflight.size && Date.now() - last >= ms) return true; await page.waitForTimeout(100) }
    return false
  }
}

async function settle(page, selector, slow = false) {
  if (selector) await page.locator(selector).first().waitFor({ timeout: 10000 }).catch(() => {})
  const quiet = await page.quiet()
  await page.evaluate(() => document.fonts.ready)
  const busy = '[aria-busy="true"], .skeleton, [class*="skeleton"], .page-loading, .eval-warmup'
  await page.waitForFunction(sel => ![...document.querySelectorAll(sel)].some(n => n.getClientRects().length), busy, { timeout: slow ? 45000 : 8000 }).catch(() => {})
  await page.quiet(300, 3000)
  await page.waitForTimeout(250)
  return quiet
}

async function metrics(page) {
  return page.evaluate(() => {
    const doc = document.documentElement
    const overflowing = [...document.querySelectorAll('body *')].filter(n => {
      const r = n.getBoundingClientRect(); return r.width > 0 && r.right > doc.clientWidth + 1
    }).slice(0, 5).map(n => n.tagName.toLowerCase() + (n.className && typeof n.className === 'string' ? '.' + n.className.trim().split(/\s+/).slice(0, 2).join('.') : ''))
    const loaders = [...document.querySelectorAll('[aria-busy="true"], [class*="skeleton"], .page-loading, .eval-warmup')].filter(n => n.getClientRects().length).length
    const videos = [...document.querySelectorAll('video')].map(v => ({ ready: v.readyState, paused: v.paused, muted: v.muted }))
    const h1 = document.querySelector('h1')?.textContent?.trim() || null
    const smallTargets = [...document.querySelectorAll('button, a, [role="button"], input, select')].filter(n => {
      const r = n.getBoundingClientRect(); return r.width > 0 && r.height > 0 && (r.width < 24 || r.height < 24)
    }).length
    return { url: location.pathname + location.search, h1, horizontalOverflow: doc.scrollWidth > doc.clientWidth, overflowing, scrollHeight: doc.scrollHeight, loadersVisible: loaders, videos, smallTargets }
  })
}

async function capture(args) {
  if (!fs.existsSync(AUTH)) throw new Error(`No session at ${AUTH}. Run: node scripts/ui-council-capture.mjs login`)
  const only = args.only ? new Set(args.only.split(',')) : null
  const sizes = args.sizes ? args.sizes.split(',').map(s => s.split('x').map(Number)) : SIZES
  const scenarios = SCENARIOS.filter(s => !only || only.has(s.id) || only.has(s.family))
  const sourceHash = createHash('sha256')
  for (const name of execSync('git ls-files --cached --others --exclude-standard frontend', { cwd: repo }).toString().trim().split('\n').sort()) {
    if (fs.existsSync(path.join(repo, name))) sourceHash.update(name).update(fs.readFileSync(path.join(repo, name)))
  }
  const rev = `${sha()}-${sourceHash.digest('hex').slice(0, 12)}-${Date.now()}`
  const server = args.serve ? await serve(Number(args.port || 4318)) : null
  if (server) BASE = server.url
  try { await run(args, rev, scenarios, sizes) } finally { server?.stop() }
}

async function run(args, rev, scenarios, sizes) {
  const dir = path.join(OUT, rev)
  fs.mkdirSync(path.join(dir, 'shots'), { recursive: true })
  fs.mkdirSync(path.join(dir, 'sheets'), { recursive: true })

  const browser = await launch(true)
  const probe = await browser.newContext({ storageState: AUTH })
  const meRes = await probe.request.get(`${BASE}/api/v1/auth/me`)
  if (!meRes.ok()) throw new Error(`Saved session rejected (auth/me ${meRes.status()}). Run login again.`)
  const me = await meRes.json()
  if (me.display_name !== 'maxime') throw new Error('Expected owner maxime; refusing to capture another account')
  await probe.close()
  console.log(`candidate ${BASE} · source ${rev} · signed in as ${me.display_name}`)

  const results = []
  const started = Date.now()
  // Warm the server once so parallel first loads do not time out.
  const warm = await browser.newPage(); await warm.goto(BASE + '/dives', { timeout: 90000 }).catch(() => {}); await warm.close()
  // One context per size; a small pool of pages per context.
  const pool = Number(args.pages || 2)
  await Promise.all(sizes.map(async ([w, h]) => {
    const context = await browser.newContext({ storageState: AUTH, viewport: { width: w, height: h }, deviceScaleFactor: 2,
      reducedMotion: 'reduce', isMobile: w < 900 && h > w, hasTouch: w < 1100 })
    const queue = [...scenarios]
    await Promise.all(Array.from({ length: pool }, async () => { for (let sc; (sc = queue.shift());) {
      // Transient host network changes and upstream 5xx happen; retry twice
      // and record every attempt so a retry never hides a real failure.
      let rec
      const attempts = []
      for (let attempt = 1; attempt <= 3; attempt++) {
        rec = await captureOne(context, sc, w, h, dir)
        rec.attempt = attempt
        attempts.push({ ...rec })
        if (rec.status === 'ok') break
        if (attempt < 3) rec.retried = true
      }
      rec.attempts = attempts
      results.push(rec)
      process.stdout.write(`${rec.status === 'ok' ? '.' : rec.status[0].toUpperCase()}`)
    } }))
    await context.close()
  }))
  console.log(`\n${results.length} captures in ${Math.round((Date.now() - started) / 1000)} s`)

  await contactSheets(browser, dir, scenarios, sizes)
  await browser.close()
  writeManifest(dir, rev, me, scenarios, sizes, results)
  console.log(`Bundle: ${path.join(dir, 'MANIFEST.md')}`)
}

async function captureOne(context, sc, w, h, dir) {
  const page = await context.newPage()
  trackRequests(page)
  await page.route('**/api/**', route => ['GET', 'HEAD', 'OPTIONS'].includes(route.request().method()) ? route.continue() : route.abort('blockedbyclient'))
  const errors = []; const failed = []
  page.on('pageerror', e => errors.push(String(e.message).slice(0, 200)))
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text().slice(0, 200)) })
  page.on('response', r => { if (r.status() >= 400 && r.url().includes('/api/')) failed.push(`${r.status()} ${new URL(r.url()).pathname}`) })
  const rec = { scenario: sc.id, family: sc.family, size: `${w}x${h}`, status: 'ok' }
  try {
    await page.goto(BASE + sc.path, { waitUntil: 'domcontentloaded', timeout: 30000 })
    if (sc.discover) {
      await settle(page)
      const target = await sc.discover(page)
      if (!target) throw new Error('no data to open this child view')
      await page.goto(BASE + target, { waitUntil: 'domcontentloaded', timeout: 30000 })
    }
    await settle(page, sc.settle, sc.slow)
    if (sc.settle && !await page.locator(sc.settle).first().isVisible()) throw new Error('required scenario element missing')
    if (new URL(page.url()).pathname === '/login') throw new Error('session redirected to login')
    const m = await metrics(page)
    if (m.loadersVisible) throw Object.assign(new Error('loader still visible'), { unsettled: true, m })
    const sub = path.join(dir, 'shots', sc.id); fs.mkdirSync(sub, { recursive: true })
    await page.screenshot({ path: path.join(sub, `${w}x${h}.png`), animations: 'disabled', caret: 'hide' })
    const full = m.scrollHeight > h * 1.2
    if (full) await page.screenshot({ path: path.join(sub, `${w}x${h}.full.png`), fullPage: true, clip: { x: 0, y: 0, width: w, height: Math.min(m.scrollHeight, h * 4) }, animations: 'disabled', caret: 'hide' })
    Object.assign(rec, m, { full })
  } catch (e) {
    rec.status = e.unsettled ? 'unsettled' : 'failed'; rec.error = String(e.message).split('\n')[0]
    if (e.m) Object.assign(rec, e.m)
  }
  rec.consoleErrors = errors.slice(0, 5); rec.apiFailures = [...new Set(failed)].slice(0, 5)
  await page.close()
  return rec
}

/* One image per scenario with the five sizes at a common height, labelled. */
async function contactSheets(browser, dir, scenarios, sizes) {
  const page = await browser.newPage({ viewport: { width: 2400, height: 800 } })
  for (const sc of scenarios) {
    const cells = sizes.map(([w, h]) => {
      const file = path.join(dir, 'shots', sc.id, `${w}x${h}.png`)
      if (!fs.existsSync(file)) return `<figure><div class="miss">${w}×${h}<br>not captured</div><figcaption>${w}×${h}</figcaption></figure>`
      const src = `data:image/png;base64,${fs.readFileSync(file).toString('base64')}`
      return `<figure><img src="${src}" style="height:${Math.round(700 * Math.min(1, h / 1024))}px"><figcaption>${w}×${h}</figcaption></figure>`
    }).join('')
    await page.setContent(`<html><body style="margin:0;background:#222;color:#eee;font:14px system-ui;display:flex;gap:16px;align-items:flex-end;padding:16px;width:max-content">
      <style>figure{margin:0;text-align:center}img{display:block;border:1px solid #555}.miss{width:200px;height:300px;border:1px dashed #a55;display:grid;place-items:center}</style>${cells}</body></html>`)
    await page.locator('body').screenshot({ path: path.join(dir, 'sheets', `${sc.id}.png`) })
  }
  await page.close()
}

function writeManifest(dir, rev, me, ran, sizes, fresh) {
  // A partial run (--only) refreshes its scenarios and keeps the rest.
  const prior = fs.existsSync(path.join(dir, 'manifest.json')) ? JSON.parse(fs.readFileSync(path.join(dir, 'manifest.json'))) : null
  const rerun = new Set(fresh.map(r => `${r.scenario}@${r.size}`))
  const results = [...(prior?.captures || []).filter(r => !rerun.has(`${r.scenario}@${r.size}`)), ...fresh]
  const scenarios = SCENARIOS.filter(s => results.some(r => r.scenario === s.id) || ran.includes(s))
  const key = r => `${r.scenario}@${r.size}`
  const byKey = new Map(results.map(r => [key(r), r]))
  const json = { candidate: BASE, source: rev, identity: me.display_name, capturedAt: new Date().toISOString(),
    sizes: sizes.map(([w, h]) => `${w}x${h}`), scenarios: scenarios.map(s => ({ id: s.id, family: s.family, path: s.path, private: !!s.private })), captures: results }
  fs.writeFileSync(path.join(dir, 'manifest.json'), JSON.stringify(json, null, 2))
  const cell = r => !r ? '—' : r.status === 'ok' ? (r.horizontalOverflow ? 'ok ⚠overflow' : 'ok') : r.status
  const lines = [
    `# UI council bundle — ${rev}`, '',
    `Candidate ${BASE}, worktree source ${rev}, signed in as **${me.display_name}** (owner session, real API data). Captured ${json.capturedAt}.`, '',
    'Every image is an unretouched Playwright capture after bounded network quiet waiting, fonts loaded and no visible loader. `sheets/<id>.png` shows the five sizes together; `shots/<id>/<WxH>.png` is the exact viewport and `.full.png` the full scroll height when the page scrolls.', '',
    'Messages captures contain private conversation text: evaluate the UI, never quote message content.', '',
    `| Scenario | Family | ${sizes.map(([w, h]) => `${w}×${h}`).join(' | ')} |`,
    `|---|---|${sizes.map(() => '---').join('|')}|`,
    ...scenarios.map(s => `| [${s.id}](sheets/${s.id}.png) | ${s.family} | ${sizes.map(([w, h]) => cell(byKey.get(`${s.id}@${w}x${h}`))).join(' | ')} |`), '',
    '## Issues detected automatically', '',
    ...results.filter(r => r.status !== 'ok' || r.horizontalOverflow || r.apiFailures?.length || r.consoleErrors?.length)
      .map(r => `- ${r.scenario} @ ${r.size}: ${[r.status !== 'ok' && `${r.status}${r.error ? ` (${r.error})` : ''}`, r.horizontalOverflow && `horizontal overflow (${r.overflowing.join(', ')})`, r.apiFailures?.length && `API ${r.apiFailures.join(', ')}`, r.consoleErrors?.length && `${r.consoleErrors.length} console errors`].filter(Boolean).join('; ')}`),
    '', 'Not captured by this bundle (interactive, needs a live room or a write): Judge Room playback/scoring/reveal/results, judging submission. See the coordinator notes for those.',
  ]
  fs.writeFileSync(path.join(dir, 'MANIFEST.md'), lines.join('\n') + '\n')
}

const [cmd, ...rest] = process.argv.slice(2)
const args = {}
for (let i = 0; i < rest.length; i++) {
  const k = rest[i].replace(/^--/, '')
  if (rest[i + 1] && !rest[i + 1].startsWith('--')) args[k] = rest[++i]; else args[k] = true
}
if (cmd === 'login') await login()
else if (cmd === 'capture') await capture(args)
else { console.log('usage: ui-council-capture.mjs login | capture [--serve] [--port 4318] [--pages 2] [--only ids|families] [--sizes 390x844,...]'); process.exit(1) }
