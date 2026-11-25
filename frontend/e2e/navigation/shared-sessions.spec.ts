import { createServer } from 'node:http'
import { readFile } from 'node:fs/promises'
import { expect, test, type Download, type Page } from '@playwright/test'
import type { SessionVideoInfo, SharedTrainingSession } from '../../src/services/sessionVideosApi'

const poster = '/session-test-poster.svg'
const startingVideo: SessionVideoInfo = {
  id: 31, session_id: 41, filename: 'PORTRAIT.MOV',
  recorded_at: '2026-11-24T20:02:00Z', recorded_date: '2026-11-24',
  duration_seconds: 3660, size_bytes: 6_300_000_000, poster_url: poster,
  codec_string: null, audio_codec_string: null, video_codec: null, color_transfer: null,
  width: 360, height: 640, fps: 30, bit_rate: 1_000_000, can_share: false,
}
const paginated = [
  { ...startingVideo, id: 34, filename: 'FIRST.MOV' },
  { ...startingVideo, id: 35, filename: 'SECOND.MOV' },
  { ...startingVideo, id: 36, filename: 'THIRD.MOV' },
]

function session(id: number, videos: SessionVideoInfo[]): SharedTrainingSession {
  return {
    session_id: id, title: 'A shared diving session', date: '2026-11-24', videos, video_count: videos.length,
    total_bytes: videos.reduce((sum, video) => sum + (video.size_bytes || 0), 0),
    total_duration: videos.reduce((sum, video) => sum + (video.duration_seconds || 0), 0),
    has_more: false, next_video_id: null,
  }
}

async function routeSessions(page: Page, guest = false) {
  await page.route('**/session-test-poster.svg', route => route.fulfill({
    contentType: 'image/svg+xml',
    body: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 640"><rect width="360" height="640" fill="#246773"/><path d="M40 270h280v18H40z" fill="#8fced3"/></svg>',
  }))
  let signedIn = !guest
  await page.route('**/api/v1/**', async route => {
    const { pathname, searchParams } = new URL(route.request().url())
    if (pathname === '/api/v1/auth/login') {
      signedIn = true
      return route.fulfill({ json: {} })
    }
    if (pathname === '/api/v1/bootstrap') {
      if (!signedIn) return route.fulfill({ status: 401, json: {} })
      return route.fulfill({ json: { me: {
        user_id: 7, display_name: 'Test diver', role: 'diver',
        divers: [], features: { shared_sessions: true, calendar: true },
      } } })
    }
    if (pathname === '/api/v1/shared-sessions/41') {
      return route.fulfill({ json: session(41, [startingVideo]) })
    }
    if (pathname === '/api/v1/shared-sessions/42') {
      const videos = Array.from({ length: 18 }, (_, i) => ({
        ...startingVideo, id: i + 32, session_id: 42,
        filename: `RECORDING-${i + 1}.MOV`, duration_seconds: 120, size_bytes: 50_000_000,
      }))
      return route.fulfill({ json: session(42, videos) })
    }
    if (pathname === '/api/v1/shared-dives/sessions/5/visit') {
      const video = { ...startingVideo, video_url: '/api/v1/shared-dives/sessions/5/video' }
      return route.fulfill({ json: session(41, [video]) })
    }
    if (pathname === '/api/v1/shared-sessions/43' ||
        pathname === '/api/v1/shared-dives/sessions/6/visit' ||
        pathname === '/api/v1/shared-dives/sessions/6/recordings') {
      const after = searchParams.has('after')
      const recordings = guest ? paginated.map(video => ({
        ...video, video_url: `/api/v1/shared-dives/sessions/6/videos/${video.id}/play`,
      })) : paginated
      return route.fulfill({ json: { ...session(43, paginated),
        videos: after ? recordings.slice(2) : recordings.slice(0, 2), next_video_id: after ? null : 35 } })
    }
    return route.fulfill({ json: { items: [], unread_count: 0, notes: [] } })
  })
}

