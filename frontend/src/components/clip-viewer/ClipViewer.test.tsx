import React from 'react'
import { MemoryRouter } from 'react-router-dom'
import { render, screen, fireEvent, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, onTestFinished, vi } from 'vitest'
import ClipViewer, { pinchState } from './ClipViewer'

vi.mock('../../services/api', () => ({ api: { get: vi.fn().mockResolvedValue({ data: { liked: false, like_count: 0, comment_count: 0 } }), put: vi.fn() } }))

vi.mock('../DiveVideoPlayer', () => ({
  default: (props: {
    diveCode: string
    videoUuid: string
    playbackRate: number
    dragEnabled?: boolean
    onDragUpdate?: (dy: number) => void
    onDragEnd?: (result: { dy: number; velocity: number; cancelled: boolean }) => void
    onPinchStart?: () => void
    onPinchUpdate?: (ratio: number) => void
    onPinchEnd?: (cancelled: boolean) => void
  }) => (
    <div data-testid="player">
      {props.diveCode}:{props.videoUuid}:{props.playbackRate}
      <video data-testid="player-video" />
      {/* Stands in for the two-finger pinch reported by ImmersiveControls. */}
      <button type="button" aria-label="Test pinch start" onClick={() => props.onPinchStart?.()} />
      <button type="button" aria-label="Test pinch close" onClick={() => props.onPinchUpdate?.(0.6)} />
      <button type="button" aria-label="Test pinch spread" onClick={() => props.onPinchUpdate?.(1.4)} />
      <button type="button" aria-label="Test pinch end" onClick={() => props.onPinchEnd?.(false)} />
      <button type="button" aria-label="Test pinch cancel" onClick={() => props.onPinchEnd?.(true)} />
      {/* Stands in for the ImmersiveControls gesture surface (arbitration is
          covered in ImmersiveControls.test.tsx): forwards raw pointer travel
          as drag callbacks so pager tests can drive finger gestures. */}
      <button
        type="button"
        aria-label="Test drag surface"
        onPointerDown={(event) => {
          event.currentTarget.dataset.startY = String(event.clientY)
        }}
        onPointerMove={(event) => {
          const start = event.currentTarget.dataset.startY
          if (start === undefined) return
          props.onDragUpdate?.(event.clientY - Number(start))
        }}
        onPointerUp={(event) => {
          const start = event.currentTarget.dataset.startY
          delete event.currentTarget.dataset.startY
          if (start === undefined) return
          props.onDragEnd?.({
            dy: event.clientY - Number(start),
            velocity: 0,
            cancelled: false,
          })
        }}
      />
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

/** Phone layout: overlay actions, bottom sheet, footer navigation. */
function stubPhoneLayout() {
  const descriptor = Object.getOwnPropertyDescriptor(window, 'matchMedia')
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: (query: string) => ({
      matches: query.includes('max-width: 599px'),
      media: query,
      onchange: null,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
      dispatchEvent() { return false },
    }),
  })
  return () => {
    if (descriptor) Object.defineProperty(window, 'matchMedia', descriptor)
    else delete (window as { matchMedia?: unknown }).matchMedia
  }
}

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
  onTestFinished(stubPhoneLayout())
  renderClipViewer(1)
  const detailsButton = screen.getByRole('button', { name: /Details/ })
  expect(detailsButton).toHaveAttribute('aria-expanded', 'false')
  const sheet = document.getElementById('clip-review-panel')!
  expect(sheet).toHaveAttribute('inert')
  await userEvent.click(detailsButton)
  expect(detailsButton).toHaveAttribute('aria-expanded', 'true')
  expect(sheet).not.toHaveAttribute('inert')
  expect(within(sheet).getByRole('tab', { name: 'Details' })).toHaveAttribute('aria-selected', 'true')
  const panel = document.getElementById('clip-viewer-details')!
  expect(within(panel).getByText('Raw caption')).toBeInTheDocument()
  expect(within(panel).getByText('103B G/G DB')).toBeInTheDocument()
  await userEvent.click(detailsButton)
  expect(sheet).toHaveAttribute('inert')
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
  onTestFinished(stubPhoneLayout())
  const { container } = renderClipViewer(1)
  const dialog = screen.getByRole('dialog')
  const next = screen.getByRole('button', { name: 'Next' })
  next.focus()
  fireEvent.keyDown(container.firstElementChild as HTMLElement, { key: 'Tab' })
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Back to Library' }))
  expect(dialog.contains(document.activeElement)).toBe(true)
})

