import { useEffect, useRef, useState } from 'react'

/** Silent, viewport-gated first frame when a cached poster is unavailable. */
export default function MediaThumbnail({ posterUrl, playbackUrl, label = '' }: {
  posterUrl?: string | null
  playbackUrl?: string | null
  label?: string
}) {
  const container = useRef<HTMLDivElement>(null)
  const [nearby, setNearby] = useState(false)
  const [failedPoster, setFailedPoster] = useState<string | null>(null)
  useEffect(() => {
    if (!container.current) return
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) {
        setNearby(true)
        observer.disconnect()
      }
    }, { rootMargin: '200px' })
    observer.observe(container.current)
    return () => observer.disconnect()
  }, [])
  // Safari may stop at metadata without painting a frame at time zero.
  // A tiny media fragment requests a frame without autoplay or downloading
  // every original in a long profile grid. Keep the authenticated app URL.
  const videoUrl = playbackUrl ? `${playbackUrl.split('#')[0]}#t=0.001` : null
  return <div ref={container} className="h-full w-full">
    {posterUrl && failedPoster !== posterUrl
      ? <img src={posterUrl} alt={label} loading="lazy" onError={() => setFailedPoster(posterUrl)} className="h-full w-full object-cover" />
      : nearby && videoUrl
        ? <video key={videoUrl} src={videoUrl} aria-label={label || undefined} aria-hidden={!label || undefined} muted playsInline preload="metadata" className="h-full w-full object-cover" />
        : null}
  </div>
}
