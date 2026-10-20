import React from 'react'
import { BrowserRouter } from 'react-router-dom'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import Dives from './Dives'

vi.mock('../services/api', () => ({ api: { get: vi.fn() } }))
vi.mock('../services/mediaApi', () => ({ getMediaStatus: vi.fn().mockResolvedValue({ poster_url: null, playback_url: null }) }))
vi.mock('../components/DiveVideoPlayer', () => ({ default: ({ videoUuid, playbackRate }: { videoUuid: string; playbackRate: number }) => <div>Native player {videoUuid}<video data-testid="player-video" data-rate={playbackRate} /></div> }))

import { api } from '../services/api'
import { getMediaStatus } from '../services/mediaApi'

const dive = (id: number, code: string, diverId: number, options: Partial<Record<string, unknown>> = {}) => ({
  id, dive_code: code, diver_id: diverId, performance: 'G', performance_numeric: 3, height: '1m', dive_datetime: `2026-07-${String((id % 28) + 1).padStart(2, '0')}T10:00:00`, session_id: 1, is_lineup: false, is_sync: false, platform_type: 'springboard', position: code.slice(-1), official_dd: 1.5, phase1_performance: 'G', phase2_performance: 'G', raw_caption: `${code} G/G`, video_uuid: `uuid-${id}`, ...options,
})

const divers = [
  { id: 1, display_name: 'Maxime', is_primary_user: true },
  { id: 2, display_name: 'Paul', is_primary_user: false },
]

function mockDives(count: number, smackFrom = Number.POSITIVE_INFINITY) {
  return Array.from({ length: count }, (_, index) => {
    const id = index + 1
    return dive(id, '103B', 1, { raw_caption: id >= smackFrom ? '103B G/G SMACK' : '103B G/G' })
  })
}

function renderAt(url: string) {
  window.history.replaceState(null, '', url)
  return render(
    <BrowserRouter>
      <Dives />
    </BrowserRouter>,
  )
}

beforeEach(() => {
  window.history.replaceState(null, '', '/')
  vi.mocked(getMediaStatus).mockResolvedValue({ poster_url: null, playback_url: null } as any)
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === '/api/v1/divers') return Promise.resolve({ data: divers })
    return Promise.resolve({ data: mockDives(3) })
  })
})

it('opening a clip pushes one history entry and preserves query params', async () => {
  renderAt('/dives?q=103&view=list')
  const cards = await screen.findAllByRole('button', { name: /Open 103B attempt/ })
  const indexBefore = window.history.state.idx
  await userEvent.click(cards[0])
  expect(await screen.findByRole('dialog')).toBeInTheDocument()
  expect(window.location.search).toBe('?q=103&view=list&clip=1')
  expect(window.history.state.idx).toBe(indexBefore + 1)
})

it('reloading a URL with a selected clip reopens the viewer', async () => {
  renderAt('/dives?clip=2')
  const dialog = await screen.findByRole('dialog')
  expect(dialog).toBeInTheDocument()
  expect(screen.getByText('Native player uuid-2')).toBeInTheDocument()
})

it('invalid or stale clip identity fails safely and keeps the Library usable', async () => {
  renderAt('/dives?clip=999')
  await screen.findAllByRole('button', { name: /Open 103B attempt/ })
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  await waitFor(() => expect(window.location.search).not.toContain('clip='))
  expect((await screen.findAllByRole('button', { name: /Open 103B attempt/ })).length).toBeGreaterThan(0)
})