it('Shift+Tab wraps from the first control to the last inside the viewer', () => {
  onTestFinished(stubPhoneLayout())
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


it('swiping up the description expands details without the following click closing it', () => {
  onTestFinished(stubPhoneLayout())
  renderClipViewer(1)
  const button = screen.getByRole('button', { name: /Details/ })
  fireEvent(button, new MouseEvent('pointerdown', { bubbles: true, clientY: 300 }))
  fireEvent(button, new MouseEvent('pointerup', { bubbles: true, clientY: 200 }))
  fireEvent.click(button, { detail: 1 })
  expect(button).toHaveAttribute('aria-expanded', 'true')
  expect(document.getElementById('clip-review-panel')).not.toHaveAttribute('inert')
})

// ---- Mobile feed-pager: the dive follows the finger (TikTok/Reels-like) ----

import { act } from 'react'
import {
  FEED_PUSH_DURATION_MS,
  FEED_SPRING_DURATION_MS,
  shouldCommitDrag,
  shouldEnableFeedPager,
} from './ClipViewer'

function stubPagerEnvironment({ mobile, reduce }: { mobile: boolean; reduce: boolean }) {
  const animateMock = vi.fn(() => ({}))
  const animateDescriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'animate')
  Object.defineProperty(HTMLElement.prototype, 'animate', {
    configurable: true,
    writable: true,
    value: animateMock,
  })
  const heightDescriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight')
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
    configurable: true,
    get() { return 800 },
  })
  // jsdom has no PointerEvent, so fireEvent.pointer* would drop clientX/Y.
  // A MouseEvent subclass carries them, mirroring ImmersiveControls.test.tsx.
  class Pointer extends MouseEvent {
    isPrimary = true
    pointerId = 1
  }
  vi.stubGlobal('PointerEvent', Pointer)
  const matchMediaDescriptor = Object.getOwnPropertyDescriptor(window, 'matchMedia')
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: (query: string) => ({
      matches: query.includes('max-width')
        ? mobile
        : query.includes('reduce')
          ? reduce
          : false,
      media: query,
      onchange: null,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
      dispatchEvent() { return false },
    }),
  })
  return {
    animateMock,
    restore() {
      vi.unstubAllGlobals()
      if (animateDescriptor) Object.defineProperty(HTMLElement.prototype, 'animate', animateDescriptor)
      else delete (HTMLElement.prototype as { animate?: unknown }).animate
      if (heightDescriptor) Object.defineProperty(HTMLElement.prototype, 'clientHeight', heightDescriptor)
      else delete (HTMLElement.prototype as { clientHeight?: unknown }).clientHeight
      if (matchMediaDescriptor) Object.defineProperty(window, 'matchMedia', matchMediaDescriptor)
      else delete (window as { matchMedia?: unknown }).matchMedia
    },
  }
}

function renderAt(
  index: number,
  handlers: { onClose?: () => void; onMove?: (a: Attempt) => void } = {},
  list: Attempt[] = attempts,
) {
  return render(
    <MemoryRouter>
      <ClipViewer
        attempt={list[index]}
        attempts={list}
        onClose={handlers.onClose ?? (() => {})}
        onMove={handlers.onMove ?? (() => {})}
        playbackRate={1}
        onPlaybackRateChange={() => {}}
      />
    </MemoryRouter>,
  )
}

function rerenderAt(
  view: ReturnType<typeof render>,
  index: number,
  handlers: { onClose?: () => void; onMove?: (a: Attempt) => void } = {},
  list: Attempt[] = attempts,
) {
  view.rerender(
    <MemoryRouter>
      <ClipViewer
        attempt={list[index]}
        attempts={list}
        onClose={handlers.onClose ?? (() => {})}
        onMove={handlers.onMove ?? (() => {})}
        playbackRate={1}
        onPlaybackRateChange={() => {}}
      />
    </MemoryRouter>,
  )
}