test('a single shared recording has a first-screen download and an unobstructed player', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await routeSessions(page)
  await page.goto('/sessions/shared/41')
  const download = page.getByRole('button', { name: /Download video.*6.3 GB/ })
  const watch = page.getByRole('button', { name: 'Watch PORTRAIT.MOV' })
  await expect(download).toBeVisible()
  expect((await download.boundingBox())!.y).toBeLessThan((await watch.boundingBox())!.y)
  await expect(page.locator('video')).toHaveCount(0)
  await watch.click()
  const player = page.getByRole('dialog', { name: 'PORTRAIT.MOV' })
  const media = player.locator('video')
  await expect(media).toHaveAttribute('preload', 'none')
  await expect(player.getByText('0:00 / 1:01:00')).toBeVisible()
  for (const size of [{ width: 390, height: 844 }, { width: 844, height: 390 }]) {
    await page.setViewportSize(size)
    await expect(player.getByRole('heading', { name: 'PORTRAIT.MOV' })).toBeInViewport()
    await expect.poll(async () => {
      const video = await media.boundingBox()
      const transport = await player.locator('.clip-transport').boundingBox()
      return !!video && !!transport && (size.width < size.height ? Math.abs(video.width - size.width) <= 1 : video.height >= size.height * .82)
        && video.y + video.height <= transport.y + 1 && transport.y + transport.height <= size.height + 1
    }).toBe(true)
  }
  await page.goBack()
  await expect(watch).toBeFocused()
  await expect(page).toHaveURL(/\/sessions\/shared\/41$/)
})

test('the fixed bulk action leaves the final recording fully reachable on a small phone', async ({ page, browserName }) => {
  await page.setViewportSize({ width: 320, height: 568 })
  await routeSessions(page)
  await page.goto('/sessions/shared/42')
  const bulk = page.getByRole('button', { name: /Download all/ })
  await expect(bulk).toBeVisible()
  await page.getByRole('button', { name: 'Play RECORDING-1.MOV' }).focus()
  for (let index = 1; index < 36; index++) {
    if (browserName === 'chromium') await page.keyboard.press('Tab')
    else await page.locator('.session-file-list button').nth(index).focus()
    await expect.poll(() => page.evaluate(() => {
      const active = document.activeElement
      const rect = active?.getBoundingClientRect()
      if (!active?.closest('.session-file-list') || !rect) return false
      return active.contains(document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2))
    })).toBe(true)
  }
  const last = page.getByRole('button', { name: /Play RECORDING-18.MOV/ })
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
  await expect(last).toBeInViewport()
  const lastBox = (await last.boundingBox())!
  const footerBox = (await bulk.boundingBox())!
  expect(lastBox.y + lastBox.height).toBeLessThanOrEqual(footerBox.y)
})

test('browser Back dismisses each guest overlay and keeps the shared link', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await routeSessions(page, true)
  await page.goto(`/share/session/5#${'g'.repeat(43)}`)
  const watch = page.getByRole('button', { name: 'Watch PORTRAIT.MOV' })
  await watch.click()
  const player = page.getByRole('dialog', { name: 'PORTRAIT.MOV' })
  const request = player.getByRole('button', { name: /Sign in to download.*PORTRAIT.MOV/ })
  await request.click()
  const access = page.getByRole('dialog', { name: 'Download recordings' })
  await expect(access.getByRole('button', { name: 'Sign in' })).toBeFocused()
  await expect(access.getByRole('button', { name: 'Create an account' })).toBeVisible()
  await page.goBack()
  await expect(request).toBeFocused()
  await request.click()
  await access.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await page.goBack()
  await expect(request).toBeFocused()
  await page.goBack()
  await expect(watch).toBeFocused()
  await expect(page).toHaveURL(`/share/session/5#${'g'.repeat(43)}`)
})

test('reloading a paginated viewer restores the selected recording and keeps the session on close', async ({ page }) => {
  await routeSessions(page)
  await page.goto('/sessions/shared/43')
  await page.getByRole('button', { name: 'Play SECOND.MOV' }).click()
  await page.getByRole('button', { name: 'Next recording' }).click()
  await expect(page.getByRole('dialog', { name: 'THIRD.MOV' })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('dialog', { name: 'THIRD.MOV' })).toBeVisible()
  await page.getByRole('button', { name: 'Close player' }).click()
  await expect(page.getByRole('button', { name: 'Play THIRD.MOV' })).toBeVisible()
  await expect(page).toHaveURL(/\/sessions\/shared\/43$/)
})

