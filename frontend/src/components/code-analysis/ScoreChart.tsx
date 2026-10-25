import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { extremes, rolling, type Extreme, fmtScore } from '../../utils/codeStats'

export type ChartPoint = { key: number; month: string; monthLabel: string; value: number; band: string; lo?: number; hi?: number }

/**
 * Score timeline: every point is a tap target (tap or scrub horizontally),
 * the rolling median and usual range are drawn behind, and the clearest
 * peaks/valleys of the median are labelled and tappable.
 */
export default function ScoreChart({ points, smoothing, selected, onSelect, label }: {
  points: ChartPoint[]
  smoothing: number
  selected: number | null
  onSelect: (index: number, extreme?: Extreme) => void
  label: string
}) {
  const { t } = useTranslation()
  const host = useRef<HTMLDivElement>(null)
  const line = useRef<SVGPathElement>(null)
  const [width, setWidth] = useState(0)
  useLayoutEffect(() => {
    const element = host.current
    if (!element) return
    const measure = () => setWidth(element.clientWidth)
    measure()
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure)
    observer?.observe(element)
    return () => observer?.disconnect()
  }, [])

  const W = Math.max(280, width), H = W < 500 ? 200 : 240, L = 24, R = 10, T = 20, B = 22
  const n = points.length
  const x = (index: number) => n === 1 ? (L + W - R) / 2 : L + index * (W - L - R) / (n - 1)
  const y = (value: number) => T + (10 - value) * (H - T - B) / 10
  const values = useMemo(() => points.map(point => point.value), [points])
  const smooth = useMemo(() => rolling(values, smoothing), [values, smoothing])
  const low = useMemo(() => rolling(values, smoothing + 2, 0.25), [values, smoothing])
  const high = useMemo(() => rolling(values, smoothing + 2, 0.75), [values, smoothing])
  const marks = useMemo(() => extremes(smooth), [smooth])
  const radius = n > 200 ? 2.4 : n > 80 ? 3 : 4

  // Draw the median once per data set (not on every selection).
  const [drawn, setDrawn] = useState<string>('')
  const dataKey = `${n}:${points[0]?.key}:${points[n - 1]?.key}:${smoothing}`
  useEffect(() => {
    const path = line.current
    if (!path || drawn === dataKey || !width) return
    const reduce = prefersReducedMotion()
    if (!reduce) {
      path.style.setProperty('--len', String(path.getTotalLength()))
      path.classList.remove('ca-medline-draw')
      void path.getBoundingClientRect()
      path.classList.add('ca-medline-draw')
    }
    setDrawn(dataKey)
  }, [dataKey, width, drawn])

  const monthTicks = useMemo(() => {
    const ticks: Array<{ index: number; text: string }> = []
    let last = '', lastX = -99
    points.forEach((point, index) => {
      if (point.month === last) return
      last = point.month
      if (x(index) - lastX > 46) { ticks.push({ index, text: point.monthLabel }); lastX = x(index) }
    })
    return ticks
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [points, W])

  const indexAt = (clientX: number) => {
    const rect = host.current!.getBoundingClientRect()
    const px = (clientX - rect.left) * W / rect.width
    return Math.max(0, Math.min(n - 1, Math.round((px - L) / ((W - L - R) / Math.max(1, n - 1)))))
  }
  const drag = useRef<{ x: number; y: number; horizontal: boolean | null } | null>(null)
  const onPointerDown = (event: React.PointerEvent) => {
    if ((event.target as Element).closest('.ca-mark')) return
    drag.current = { x: event.clientX, y: event.clientY, horizontal: event.pointerType === 'mouse' ? true : null }
    onSelect(indexAt(event.clientX))
  }
  const onPointerMove = (event: React.PointerEvent) => {
    const state = drag.current
    if (!state) return
    if (state.horizontal === null) {
      const dx = Math.abs(event.clientX - state.x), dy = Math.abs(event.clientY - state.y)
      if (dx + dy > 6) state.horizontal = dx > dy
    }
    if (state.horizontal) onSelect(indexAt(event.clientX))
  }
  const endDrag = () => { drag.current = null }
  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    event.preventDefault()
    onSelect(Math.max(0, Math.min(n - 1, (selected ?? n - 1) + (event.key === 'ArrowLeft' ? -1 : 1))))
  }

  const bandPath = n > 1 ? `M${high.map((value, index) => `${x(index)},${y(value)}`).join('L')}L${low.map((value, index) => `${x(index)},${y(value)}`).reverse().join('L')}Z` : ''
  const medianPath = n > 1 ? `M${smooth.map((value, index) => `${x(index).toFixed(1)},${y(value).toFixed(1)}`).join('L')}` : ''
  const current = selected != null ? points[selected] : null

  return <div ref={host} className="ca-chart" tabIndex={0} role="group" aria-label={`${label}. ${t('codeAnalysis.chartKeys')}`}
    onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={endDrag} onPointerCancel={endDrag} onPointerLeave={endDrag} onKeyDown={onKeyDown}>
    {width > 0 && <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden="true">
      {[0, 2.5, 5, 7.5, 10].map(value => <g key={value}>
        <line className="ca-grid" x1={L} x2={W - R} y1={y(value)} y2={y(value)} />
        <text className="ca-axis" x={L - 6} y={y(value) + 3} textAnchor="end">{value}</text>
      </g>)}
      {monthTicks.map(tick => <text key={tick.index} className="ca-axis" x={x(tick.index)} y={H - 6}>{tick.text}</text>)}
      {bandPath && <path className="ca-band" d={bandPath} />}
      {points.map((point, index) => point.lo != null && point.hi != null &&
        <line key={`r${point.key}`} x1={x(index)} x2={x(index)} y1={y(point.lo)} y2={y(point.hi)} stroke={`var(--ca-${point.band})`} strokeOpacity=".45" strokeLinecap="round"
          strokeWidth={Math.max(2, Math.min(8, (W - L - R) / n * 0.5))} />)}
      {points.map((point, index) => <circle key={point.key} cx={x(index)} cy={y(point.value)} r={radius} fill={`var(--ca-${point.band})`} fillOpacity=".9" />)}
      {medianPath && <path ref={line} className="ca-medline" d={medianPath} />}
      {marks.map(mark => {
        const up = mark.kind === 'peak', colour = up ? 'var(--ca-P)' : 'var(--ca-B)'
        const text = `${up ? '▲' : '▼'} ${fmtScore(mark.value)}`
        return <g key={`${mark.kind}${mark.index}`} className="ca-mark" role="button" tabIndex={0} aria-label={`${up ? t('codeAnalysis.peak') : t('codeAnalysis.valley')} ${fmtScore(mark.value)}`}
          onPointerDown={event => { event.stopPropagation(); onSelect(mark.index, mark) }}
          onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); event.stopPropagation(); onSelect(mark.index, mark) } }}>
          <circle cx={x(mark.index)} cy={y(mark.value)} r="14" fill="transparent" />
          <circle cx={x(mark.index)} cy={y(mark.value)} r="5" fill="var(--app-bg)" stroke={colour} strokeWidth="2.5" />
          <text x={x(mark.index)} y={up ? y(mark.value) - 11 : y(mark.value) + 19} textAnchor="middle" fill={colour}>{text}</text>
        </g>
      })}
      {current && selected != null && <g pointerEvents="none">
        <line x1={x(selected)} x2={x(selected)} y1={T - 6} y2={H - B} stroke="#fff" strokeOpacity=".35" strokeDasharray="3 3" />
        <circle cx={x(selected)} cy={y(current.value)} r={radius + 4} fill="none" stroke="#fff" strokeWidth="2" />
      </g>}
    </svg>}
  </div>
}

function prefersReducedMotion() {
  return typeof window !== 'undefined' && Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)
}