/** A scripted finger: press at y=400, travel to y=400+dy, release. */
function dragBy(surface: HTMLElement, dy: number) {
  fireEvent.pointerDown(surface, { clientX: 100, clientY: 400, button: 0 })
  fireEvent.pointerMove(surface, { clientX: 100, clientY: 400 + dy })
  fireEvent.pointerUp(surface, { clientX: 100, clientY: 400 + dy })
}

function dragMoveOnly(surface: HTMLElement, dy: number) {
  fireEvent.pointerDown(surface, { clientX: 100, clientY: 400, button: 0 })
  fireEvent.pointerMove(surface, { clientX: 100, clientY: 400 + dy })
}

it('renders warmed neighbor frames around the live dive', () => {
  const env = stubPagerEnvironment({ mobile: true, reduce: false })
  try {
    renderAt(1)
    const prev = document.querySelector('.clip-pager-neighbor.is-prev') as HTMLElement
    const next = document.querySelector('.clip-pager-neighbor.is-next') as HTMLElement
    expect(prev?.dataset.neighbor).toBe('1')
    expect(next?.dataset.neighbor).toBe('3')
    expect(prev).toHaveAttribute('aria-hidden', 'true')
    // Poster frames are never interactive: no Tab stop, no pointer target.
    expect(prev.querySelectorAll('button, a, input, select').length).toBe(0)
    expect(next.querySelectorAll('button, a, input, select').length).toBe(0)
  } finally {
    env.restore()
  }
})

it('the dive follows the finger 1:1 without navigating mid-gesture', () => {
  const env = stubPagerEnvironment({ mobile: true, reduce: false })
  try {
    const onMove = vi.fn()
    renderAt(1, { onMove })
    const surface = screen.getByRole('button', { name: 'Test drag surface' })
    const stage = document.querySelector('.clip-stage') as HTMLElement
    const next = document.querySelector('.clip-pager-neighbor.is-next') as HTMLElement
    dragMoveOnly(surface, -200)
    expect(stage.style.transform).toBe('translateY(-200px)')
    expect(next.style.transform).toBe('translateY(600px)')
    expect(onMove).not.toHaveBeenCalled()
  } finally {
    env.restore()
  }
})

it('release past the threshold snaps through to the next dive', () => {
  const env = stubPagerEnvironment({ mobile: true, reduce: false })
  vi.useFakeTimers()
  try {
    const onMove = vi.fn()
    renderAt(1, { onMove })
    const surface = screen.getByRole('button', { name: 'Test drag surface' })
    dragBy(surface, -300)
    // Snap FIRST, selection swap only when the neighbor lands.
    expect(onMove).not.toHaveBeenCalled()
    expect(env.animateMock).toHaveBeenCalled()
    const keyframes = env.animateMock.mock.calls.map(
      (call) => JSON.stringify((call as unknown as [Keyframe[]])[0]),
    )
    expect(keyframes.some((frames) => frames.includes('translateY(-800px)'))).toBe(true)
    expect(keyframes.some((frames) => frames.includes('translateY(0)'))).toBe(true)
    const durations = env.animateMock.mock.calls.map(
      (call) => (call as unknown as [Keyframe[], KeyframeAnimationOptions])[1]?.duration,
    )
    expect(durations).toContain(FEED_PUSH_DURATION_MS)
    act(() => vi.advanceTimersByTime(FEED_PUSH_DURATION_MS + 50))
    expect(onMove).toHaveBeenCalledTimes(1)
    expect(onMove).toHaveBeenCalledWith(attempts[2])
  } finally {
    vi.useRealTimers()
    env.restore()
  }
})

