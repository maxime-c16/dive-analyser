import { useLayoutEffect, useRef, type RefObject } from 'react'
import { acquirePlaybackVideo, releasePlaybackVideo, onPreparedPlaybackReset } from '../utils/preparedPlayback'

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

// Reuse one native element and stream the chosen full-quality source. The
// player's poster covers startup until its first frame; no whole-file gate,
// hidden original decoder or separate audio clock is needed.
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

  useLayoutEffect(() => onPreparedPlaybackReset(() => {
    const video = primaryRef.current;
    if (video) { video.pause(); video.removeAttribute('src'); video.load(); }
  }), [props.videoUuid]);
  return <div ref={hostRef} className="relative h-full w-full" />
}
