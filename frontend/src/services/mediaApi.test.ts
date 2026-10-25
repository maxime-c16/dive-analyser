import { describe, expect, it } from 'vitest'
import {
  getDerivativePlaybackUrl,
  getPlaybackUrlFromStatus,
  getPreviewPlaybackUrl,
  getQualityChoices,
  type MediaStatus,
} from './mediaApi'

const base: MediaStatus = {
  video_uuid: 'uuid',
  status: 'ready',
  can_request: true,
  available_renditions: [],
  playback_url: '/api/v1/media/revisions/9/play',
  poster_url: null,
  full_quality_url: '/api/v1/media/revisions/9/play',
  preview_url: null,
}

describe('D5 derivative contract helpers', () => {
  it('ignores non-ready derivative roles (no invented URLs)', () => {
    const status: MediaStatus = {
      ...base,
      derivatives: {
        source_revision_id: 1,
        transform_version: 'ffmpeg-h264-web-v1',
        start: 'original',
        recommended: 'original',
        hq: { state: 'stale', playback_url: null, revision_id: 2, aliased_to: null },
        light: { state: 'missing', playback_url: null, revision_id: null, aliased_to: null },
        poster: { state: 'unavailable', playback_url: null, revision_id: null, aliased_to: null },
      },
    }
    expect(getDerivativePlaybackUrl(status, 'hq')).toBeNull()
    expect(getDerivativePlaybackUrl(status, 'light')).toBeNull()
    expect(getDerivativePlaybackUrl(status, 'poster')).toBeNull()
  })

  it('resolves ready light/hq/poster revision URLs', () => {
    const status: MediaStatus = {
      ...base,
      preview_url: '/api/v1/media/revisions/3/play',
      derivatives: {
        source_revision_id: 1,
        transform_version: 'ffmpeg-h264-web-v1',
        start: 'light',
        recommended: 'hq',
        hq: { state: 'ready', playback_url: '/api/v1/media/revisions/2/play', revision_id: 2, aliased_to: null },
        light: { state: 'ready', playback_url: '/api/v1/media/revisions/3/play', revision_id: 3, aliased_to: null },
        poster: { state: 'ready', playback_url: '/api/v1/media/revisions/4/play', revision_id: 4, aliased_to: null },
      },
    }
    expect(getDerivativePlaybackUrl(status, 'light')).toBe('/api/v1/media/revisions/3/play')
    expect(getDerivativePlaybackUrl(status, 'hq')).toBe('/api/v1/media/revisions/2/play')
    expect(getDerivativePlaybackUrl(status, 'poster')).toBe('/api/v1/media/revisions/4/play')
    // Starter stays the light derivative (fast first frame), never the original.
    expect(getPreviewPlaybackUrl(status)).toBe('/api/v1/media/revisions/3/play')
    expect(getPlaybackUrlFromStatus(status)).toBe('/api/v1/media/revisions/3/play')
  })

  it('orders quality choices starter-light, HQ, original without duplicates', () => {
    const status: MediaStatus = {
      ...base,
      preview_url: '/api/v1/media/revisions/3/play',
      derivatives: {
        source_revision_id: 1,
        transform_version: 'ffmpeg-h264-web-v1',
        start: 'light',
        recommended: 'hq',
        hq: { state: 'ready', playback_url: '/api/v1/media/revisions/2/play', revision_id: 2, aliased_to: null },
        light: { state: 'ready', playback_url: '/api/v1/media/revisions/3/play', revision_id: 3, aliased_to: null },
        poster: { state: 'ready', playback_url: '/api/v1/media/revisions/4/play', revision_id: 4, aliased_to: null },
      },
    }
    const keys = getQualityChoices(status).map(choice => choice.key)
    expect(keys).toEqual(['light', 'hq', 'original'])
  })

  it('deduplicates an aliased HQ (same bytes as light) out of the cycle', () => {
    const status: MediaStatus = {
      ...base,
      preview_url: '/api/v1/media/revisions/3/play',
      full_quality_url: '/api/v1/media/revisions/9/play',
      derivatives: {
        source_revision_id: 1,
        transform_version: 'ffmpeg-h264-web-v1',
        start: 'light',
        recommended: 'hq',
        hq: { state: 'ready', playback_url: '/api/v1/media/revisions/3/play', revision_id: 3, aliased_to: 'light' },
        light: { state: 'ready', playback_url: '/api/v1/media/revisions/3/play', revision_id: 3, aliased_to: null },
        poster: { state: 'missing', playback_url: null, revision_id: null, aliased_to: null },
      },
    }
    const keys = getQualityChoices(status).map(choice => choice.key)
    expect(keys).toEqual(['light', 'original'])
  })

  it('falls back to legacy preview/original with no derivatives block', () => {
    const status: MediaStatus = {
      ...base,
      preview_url: '/api/v1/media/cache/7/play',
      cache_entries: [{ id: 7, rendition: 'proxy_720p', playback_url: '/api/v1/media/cache/7/play' }],
    }
    expect(getDerivativePlaybackUrl(status, 'light')).toBeNull()
    const keys = getQualityChoices(status).map(choice => choice.key)
    expect(keys).toEqual(['preview', 'original'])
    // Legacy order is unchanged: preview first, never the original.
    expect(getPlaybackUrlFromStatus(status)).toBe('/api/v1/media/cache/7/play')
  })

  it('starts locally with HQ kept as an explicit choice', () => {
    const status: MediaStatus = {
      ...base,
      preview_url: '/api/v1/media/cache/7/play',
      cache_entries: [{ id: 7, rendition: 'proxy_720p', playback_url: '/api/v1/media/cache/7/play' }],
      derivatives: {
        source_revision_id: 1,
        transform_version: 'ffmpeg-h264-web-v1',
        start: 'hq',
        recommended: 'hq',
        hq: { state: 'ready', playback_url: '/api/v1/media/revisions/2/play', revision_id: 2, aliased_to: null },
        light: { state: 'missing', playback_url: null, revision_id: null, aliased_to: null },
        poster: { state: 'missing', playback_url: null, revision_id: null, aliased_to: null },
      },
    }
    expect(getPlaybackUrlFromStatus(status)).toBe('/api/v1/media/cache/7/play')
    const choices = getQualityChoices(status)
    expect(choices.map(choice => choice.key)).toEqual(['preview', 'hq', 'original'])
    expect(choices[1].url).toBe('/api/v1/media/revisions/2/play')
  })

  it('starts light with no cache entries at all', () => {
    const status: MediaStatus = {
      ...base,
      preview_url: '/api/v1/media/revisions/3/play',
      derivatives: {
        source_revision_id: 1,
        transform_version: 'ffmpeg-h264-web-v1',
        start: 'light',
        recommended: 'hq',
        hq: { state: 'ready', playback_url: '/api/v1/media/revisions/2/play', revision_id: 2, aliased_to: null },
        light: { state: 'ready', playback_url: '/api/v1/media/revisions/3/play', revision_id: 3, aliased_to: null },
        poster: { state: 'ready', playback_url: '/api/v1/media/revisions/4/play', revision_id: 4, aliased_to: null },
      },
    }
    expect(getPlaybackUrlFromStatus(status)).toBe('/api/v1/media/revisions/3/play')
  })

  it('starts browser-original light-only clips with zero cache and no original', () => {
    // Actual backend shape for a browser_original canonical source with
    // a ready durable light, zero cache entries and no backbone original.
    const status: MediaStatus = {
      video_uuid: 'browser-light',
      status: 'ready',
      can_request: true,
      available_renditions: [],
      playback_url: '/api/v1/media/revisions/3/play',
      poster_url: '/api/v1/media/revisions/4/play',
      full_quality_url: null,
      preview_url: '/api/v1/media/revisions/3/play',
      cache_entries: [],
      job: null,
      derivatives: {
        source_revision_id: 1,
        transform_version: 'ffmpeg-h264-web-v1',
        start: 'light',
        recommended: 'light',
        hq: { state: 'missing', playback_url: null, revision_id: null, aliased_to: null },
        light: { state: 'ready', playback_url: '/api/v1/media/revisions/3/play', revision_id: 3, aliased_to: null },
        poster: { state: 'ready', playback_url: '/api/v1/media/revisions/4/play', revision_id: 4, aliased_to: null },
      },
    }
    expect(getPlaybackUrlFromStatus(status)).toBe('/api/v1/media/revisions/3/play')
    expect(getPreviewPlaybackUrl(status)).toBe('/api/v1/media/revisions/3/play')
    expect(getQualityChoices(status).map(choice => choice.key)).toEqual(['light'])
  })

  it('starts browser-original HQ-only clips on the HQ derivative', () => {
    const status: MediaStatus = {
      video_uuid: 'browser-hq',
      status: 'ready',
      can_request: true,
      available_renditions: [],
      playback_url: '/api/v1/media/revisions/2/play',
      poster_url: null,
      full_quality_url: null,
      preview_url: '/api/v1/media/revisions/2/play',
      cache_entries: [],
      job: null,
      derivatives: {
        source_revision_id: 1,
        transform_version: 'ffmpeg-h264-web-v1',
        start: 'hq',
        recommended: 'hq',
        hq: { state: 'ready', playback_url: '/api/v1/media/revisions/2/play', revision_id: 2, aliased_to: null },
        light: { state: 'missing', playback_url: null, revision_id: null, aliased_to: null },
        poster: { state: 'missing', playback_url: null, revision_id: null, aliased_to: null },
      },
    }
    expect(getPlaybackUrlFromStatus(status)).toBe('/api/v1/media/revisions/2/play')
    expect(getQualityChoices(status).map(choice => choice.key)).toEqual(['hq'])
  })

  it('offers nothing playable for poster-only durable clips', () => {
    const status: MediaStatus = {
      video_uuid: 'browser-poster',
      status: 'missing',
      can_request: true,
      available_renditions: [],
      playback_url: null,
      poster_url: '/api/v1/media/revisions/4/play',
      full_quality_url: null,
      preview_url: null,
      cache_entries: [],
      job: null,
      derivatives: {
        source_revision_id: 1,
        transform_version: 'ffmpeg-h264-web-v1',
        start: 'original',
        recommended: 'original',
        hq: { state: 'missing', playback_url: null, revision_id: null, aliased_to: null },
        light: { state: 'missing', playback_url: null, revision_id: null, aliased_to: null },
        poster: { state: 'ready', playback_url: '/api/v1/media/revisions/4/play', revision_id: 4, aliased_to: null },
      },
    }
    expect(getDerivativePlaybackUrl(status, 'light')).toBeNull()
    expect(getDerivativePlaybackUrl(status, 'hq')).toBeNull()
    expect(getPlaybackUrlFromStatus(status)).toBeNull()
    expect(getPreviewPlaybackUrl(status)).toBeNull()
    expect(getQualityChoices(status)).toEqual([])
  })
})
