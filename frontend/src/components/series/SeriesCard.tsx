import { useLayoutEffect, useRef, type CSSProperties, type ReactNode } from 'react'

export const seriesMotionEnabled = () => !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/** Animate content without remounting the code input or its clip thumbnail. */
export default function SeriesCard({ index, code, dd, videoId, className, children }: {
  index: number; code: string; dd: number | null | undefined; videoId?: string; className: string; children: ReactNode
}) {
  const card = useRef<HTMLLIElement>(null)
  const previous = useRef({ code, dd, videoId })
  useLayoutEffect(() => {
    const before = previous.current
    previous.current = { code, dd, videoId }
    const root = card.current
    if (!root || root.dataset.seriesReordering || !seriesMotionEnabled() || !root.animate) return
    const animations: Animation[] = []
    const reveal = (selector: string, frames: Keyframe[], duration: number) => {
      const element = root.querySelector<HTMLElement>(selector)
      if (element) animations.push(element.animate(frames, { duration, easing: 'cubic-bezier(.2,.8,.2,1)' }))
    }
    if (before.dd !== dd && dd != null) reveal('.series-dd', [
      { opacity: .25, transform: 'translateY(5px)' }, { opacity: 1, transform: 'translateY(0)' },
    ], 220)
    if (before.videoId !== videoId && videoId) reveal('.series-card-media', [
      { opacity: .3, transform: 'perspective(650px) rotateY(-24deg) scale(.96)' },
      { opacity: 1, transform: 'perspective(650px) rotateY(0deg) scale(1)' },
    ], 360)
    return () => animations.forEach(animation => animation.cancel())
  }, [code, dd, videoId])
  return <li ref={card} data-series-card={index} className={className} style={{ '--deal-index': index } as CSSProperties}>{children}</li>
}