it('Next and Previous update the selected clip without history spam', async () => {
  renderAt('/dives?scope=all')
  const cards = await screen.findAllByRole('button', { name: /Open 103B attempt/ })
  const indexBefore = window.history.state.idx
  await userEvent.click(cards[0])
  expect(await screen.findByText('Native player uuid-1')).toBeInTheDocument()
  expect(window.history.state.idx).toBe(indexBefore + 1)

  await userEvent.click(screen.getByRole('button', { name: 'Next' }))
  expect(await screen.findByText('Native player uuid-2')).toBeInTheDocument()
  expect(window.location.search).toBe('?scope=all&clip=2')
  expect(window.history.state.idx).toBe(indexBefore + 1)

  await userEvent.click(screen.getByRole('button', { name: 'Previous' }))
  expect(await screen.findByText('Native player uuid-1')).toBeInTheDocument()
  expect(window.location.search).toBe('?scope=all&clip=1')
  expect(window.history.state.idx).toBe(indexBefore + 1)
})

it('the position counter N / TOTAL reflects the filtered result set', async () => {
  renderAt('/dives?scope=all')
  const cards = await screen.findAllByRole('button', { name: /Open 103B attempt/ })
  await userEvent.click(cards[0])
  const dialog = await screen.findByRole('dialog')
  expect(dialog.textContent).toContain('1 / 3')
  await userEvent.click(screen.getByRole('button', { name: 'Next' }))
  expect(await screen.findByText('Native player uuid-2')).toBeInTheDocument()
  expect(dialog.textContent).toContain('2 / 3')
})