it('a short drag springs back without navigating', () => {
  const env = stubPagerEnvironment({ mobile: true, reduce: false })
  vi.useFakeTimers()
  try {
    const onMove = vi.fn()
    renderAt(1, { onMove })
    const surface = screen.getByRole('button', { name: 'Test drag surface' })
    const stage = document.querySelector('.clip-stage') as HTMLElement
    dragBy(surface, -100)
    expect(onMove).not.toHaveBeenCalled()
    expect(env.animateMock).toHaveBeenCalled()
    act(() => vi.advanceTimersByTime(FEED_SPRING_DURATION_MS + 50))
    expect(onMove).not.toHaveBeenCalled()
    expect(stage.style.transform).toBe('')
  } finally {
    vi.useRealTimers()
    env.restore()
  }
})

it('dragging past the first dive rubber-bands and never commits', () => {
  const env = stubPagerEnvironment({ mobile: true, reduce: false })
  vi.useFakeTimers()
  try {
    const onMove = vi.fn()
    renderAt(0, { onMove })
    expect(document.querySelector('.clip-pager-neighbor.is-prev')).toBeNull()
    const surface = screen.getByRole('button', { name: 'Test drag surface' })
    const stage = document.querySelector('.clip-stage') as HTMLElement
    dragMoveOnly(surface, 200)
    expect(stage.style.transform).toBe('translateY(70px)')
    fireEvent.pointerUp(surface, { clientX: 100, clientY: 600 })
    // Spring-back starts from the rendered (rubber-banded) position, so
    // release never jumps back out to the raw finger travel.
    const springFrames = JSON.stringify(
      (env.animateMock.mock.calls[0] as unknown as [Keyframe[]])[0],
    )
    expect(springFrames).toContain('translateY(70px)')
    expect(springFrames).not.toContain('translateY(200px)')
    act(() => vi.advanceTimersByTime(FEED_SPRING_DURATION_MS + 50))
    expect(onMove).not.toHaveBeenCalled()
    expect(stage.style.transform).toBe('')
  } finally {
    vi.useRealTimers()
    env.restore()
  }
})

it('a pending commit is dropped when the list changes underneath it', () => {
  const env = stubPagerEnvironment({ mobile: true, reduce: false })
  vi.useFakeTimers()
  try {
    const onMove = vi.fn()
    const view = renderAt(1, { onMove })
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    // A filter lands mid-snap: same selected dive, but the neighbor that the
    // commit captured (id 3) is no longer adjacent.
    const relisted = [attempts[0], attempts[1], attempt(99), attempts[3], attempts[4]]
    rerenderAt(view, 1, { onMove }, relisted)
    act(() => vi.advanceTimersByTime(FEED_PUSH_DURATION_MS + 50))
    expect(onMove).not.toHaveBeenCalled()
  } finally {
    vi.useRealTimers()
    env.restore()
  }
})

it('an external selection mid-snap cancels running animations', () => {
  const env = stubPagerEnvironment({ mobile: true, reduce: false })
  const cancelSpy = vi.fn()
  env.animateMock.mockReturnValue({ cancel: cancelSpy })
  vi.useFakeTimers()
  try {
    const onMove = vi.fn()
    const view = renderAt(1, { onMove })
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(env.animateMock).toHaveBeenCalled()
    // Browser Back lands mid-snap on a different dive: the in-flight slide
    // must stop instead of gliding over the newly selected dive.
    rerenderAt(view, 0, { onMove })
    expect(cancelSpy).toHaveBeenCalled()
    act(() => vi.advanceTimersByTime(FEED_PUSH_DURATION_MS + 50))
    expect(onMove).not.toHaveBeenCalled()
  } finally {
    vi.useRealTimers()
    env.restore()
  }
})

it('Next takes the same push on mobile, minus the finger', () => {
  const env = stubPagerEnvironment({ mobile: true, reduce: false })
  vi.useFakeTimers()
  try {
    const onMove = vi.fn()
    renderAt(1, { onMove })
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(onMove).not.toHaveBeenCalled()
    expect(env.animateMock).toHaveBeenCalled()
    act(() => vi.advanceTimersByTime(FEED_PUSH_DURATION_MS + 50))
    expect(onMove).toHaveBeenCalledWith(attempts[2])
  } finally {
    vi.useRealTimers()
    env.restore()
  }
})

