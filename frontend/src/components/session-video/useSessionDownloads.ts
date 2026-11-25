import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../services/api'
import { SessionDownloadBusy, startSessionDownload, type SessionVideoInfo, type SharedTrainingSession } from '../../services/sessionVideosApi'

type Download = { kind: 'file'; id: number } | { kind: 'batch'; requested: number }

function waitForNextDownload(signal: AbortSignal, delay = 1000) {
  if (signal.aborted) return Promise.resolve()
  return new Promise<void>(resolve => {
    const finish = () => {
      clearTimeout(timer)
      signal.removeEventListener('abort', finish)
      resolve()
    }
    const timer = setTimeout(finish, delay)
    signal.addEventListener('abort', finish, { once: true })
  })
}

export function useSessionDownloads(pageUrl: string, videos: SessionVideoInfo[], next: number | null | undefined, total: number) {
  const active = useRef<AbortController | null>(null)
  // A batch is resumable until every request has been handed to the browser.
  // A later, deliberate "Download all" starts a fresh batch.
  const sent = useRef<Set<number> | null>(null)
  const [requestedCount, setRequestedCount] = useState(0)
  const [download, setDownload] = useState<Download | null>(null)
  const [failed, setFailed] = useState<Set<number>>(() => new Set())

  useEffect(() => () => active.current?.abort(), [])
  const stop = useCallback(() => {
    active.current?.abort()
    active.current = null
    setDownload(null)
  }, [])
  const reset = useCallback(() => {
    stop()
    sent.current = null
    setRequestedCount(0)
    setFailed(new Set())
  }, [stop])

  async function start(item: SessionVideoInfo | undefined, onError: (failure?: number | 'busy') => void) {
    if (active.current) return
    const controller = new AbortController()
    const { signal } = controller
    active.current = controller
    const batch = item ? sent.current : (sent.current ??= new Set())
    setDownload(item ? { kind: 'file', id: item.id } : { kind: 'batch', requested: batch?.size ?? 0 })

    async function attempt(id: number) {
      try {
        await startSessionDownload(id, signal)
      } catch (error) {
        if (item || !(error instanceof SessionDownloadBusy)) throw error
        await waitForNextDownload(signal, error.retryAfterMs)
        await startSessionDownload(id, signal)
      }
    }

    async function request(id: number) {
      let failure: 'busy' | 'failed' | undefined
      try {
        await attempt(id)
      } catch (error) {
        failure = error instanceof SessionDownloadBusy ? 'busy' : 'failed'
      }
      if (signal.aborted) return failure
      if (!failure && batch) {
        batch.add(id)
        setRequestedCount(batch.size)
      }
      setFailed(current => {
        const updated = new Set(current)
        if (failure) updated.add(id)
        else updated.delete(id)
        return updated
      })
      return failure
    }

    try {
      if (item) {
        const failure = await request(item.id)
        if (signal.aborted) return
        if (failure) onError(failure === 'busy' ? 'busy' : undefined)
        else if (batch && batch.size === total) {
          sent.current = null
          setRequestedCount(0)
        }
        return
      }
      if (!batch) return
      const seen = new Set<number>()
      let failures = 0
      let page = videos
      let cursor = next
      while (!signal.aborted) {
        for (const file of page) {
          if (signal.aborted) return
          if (batch.has(file.id) || seen.has(file.id)) continue
          if (seen.size) await waitForNextDownload(signal)
          if (signal.aborted) return
          if (await request(file.id)) failures++
          if (signal.aborted) return
          seen.add(file.id)
          setDownload({ kind: 'batch', requested: batch.size })
        }
        if (cursor == null || signal.aborted) break
        const { data } = await api.get<SharedTrainingSession>(pageUrl, { params: { after: cursor }, signal })
        if (data.next_video_id != null && data.next_video_id <= cursor) throw new Error('Nonadvancing recording page')
        page = data.videos
        cursor = data.next_video_id
      }
      if (signal.aborted) return
      if (failures) onError(failures)
      else {
        sent.current = null
        setRequestedCount(0)
      }
    } catch {
      if (!signal.aborted) onError()
    } finally {
      if (active.current === controller) {
        active.current = null
        if (!signal.aborted) setDownload(null)
      }
    }
  }

  return { download, failed, requestedCount, reset, start, stop }
}
