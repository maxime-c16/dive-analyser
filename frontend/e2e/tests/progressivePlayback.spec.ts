import { test, expect } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import http from 'node:http'
let mediaServer: http.Server
let mediaBase = ''

// External, uncommitted test media: an AAC preview and an H.264 original
// without an audio track. This reproduces the audio handoff failure without
// depending on production credentials or browser-specific original codecs.
const previewPath = process.env.PLAYBACK_PREVIEW_FILE || path.resolve('.codex-playback-fixtures/preview.mp4')
const originalPath = process.env.PLAYBACK_ORIGINAL_FILE || path.resolve('.codex-playback-fixtures/original.mov')
test.beforeAll(async () => {
  mediaServer = http.createServer((request, response) => {
    if (request.url?.includes('/media/revisions/')) {
      setTimeout(() => { response.writeHead(302, { Location: '/original.mov', 'Cache-Control': 'private, no-store' }); response.end() }, 1000)
      return
    }
    const bytes = fs.readFileSync(request.url === '/original.mov' ? originalPath : previewPath)
    const range = request.headers.range?.match(/bytes=(\d+)-(\d*)/)
    const start = range ? Number(range[1]) : 0
    const end = range?.[2] ? Math.min(Number(range[2]), bytes.length - 1) : bytes.length - 1
    response.writeHead(range ? 206 : 200, { 'Content-Type': 'video/mp4', 'Accept-Ranges': 'bytes',
      'Content-Length': end - start + 1, 'Cache-Control': 'private, max-age=3600',
      ...(range ? { 'Content-Range': `bytes ${start}-${end}/${bytes.length}` } : {}) })
    response.end(bytes.subarray(start, end + 1))
  })
  await new Promise<void>(resolve => mediaServer.listen(0, '127.0.0.1', resolve))
  mediaBase = `http://127.0.0.1:${(mediaServer.address() as { port: number }).port}`
})
test.afterAll(async () => { mediaServer.closeAllConnections(); await new Promise<void>(resolve => mediaServer.close(() => resolve())) })
const status = (uuid: string) => ({
  video_uuid: uuid, status: 'ready', can_request: false, available_renditions: ['proxy_360p'],
  playback_url: `${mediaBase}/api/v1/media/revisions/${uuid}/play`,
  cache_entries: [{ rendition: 'proxy_360p', playback_url: `${mediaBase}/api/v1/media/cache/${uuid}/play` }],
})
test.beforeEach(async ({ page }) => {
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url())
    const pathname = url.pathname
    if (pathname === '/api/v1/auth/me') return route.fulfill({ json: { user_id: 1, email: 'fixture@example.test', role: 'owner', divers: [] } })
    if (pathname.endsWith('/media/status/batch')) {
      const { video_uuids } = route.request().postDataJSON()
      return route.fulfill({ json: Object.fromEntries(video_uuids.map((uuid: string) => [uuid, status(uuid)])) })
    }
    if (pathname.endsWith('/status')) return route.fulfill({ json: status(pathname.split('/').at(-2)!) })
    if (url.origin === mediaBase) return route.continue()
    return route.fulfill({ json: { liked: false, like_count: 0, comment_count: 0, items: [], active_count: 0 } })
  })
  await page.goto('/e2e/fixtures/playback-regression.html')
})
const visibleVideo = '[role=dialog] video:not([aria-hidden])'
test('starts from the prepared preview, upgrades HQ and keeps AAC continuous', async ({ page }) => {
  await page.getByRole('button', { name: 'Open dive' }).focus()
  await page.waitForTimeout(700)
  const opened = Date.now()
  await page.getByRole('button', { name: 'Open dive' }).click()
  await expect.poll(() => page.locator(visibleVideo).evaluate((v: HTMLVideoElement) => v.currentTime)).toBeGreaterThan(0.15)
  expect(Date.now() - opened).toBeLessThan(1500)
  await expect.poll(() => page.locator(visibleVideo).evaluate((v: HTMLVideoElement) => v.videoWidth)).toBe(1080)
  // Restore browser-blocked startup sound with a genuine control gesture.
  const unmute = page.getByRole('button', { name: 'Unmute video', exact: true })
  if (await unmute.count()) await unmute.click()
  await expect.poll(() => page.locator('video[aria-hidden]').evaluate((v: HTMLVideoElement) => !v.muted && !v.paused)).toBe(true)
  await page.evaluate(() => {
    const audio = document.querySelector<HTMLVideoElement>('video[aria-hidden]')!
    ;(window as any).__audioSeeks = []
    audio.addEventListener('seeking', () => (window as any).__audioSeeks.push(audio.currentTime))
  })
  await page.waitForTimeout(3000)
  const seekPositions = await page.evaluate(() => (window as any).__audioSeeks as number[])
  expect(seekPositions.filter(time => time > 0.1)).toHaveLength(0)
  await page.getByRole('button', { name: 'Pause video', exact: true }).last().click()
  await expect.poll(() => page.locator('video[aria-hidden]').evaluate((v: HTMLVideoElement) => v.paused)).toBe(true)
  await page.getByRole('button', { name: 'Play video', exact: true }).last().click()
  await expect.poll(() => page.locator('video[aria-hidden]').evaluate((v: HTMLVideoElement) => v.paused)).toBe(false)
  await page.getByRole('combobox', { name: 'Playback speed' }).selectOption('0.5')
  await expect.poll(() => page.locator('video[aria-hidden]').evaluate((v: HTMLVideoElement) => v.playbackRate)).toBe(0.5)
  await page.getByRole('button', { name: 'Mute video', exact: true }).click()
  await expect.poll(() => page.locator('video[aria-hidden]').evaluate((v: HTMLVideoElement) => v.muted)).toBe(true)
})
test('prepared next and previous dives start without waiting for the original redirect', async ({ page }) => {
  await page.getByRole('button', { name: 'Open dive' }).click()
  await expect.poll(() => page.locator(visibleVideo).evaluate((v: HTMLVideoElement) => v.currentTime)).toBeGreaterThan(0.2)
  await page.waitForTimeout(1000)
  for (const direction of ['Next', 'Previous']) {
    await page.evaluate(() => {
      const previous = document.querySelector('[role=dialog] video:not([aria-hidden])')
      const state = { start: 0, frame: 0 }
      ;(window as any).__navigation = state
      document.addEventListener('click', () => {
        state.start = performance.now()
        const observe = new MutationObserver(() => {
          const video = document.querySelector<HTMLVideoElement>('[role=dialog] video:not([aria-hidden])')
          if (!video || video === previous || state.frame) return
          video.requestVideoFrameCallback(() => { if (!state.frame) state.frame = performance.now() - state.start })
        })
        observe.observe(document.querySelector('[role=dialog]')!, { childList: true, subtree: true })
        setTimeout(() => observe.disconnect(), 2000)
      }, { once: true, capture: true })
    })
    await page.getByRole('button', { name: direction, exact: true }).click()
    await expect.poll(() => page.locator(visibleVideo).evaluate((v: HTMLVideoElement) => v.currentTime)).toBeGreaterThan(0.15)
    await expect.poll(() => page.evaluate(() => (window as any).__navigation.frame)).toBeGreaterThan(0)
    expect(await page.evaluate(() => (window as any).__navigation.frame)).toBeLessThan(1000)
    await expect(page.getByTestId('clip-cover')).toHaveCount(0)
  }
})

