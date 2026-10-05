import React from 'react'
import { MemoryRouter } from 'react-router-dom'
import { render, screen, fireEvent, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import ClipViewer from './ClipViewer'

vi.mock('../../services/api', () => ({ api: { get: vi.fn().mockResolvedValue({ data: { liked: false, like_count: 0, comment_count: 0 } }), put: vi.fn() } }))

vi.mock('../DiveVideoPlayer', () => ({
  default: ({ diveCode, videoUuid, playbackRate }: { diveCode: string; videoUuid: string; playbackRate: number }) => (
    <div data-testid="player">
      {diveCode}:{videoUuid}:{playbackRate}
      <video data-testid="player-video" />
    </div>
  ),
}))

import { api } from '../../services/api'
beforeEach(() => { vi.mocked(api.get).mockResolvedValue({ data: { liked: false, like_count: 0, comment_count: 0 } }) })

import type { Attempt } from '../../utils/attemptPresentation'

const attempt = (id: number, options: Partial<Attempt> = {}): Attempt => ({
  id,
  dive_code: '103B',
  performance: 'G',
  performance_numeric: 3,
  height: '3m',
  dive_datetime: `2026-07-${String((id % 28) + 1).padStart(2, '0')}T10:00:00`,
  session_id: 1,
  is_lineup: false,
  is_sync: false,
  platform_type: 'springboard',
  position: 'B',
  official_dd: 2.0,
  phase1_performance: 'G',
  phase2_performance: 'M',
  raw_caption: '103B G/G DB',
  video_uuid: `uuid-${id}`,
  diver_id: 1,
  ...options,
})

const attempts = [attempt(1), attempt(2), attempt(3), attempt(4), attempt(5)]

function renderClipViewer(
  index: number,
  handlers: { onClose?: () => void; onMove?: (a: Attempt) => void } = {},
  override?: Partial<Attempt>,
) {
  return render(
    <MemoryRouter>
      <ClipViewer
        attempt={attempts[index]}
        attempts={attempts.map((a) => ({ ...a, ...override }))}
        onClose={handlers.onClose ?? (() => {})}
        onMove={handlers.onMove ?? (() => {})}
        playbackRate={1}
        onPlaybackRateChange={() => {}}
      />
    </MemoryRouter>,
  )
}

it('renders the selected attempt with essential metadata and position', () => {
  renderClipViewer(1)
  const dialog = screen.getByRole('dialog')
  expect(within(dialog).getAllByText('103B').length).toBeGreaterThan(0)
  expect(within(dialog).getAllByText('3m').length).toBeGreaterThan(0)
  expect(within(dialog).getAllByText('springboard').length).toBeGreaterThan(0)
  expect(dialog.textContent).toContain('2 / 5')
})

it('Back to Library invokes close', async () => {
  const onClose = vi.fn()
  renderClipViewer(1, { onClose })
  await userEvent.click(screen.getByRole('button', { name: 'Back to Library' }))
  expect(onClose).toHaveBeenCalledOnce()
})

it('Escape invokes close', () => {
  const onClose = vi.fn()
  renderClipViewer(1, { onClose })
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(onClose).toHaveBeenCalledOnce()
})

it('Shift+Arrow keys navigate Previous/Next within bounds', () => {
  const onMove = vi.fn()
  renderClipViewer(2, { onMove })
  fireEvent.keyDown(document, { key: 'ArrowLeft', shiftKey: true })
  expect(onMove).toHaveBeenLastCalledWith(attempts[1])
  fireEvent.keyDown(document, { key: 'ArrowRight', shiftKey: true })
  expect(onMove).toHaveBeenLastCalledWith(attempts[3])
  expect(onMove).toHaveBeenCalledTimes(2)
})

it('Previous/Next are disabled at result-set boundaries', () => {
  const first = renderClipViewer(0)
  expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()
  first.unmount()
  renderClipViewer(attempts.length - 1)
  expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
})

it('plain ArrowLeft/ArrowRight do not navigate', () => {
  const onMove = vi.fn()
  renderClipViewer(2, { onMove })
  fireEvent.keyDown(document, { key: 'ArrowRight' })
  fireEvent.keyDown(document, { key: 'ArrowLeft' })
  expect(onMove).not.toHaveBeenCalled()
})

it('review shortcuts do not fire while typing in a text field', () => {
  const onMove = vi.fn()
  const { container } = renderClipViewer(2, { onMove })
  const input = document.createElement('input')
  container.firstChild!.firstChild!.appendChild(input)
  fireEvent.keyDown(input, { key: 'ArrowRight', shiftKey: true })
  fireEvent.keyDown(input, { key: 'ArrowLeft', shiftKey: true })
  expect(onMove).not.toHaveBeenCalled()
})

it('Space toggles playback when focus is on a non-interactive surface', () => {
  const { container } = renderClipViewer(1)
  const video = container.querySelector('video') as HTMLVideoElement
  let paused = true
  Object.defineProperty(video, 'paused', { configurable: true, get: () => paused })
  const play = vi.fn(() => { paused = false })
  const pause = vi.fn(() => { paused = true })
  Object.defineProperty(video, 'play', { configurable: true, value: play })
  Object.defineProperty(video, 'pause', { configurable: true, value: pause })

  fireEvent.keyDown(screen.getByRole('dialog'), { key: ' ' })
  expect(play).toHaveBeenCalledTimes(1)
  expect(pause).not.toHaveBeenCalled()

  fireEvent.keyDown(screen.getByRole('dialog'), { key: ' ' })
  expect(pause).toHaveBeenCalledTimes(1)
  expect(play).toHaveBeenCalledTimes(1)
})

it('Space does not hijack interactive controls', () => {
  const { container } = renderClipViewer(1)
  const video = container.querySelector('video') as HTMLVideoElement
  const play = vi.fn()
  const pause = vi.fn()
  Object.defineProperty(video, 'paused', { configurable: true, get: () => true })
  Object.defineProperty(video, 'play', { configurable: true, value: play })
  Object.defineProperty(video, 'pause', { configurable: true, value: pause })

  const nextButton = screen.getByRole('button', { name: 'Next' })
  fireEvent.keyDown(nextButton, { key: ' ' })
  const speedSelect = screen.getByRole('combobox', { name: 'Playback speed' })
  fireEvent.keyDown(speedSelect, { key: ' ' })
  expect(play).not.toHaveBeenCalled()
  expect(pause).not.toHaveBeenCalled()
})

it('the playback-rate select reports the chosen rate', async () => {
  const onPlaybackRateChange = vi.fn()
  render(
    <MemoryRouter>
      <ClipViewer
        attempt={attempts[0]}
        attempts={attempts}
        onClose={() => {}}
        onMove={() => {}}
        playbackRate={0.5}
        onPlaybackRateChange={onPlaybackRateChange}
      />
    </MemoryRouter>,
  )
  const select = screen.getByRole('combobox', { name: 'Playback speed' }) as HTMLSelectElement
  expect(select.value).toBe('0.5')
  await userEvent.selectOptions(select, '1.5')
  expect(onPlaybackRateChange).toHaveBeenLastCalledWith(1.5)
})

it('Details is closed by default and toggles secondary metadata', async () => {
  renderClipViewer(1)
  const detailsButton = screen.getByRole('button', { name: /Details/ })
  expect(detailsButton).toHaveAttribute('aria-expanded', 'false')
  const panel = document.getElementById('clip-viewer-details')!
  expect(panel).toHaveAttribute('hidden')
  await userEvent.click(detailsButton)
  expect(detailsButton).toHaveAttribute('aria-expanded', 'true')
  expect(panel).not.toHaveAttribute('hidden')
  expect(within(panel).getByText('Raw caption')).toBeInTheDocument()
  expect(within(panel).getByText('103B G/G DB')).toBeInTheDocument()
  await userEvent.click(detailsButton)
  expect(panel).toHaveAttribute('hidden')
})

it('Analysis is a secondary link that preserves the review return path', () => {
  renderClipViewer(1)
  const link = screen.getByRole('link', { name: 'Analysis' })
  expect(link).toHaveAttribute('href', '/dives/analysis/103B?attempt=2')
})

it('an attempt without linked media shows a usable state', () => {
  render(
    <MemoryRouter>
      <ClipViewer
        attempt={attempt(1, { video_uuid: null })}
        attempts={[attempt(1, { video_uuid: null })]}
        onClose={() => {}}
        onMove={() => {}}
        playbackRate={1}
        onPlaybackRateChange={() => {}}
      />
    </MemoryRouter>,
  )
  expect(screen.getByText('No linked clip for this attempt.')).toBeInTheDocument()
})

// ---- U4/U5: modal interaction model ----

it('background content becomes inert while the viewer is open and is restored on close', () => {
  const outside = document.createElement('button')
  outside.textContent = 'Background control'
  document.body.appendChild(outside)
  const { unmount } = renderClipViewer(1)
  expect(outside).toHaveAttribute('inert')
  unmount()
  expect(outside.hasAttribute('inert')).toBe(false)
  outside.remove()
})

it('the dialog itself is never inert', () => {
  renderClipViewer(1)
  expect(screen.getByRole('dialog')).not.toHaveAttribute('inert')
})

it('Tab wraps from the last control back to the first inside the viewer', () => {
  const { container } = renderClipViewer(1)
  const dialog = screen.getByRole('dialog')
  const next = screen.getByRole('button', { name: 'Next' })
  next.focus()
  fireEvent.keyDown(container.firstElementChild as HTMLElement, { key: 'Tab' })
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Back to Library' }))
  expect(dialog.contains(document.activeElement)).toBe(true)
})

it('Shift+Tab wraps from the first control to the last inside the viewer', () => {
  const { container } = renderClipViewer(1)
  const back = screen.getByRole('button', { name: 'Back to Library' })
  back.focus()
  fireEvent.keyDown(container.firstElementChild as HTMLElement, { key: 'Tab', shiftKey: true })
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Next' }))
})

it('Tab from outside the viewer is pulled back into the first control', () => {
  const { container } = renderClipViewer(1)
  ;(document.activeElement as HTMLElement)?.blur()
  fireEvent.keyDown(container.firstElementChild as HTMLElement, { key: 'Tab' })
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Back to Library' }))
})

it('hidden Details content is never a Tab target', () => {
  const { container } = renderClipViewer(1)
  const dialog = screen.getByRole('dialog')
  const focusables = Array.from(
    dialog.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), select:not([disabled])',
    ),
  ).filter((element) => !element.closest('[hidden]'))
  expect(focusables.length).toBeGreaterThan(0)
  focusables.forEach((element) => expect(element.closest('[hidden]')).toBeNull())
  expect(container).toBeInTheDocument()
})
