import { useLayoutEffect, useRef, type RefObject } from 'react'
import { seriesMotionEnabled } from './SeriesCard'

/** FLIP only the two moved positions; inputs retain their DOM identity/focus. */
export function useSeriesReorderMotion(board: RefObject<HTMLOListElement>) {
  const pending = useRef<{ from: number; to: number; fromRect: DOMRect; toRect: DOMRect } | null>(null)
  const animations = useRef<Animation[]>([])
  const cancel = () => { animations.current.forEach(animation => animation.cancel()); animations.current = [] }
  useLayoutEffect(() => {
    const move = pending.current
    pending.current = null
    if (!move) return
    const nodes = board.current?.children
    if (!nodes) return
    for (const index of [move.from, move.to]) {
      const node = nodes[index] as HTMLElement | undefined
      if (node) delete node.dataset.seriesReordering
    }
    if (!seriesMotionEnabled()) return
    for (const [index, oldRect] of [[move.to, move.fromRect], [move.from, move.toRect]] as const) {
      const node = nodes[index] as HTMLElement | undefined
      if (!node?.animate) continue
      const rect = node.getBoundingClientRect()
      animations.current.push(node.animate([
        { transform: `translate(${oldRect.left - rect.left}px, ${oldRect.top - rect.top}px) scale(.98)` },
        { transform: 'translate(0, 0) scale(1)' },
      ], { duration: 320, easing: 'cubic-bezier(.2,.8,.2,1)' }))
    }
  })
  useLayoutEffect(() => cancel, [])
  return (from: number, to: number) => {
    cancel()
    const nodes = board.current?.children
    if (!nodes || !seriesMotionEnabled()) return
    ;(nodes[from] as HTMLElement).dataset.seriesReordering = 'true'
    ;(nodes[to] as HTMLElement).dataset.seriesReordering = 'true'
    pending.current = { from, to, fromRect: nodes[from].getBoundingClientRect(), toRect: nodes[to].getBoundingClientRect() }
  }
}