it('reduced motion renders no pager and navigates instantly', () => {
  const env = stubPagerEnvironment({ mobile: true, reduce: true })
  try {
    const onMove = vi.fn()
    renderAt(1, { onMove })
    expect(document.querySelector('.clip-pager-neighbor')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(onMove).toHaveBeenCalledWith(attempts[2])
    expect(env.animateMock).not.toHaveBeenCalled()
  } finally {
    env.restore()
  }
})

it('desktop falls back to instant navigation with no pager frames', () => {
  const env = stubPagerEnvironment({ mobile: false, reduce: false })
  try {
    const onMove = vi.fn()
    renderAt(1, { onMove })
    expect(document.querySelector('.clip-pager-neighbor')).toBeNull()
    const surface = screen.getByRole('button', { name: 'Test drag surface' })
    // The real gesture layer never reports drags on desktop (legacy swipe
    // path instead); if one arrives, it resolves instantly with no animation.
    dragBy(surface, -300)
    expect(onMove).toHaveBeenCalledWith(attempts[2])
    expect(env.animateMock).not.toHaveBeenCalled()
  } finally {
    env.restore()
  }
})

it('shouldCommitDrag commits on distance or a matching fling', () => {
  // Quarter of an 800px stage commits regardless of (zero) velocity.
  expect(shouldCommitDrag(-201, 800, 0)).toBe(true)
  expect(shouldCommitDrag(201, 800, 0)).toBe(true)
  expect(shouldCommitDrag(-200, 800, 0)).toBe(false)
  // A fast fling commits a short drag when velocity matches its direction.
  expect(shouldCommitDrag(-100, 800, -0.8)).toBe(true)
  expect(shouldCommitDrag(-100, 800, 0.8)).toBe(false)
  // Tiny drags never commit, however fast.
  expect(shouldCommitDrag(-10, 800, -5)).toBe(false)
  // Degenerate geometry never commits.
  expect(shouldCommitDrag(-300, 0, 0)).toBe(false)
})

it('shouldEnableFeedPager is mobile-only and honors reduced motion', () => {
  const matchMedia = window.matchMedia
  const stub = (mobile: boolean, reduce: boolean) => {
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      writable: true,
      value: (query: string) => ({
        matches: query.includes('max-width') ? mobile : reduce,
        media: query,
        onchange: null,
        addEventListener() {},
        removeEventListener() {},
        dispatchEvent() { return false },
      }),
    })
  }
  try {
    stub(true, false)
    expect(shouldEnableFeedPager()).toBe(true)
    stub(true, true)
    expect(shouldEnableFeedPager()).toBe(false)
    stub(false, false)
    expect(shouldEnableFeedPager()).toBe(false)
  } finally {
    if (matchMedia === undefined) delete (window as { matchMedia?: unknown }).matchMedia
    else Object.defineProperty(window, 'matchMedia', { configurable: true, writable: true, value: matchMedia })
  }
})

const press = (name: string) => fireEvent.click(screen.getByRole('button', { name }))

it('a pinch drives the pose live, release closing past halfway settles to the clean view', () => {
  renderClipViewer(1)
  const dialog = screen.getByTestId('clip-viewer')
  press('Test pinch start')
  expect(dialog).toHaveClass('is-pinching')
  expect(dialog).not.toHaveClass('is-clean')
  press('Test pinch close')
  expect(dialog.style.getPropertyValue('--clip-pinch-p')).toBe('1')
  expect(Number(dialog.style.getPropertyValue('--clip-pinch-shrink'))).toBeGreaterThan(0)
  press('Test pinch end')
  expect(dialog).toHaveClass('is-clean')
  expect(dialog).not.toHaveClass('is-pinching')
  expect(dialog.style.getPropertyValue('--clip-pinch-p')).toBe('')
})

