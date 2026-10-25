import React from 'react'
import { MemoryRouter } from 'react-router-dom'
import { act, fireEvent, render } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import ClipViewer, { FEED_PUSH_DURATION_MS } from './ClipViewer'
import { getPreviewForPlayback } from '../../utils/mediaPreview'
import type { Attempt } from '../../utils/attemptPresentation'

// Regression coverage for issue #57 at the viewer level: the incoming-clip
// cover the active player renders must be the very poster the pager neighbor
// frames show, carried through library-style selection changes (pointer
// drags on the live gesture surface, Next/Previous, browser Back / deep-link
// adoption) without a black gap. The real DiveVideoPlayer and
// ImmersiveControls render here; only the social API is mocked.

vi.mock('../../services/api', () => ({
  api: {
    get: vi.fn().mockResolvedValue({ data: { liked: false, like_count: 0, comment_count: 0 } }),
    put: vi.fn(),
  },
}))

import { api } from '../../services/api'

const attempts: Attempt[] = [1, 2, 3, 4, 5].map((id) => ({
  id,
  dive_code: '103B',
  performance: 'G',
  performance_numeric: 3,
  height: '3m',
  dive_datetime: `2026-07-0${id}T10:00:00`,
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
}))

const statuses = Object.fromEntries(
  [1, 2, 3, 4, 5].map((id) => [
    `uuid-${id}`,
    { status: 'ready', poster_url: `/poster-${id}.jpg`, playback_url: `/video-${id}.mp4` },
  ]),
)

function stubMediaFetch() {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/api/v1/media/status/batch')) {
      return { ok: true, json: async () => statuses }
    }
    // Authoritative per-clip revalidation must answer ready like production,
    // otherwise applyStatus('' status) drops the ready phase mid-navigation.
    const statusMatch = url.match(/\/api\/v1\/media\/([^/]+)\/status/)
    if (statusMatch) {
      const status = statuses[statusMatch[1]] ?? { status: 'missing', poster_url: null, playback_url: null }
      return {
        ok: true,
        json: async () => ({ video_uuid: statusMatch[1], can_request: false, available_renditions: [], ...status }),
      }
    }
    // Warm-up fetches of poster/playback bytes.
    return { ok: true, body: null, json: async () => ({}) }
  }))
}

function stubPagerEnvironment() {
  const animateMock = vi.fn(() => ({}))
  const animateDescriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'animate')
  const heightDescriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight')
  Object.defineProperty(HTMLElement.prototype, 'animate', {
    configurable: true,
    writable: true,
    value: animateMock,
  })
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
    configurable: true,
    get() { return 800 },
  })
  // jsdom has no PointerEvent; a MouseEvent subclass carries pointer fields.
  class Pointer extends MouseEvent {
    isPrimary = true
    pointerId = 1
  }
  vi.stubGlobal('PointerEvent', Pointer)
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
  return {
    animateMock,
    restore() {
      if (animateDescriptor) Object.defineProperty(HTMLElement.prototype, 'animate', animateDescriptor)
      else delete (HTMLElement.prototype as { animate?: unknown }).animate
      if (heightDescriptor) Object.defineProperty(HTMLElement.prototype, 'clientHeight', heightDescriptor)
      else delete (HTMLElement.prototype as { clientHeight?: unknown }).clientHeight
    },
  }
}

async function seedPreviewCache() {
  stubMediaFetch()
  await act(async () => {
    await Promise.all(attempts.map((attempt) => getPreviewForPlayback(attempt.video_uuid!)))
  })
}

function renderViewer(index: number, onMove: (attempt: Attempt) => void) {
  const view = render(
    <MemoryRouter>
      <ClipViewer
        attempt={attempts[index]}
        attempts={attempts}
        onClose={() => {}}
        onMove={onMove}
        playbackRate={1}
        onPlaybackRateChange={() => {}}
      />
    </MemoryRouter>,
  )
  const rerenderAt = (next: number) => {
    view.rerender(
      <MemoryRouter>
        <ClipViewer
          attempt={attempts[next]}
          attempts={attempts}
          onClose={() => {}}
          onMove={onMove}
          playbackRate={1}
          onPlaybackRateChange={() => {}}
        />
      </MemoryRouter>,
    )
  }
  return { view, rerenderAt }
}

const neighborPoster = (position: 'prev' | 'next') =>
  document.querySelector<HTMLImageElement>(`.clip-pager-neighbor.is-${position} img`)