it('boundaries disable Previous on the first and Next on the last result', async () => {
  renderAt('/dives?scope=all')
  const cards = await screen.findAllByRole('button', { name: /Open 103B attempt/ })
  await userEvent.click(cards[0])
  await screen.findByRole('dialog')
  expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Next' })).toBeEnabled()
  await userEvent.click(screen.getByRole('button', { name: 'Next' }))
  await userEvent.click(screen.getByRole('button', { name: 'Next' }))
  expect(await screen.findByText('Native player uuid-3')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Previous' })).toBeEnabled()
})

it('browser Back closes the viewer before leaving the Library', async () => {
  renderAt('/dives?q=103&view=list')
  const cards = await screen.findAllByRole('button', { name: /Open 103B attempt/ })
  await userEvent.click(cards[0])
  expect(await screen.findByRole('dialog')).toBeInTheDocument()
  window.history.back()
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(window.location.pathname).toBe('/dives')
  expect(window.location.search).toBe('?q=103&view=list')
})

it('the Back to Library control removes clip state without adding history noise', async () => {
  renderAt('/dives?scope=all')
  const cards = await screen.findAllByRole('button', { name: /Open 103B attempt/ })
  await userEvent.click(cards[0])
  expect(await screen.findByRole('dialog')).toBeInTheDocument()
  const lengthAfterOpen = window.history.length
  await userEvent.click(screen.getByRole('button', { name: 'Back to Library' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(window.location.search).toBe('?scope=all')
  expect(window.history.length).toBe(lengthAfterOpen)
})

it('Escape closes the viewer', async () => {
  renderAt('/dives?scope=all')
  const cards = await screen.findAllByRole('button', { name: /Open 103B attempt/ })
  await userEvent.click(cards[0])
  expect(await screen.findByRole('dialog')).toBeInTheDocument()
  fireEvent.keyDown(document, { key: 'Escape' })
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(window.location.search).toBe('?scope=all')
})

it('Shift+ArrowLeft / Shift+ArrowRight move through the result set with REPLACE', async () => {
  renderAt('/dives?scope=all')
  const cards = await screen.findAllByRole('button', { name: /Open 103B attempt/ })
  const indexBefore = window.history.state.idx
  await userEvent.click(cards[0])
  expect(await screen.findByRole('dialog')).toBeInTheDocument()

  fireEvent.keyDown(document, { key: 'ArrowRight', shiftKey: true })
  expect(await screen.findByText('Native player uuid-2')).toBeInTheDocument()
  expect(window.location.search).toBe('?scope=all&clip=2')
  expect(window.history.state.idx).toBe(indexBefore + 1)

  fireEvent.keyDown(document, { key: 'ArrowLeft', shiftKey: true })
  expect(await screen.findByText('Native player uuid-1')).toBeInTheDocument()
  expect(window.location.search).toBe('?scope=all&clip=1')
  expect(window.history.state.idx).toBe(indexBefore + 1)
})

it('plain ArrowLeft/ArrowRight do not hijack clip navigation or native video seek', async () => {
  renderAt('/dives?scope=all')
  const cards = await screen.findAllByRole('button', { name: /Open 103B attempt/ })
  await userEvent.click(cards[0])
  await screen.findByRole('dialog')

  fireEvent.keyDown(document, { key: 'ArrowRight' })
  fireEvent.keyDown(document, { key: 'ArrowLeft' })
  expect(screen.getByText('Native player uuid-1')).toBeInTheDocument()
  expect(window.location.search).toBe('?scope=all&clip=1')
})

it('Space does not navigate and is inert when the viewer has no video element', async () => {
  renderAt('/dives?scope=all')
  const cards = await screen.findAllByRole('button', { name: /Open 103B attempt/ })
  await userEvent.click(cards[0])
  await screen.findByRole('dialog')

  // The mocked player renders a video stub; dispatching Space on the dialog
  // must not change the selected clip or throw.
  fireEvent.keyDown(screen.getByRole('dialog'), { key: ' ' })
  expect(window.location.search).toBe('?scope=all&clip=1')
})

it('the playback-rate select drives the player rate and survives clip navigation', async () => {
  renderAt('/dives?scope=all')
  const cards = await screen.findAllByRole('button', { name: /Open 103B attempt/ })
  await userEvent.click(cards[0])
  await screen.findByRole('dialog')

  const rate = screen.getByRole('combobox', { name: 'Playback speed' }) as HTMLSelectElement
  await userEvent.selectOptions(rate, '0.5')
  expect(screen.getByTestId('player-video').getAttribute('data-rate')).toBe('0.5')

  await userEvent.click(screen.getByRole('button', { name: 'Next' }))
  expect(await screen.findByText('Native player uuid-2')).toBeInTheDocument()
  expect(screen.getByTestId('player-video').getAttribute('data-rate')).toBe('0.5')
  expect((screen.getByRole('combobox', { name: 'Playback speed' }) as HTMLSelectElement).value).toBe('0.5')
})

it('closing the viewer returns focus to the originating Library card', async () => {
  renderAt('/dives?scope=all')
  const cards = await screen.findAllByRole('button', { name: /Open 103B attempt/ })
  await userEvent.click(cards[0])
  const dialog = await screen.findByRole('dialog')
  expect(dialog).toHaveFocus()
  await userEvent.click(screen.getByRole('button', { name: 'Back to Library' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  await waitFor(() =>
    expect((document.activeElement as HTMLElement).getAttribute('data-attempt-id')).toBe('1'),
  )
})

it('an attempt without linked media keeps a usable viewer state', async () => {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === '/api/v1/divers') return Promise.resolve({ data: divers })
    return Promise.resolve({ data: [dive(1, '103B', 1, { video_uuid: null })] })
  })
  renderAt('/dives?clip=1')
  const dialog = await screen.findByRole('dialog')
  expect(screen.getByText('No linked clip for this attempt.')).toBeInTheDocument()
  expect(dialog.querySelectorAll('video')).toHaveLength(0)
})

it(
  'expanded result depth survives the clip loop; filter changes still reset it',
  async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === '/api/v1/divers') return Promise.resolve({ data: divers })
      return Promise.resolve({ data: mockDives(120, 61) })
    })
    renderAt('/dives?scope=all')
    const showMore = () => screen.queryByRole('button', { name: 'Show 48 more attempts' })
    await screen.findAllByRole('button', { name: /Open 103B attempt/ })
    for (let i = 0; i < 3 && showMore(); i += 1) {
      await userEvent.click(showMore()!)
    }
    await waitFor(() => expect(showMore()).not.toBeInTheDocument())

    const cards = screen.getAllByRole('button', { name: /Open 103B attempt/ })
    await userEvent.click(cards[0])
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Back to Library' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(showMore()).not.toBeInTheDocument()

    const search = screen.getByRole('textbox', { name: 'Search dives' })
    await userEvent.type(search, 'smack')
    await waitFor(() => expect(showMore()).toBeInTheDocument(), { timeout: 4000 })
  },
  20000,
)

