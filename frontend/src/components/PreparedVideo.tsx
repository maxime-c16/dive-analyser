import { useLayoutEffect, useRef, type MutableRefObject, type RefObject } from 'react'
import { acquirePlaybackVideo, adoptPlaybackVideo, holdWarmup, releasePlaybackVideo, onPreparedPlaybackReset } from '../utils/preparedPlayback'

/** Replace the hosted element with a prepared one; false if not possible. */
export type SwapVideo = (next: HTMLVideoElement) => boolean

interface Props {
  videoUuid: string
  videoRef: RefObject<HTMLVideoElement>
  soundRef: RefObject<HTMLVideoElement>
  src?: string
  originalSrc?: string
  poster?: string
  className: string
  label: string
  onVideoChange: () => void
  onLoadedMetadata: () => void
  onCanPlay: () => void
  onPlay: () => void
  onPause: () => void
  onError: () => void
  /** Filled with a swap function while mounted (background quality swap). */
  swapRef?: MutableRefObject<SwapVideo | null>
  /** The clip presented, failed or gave up: neighbors may warm now. */
  warmupDone?: boolean
}

// Reuse one native element and stream the chosen full-quality source. The
// player's poster covers startup until its first frame; no whole-file gate,
// hidden original decoder or separate audio clock is needed. A background
// swap may replace that element with an already-buffered one; every listener,
// ref and the pool slot follow the element currently hosted.
export default function PreparedVideo(props: Props) {
  const hostRef = useRef<HTMLDivElement>(null)
  const primaryRef = useRef<HTMLVideoElement | null>(null)
  const unlistenRef = useRef<(() => void) | null>(null)
  const releaseHoldRef = useRef<(() => void) | null>(null)
  const latest = useRef(props)
  latest.current = props
  const setVideo = (video: HTMLVideoElement | null) => {
    ;(props.videoRef as { current: HTMLVideoElement | null }).current = video
    ;(props.soundRef as { current: HTMLVideoElement | null }).current = video
  }
  const listen = (video: HTMLVideoElement) => {
    const events = {
      loadedmetadata: () => latest.current.onLoadedMetadata(),
      canplay: () => latest.current.onCanPlay(),
      play: () => latest.current.onPlay(),
      pause: () => latest.current.onPause(),
      error: () => latest.current.onError(),
    }
    const handlers = Object.entries(events).map(([name, callback]) => {
      const handler = () => { if (props.videoRef.current === video) callback() }
      video.addEventListener(name, handler)
      return [name, handler] as const
    })
    return () => handlers.forEach(([name, handler]) => video.removeEventListener(name, handler))
  }
  const decorate = (video: HTMLVideoElement) => {
    const current = latest.current
    video.className = current.className
    video.setAttribute('aria-label', current.label)
    if (current.poster) video.poster = current.poster
    else video.removeAttribute('poster')
  }
  useLayoutEffect(() => {
    // Layout effects run before any passive effect: the visible clip claims
    // the network before thumbnails or neighbors start warming.
    const releaseHold = holdWarmup()
    releaseHoldRef.current = releaseHold
    const video = acquirePlaybackVideo(props.videoUuid)
    primaryRef.current = video
    setVideo(video)
    unlistenRef.current = listen(video)
    video.autoplay = true
    video.loop = true
    video.muted = false
    hostRef.current!.appendChild(video)
    return () => {
      // The hosted element may have been swapped since acquisition.
      const hosted = primaryRef.current ?? video
      unlistenRef.current?.()
      unlistenRef.current = null
      hosted.remove()
      setVideo(null)
      primaryRef.current = null
      hosted.removeAttribute('aria-hidden')
      hosted.removeAttribute('style')
      releasePlaybackVideo(props.videoUuid, hosted)
      releaseHold()
    }
  }, [props.videoUuid, props.videoRef])
  useLayoutEffect(() => {
    if (props.warmupDone) releaseHoldRef.current?.()
  }, [props.warmupDone, props.videoUuid])
  useLayoutEffect(() => {
    const video = primaryRef.current
    if (!video) return
    decorate(video)
    if (video.getAttribute('src') !== (props.src ?? null)) {
      if (props.src) video.src = props.src
      else { video.removeAttribute('src'); video.load() }
    }
    // These events may already have fired before adopting the warm video.
    if (props.src && video.readyState >= 1) props.onLoadedMetadata()
    if (props.src && video.readyState >= 3) props.onCanPlay()
  }, [props.src, props.poster, props.className, props.label, props.videoUuid])

  useLayoutEffect(() => {
    if (!props.swapRef) return
    const swapRef = props.swapRef
    swapRef.current = (next) => {
      const current = primaryRef.current
      const host = hostRef.current
      if (!current || !host || current === next || current.parentNode !== host) return false
      unlistenRef.current?.()
      decorate(next)
      next.loop = current.loop
      next.autoplay = false
      next.playsInline = true
      next.preload = 'auto'
      host.replaceChild(next, current)
      primaryRef.current = next
      setVideo(next)
      unlistenRef.current = listen(next)
      adoptPlaybackVideo(latest.current.videoUuid, current, next)
      latest.current.onVideoChange()
      return true
    }
    return () => { swapRef.current = null }
  }, [props.swapRef, props.videoUuid])

  useLayoutEffect(() => onPreparedPlaybackReset(() => {
    const video = primaryRef.current;
    if (video) { video.pause(); video.removeAttribute('src'); video.load(); }
  }), [props.videoUuid]);
  return <div ref={hostRef} className="relative h-full w-full" />
}
