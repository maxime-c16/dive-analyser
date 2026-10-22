import { useEffect, useRef, useState } from 'react'
import { api } from '../../services/api'
import { getPlaybackUrlFromStatus, type MediaStatus } from '../../services/mediaApi'
import type { SeriesClip } from '../../services/seriesApi'

export interface SeriesMediaEntry { clip: SeriesClip | null; poster?: string; playbackUrl?: string }
export type Media = { state: 'loading' | 'preparing' | 'ready' | 'error'; url?: string; poster?: string; forbidden?: boolean }

function delay(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const abort = () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')) }
    const timer = window.setTimeout(() => { signal.removeEventListener('abort', abort); resolve() }, ms)
    signal.addEventListener('abort', abort, { once: true })
  })
}

export function useSeriesMedia(entries: SeriesMediaEntry[], initialIndex?: number, retry = 0) {
  const [media, setMedia] = useState<Record<string, Media>>(() => Object.fromEntries(entries.flatMap(e => e.clip ? [[e.clip.video_uuid, { state: e.playbackUrl ? 'ready' : 'loading', url: e.playbackUrl, poster: e.poster }]] : [])))
  const mediaRef = useRef(media)
  mediaRef.current = media
  // Resolve authorized media URLs with at most two concurrent requests.
  // Preserve editor previews and never fetch camera bytes for the whole series. Consumers decide which video elements to preload.
  useEffect(() => {
    const controller = new AbortController()
    const { signal } = controller
    const start = initialIndex ?? Math.max(0, entries.findIndex(e => e.clip))
    const ordered = [...entries.slice(start), ...entries.slice(0, start)]
    const uuids = [...new Set(ordered.flatMap(e => e.clip ? [e.clip.video_uuid] : []))]
    const update = (uuid: string, value: Media) => {
      if (!signal.aborted) setMedia(old => ({ ...old, [uuid]: value }))
    }
    // Limit network calls, not whole preparation loops. A queued transcode
    // must never occupy a worker while unrelated clips are ready to play.
    let active = 0
    const waiting: Array<() => void> = []
    const request = async <T,>(task: () => Promise<T>): Promise<T> => {
      if (active >= 2) await new Promise<void>(resolve => waiting.push(resolve))
      else active++
      try {
        if (signal.aborted) throw new DOMException('Aborted', 'AbortError')
        return await task()
      } finally {
        const next = waiting.shift()
        if (next) next()
        else active--
      }
    }
    const resolve = async (uuid: string) => {
      const existing = mediaRef.current[uuid]
      if (existing?.state === 'ready' && existing.url) return
      const seed = entries.find(e => e.clip?.video_uuid === uuid)
      if (!existing && seed?.playbackUrl) { update(uuid, { state: 'ready', url: seed.playbackUrl, poster: seed.poster }); return }
      let poster = existing?.poster || seed?.poster
      update(uuid, { state: 'loading', poster })
      try {
        const statusUrl = `/api/v1/media/${encodeURIComponent(uuid)}/status`
        const get = () => request(async () => (await api.get<MediaStatus>(statusUrl, { signal, timeout: 12000 })).data)
        let status = await get()
        let requested = false
        let attempts = 0
        while (!signal.aborted) {
          poster = status.poster_url || poster
          const url = getPlaybackUrlFromStatus(status)
          if (url) { update(uuid, { state: 'ready', url, poster }); return }
          if (requested && ['failed', 'error', 'cancelled'].includes(status.job?.status || status.status)) {
            update(uuid, { state: 'error', poster }); return
          }
          if (status.can_request && !requested) {
            requested = true
            update(uuid, { state: 'preparing', poster })
            status = await request(async () => (await api.post<MediaStatus>(`/api/v1/media/${encodeURIComponent(uuid)}/request`,
              { rendition: 'proxy_720p', reason: 'user_view' }, { signal, timeout: 12000 })).data)
            continue
          }
          if (++attempts > 30 || (!status.can_request && !['preparing', 'queued', 'processing', 'running', 'pending'].includes(status.status))) {
            update(uuid, { state: 'error', poster }); return
          }
          update(uuid, { state: 'preparing', poster })
          await delay(Math.min(1500 + attempts * 150, 4000), signal)
          status = await get()
        }
      } catch (e) {
        const code = (e as { response?: { status: number } }).response?.status
        update(uuid, { state: 'error', poster, forbidden: code === 401 || code === 403 || code === 404 })
      }
    }
    uuids.forEach(uuid => { void resolve(uuid) })
    return () => controller.abort()
  }, [entries, initialIndex, retry])

  return [media, setMedia] as const
}
