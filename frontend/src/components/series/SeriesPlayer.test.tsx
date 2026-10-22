import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '../../i18n'
import { api } from '../../services/api'
import SeriesPlayer, { type SeriesPlaybackEntry } from './SeriesPlayer'

vi.mock('../../services/api', () => ({ api: { get: vi.fn(), post: vi.fn() } }))
const clip = (id: number) => ({ id, video_uuid: `clip-${id}`, date: '2026-10-22', mean_score: 7,
  rating_count: 2, url: `/dives?clip=${id}` })
const entries: SeriesPlaybackEntry[] = [
  { code: '101B', clip: clip(1) }, { code: '201B', clip: null }, { code: '301B', clip: clip(3) },
]
const ready = (id: number) => ({ video_uuid: `clip-${id}`, status: 'ready', can_request: false,
  available_renditions: ['proxy_720p'], preview_url: `/api/v1/media/cache/${id}/play` })

beforeEach(async () => {
  vi.clearAllMocks()
  await i18n.changeLanguage('fr')
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {})
  vi.mocked(api.get).mockImplementation(async url => ({ data: ready(url.includes('clip-3') ? 3 : 1) }))
})

describe('series video playback', () => {
  it('preloads the next clip, plays in sheet order, and reports missing slots explicitly', async () => {
    render(<SeriesPlayer entries={entries} height="3m" title="Printemps" onClose={vi.fn()} />)
    expect(screen.getByText(/1 passage sans clip/)).toBeInTheDocument()
    const first = await screen.findByLabelText('Vidéo du passage 1')
    const incoming = await screen.findByLabelText('Vidéo du passage 3')
    expect(incoming).toHaveAttribute('preload', 'auto')
    expect(incoming).toHaveClass('is-preloading')
    await userEvent.click(screen.getByRole('button', { name: 'Lire la série' }))
    await waitFor(() => expect(HTMLMediaElement.prototype.play).toHaveBeenCalled())
    fireEvent.ended(first)
    await waitFor(() => expect(incoming).toHaveClass('is-current'))
    expect(screen.getByText('Passage 3/3 · 301B')).toBeInTheDocument()
    // The buffered element is reused, not recreated with a second source load.
    expect(screen.getByLabelText('Vidéo du passage 3')).toBe(incoming)
    fireEvent.ended(incoming)
    expect(await screen.findByText('Fin de la série')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Revoir la série' }))
    await screen.findByLabelText('Vidéo du passage 1')
    expect(screen.getByText('Passage 1/3 · 101B')).toBeInTheDocument()
  })

  it('does not silently skip a clip whose authorization was revoked', async () => {
    vi.mocked(api.get).mockImplementation(async url => {
      if (url.includes('clip-3')) throw { response: { status: 404 } }
      return { data: ready(1) }
    })
    render(<SeriesPlayer entries={entries} height="3m" title="Printemps" onClose={vi.fn()} />)
    const first = await screen.findByLabelText('Vidéo du passage 1')
    await waitFor(() => expect(screen.getByRole('button', { name: /3 301B/ })).toHaveTextContent('Indisponible'))
    fireEvent.ended(first)
    expect(await screen.findByRole('alert')).toHaveTextContent('plus accessible')
    expect(screen.getByRole('button', { name: 'Lire la série' })).toBeDisabled()
    expect(screen.queryByLabelText('Vidéo du passage 3')).not.toBeInTheDocument()
  })

  it('uses the existing preparation endpoint when no playable rendition is ready', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { status: 'missing', can_request: true } })
    vi.mocked(api.post).mockResolvedValue({ data: ready(1) })
    render(<SeriesPlayer entries={[entries[0]]} height="3m" title="Printemps" onClose={vi.fn()} />)
    await screen.findByLabelText('Vidéo du passage 1')
    expect(api.post).toHaveBeenCalledWith('/api/v1/media/clip-1/request',
      { rendition: 'proxy_720p', reason: 'user_view' }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
  })

  it('stops transfers and aborts status requests when the player closes', async () => {
    let resolve!: (r: { data: ReturnType<typeof ready> }) => void
    vi.mocked(api.get).mockReturnValue(new Promise(r => { resolve = r }))
    const { unmount } = render(<SeriesPlayer entries={[entries[0]]} height="3m" title="Printemps" onClose={vi.fn()} />)
    const signal = vi.mocked(api.get).mock.calls[0][1]?.signal
    unmount()
    expect(signal?.aborted).toBe(true)
    await act(async () => resolve({ data: ready(1) }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
  it('prioritizes the clicked card when starting from the middle of the series', async () => {
    render(<SeriesPlayer entries={entries} height="3m" title="Printemps" initialIndex={2} onClose={vi.fn()} />)
    await screen.findByLabelText('Vidéo du passage 3')
    expect(api.get).toHaveBeenNthCalledWith(1, '/api/v1/media/clip-3/status', expect.anything())
    expect(screen.getByText('Passage 3/3 · 301B')).toBeInTheDocument()
  })
})


it('starts with the authorized preview already loaded by the editor', async () => {
  render(<SeriesPlayer entries={[{ ...entries[0], poster: '/poster.jpg', playbackUrl: '/cached-preview.mp4' }]} height="3m" title="Ready" onClose={vi.fn()} />)
  const video = screen.getByLabelText('Vidéo du passage 1')
  expect(video).toHaveAttribute('src', '/cached-preview.mp4')
  expect(api.get).not.toHaveBeenCalled()
  expect(api.post).not.toHaveBeenCalled()
  expect(screen.getByText('Chargement de la vidéo…')).toBeInTheDocument()
  fireEvent.loadedData(video)
  expect(screen.queryByText('Chargement de la vidéo…')).not.toBeInTheDocument()
})

it('checks later clips while two earlier clips are being prepared', async () => {
  vi.mocked(api.get).mockImplementation(async url => ({ data: url.includes('clip-3') ? ready(3) : { status: 'queued', can_request: true, poster_url: '/waiting.jpg', job: { status: 'queued' } } }))
  vi.mocked(api.post).mockResolvedValue({ data: { status: 'queued', can_request: true, job: { status: 'queued' } } })
  const all = [entries[0], { code: '201B', clip: clip(2) }, entries[2]]
  const { unmount } = render(<SeriesPlayer entries={all} height="3m" title="Mixed" onClose={vi.fn()} />)
  await waitFor(() => expect(screen.getByRole('button', { name: /3 301B/ })).not.toHaveTextContent('Vérification'))
  await userEvent.click(screen.getByRole('button', { name: /3 301B/ }))
  expect(await screen.findByLabelText('Vidéo du passage 3')).toHaveAttribute('src', '/api/v1/media/cache/3/play')
  expect(screen.getByRole('button', { name: /1 101B/ })).toHaveTextContent('Préparation')
  unmount()
})

it('retries only the failed clip without reloading a ready neighbour', async () => {
  render(<SeriesPlayer entries={entries} height="3m" title="Retry" onClose={vi.fn()} />)
  const first = await screen.findByLabelText('Vidéo du passage 1')
  const next = await screen.findByLabelText('Vidéo du passage 3')
  fireEvent.error(first)
  await userEvent.click(await screen.findByRole('button', { name: 'Réessayer' }))
  await screen.findByLabelText('Vidéo du passage 1')
  expect(screen.getByLabelText('Vidéo du passage 3')).toBe(next)
  expect(vi.mocked(api.get).mock.calls.filter(([url]) => url.includes('clip-3'))).toHaveLength(1)
})
