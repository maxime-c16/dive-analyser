import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import ProfileDiveGrid from './ProfileDiveGrid'
import { getProfileDives } from '../services/communityApi'

vi.mock('../services/communityApi', () => ({ getProfileDives: vi.fn() }))

let intersect: IntersectionObserverCallback
const disconnect = vi.fn()
beforeEach(() => {
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
  return result
}
function visible() {
  act(() => intersect([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver))
}

it('loads a silent B2 first frame only when the tile approaches the viewport', async () => {
  const { container } = await grid()
  expect(container.querySelector('video')).toBeNull()
  visible()
  const video = container.querySelector('video')!
  expect(video).toHaveAttribute('src', '/api/v1/media/revisions/1785/play#t=0.001')
  expect(video).toHaveAttribute('preload', 'metadata')
  expect(video.muted).toBe(true)
  expect(video.autoplay).toBe(false)
  expect(video).toHaveAttribute('playsinline')
  expect(screen.getByRole('link', { name: /102C/ })).toHaveAttribute('href', '/dives?clip=557&scope=all')
})

it('uses the poster first and recovers with B2 if its request fails', async () => {
  const page = await getProfileDives(20)
  page.items[0].poster_url = '/api/v1/media/cache/20/play'
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