const coverImg = () => document.querySelector<HTMLImageElement>('[data-testid="clip-cover"] img')
const gestureSurface = () => document.querySelector<HTMLButtonElement>('.clip-gesture')

/** A real vertical finger on the live gesture surface: press, travel, release. */
function dragOnGesture(dy: number) {
  const surface = gestureSurface()
  if (!surface) throw new Error('gesture surface not mounted')
  fireEvent.pointerDown(surface, { clientX: 100, clientY: 400, button: 0 })
  fireEvent.pointerMove(surface, { clientX: 100, clientY: 400 + Math.round(dy / 2) })
  fireEvent.pointerMove(surface, { clientX: 100, clientY: 400 + dy })
  fireEvent.pointerUp(surface, { clientX: 100, clientY: 400 + dy })
}

function findNavButton(label: 'Previous' | 'Next') {
  const button = Array.from(document.querySelectorAll('.clip-navigation button')).find(
    (candidate) => candidate.getAttribute('aria-label') === label,
  ) as HTMLButtonElement | undefined
  if (!button) throw new Error(`${label} button not found`)
  return button
}

beforeEach(() => {
  vi.mocked(api.get).mockResolvedValue({ data: { liked: false, like_count: 0, comment_count: 0 } })
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

it('the active player opens on the cached poster synchronously, before any status lookup', async () => {
  await seedPreviewCache()
  renderViewer(1, () => {})
  // The very first paint holds the incoming poster over the video — no
  // black frame while the player mounts.
  expect(coverImg()).toHaveAttribute('src', '/poster-2.jpg')
})

it('a pointer drag commits the swipe and hands the neighbor poster to the cover', async () => {
  const env = stubPagerEnvironment()
  try {
    vi.useFakeTimers()
    await seedPreviewCache()
    const seen: number[] = []
    const { rerenderAt } = renderViewer(1, (moved) => {
      seen.push(moved.id)
      rerenderAt(attempts.findIndex((attempt) => attempt.id === moved.id))
    })
    // The pager poster that followed the finger during the drag…
    const incoming = neighborPoster('next')
    expect(incoming).toHaveAttribute('src', '/poster-3.jpg')

    // …is captured by the gesture surface mounted OVER the loading cover,
    // and releasing past the threshold commits through to the next dive.
    dragOnGesture(-300)
    act(() => { vi.advanceTimersByTime(FEED_PUSH_DURATION_MS + 60) })
    expect(seen).toEqual([3])
    // The freshly mounted player's cover holds the very same poster bytes
    // the neighbor frame showed — same crop, same placement, no black gap.
    expect(coverImg()).toHaveAttribute('src', '/poster-3.jpg')
    expect(coverImg()).toHaveAttribute('src', incoming!.getAttribute('src')!)
    // The landed clip's own neighbors warmed in turn.
    expect(neighborPoster('prev')).toHaveAttribute('src', '/poster-2.jpg')
    expect(neighborPoster('next')).toHaveAttribute('src', '/poster-4.jpg')
    void rerenderAt
  } finally {
    vi.useRealTimers()
    env.restore()
  }
})

it('Next/Previous buttons land on the neighbor with its cached cover', async () => {
  const env = stubPagerEnvironment()
  try {
    vi.useFakeTimers()
    await seedPreviewCache()
    const { rerenderAt } = renderViewer(1, (moved) => {
      rerenderAt(attempts.findIndex((attempt) => attempt.id === moved.id))
    })
    fireEvent.click(findNavButton('Next'))
    act(() => { vi.advanceTimersByTime(FEED_PUSH_DURATION_MS + 60) })
    expect(coverImg()).toHaveAttribute('src', '/poster-3.jpg')
    fireEvent.click(findNavButton('Previous'))
    act(() => { vi.advanceTimersByTime(FEED_PUSH_DURATION_MS + 60) })
    expect(coverImg()).toHaveAttribute('src', '/poster-2.jpg')
  } finally {
    vi.useRealTimers()
    env.restore()
  }
})

it('browser Back / deep-link adoption lands on the adopted clip with its cached cover', async () => {
  await seedPreviewCache()
  const { rerenderAt } = renderViewer(1, () => {})
  rerenderAt(0)
  expect(coverImg()).toHaveAttribute('src', '/poster-1.jpg')
  rerenderAt(4)
  expect(coverImg()).toHaveAttribute('src', '/poster-5.jpg')
})