test('returning to a loaded dive keeps the same HQ element and soundtrack', async ({ page }, info) => {
  await page.getByRole('button', { name: 'Open dive' }).click()
  await expect.poll(() => page.locator(visibleVideo).evaluate((v: HTMLVideoElement) => v.videoWidth)).toBe(1080)
  await page.evaluate(() => { (window as any).__loadedHQ = document.querySelector('[role=dialog] video:not([aria-hidden])') })
  const navigate = async (direction: 'Next' | 'Previous') => {
    if (!info.project.use.isMobile) {
      await page.getByRole('button', { name: direction, exact: true }).click()
      return
    }
    // Exercise the feed drag itself on the mobile layout.
    const box = await page.locator('.clip-gesture').boundingBox()
    expect(box).not.toBeNull()
    const x = box!.x + box!.width / 2
    const from = box!.y + box!.height * (direction === 'Next' ? 0.7 : 0.3)
    const to = box!.y + box!.height * (direction === 'Next' ? 0.3 : 0.7)
    await page.mouse.move(x, from)
    await page.mouse.down()
    await page.mouse.move(x, to, { steps: 6 })
    await page.mouse.up()
  }
  await navigate('Next')
  await expect(page.locator(visibleVideo)).toHaveAttribute('src', /playback-2/)
  await expect.poll(() => page.locator(visibleVideo).evaluate((v: HTMLVideoElement) => v.currentTime)).toBeGreaterThan(0.15)
  await navigate('Previous')
  await expect.poll(() => page.evaluate(() => document.querySelector('[role=dialog] video:not([aria-hidden])') === (window as any).__loadedHQ)).toBe(true)
  await expect.poll(() => page.locator(visibleVideo).evaluate((v: HTMLVideoElement) => !v.paused && v.videoWidth === 1080)).toBe(true)
  await expect.poll(() => page.locator('video[aria-hidden]').evaluate((v: HTMLVideoElement) => !v.paused)).toBe(true)
})