it('spreading from the clean view restores the overlays; a cancelled pinch reverts', () => {
  renderClipViewer(1)
  const dialog = screen.getByTestId('clip-viewer')
  press('Test pinch start')
  press('Test pinch close')
  press('Test pinch end')
  expect(dialog).toHaveClass('is-clean')
  press('Test pinch start')
  expect(dialog.style.getPropertyValue('--clip-pinch-p')).toBe('1')
  press('Test pinch spread')
  expect(dialog.style.getPropertyValue('--clip-pinch-p')).toBe('0')
  press('Test pinch end')
  expect(dialog).not.toHaveClass('is-clean')
  press('Test pinch start')
  press('Test pinch close')
  press('Test pinch cancel')
  expect(dialog).not.toHaveClass('is-clean')
})

it('changing dive restores the overlays', () => {
  const view = renderClipViewer(1)
  press('Test pinch start')
  press('Test pinch close')
  press('Test pinch end')
  expect(screen.getByTestId('clip-viewer')).toHaveClass('is-clean')
  view.rerender(
    <MemoryRouter>
      <ClipViewer
        attempt={attempts[2]}
        attempts={attempts}
        onClose={() => {}}
        onMove={() => {}}
        playbackRate={1}
        onPlaybackRateChange={() => {}}
      />
    </MemoryRouter>,
  )
  expect(screen.getByTestId('clip-viewer')).not.toHaveClass('is-clean')
})

it('pinchState maps finger travel to clean progress with a rounded overshoot', () => {
  expect(pinchState(false, 1)).toMatchObject({ progress: 0, overshoot: 0, clean: false })
  expect(pinchState(false, 0.9).progress).toBeCloseTo(0.2857, 3)
  expect(pinchState(false, 0.9).clean).toBe(false)
  expect(pinchState(false, 0.8).clean).toBe(true)
  expect(pinchState(false, 0.5)).toMatchObject({ progress: 1, clean: true })
  expect(pinchState(false, 0.5).overshoot).toBeGreaterThan(0)
  expect(pinchState(false, 0.1).overshoot).toBe(1)
  expect(pinchState(true, 1)).toMatchObject({ progress: 1, overshoot: 0, clean: true })
  expect(pinchState(true, 1.4)).toMatchObject({ progress: 0, clean: false })
  expect(pinchState(true, 1.1).clean).toBe(true)
  expect(pinchState(false, 1.5)).toMatchObject({ progress: 0, overshoot: 0 })
  expect(pinchState(true, NaN)).toMatchObject({ progress: 1, clean: true })
})

// ---- Studio layout (tablets and desktops) ----

it('studio shows the dive in a side panel with tabs, steps and the same-day filmstrip', async () => {
  const day = (id: number) => attempt(id, { dive_datetime: '2026-10-18T17:00:00', dive_code: id === 3 ? '201C' : '5122D', height: '1m' })
  const list = [day(1), day(2), day(3)]
  const onMove = vi.fn()
  render(
    <MemoryRouter>
      <ClipViewer attempt={list[0]} attempts={list} onClose={() => {}} onMove={onMove} playbackRate={1} onPlaybackRateChange={() => {}} />
    </MemoryRouter>,
  )
  const dialog = screen.getByRole('dialog')
  expect(dialog).toHaveClass('is-studio')
  expect(within(dialog).getByRole('heading', { name: '5122D' })).toBeInTheDocument()
  expect(screen.getByText('Forward somersault 1 twist free')).toBeInTheDocument()
  expect(screen.getByText(/1m springboard · DD 2.0 · Individual/)).toBeInTheDocument()
  // One like control, in the panel; no overlay copy.
  expect(screen.getAllByRole('button', { name: 'Like dive' })).toHaveLength(1)
  expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()
  // Anonymous viewers get comments and details, no evaluation tab.
  expect(screen.queryByRole('tab', { name: /Evaluation/ })).toBeNull()
  expect(screen.getByRole('tab', { name: 'Details' })).toHaveAttribute('aria-selected', 'true')
  const strip = screen.getByRole('navigation', { name: 'Dives from the same day' })
  expect(within(strip).getAllByRole('button')).toHaveLength(3)
  expect(within(strip).getAllByRole('button')[0]).toHaveAttribute('aria-current', 'true')
  await userEvent.click(within(strip).getByRole('button', { name: /Open 201C/ }))
  expect(onMove).toHaveBeenCalledWith(list[2])
})