test('guest sign-in preserves the paginated viewer and restores its focus just once', async ({ page }) => {
  await routeSessions(page, true)
  await page.goto(`/share/session/6#${'g'.repeat(43)}`)
  const opener = page.getByRole('button', { name: 'Play SECOND.MOV' })
  await opener.click()
  await page.getByRole('button', { name: 'Next recording' }).click()
  const player = page.getByRole('dialog', { name: 'THIRD.MOV' })
  const download = player.getByRole('button', { name: /Sign in to download THIRD.MOV/ })
  await download.click()
  await page.getByRole('dialog', { name: 'Download recordings' }).getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await page.goBack()
  await expect(download).toBeFocused()
  await player.getByRole('button', { name: 'Close player' }).click()
  await expect(opener).toBeFocused()
  await page.getByRole('button', { name: 'Play THIRD.MOV' }).click()
  await expect(player.getByRole('heading', { name: 'THIRD.MOV' })).toBeFocused()
})

test('two Escape events for one viewer leave the user in the same session', async ({ page }) => {
  await routeSessions(page)
  await page.goto('/sessions/shared/42')
  await page.goto('/sessions/shared/41')
  const watch = page.getByRole('button', { name: 'Watch PORTRAIT.MOV' })
  await watch.click()
  await expect(page.getByRole('dialog', { name: 'PORTRAIT.MOV' })).toBeVisible()
  await page.evaluate(() => {
    for (let index = 0; index < 2; index++) document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  })
  await expect(watch).toBeFocused()
  await expect(page).toHaveURL(/\/sessions\/shared\/41$/)
})

