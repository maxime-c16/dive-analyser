import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import ProfileDiveGrid from './ProfileDiveGrid'
import { getProfileDives } from '../services/communityApi'

vi.mock('../services/communityApi', () => ({ getProfileDives: vi.fn() }))

let intersect: IntersectionObserverCallback | undefined
const disconnect = vi.fn()
beforeEach(() => {
  intersect = undefined
  vi.stubGlobal('IntersectionObserver', class {
    constructor(callback: IntersectionObserverCallback) { intersect = callback }
    observe() {}
    disconnect = disconnect
  })
  vi.mocked(getProfileDives).mockResolvedValue({ items: [{
    id: 557, dive_code: '102C', height: '1m', dive_datetime: '2025-04-29T18:45:54Z',
    visibility: 'public', poster_url: null, playback_url: '/api/v1/media/revisions/1785/play',
  }], next_before: null })
})
afterEach(() => { vi.unstubAllGlobals() })

async function grid() {
  const result = render(<MemoryRouter><ProfileDiveGrid userId={20} /></MemoryRouter>)
  await screen.findByRole('link', { name: /102C/ })
  await waitFor(() => expect(intersect).toBeTypeOf('function'))
  return result
}
function visible() {
  act(() => intersect!([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver))
}

it('never loads a B2 original from a tile, even near the viewport', async () => {
  const { container } = await grid()
  expect(container.querySelector('video')).toBeNull()
  visible()
  // A B2 revision URL is not a renderable tile source: no grant, no
  // download, no black tile — the clip link stays usable.
  expect(container.querySelector('video')).toBeNull()
  expect(screen.getByRole('link', { name: /102C/ })).toHaveAttribute('href', '/dives?clip=557&scope=all')
})

it('renders the ready local web preview once the tile approaches the viewport', async () => {
  const page = await getProfileDives(20)
  page.items[0].playback_url = '/api/v1/media/cache/20/play'
  vi.mocked(getProfileDives).mockResolvedValue(page)
  const { container } = await grid()
  expect(container.querySelector('video')).toBeNull()
  visible()
  const video = container.querySelector('video')!
  expect(video).toHaveAttribute('src', '/api/v1/media/cache/20/play#t=0.001')
  expect(video).toHaveAttribute('preload', 'metadata')
  expect(video.muted).toBe(true)
  expect(video.autoplay).toBe(false)
  expect(video).toHaveAttribute('playsinline')
  expect(screen.getByRole('link', { name: /102C/ })).toHaveAttribute('href', '/dives?clip=557&scope=all')
})

it('uses the poster first and recovers with the ready web preview if its request fails', async () => {
  const page = await getProfileDives(20)
  page.items[0].poster_url = '/api/v1/media/cache/20/play'
  page.items[0].playback_url = '/api/v1/media/cache/21/play'
  vi.mocked(getProfileDives).mockResolvedValue(page)
  const { container } = await grid()
  expect(container.querySelector('img')).toHaveAttribute('src', '/api/v1/media/cache/20/play')
  visible()
  expect(container.querySelector('video')).toBeNull()
  fireEvent.error(container.querySelector('img')!)
  await waitFor(() => expect(container.querySelector('video')).not.toBeNull())
})

it('keeps a usable clip link without submitting preparation work when no media exists', async () => {
  const page = await getProfileDives(20)
  page.items[0].playback_url = null
  vi.mocked(getProfileDives).mockResolvedValue(page)
  const { container } = await grid()
  visible()
  expect(container.querySelector('video, img')).toBeNull()
  expect(screen.getByRole('link', { name: /102C/ })).toBeInTheDocument()
})
