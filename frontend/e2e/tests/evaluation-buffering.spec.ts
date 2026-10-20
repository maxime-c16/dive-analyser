import { expect, test } from '@playwright/test'
import { spawnSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'

let folder: string
let clip: Buffer
// Generate synthetic video; no private media is stored in the repository.
test.beforeAll(() => {
  folder = mkdtempSync(path.join(os.tmpdir(), 'evaluation-playback-'))
  const target = path.join(folder, 'clip.mp4')
  const result = spawnSync('ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x120:rate=10', '-t', '3', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', target])
  if (result.error) throw new Error('Evaluation browser tests require ffmpeg on PATH')
  expect(result.status, result.stderr?.toString()).toBe(0)
  clip = readFileSync(target)
})
test.afterAll(() => { if (folder) rmSync(folder, { recursive: true, force: true }) })

const media = (id: number) => ({ request_id: id, dive_id: id, video_uuid: `fixture-${id}`, status: 'ready', rendition: 'original', poster_url: null, playback_url: `/api/v1/evaluations/automatic/${id}/media/play`, available_renditions: ['original', 'proxy_720p'] })

test('holds the introduction for a slow download, replays, and promotes the buffered next video', async ({ page }) => {
  let release!: () => void
  const download = new Promise<void>(resolve => { release = resolve })
  let transfers = 0
  await page.route('**/api/**', async route => {
    const url = route.request().url()
    if (url.includes('/media/play')) {
      transfers += 1
      await download
      await route.fulfill({ contentType: 'video/mp4', body: clip })
      return
    }
    let json: unknown = {}
    if (url.endsWith('/stacks')) json = { session_id: 5 }
    if (url.includes('/queue')) json = { batch_id: 'fixture', has_more: false, items: [1, 2].map(id => ({ request_id: id, dive_id: id, prompt: null, dive: { id, video_uuid: `fixture-${id}`, dive_code: `10${id}B`, height: '3m', owner_display_name: 'Reviewer' }, media: media(id) })) }
    if (url.includes('/media/status')) json = media(Number(url.match(/automatic\/(\d+)/)?.[1]))
    await route.fulfill({ json })
  })
  await page.goto('/e2e/fixtures/evaluation-review.html')
  const stage = page.getByRole('dialog')
  await expect(stage).toHaveAttribute('data-preparing', 'true')
  await expect(stage.locator('.eval-warmup')).toBeVisible()
  await expect.poll(() => transfers).toBeGreaterThanOrEqual(2)
  expect(await page.locator('video').first().evaluate((v: HTMLVideoElement) => v.currentTime)).toBe(0)
  release()
  await expect(stage).not.toHaveAttribute('data-preparing', 'true')
  await expect.poll(() => page.locator('video').first().evaluate((v: HTMLVideoElement) => v.currentTime)).toBeGreaterThan(0)
  await expect.poll(() => page.locator('video').evaluateAll(videos => videos.every(v => (v as HTMLVideoElement).readyState >= 2))).toBe(true)
  const completedTransfers = transfers
  await page.locator('video').first().evaluate(v => { (window as unknown as { first: Element }).first = v })
  await expect(stage.getByRole('group', { name: 'Judging actions' })).toBeVisible()
  await stage.getByRole('button', { name: 'Replay from the start', exact: true }).first().click()
  await expect.poll(() => page.locator('video').first().evaluate((v: HTMLVideoElement) => v.currentTime)).toBeGreaterThan(0)
  expect(await page.locator('video').first().evaluate(v => v === (window as unknown as { first: Element }).first)).toBe(true)
  expect(transfers).toBe(completedTransfers)
  await expect(stage.getByRole('group', { name: 'Judging actions' })).toBeVisible()
  await page.locator('video').nth(1).evaluate(v => { (window as unknown as { next: Element }).next = v })
  await stage.getByRole('button', { name: 'Pass', exact: true }).click()
  await expect(stage.getByText('102B · 3m')).toBeAttached()
  expect(await page.locator('video').first().evaluate(v => v === (window as unknown as { next: Element }).next)).toBe(true)
  await expect.poll(() => page.locator('video').first().evaluate((v: HTMLVideoElement) => v.currentTime)).toBeGreaterThan(0)
  expect(transfers).toBe(completedTransfers)
})

test('a failed download stays in one error view and Retry performs a fresh download', async ({ page }) => {
  let failed = true
  await page.route('**/api/**', async route => {
    const url = route.request().url()
    if (url.includes('/media/play')) {
      await route.fulfill(failed ? { status: 503, body: 'unavailable' } : { contentType: 'video/mp4', body: clip })
      return
    }
    let json: unknown = {}
    if (url.endsWith('/stacks')) json = { session_id: 5 }
    if (url.includes('/queue')) json = { batch_id: 'fixture', has_more: false, items: [{ request_id: 1, dive_id: 1, prompt: null, dive: { id: 1, video_uuid: 'fixture-1', dive_code: '101B', height: '3m', owner_display_name: 'Reviewer' }, media: media(1) }] }
    if (url.includes('/media/status')) json = media(1)
    await route.fulfill({ json })
  })
  await page.goto('/e2e/fixtures/evaluation-review.html')
  const stage = page.getByRole('dialog')
  await expect(stage.locator('.eval-preparation-error')).toBeVisible()
  await expect(stage.getByRole('button', { name: 'Retry', exact: true })).toHaveCount(1)
  failed = false
  await stage.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(stage.locator('.eval-preparation-error')).toHaveCount(0)
  await expect(stage).not.toHaveAttribute('data-preparing', 'true')
  await expect.poll(() => page.locator('video').first().evaluate((v: HTMLVideoElement) => v.currentTime)).toBeGreaterThan(0)
})

for (const viewport of [
  { width: 320, height: 568 }, { width: 375, height: 667 },
  { width: 390, height: 844 }, { width: 430, height: 932 },
  { width: 568, height: 320 }, { width: 844, height: 390 },
  { width: 599, height: 800 }, { width: 600, height: 800 },
  { width: 768, height: 1024 }, { width: 1024, height: 768 },
  { width: 1280, height: 720 }, { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
]) {
  for (const lateBaseStyles of [false, true]) {
    test(`keeps identity visible and quality text contained at ${viewport.width}x${viewport.height} (late base styles: ${lateBaseStyles})`, async ({ page }, testInfo) => {
      await page.setViewportSize(viewport)
      await page.route('**/api/**', async route => {
        const url = route.request().url()
        if (url.includes('/media/play')) { await route.fulfill({ contentType: 'video/mp4', body: clip }); return }
        let json: unknown = {}
        if (url.endsWith('/stacks')) json = { session_id: 5 }
        if (url.includes('/queue')) json = { batch_id: 'fixture', has_more: false, items: [{ request_id: 1, dive_id: 1, prompt: null, dive: { id: 1, video_uuid: 'fixture-1', dive_code: '101B', height: '3m', owner_display_name: 'Reviewer' }, media: media(1) }] }
        if (url.includes('/media/status')) json = media(1)
        await route.fulfill({ json })
      })
      await page.goto('/e2e/fixtures/evaluation-review.html')
      // Library loads evaluationA before the lazy Evaluations route loads its base CSS.
      if (lateBaseStyles) await page.addStyleTag({ path: 'src/components/evaluation/evaluations.css' })
      const stage = page.getByRole('dialog')
      await expect(stage).not.toHaveAttribute('data-preparing', 'true')
      await expect.poll(() => page.locator('video').first().evaluate((v: HTMLVideoElement) => v.currentTime)).toBeGreaterThan(0)
      await expect(stage.locator('.eval-head-owner')).toBeVisible()
      await expect(stage.locator('.eval-meta')).toBeVisible()
      const identity = await stage.locator('.eval-stage-head-center').boundingBox()
      const video = await stage.locator('.eval-stage-video').boundingBox()
      expect(identity).not.toBeNull(); expect(video).not.toBeNull()
      if (viewport.width >= 600 && viewport.width > viewport.height && viewport.height > 500) expect(identity!.x).toBeGreaterThanOrEqual(video!.x + video!.width)
      else {
        expect(identity!.x).toBeGreaterThanOrEqual(video!.x)
        expect(identity!.y + identity!.height).toBeLessThan(video!.y + video!.height)
      }
      await page.locator('video').first().evaluate((v: HTMLVideoElement) => { v.loop = true })
      await stage.dispatchEvent('pointerdown')
      await page.locator('video').first().dispatchEvent('pointermove')
      const quality = stage.locator('.eval-quality-toggle')
      await expect(quality).toHaveText('720p')
      expect(await quality.evaluate(button => button.scrollWidth <= button.clientWidth)).toBe(true)
      await page.screenshot({ path: testInfo.outputPath(`identity-${viewport.width}.png`) })
      await quality.click()
      await expect(quality).toHaveText('Original')
      expect(await quality.evaluate(button => button.scrollWidth <= button.clientWidth)).toBe(true)
      for (const button of await stage.locator('.eval-player-controls button').all()) {
        const box = (await button.boundingBox())!
        expect(box.x).toBeGreaterThanOrEqual(video!.x)
        expect(box.x + box.width).toBeLessThanOrEqual(video!.x + video!.width)
      }
      // Watching uses the full phone viewport; the scoring side panel is hidden.
      // The narrower landscape video area only applies after playback ends below.
      if (viewport.height <= 500) expect(video!.width).toBe(viewport.width)
      const rail = await stage.locator('.eval-player-controls').boundingBox()
      expect(rail!.height).toBeLessThanOrEqual(54)
      expect(rail!.y).toBeGreaterThanOrEqual(0)
      expect(rail!.y + rail!.height).toBeLessThanOrEqual(viewport.height)
      const chip = await quality.boundingBox()
      expect(chip!.height).toBe(44)
      expect(chip!.width).toBeLessThan(100)
      expect(rail!.x).toBeGreaterThanOrEqual(0)
      expect(rail!.x + rail!.width).toBeLessThanOrEqual(viewport.width)
      await page.locator('video').first().dispatchEvent('ended')
      await expect(stage).not.toHaveAttribute('data-watching', 'true')
      await expect(stage.getByRole('group', { name: 'Judging actions' })).toBeVisible()
      const judgingRail = (await stage.locator('.eval-player-controls').boundingBox())!
      const judgingVideo = (await stage.locator('.eval-stage-video').boundingBox())!
      expect(judgingRail.height).toBeLessThanOrEqual(104)
      if (viewport.width === 568 && viewport.height === 320) {
        expect(judgingVideo.width).toBeCloseTo(255.6, 0)
        const rows = await stage.locator('.eval-player-controls button').evaluateAll(buttons =>
          new Set(buttons.map(button => (button as HTMLElement).offsetTop)).size)
        expect(rows).toBe(2)
      }
      for (const button of await stage.locator('.eval-player-controls button').all()) {
        const box = (await button.boundingBox())!
        expect(box.x).toBeGreaterThanOrEqual(judgingVideo.x)
        expect(box.x + box.width).toBeLessThanOrEqual(judgingVideo.x + judgingVideo.width)
        expect(box.y).toBeGreaterThanOrEqual(judgingVideo.y)
        expect(box.y + box.height).toBeLessThanOrEqual(judgingVideo.y + judgingVideo.height)
      }
      const dock = (await stage.locator('.eval-stage-dock').boundingBox())!
      expect(judgingRail.x + judgingRail.width <= dock.x + 1 || judgingRail.y + judgingRail.height <= dock.y + 1).toBe(true)
      await page.screenshot({ path: testInfo.outputPath(`judging-${viewport.width}x${viewport.height}.png`) })
    })
  }
}

test('waits for preview preparation without requesting the failing cloud original', async ({ page }) => {
  let previewReady = false
  let prepared = 0
  let originals = 0
  await page.route('**/api/**', async route => {
    const url = route.request().url()
    const original = { ...media(1), available_renditions: ['original'] }
    if (url.includes('/media/play')) {
      if (url.includes('rendition=original')) { originals += 1; await route.fulfill({ status: 503 }); return }
      await route.fulfill({ contentType: 'video/mp4', body: clip }); return
    }
    let json: unknown = {}
    if (url.endsWith('/stacks')) json = { session_id: 5 }
    if (url.includes('/queue')) json = { batch_id: 'fixture', has_more: false, items: [{ request_id: 1, dive_id: 1, prompt: null, dive: { id: 1, video_uuid: 'fixture-1', dive_code: '101B', height: '3m', owner_display_name: 'Reviewer' }, media: original }] }
    if (url.includes('/media/status')) json = previewReady ? media(1) : original
    if (url.includes('/media/prepare')) { prepared += 1; json = { ...original, created_jobs: ['proxy_720p'], reused_jobs: [] } }
    await route.fulfill({ json })
  })
  await page.goto('/e2e/fixtures/evaluation-review.html')
  const stage = page.getByRole('dialog')
  await expect.poll(() => prepared).toBeGreaterThan(0)
  await expect(stage).toHaveAttribute('data-preparing', 'true')
  expect(originals).toBe(0)
  previewReady = true
  await expect(stage).not.toHaveAttribute('data-preparing', 'true')
  await expect.poll(() => page.locator('video').first().evaluate((v: HTMLVideoElement) => v.currentTime)).toBeGreaterThan(0)
  expect(originals).toBe(0)
  await expect(stage.locator('.eval-preparation-error')).toHaveCount(0)
})