test('native fullscreen keeps Tab inside playback and Escape inside the session', async ({ page, browserName }) => {
  test.skip(browserName !== 'chromium', 'Standard element fullscreen is exercised in Chromium')
  await routeSessions(page)
  await page.goto('/sessions/shared/41')
  await page.getByRole('button', { name: 'Watch PORTRAIT.MOV' }).click()
  const player = page.getByRole('dialog', { name: 'PORTRAIT.MOV' })
  await player.getByRole('button', { name: 'Fullscreen' }).click()
  await expect.poll(() => page.evaluate(() => document.fullscreenElement?.classList.contains('session-video-frame'))).toBe(true)
  await player.getByRole('button', { name: 'Mute' }).focus()
  await page.keyboard.press('Tab')
  await expect(player.getByRole('button', { name: 'Play video' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect.poll(() => page.evaluate(() => document.fullscreenElement === null)).toBe(true)
  await expect(player).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(player).toHaveCount(0)
})

test('the browser receives each attachment once across a partial batch and a 429 retry', async ({ page }) => {
  const storage = createServer((request, response) => {
    const name = request.url?.slice(1)
    response.writeHead(200, {
      'Content-Disposition': `attachment; filename="${name}.mov"`,
      'Content-Type': 'video/quicktime',
    }).end(`bytes for ${name}`)
  })
  await new Promise<void>(resolve => storage.listen(0, '127.0.0.1', resolve))
  try {
    const address = storage.address()
    if (!address || typeof address === 'string') throw new Error('Missing fixture HTTP port')
    await routeSessions(page)
    const requested: string[] = []
    let middleAttempts = 0
    await page.route('**/api/v1/session-videos/*/download/prepare', async route => {
      const name = new URL(route.request().url()).pathname.split('/').slice(-3)[0]
      requested.push(name)
      if (name === '35') {
        middleAttempts++
        if (middleAttempts === 1) return route.fulfill({ status: 503, json: {} })
        if (middleAttempts === 2) return route.fulfill({ status: 429, headers: { 'Retry-After': '1' }, json: {} })
      }
      return route.fulfill({ json: { url: `http://127.0.0.1:${address.port}/${name}` } })
    })
    const downloaded: Download[] = []
    page.on('download', file => downloaded.push(file))
    await page.goto('/sessions/shared/43')
    await page.getByRole('button', { name: /Download all/ }).click()
    await expect(page.getByRole('alert')).toHaveText(/1 file could not be downloaded/)
    await expect.poll(() => downloaded.map(file => file.suggestedFilename())).toEqual(['34.mov', '36.mov'])
    await expect(page.getByRole('button', { name: /Retry download of SECOND.MOV/ })).toBeVisible()
    await page.getByRole('button', { name: 'Download the remaining video' }).click()
    await expect.poll(() => downloaded.map(file => file.suggestedFilename())).toEqual(['34.mov', '36.mov', '35.mov'])
    expect(requested).toEqual(['34', '35', '36', '35', '35'])
    await expect(page.getByRole('alert')).toHaveCount(0)
    await expect(page.getByRole('button', { name: /Download all/ })).toBeVisible()
    for (const file of downloaded) {
      expect(await file.failure()).toBeNull()
      expect(await readFile(await file.path(), 'utf8')).toBe(`bytes for ${file.suggestedFilename().replace('.mov', '')}`)
    }
  } finally {
    storage.closeAllConnections()
    await new Promise<void>(resolve => storage.close(() => resolve()))
  }
})

test('a failed single download stays focused and offers a visible retry', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 })
  await routeSessions(page)
  let attempts = 0
  let release!: () => void
  const response = new Promise<void>(resolve => { release = resolve })
  await page.route('**/download/prepare', async route => {
    attempts++
    await response
    await route.fulfill({ status: 503, json: {} })
  })
  await page.goto('/sessions/shared/41')
  const action = page.locator('.session-download-all')
  await action.focus()
  await page.keyboard.press('Enter')
  await expect(action).toHaveAttribute('aria-busy', 'true')
  await expect(action).toBeFocused()
  await page.keyboard.press('Enter')
  release()
  await expect(action).toHaveText(/Retry download/)
  await expect(action).toBeFocused()
  await expect(page.getByRole('alert')).toBeInViewport()
  expect(attempts).toBe(1)
})

test('a pending bulk download can be stopped from the player', async ({ page }) => {
  await routeSessions(page)
  let requested = 0
  let release!: () => void
  const response = new Promise<void>(resolve => { release = resolve })
  await page.route('**/download/prepare', async route => {
    requested++
    await response
    await route.fulfill({ status: 503, json: {} })
  })
  try {
    await page.goto('/sessions/shared/43')
    await page.getByRole('button', { name: /Download all/ }).click()
    await expect.poll(() => requested).toBe(1)
    await page.getByRole('button', { name: 'Play FIRST.MOV' }).click()
    const player = page.getByRole('dialog', { name: 'FIRST.MOV' })
    await player.getByRole('button', { name: 'Stop downloads' }).click()
    release()
    await expect(player.getByRole('alert')).toHaveCount(0)
    await expect(player.getByRole('button', { name: /Download FIRST.MOV/ })).toBeEnabled()
    expect(requested).toBe(1)
  } finally { release() }
})

test('one Back after a successful guest login reaches the previous page', async ({ page }) => {
  await routeSessions(page, true)
  await page.goto('/e2e/fixtures/navigation-review.html')
  await page.goto(`/share/session/5#${'g'.repeat(43)}`)
  await page.getByRole('button', { name: 'Watch PORTRAIT.MOV' }).click()
  await page.getByRole('button', { name: /Sign in to download.*PORTRAIT.MOV/ }).click()
  await page.getByRole('dialog', { name: 'Download recordings' }).getByRole('button', { name: 'Sign in' }).click()
  await page.getByRole('textbox', { name: 'Email' }).fill('diver@example.test')
  await page.locator('input[type=password]').fill('fixture password')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page).toHaveURL(/\/sessions\/shared\/41$/)
  await page.goBack()
  await expect(page).toHaveURL(/\/e2e\/fixtures\/navigation-review.html$/)
})
