import React, { useEffect, useLayoutEffect, useMemo, useRef, useState, useId } from 'react'
import { useTranslation } from 'react-i18next'
import { extremes, rolling, type Extreme, fmtScore } from '../../utils/codeStats'

export type ChartPoint = { key: number | string; highlight?: boolean; segment?: number; curveMedian?: number | null; curveQ1?: number | null; curveQ3?: number | null; occurredAt?: number; month: string; monthLabel: string; value: number; band: string; lo?: number; hi?: number }

/**
 * Score timeline: every point is a tap target (tap or scrub horizontally),
 * the rolling median and usual range are drawn behind, and the clearest
 * peaks/valleys of the median are labelled and tappable.
 */
export default function ScoreChart({ points, smoothing, selected, onSelect, label, boundary, markers }: {
  markers?: { at: number; until?: number }[]
  boundary?: { start: number; end?: number; uncertainUntil?: number }
  points: ChartPoint[]
  smoothing: number
  selected: number | null
  onSelect: (index: number, extreme?: Extreme) => void
  label: string
}) {
  const { t, i18n } = useTranslation()
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
  const hatchId = useId().replace(/:/g, '')
  const timeStart = boundary?.start ?? 0
  const timeEnd = Math.max(timeStart + 1, boundary?.end ?? 0, ...points.map(p => p.occurredAt ?? timeStart))
  const timeX = (time: number) => L + Math.max(0, Math.min(1, (time - timeStart) / (timeEnd - timeStart))) * (W - L - R)
  const x = (index: number) => boundary ? timeX(points[index]?.occurredAt ?? timeStart) : n === 1 ? (L + W - R) / 2 : L + index * (W - L - R) / (n - 1)
  const y = (value: number) => T + (10 - value) * (H - T - B) / 10
  const values = useMemo(() => points.map(point => point.value), [points])
  const smooth = useMemo(() => points.every(p => p.curveMedian !== undefined) ? points.map(p => p.curveMedian!) : rolling(values, smoothing), [points, values, smoothing])
  const low = useMemo(() => points.every(p => p.curveQ1 !== undefined) ? points.map(p => p.curveQ1!) : rolling(values, smoothing + 2, 0.25), [points, values, smoothing])
  const high = useMemo(() => points.every(p => p.curveQ3 !== undefined) ? points.map(p => p.curveQ3!) : rolling(values, smoothing + 2, 0.75), [points, values, smoothing])
  const groups = useMemo(() => {
    const result: number[][] = []
    points.forEach((point, index) => { if (!index || point.segment !== points[index - 1].segment) result.push([]); result[result.length - 1].push(index) })
    return result
  }, [points])
  const marks = useMemo(() => groups.flatMap(group => group.every(i => smooth[i] != null) ? extremes(group.map(i => smooth[i]!)).map(mark => ({ ...mark, index: group[mark.index] })) : []), [groups, smooth])
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
    if (boundary) return points.reduce((best, _, index) => Math.abs(x(index) - px) < Math.abs(x(best) - px) ? index : best, 0)
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

  const bandPath = groups.filter(group => group.length > 1 && group.every(i => high[i] != null && low[i] != null)).map(group => `M${group.map(i => `${x(i)},${y(high[i]!)}`).join('L')}L${[...group].reverse().map(i => `${x(i)},${y(low[i]!)}`).join('L')}Z`).join(' ')
  const medianPath = groups.filter(group => group.length > 1 && group.every(i => smooth[i] != null)).map(group => `M${group.map(i => `${x(i).toFixed(1)},${y(smooth[i]!).toFixed(1)}`).join('L')}`).join(' ')
  const current = selected != null ? points[selected] : null

  return <div ref={host} className="ca-chart" tabIndex={0} role="group" aria-label={`${label}. ${t('codeAnalysis.chartKeys')}`}
    onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={endDrag} onPointerCancel={endDrag} onPointerLeave={endDrag} onKeyDown={onKeyDown}>
    {width > 0 && <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden="true">
      {groups.filter(group => group.some(i => points[i].highlight)).map(group => <rect key={`selected-${group[0]}`} x={x(group[0]) - 4} y={T} width={Math.max(8, x(group[group.length - 1]) - x(group[0]) + 8)} height={H - B - T} fill="currentColor" fillOpacity=".08" pointerEvents="none" />)}
      {boundary && <g pointerEvents="none"><defs><pattern id={hatchId} width="6" height="6" patternUnits="userSpaceOnUse"><path d="M0 6L6 0" stroke="currentColor" strokeOpacity=".3" /></pattern></defs>
        {boundary.uncertainUntil && <rect x={L} y={T} width={Math.max(0, timeX(boundary.uncertainUntil) - L)} height={H - B - T} fill={`url(#${hatchId})`} />}
        {markers?.filter(marker => marker.at <= timeEnd && (marker.at >= timeStart || (marker.until ?? marker.at) >= timeStart)).map((marker, i) => <g key={i}><line x1={timeX(marker.at)} x2={timeX(marker.at)} y1={T} y2={H - B} stroke="currentColor" strokeOpacity=".4" strokeDasharray="2 3" />{marker.until && <rect x={timeX(marker.at)} y={T} width={Math.max(0, timeX(marker.until) - timeX(marker.at))} height={H - B - T} fill={`url(#${hatchId})`} />}</g>)}
        <line x1={L} x2={L} y1={T} y2={H - B} stroke="currentColor" strokeDasharray="2 3"><title>{new Date(boundary.start).toISOString()}</title></line>
        {boundary.end && <line x1={timeX(boundary.end)} x2={timeX(boundary.end)} y1={T} y2={H - B} stroke="currentColor" strokeDasharray="2 3" />}
      </g>}
      {[0, 2.5, 5, 7.5, 10].map(value => <g key={value}>
        <line className="ca-grid" x1={L} x2={W - R} y1={y(value)} y2={y(value)} />
        <text className="ca-axis" x={L - 6} y={y(value) + 3} textAnchor="end">{value.toLocaleString(i18n.language)}</text>
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