it('an empty result set is distinct from a failure and offers Clear filters', async () => {
  renderAt('/dives?scope=all')
  await screen.findAllByRole('button', { name: /Open 103B attempt/ })
  const search = screen.getByRole('textbox', { name: 'Search dives' })
  await userEvent.type(search, 'zzz')
  expect(await screen.findByText('No attempts match this search.')).toBeInTheDocument()
  expect(screen.queryByText('The dive library could not be loaded.')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /Clear filters/ }))
  expect(await screen.findAllByRole('button', { name: /Open 103B attempt/ })).toHaveLength(3)
})

it('a library load failure exposes what failed and a working Retry', async () => {
  vi.mocked(api.get).mockRejectedValueOnce(new Error('network down'))
  renderAt('/dives')
  expect(await screen.findByText('The dive library could not be loaded.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
  expect((await screen.findAllByRole('button', { name: /Open 103B attempt/ })).length).toBeGreaterThan(0)
  expect(screen.queryByText('The dive library could not be loaded.')).not.toBeInTheDocument()
})

it('closing an in-library viewer then Back reaches the preceding page, without a duplicate Library entry', async () => {
  window.history.pushState(null, '', '/messages/42')
  window.history.pushState(null, '', '/dives?q=103&view=list')
  renderAt('/dives?q=103&view=list')
  const cards = await screen.findAllByRole('button', { name: /Open 103B attempt/ })
  await userEvent.click(cards[0])
  await screen.findByRole('dialog')
  await userEvent.click(screen.getByRole('button', { name: 'Next' }))
  await screen.findByText('Native player uuid-2')
  await userEvent.click(screen.getByRole('button', { name: 'Back to Library' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(window.location.search).toBe('?q=103&view=list')
  window.history.back()
  await waitFor(() => expect(window.location.pathname).toBe('/messages/42'))
})

it.each(['/users/5', '/messages/42'])('closing a clip linked from %s stays in Library and Back returns to its source', async source => {
  window.history.pushState(null, '', source)
  window.history.pushState(null, '', '/dives?scope=all&clip=2')
  renderAt('/dives?scope=all&clip=2')
  await screen.findByRole('dialog')
  await userEvent.click(screen.getByRole('button', { name: 'Back to Library' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(window.location.pathname).toBe('/dives')
  expect(window.location.search).toBe('?scope=all')
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'Search dives' })).toHaveFocus())
  window.history.back()
  await waitFor(() => expect(window.location.pathname).toBe(source))
})


it('keeps changed filters on close instead of returning to a stale Library entry', async () => {
  renderAt('/dives?q=103')
  const cards = await screen.findAllByRole('button', { name: /Open 103B attempt/ })
  await userEvent.click(cards[0]); await screen.findByRole('dialog')
  fireEvent.change(screen.getByRole('textbox', { name: 'Search dives' }), { target: { value: '103B' } })
  await waitFor(() => expect(window.location.search).toContain('q=103B'))
  await userEvent.click(screen.getByRole('button', { name: 'Back to Library' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(window.location.search).toBe('?q=103B')
})


it('recognizes an in-library opener with noncanonical URL encoding', async () => {
  window.history.pushState(null, '', '/community')
  window.history.pushState(null, '', '/dives?q=103&from=message%20link')
  renderAt('/dives?q=103&from=message%20link')
  const cards = await screen.findAllByRole('button', { name: /Open 103B attempt/ })
  await userEvent.click(cards[0]); await screen.findByRole('dialog')
  await userEvent.click(screen.getByRole('button', { name: 'Back to Library' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(window.location.search).toBe('?q=103&from=message%20link')
  window.history.back()
  await waitFor(() => expect(window.location.pathname).toBe('/community'))
})
