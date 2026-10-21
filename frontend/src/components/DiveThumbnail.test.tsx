import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import DiveThumbnail from './DiveThumbnail'
import type { Attempt } from '../utils/attemptPresentation'

vi.mock('../utils/mediaPreview', () => ({
  cachedPreview: vi.fn(),
  getPreview: vi.fn(),
}))

import { cachedPreview } from '../utils/mediaPreview'

const dive = {
  id: 2901,
  dive_code: '201C',
  performance: '8.4',
  performance_numeric: 8.4,
  height: '1m',
  dive_datetime: '2026-10-03T09:21:03',
  session_id: 1,
  is_lineup: false,
  is_sync: false,
  platform_type: 'springboard',
  official_dd: null,
  video_uuid: 'FE1E4259-E095-4E9B-8A86-B4EE8A93072B',
} as Attempt

beforeEach(() => {
  vi.mocked(cachedPreview).mockReset()
})

it('renders the poster image when available', () => {
  vi.mocked(cachedPreview).mockReturnValue({
    posterUrl: '/api/v1/media/cache/1/play',
    videoThumbUrl: null,
    playbackUrl: '/api/v1/media/cache/2/play',
    ready: true,
  })
  render(<DiveThumbnail dive={dive} compact />)
  expect(screen.getByRole('img')).toHaveAttribute('src', '/api/v1/media/cache/1/play')
})

it('falls back to the playable proxy when the poster is missing (poster job failed)', () => {
  // Regression: dive 2901 had a ready proxy_360p but no poster
  // (poster job osxphotos_export_timeout) and rendered a blank tile.
  vi.mocked(cachedPreview).mockReturnValue({
    posterUrl: null,
    videoThumbUrl: '/api/v1/media/cache/2289/play',
    playbackUrl: '/api/v1/media/cache/2289/play',
    ready: true,
  })
  const { container } = render(<DiveThumbnail dive={dive} compact />)
  const video = container.querySelector('video')
  expect(video).not.toBeNull()
  expect(video).toHaveAttribute('src', '/api/v1/media/cache/2289/play')
})

it('falls back to the ready web preview when the poster image fails to load', () => {
  // The tile carries both the poster and its cheap local web preview, so a
  // broken poster recovers to motion instead of a blank tile. A B2 original
  // URL would never be carried here (mediaPreview.ts filters it out).
  vi.mocked(cachedPreview).mockReturnValue({
    posterUrl: '/api/v1/media/cache/broken/play',
    videoThumbUrl: '/api/v1/media/cache/2289/play',
    playbackUrl: '/api/v1/media/cache/2289/play',
    ready: true,
  })
  const { container } = render(<DiveThumbnail dive={dive} compact />)
  fireEvent.error(screen.getByRole('img'))
  const video = container.querySelector('video')
  expect(video).not.toBeNull()
  expect(video).toHaveAttribute('src', '/api/v1/media/cache/2289/play')
})

it('shows a placeholder rather than the camera original when no web preview exists', () => {
  vi.mocked(cachedPreview).mockReturnValue({
    posterUrl: null,
    videoThumbUrl: null,
    playbackUrl: '/api/v1/media/revisions/1785/play',
    ready: false,
  })
  const { container } = render(<DiveThumbnail dive={dive} compact />)
  expect(container.querySelector('video')).toBeNull()
  expect(screen.getByText('201C')).toBeInTheDocument()
})

it('compact placeholder still shows the dive code when nothing is playable', () => {
  vi.mocked(cachedPreview).mockReturnValue({
    posterUrl: null,
    videoThumbUrl: null,
    playbackUrl: null,
    ready: false,
  })
  render(<DiveThumbnail dive={dive} compact />)
  expect(screen.getByText('201C')).toBeInTheDocument()
})
