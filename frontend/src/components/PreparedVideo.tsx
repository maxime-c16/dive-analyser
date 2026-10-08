import { useLayoutEffect, useRef, type RefObject } from 'react'
import { acquirePlaybackVideo, releasePlaybackVideo, onPreparedPlaybackReset, preparedOriginal, retainPreparedOriginal } from '../utils/preparedPlayback'
import { canPrefetch } from '../hooks/useNavigationIntent'

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
}

export function fullyBuffered(video: HTMLVideoElement): boolean {
  if (!Number.isFinite(video.duration) || video.duration <= 0) return false
  let end = 0
  for (let i = 0; i < video.buffered.length; i++) {
    if (video.buffered.start(i) > end + 0.05) return false
    end = Math.max(end, video.buffered.end(i))
  }
  return end >= video.duration - 0.05
}

// React owns the host; the pool owns the startup video. Keeping the native
// element retains the buffered frames even through a no-store B2 redirect.
// HQ is prepared only for the selected dive, AFTER startup. The preview
// stays visible until a fully buffered original presents the matching frame.
export default function PreparedVideo(props: Props) {
  const hostRef = useRef<HTMLDivElement>(null)
  const primaryRef = useRef<HTMLVideoElement | null>(null)
  const latest = useRef(props)
  latest.current = props
  const setVideo = (video: HTMLVideoElement | null) => {
    ;(props.videoRef as { current: HTMLVideoElement | null }).current = video
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
  useLayoutEffect(() => {
    const video = acquirePlaybackVideo(props.videoUuid)
    primaryRef.current = video
    ;(props.soundRef as { current: HTMLVideoElement | null }).current = video
    setVideo(video)
    const unlisten = listen(video)
    video.autoplay = true
    video.loop = true
    video.muted = false
    hostRef.current!.appendChild(video)
    return () => {
      unlisten()
      video.remove()
      setVideo(null)
      primaryRef.current = null
      ;(props.soundRef as { current: HTMLVideoElement | null }).current = null
      video.removeAttribute('aria-hidden')
      video.removeAttribute('style')
      releasePlaybackVideo(props.videoUuid, video)
    }
  }, [props.videoUuid, props.videoRef])
  useLayoutEffect(() => {
    const video = primaryRef.current
    if (!video) return
    video.className = props.className
    video.setAttribute('aria-label', props.label)
    if (props.poster) video.poster = props.poster
    else video.removeAttribute('poster')
    if (video.getAttribute('src') !== (props.src ?? null)) {
      if (props.src) video.src = props.src
      else { video.removeAttribute('src'); video.load() }
    }
    // These events may already have fired before adopting the warm video.
    if (props.src && video.readyState >= 1) props.onLoadedMetadata()
    if (props.src && video.readyState >= 3) props.onCanPlay()
  }, [props.src, props.poster, props.className, props.label, props.videoUuid])

  useLayoutEffect(() => {
    const preview = primaryRef.current
    if (!preview || !props.originalSrc || props.originalSrc === props.src || !canPrefetch()) return
    const retained = preparedOriginal(props.videoUuid, props.originalSrc)
    const original = retained || document.createElement('video')
    original.className = props.className
    original.preload = 'auto'
    original.playsInline = true
    original.muted = true
    original.loop = true
    original.setAttribute('aria-hidden', 'true')
    Object.assign(original.style, { position: 'absolute', inset: '0', opacity: '0', pointerEvents: 'none' })
    let cancelled = false
    let started = false
    let switching = false
    let upgraded = false
    let frameHandle: number | null = null
    let raf = 0
    let unlisten = () => {}
    const start = () => {
      if (started || cancelled || preview.paused) return
      started = true
      // This native load works across B2 redirects without a CORS-readable
      // fetch, and starts only once the small preview is already playing.
      original.src = props.originalSrc!
      hostRef.current?.appendChild(original)
      // Native preload may stop after a few seconds of a large original.
      // Muted background playback drives the remaining buffer; the visible
      // preview remains the only audio source until the handoff.
      void original.play().catch(() => {})
    }
    const upgrade = async () => {
      if (cancelled || upgraded || switching || preview.paused || preview.seeking || !fullyBuffered(original)) return
      switching = true
      const rate = preview.playbackRate
      original.playbackRate = rate
      original.currentTime = Math.min(preview.currentTime, Math.max(0, original.duration - 0.05))
      const show = async () => {
        if (cancelled || preview.paused || preview.seeking || original.readyState < 2) { switching = false; return }
        // A seek/decode must not introduce a repeated or skipped frame.
        if (Math.abs(original.currentTime - preview.currentTime) > 0.12) {
          switching = false
          // Fully buffered HQ may emit no more progress/canplaythrough
          // events. Retry alignment explicitly after a delayed decode.
          raf = requestAnimationFrame(() => { raf = 0; void upgrade() })
          return
        }
        // Keep the AAC preview as the soundtrack. Some camera originals
        // have audio codecs a browser cannot decode even when video works.
        // HQ stays muted, so the handoff never drops or duplicates sound.
        try { await original.play() } catch { original.muted = true; switching = false; return }
        if (cancelled || preview.paused) return
        upgraded = true
        retainPreparedOriginal(props.videoUuid, original)
        setVideo(original)
        unlisten = listen(original)
        original.setAttribute('aria-label', latest.current.label)
        original.removeAttribute('aria-hidden')
        original.style.opacity = '1'
        preview.setAttribute('aria-hidden', 'true')
        Object.assign(preview.style, { position: 'absolute', inset: '0', opacity: '0', pointerEvents: 'none' })
        latest.current.onVideoChange()
        latest.current.onLoadedMetadata()
      }
      try {
        await original.play() // muted, offscreen preparation
        if (cancelled) return
        if (typeof original.requestVideoFrameCallback === 'function') {
          frameHandle = original.requestVideoFrameCallback(() => { void show() })
        } else {
          raf = requestAnimationFrame(() => { void show() })
        }
      } catch { switching = false }
    }
    // Audio is the clock. Repeatedly seeking the audible preview to the
    // silent original cuts AAC output into fragments (their native clocks
    // include different output latency). Correct the SILENT video gently;
    // only an explicit seek moves the soundtrack.
    let correctionRate: number | null = null
    const drift = () => {
      let delta = original.currentTime - preview.currentTime
      const duration = preview.duration
      if (Number.isFinite(duration) && duration > 0) {
        if (delta > duration / 2) delta -= duration
        if (delta < -duration / 2) delta += duration
      }
      return delta
    }
    const syncSound = (event: Event) => {
      if (!upgraded || cancelled) return
      if (event.type === 'ratechange') {
        if (original.playbackRate === correctionRate) return
        preview.playbackRate = original.playbackRate
        correctionRate = null
      } else if (event.type === 'seeked') {
        // Native loop boundaries differ by a few milliseconds; they are
        // not user seeks and must never interrupt the sound.
        if (Math.abs(drift()) > 0.2) preview.currentTime = original.currentTime
      } else if (event.type === 'timeupdate') {
        if (original.paused || preview.paused || original.seeking || preview.seeking) return
        const delta = drift()
        const speed = preview.playbackRate
        correctionRate = speed * (Math.abs(delta) < 0.04 ? 1 : delta > 0 ? 0.97 : 1.03)
        if (original.playbackRate !== correctionRate) original.playbackRate = correctionRate
        return
      }
      if (original.paused) preview.pause()
      else if (preview.paused) void preview.play().catch(() => {})
    }
    const transportEvents = ['play', 'pause', 'seeked', 'ratechange', 'timeupdate']
    transportEvents.forEach(name => original.addEventListener(name, syncSound))
    preview.addEventListener('playing', start)
    preview.addEventListener('playing', upgrade)
    // A frame can arrive during a preview loop/seek or before seek data
    // becomes ready. Playback ticks provide another opportunity even
    // when a fully buffered original emits no further load events.
    preview.addEventListener('timeupdate', upgrade)
    original.addEventListener('progress', upgrade)
    original.addEventListener('canplaythrough', upgrade)
    original.addEventListener('seeked', upgrade)
    if (retained) {
      started = true
      upgraded = true
      setVideo(original)
      unlisten = listen(original)
      original.setAttribute('aria-label', latest.current.label)
      original.removeAttribute('aria-hidden')
      original.style.opacity = '1'
      preview.setAttribute('aria-hidden', 'true')
      Object.assign(preview.style, { position: 'absolute', inset: '0', opacity: '0', pointerEvents: 'none' })
      hostRef.current?.appendChild(original)
      latest.current.onVideoChange()
      latest.current.onLoadedMetadata()
    } else if (!preview.paused && preview.readyState >= 2) start()
    const stop = () => {
      if (cancelled) return
      cancelled = true
      preview.removeEventListener('playing', start)
      preview.removeEventListener('playing', upgrade)
      preview.removeEventListener('timeupdate', upgrade)
      original.removeEventListener('progress', upgrade)
      original.removeEventListener('canplaythrough', upgrade)
      original.removeEventListener('seeked', upgrade)
      if (frameHandle !== null) original.cancelVideoFrameCallback?.(frameHandle)
      if (raf) cancelAnimationFrame(raf)
      unlisten()
      transportEvents.forEach(name => original.removeEventListener(name, syncSound))
      original.pause()
      if (!preparedOriginal(props.videoUuid, props.originalSrc!)) {
        original.removeAttribute('src')
        original.load()
      }
      original.remove()
      if (props.videoRef.current === original && primaryRef.current === preview) {
        setVideo(preview)
        preview.removeAttribute('aria-hidden')
        preview.removeAttribute('style')
        hostRef.current?.appendChild(preview)
        latest.current.onVideoChange()
      }
    }
    const unsubscribe = onPreparedPlaybackReset(stop)
    return () => { unsubscribe(); stop() }
  }, [props.originalSrc, props.src, props.videoUuid])
  return <div ref={hostRef} className="relative h-full w-full" />
}
