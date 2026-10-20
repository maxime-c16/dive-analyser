import { useEffect, useState } from 'react'

// Each preview is bounded to 16 MiB and only two players are mounted. Originals always
// stream, and unexpectedly large previews fall back to regular streaming.
const MAX_PREVIEW_BYTES = 16 * 1024 * 1024

/** Fetch small evaluation previews before decoding. Unlike hidden-video
 * preload, fetch is not discretionary; blob playback also keeps media bytes
 * on the same authenticated transport as the rest of the page. No shared
 * cache, signed URLs, or references survive the player's lifetime. */
export default function useEvaluationVideoSource(url: string | undefined, rendition?: string) {
  const bufferPreview = !!url && rendition?.startsWith('proxy_') && typeof URL.createObjectURL === 'function'
  const [result, setResult] = useState<{ url?: string; src?: string; error?: Error }>({})
  useEffect(() => {
    if (!url || !bufferPreview) { setResult({}); return }
    const controller = new AbortController()
    let objectUrl: string | undefined
    const load = async () => {
      try {
        const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store', signal: controller.signal })
        if (!response.ok) throw new Error(`Evaluation preview HTTP ${response.status}`)
        if (Number(response.headers.get('content-length')) > MAX_PREVIEW_BYTES || !response.body) {
          await response.body?.cancel()
          if (!controller.signal.aborted) setResult({ url, src: url })
          return
        }
        const reader = response.body.getReader()
        const chunks: ArrayBuffer[] = []
        let size = 0
        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          size += value.byteLength
          if (size > MAX_PREVIEW_BYTES) {
            await reader.cancel()
            if (!controller.signal.aborted) setResult({ url, src: url })
            return
          }
          chunks.push(new Uint8Array(value).buffer)
        }
        if (controller.signal.aborted) return
        if (!size) throw new Error('Empty evaluation preview')
        objectUrl = URL.createObjectURL(new Blob(chunks, { type: response.headers.get('content-type') || 'video/mp4' }))
        setResult({ url, src: objectUrl })
      } catch (error) {
        if (!controller.signal.aborted) setResult({ url, error: error instanceof Error ? error : new Error('Preview fetch failed') })
      }
    }
    void load()
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [url, bufferPreview])
  if (!bufferPreview) return { src: url, error: undefined }
  return result.url === url ? result : { src: undefined, error: undefined }
}
