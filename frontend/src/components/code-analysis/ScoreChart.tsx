import React, { useEffect, useLayoutEffect, useMemo, useRef, useState, useId } from 'react'
import { useTranslation } from 'react-i18next'
import { extremes, rolling, type Extreme, fmtScore } from '../../utils/codeStats'

export type ChartPoint = { key: number | string; highlight?: boolean; segment?: number; curveMedian?: number | null; curveQ1?: number | null; curveQ3?: number | null; occurredAt?: number; month: string; monthLabel: string; value: number; band: string; lo?: number; hi?: number }

/**
 * Score timeline: every point is a tap target (tap or scrub horizontally),
 * the rolling median and usual range are drawn behind, and the clearest
 * peaks/valleys of the median are labelled and tappable.
 */
export default function ScoreChart({ points, smoothing, selected, onSelect, label, boundary, markers, timeDomain, renderTimeline, timeScale = false, selectionMode = 'scrub', showCursor = true, outsideOpacity = .25, simple = false }: {
  /** Points and rolling median only: no usual-range band, no peak/valley labels. */
  simple?: boolean
  showCursor?: boolean
  timeScale?: boolean
  timeDomain?: { start: number; end: number }
  renderTimeline?: (dateX: (date: number) => number, width: number) => React.ReactNode
  outsideOpacity?: number
  selectionMode?: 'tap' | 'scrub'
  markers?: { at: number; until?: number }[]
  boundary?: { start: number; end?: number; uncertainUntil?: number }
  points: ChartPoint[]
  smoothing: number
  selected: number | null
  onSelect?: (index: number, extreme?: Extreme) => void
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

  const W = Math.max(280, width), H = W < 500 ? 200 : 240, L = 24, R = renderTimeline ? 24 : 10, T = 20, B = 22
  const n = points.length
  const hatchId = useId().replace(/:/g, '')
  const timed = timeScale || Boolean(boundary)
  const times = points.map(p => p.occurredAt).filter((value): value is number => value != null && Number.isFinite(value))
  const firstTime = timeDomain?.start ?? (times.length ? Math.min(...times) : 0)
  const lastTime = timeDomain?.end ?? (times.length ? Math.max(...times) : 0)
  const singleTime = firstTime === lastTime
  const timeStart = firstTime - (singleTime ? DAY / 2 : 0)
  const timeEnd = lastTime + (singleTime ? DAY / 2 : 0)
  const timeX = (time: number) => L + Math.max(0, Math.min(1, (time - timeStart) / (timeEnd - timeStart))) * (W - L - R)
  const onAxis = (time: number) => time >= timeStart && time <= timeEnd
  const showBand = boundary && boundary.start <= timeEnd && (boundary.end ?? timeEnd) >= timeStart
  const x = (index: number) => timed ? timeX(points[index]?.occurredAt ?? timeStart) : n === 1 ? (L + W - R) / 2 : L + index * (W - L - R) / (n - 1)
  const y = (value: number) => T + (10 - value) * (H - T - B) / 10
  const values = useMemo(() => points.map(point => point.value), [points])
  // The rolling window restarts after a 60-day break (on every screen, calendar axis or not), so the line never averages across an unmeasured stretch.
  const smooth = useMemo(() => {
    if (points.every(p => p.curveMedian !== undefined)) return points.map(p => p.curveMedian!)
    if (!points.every(p => p.occurredAt != null)) return rolling(values, smoothing)
    const out: Array<number | null> = []
    let start = 0
    points.forEach((point, index) => {
      const last = index === points.length - 1 || (points[index + 1].occurredAt ?? 0) - (point.occurredAt ?? 0) > 60 * DAY
      if (last) { out.push(...rolling(values.slice(start, index + 1), smoothing)); start = index + 1 }
    })
    return out
  }, [points, values, smoothing, timed])
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
    if (!timed) points.forEach((point, index) => {
      if (point.month === last) return
      last = point.month
      if (x(index) - lastX > 46) { ticks.push({ index, text: point.monthLabel }); lastX = x(index) }
    })
    return ticks
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [points, W, timed])
  const dateTicks = timed ? calendarTicks(timeStart, timeEnd, W - L - R, i18n.language) : []

  const indexAt = (clientX: number, clientY?: number) => {
    const rect = host.current!.getBoundingClientRect()
    const px = (clientX - rect.left) * W / rect.width
    const py = clientY == null ? null : (clientY - rect.top) * H / rect.height
    // Scrubbing follows x; dives sharing a date are told apart by the pointer's height.
    const distance = (index: number) => selectionMode === 'tap' && py != null ? Math.hypot(x(index)-px,y(points[index].value)-py) : Math.abs(x(index)-px) * 1000 + (py == null ? 0 : Math.abs(y(points[index].value)-py))
    if (timed) return points.reduce((best, _, index) => distance(index) < distance(best) ? index : best, 0)
    return Math.max(0, Math.min(n - 1, Math.round((px - L) / ((W - L - R) / Math.max(1, n - 1)))))
  }
  const drag = useRef<{ x: number; y: number; horizontal: boolean | null; moved: boolean } | null>(null)
  const onPointerDown = (event: React.PointerEvent) => {
    if (!onSelect || !n || (event.target as Element).closest('.ca-mark')) return
    drag.current = { x: event.clientX, y: event.clientY, horizontal: event.pointerType === 'mouse' ? true : null, moved: false }
    if (selectionMode === 'scrub' && event.pointerType === 'mouse') onSelect(indexAt(event.clientX,event.clientY))
  }
  const onPointerMove = (event: React.PointerEvent) => {
    const state = drag.current
    if (!state) return
    if (Math.hypot(event.clientX - state.x, event.clientY - state.y) > 6) state.moved = true
    if (state.horizontal === null) {
      const dx = Math.abs(event.clientX - state.x), dy = Math.abs(event.clientY - state.y)
      if (dx + dy > 6) state.horizontal = dx > dy
    }
    if (state.horizontal && selectionMode === 'scrub') onSelect?.(indexAt(event.clientX,event.clientY))
  }
  const cancelDrag = () => { drag.current = null }
  const endDrag = (event: React.PointerEvent) => {
    const state = drag.current
    drag.current = null
    if (state && !state.moved && n && (selectionMode === 'tap' || state.horizontal === null)) onSelect?.(indexAt(event.clientX,event.clientY))
  }
  const onKeyDown = (event: React.KeyboardEvent) => {
    if (!onSelect || !n) return
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    event.preventDefault()
    onSelect(Math.max(0, Math.min(n - 1, (selected ?? n - 1) + (event.key === 'ArrowLeft' ? -1 : 1))))
  }

  const bandPath = groups.filter(group => group.length > 1 && group.every(i => high[i] != null && low[i] != null)).map(group => `M${group.map(i => `${x(i)},${y(high[i]!)}`).join('L')}L${[...group].reverse().map(i => `${x(i)},${y(low[i]!)}`).join('L')}Z`).join(' ')
  // On a calendar axis a session's dives share one x: keep the last of each so the line does not spike inside a session.
  // A break of more than 60 days lifts the pen, so an unmeasured stretch does not look like a steady level.
  const medianPath = groups.filter(group => group.length > 1 && group.every(i => smooth[i] != null)).map(group => {
    const kept = group.filter((i, k) => !timed || k === group.length - 1 || x(i) !== x(group[k + 1]))
    return kept.map((i, k) => `${k && !((points[i].occurredAt ?? 0) - (points[kept[k - 1]].occurredAt ?? 0) > 60 * DAY) ? 'L' : 'M'}${x(i).toFixed(1)},${y(smooth[i]!).toFixed(1)}`).join('')
  }).join(' ')
  const current = selected != null ? points[selected] : null

  return <><div ref={host} className="ca-chart" tabIndex={onSelect ? 0 : undefined} role={onSelect ? 'group' : 'img'} aria-label={onSelect ? `${label}. ${t('codeAnalysis.chartKeys')}` : label}
    onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={endDrag} onPointerCancel={cancelDrag} onPointerLeave={cancelDrag} onKeyDown={onKeyDown}>
    {width > 0 && <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden="true">
      {!timed && groups.filter(group => group.some(i => points[i].highlight)).map(group => <rect key={`selected-${group[0]}`} x={x(group[0]) - 4} y={T} width={Math.max(8, x(group[group.length - 1]) - x(group[0]) + 8)} height={H - B - T} fill="currentColor" fillOpacity=".08" pointerEvents="none" />)}
      {timed && showBand && <rect className="ca-selection-band" x={timeX(boundary.start)} y={T} width={Math.max(0, timeX(boundary.end ?? timeEnd) - timeX(boundary.start))} height={H-B-T} fill="currentColor" fillOpacity=".08" pointerEvents="none" />}
      {timed && <g pointerEvents="none"><defs><pattern id={hatchId} width="6" height="6" patternUnits="userSpaceOnUse"><path d="M0 6L6 0" stroke="currentColor" strokeOpacity=".3" /></pattern></defs>
        {boundary?.uncertainUntil && <rect x={timeX(boundary.start)} y={T} width={Math.max(0, timeX(boundary.uncertainUntil) - timeX(boundary.start))} height={H - B - T} fill={`url(#${hatchId})`} />}
        {markers?.filter(marker => marker.at <= timeEnd && (marker.at >= timeStart || (marker.until ?? marker.at) >= timeStart)).map((marker, i) => <g key={i}><line x1={timeX(marker.at)} x2={timeX(marker.at)} y1={T} y2={H - B} stroke="currentColor" strokeOpacity=".4" strokeDasharray="2 3" />{marker.until && <rect x={timeX(marker.at)} y={T} width={Math.max(0, timeX(marker.until) - timeX(marker.at))} height={H - B - T} fill={`url(#${hatchId})`} />}</g>)}
        {boundary && onAxis(boundary.start) && <line className="ca-selection-edge ca-selection-start" x1={timeX(boundary.start)} x2={timeX(boundary.start)} y1={T} y2={H - B} stroke="currentColor" strokeDasharray="2 3"><title>{new Date(boundary.start).toISOString()}</title></line>}
        {boundary?.end != null && onAxis(boundary.end) && <line className="ca-selection-edge" x1={timeX(boundary.end)} x2={timeX(boundary.end)} y1={T} y2={H - B} stroke="currentColor" strokeDasharray="2 3" />}
      </g>}
      {[0, 2.5, 5, 7.5, 10].map(value => <g key={value}>
        <line className="ca-grid" x1={L} x2={W - R} y1={y(value)} y2={y(value)} />
        <text className="ca-axis" x={L - 6} y={y(value) + 3} textAnchor="end">{value.toLocaleString(i18n.language)}</text>
      </g>)}
      {monthTicks.map(tick => <text key={tick.index} className="ca-axis" x={x(tick.index)} y={H - 6}>{tick.text}</text>)}
      {dateTicks.map(tick => {
        const px = timeX(tick.at)
        return <g key={tick.at}>
          <line className="ca-grid" x1={px} x2={px} y1={T} y2={H - B + 4} opacity=".55" />
          <text className="ca-axis" x={Math.min(W - 2, Math.max(2, px))} y={H - 6}
            textAnchor={px < 32 ? 'start' : px > W - 32 ? 'end' : 'middle'}>{tick.text}</text>
        </g>
      })}
      {bandPath && !simple && <path className="ca-band" d={bandPath} />}
      {points.map((point, index) => point.lo != null && point.hi != null &&
        <line key={`r${point.key}`} x1={x(index)} x2={x(index)} y1={y(point.lo)} y2={y(point.hi)} stroke={`var(--ca-${point.band})`} strokeOpacity=".45" strokeLinecap="round"
          strokeWidth={Math.max(2, Math.min(8, (W - L - R) / n * 0.5))} />)}
      {points.map((point, index) => <circle key={point.key} cx={x(index)} cy={y(point.value)} r={radius} fill={`var(--ca-${point.band})`} className="ca-score-point" fillOpacity={boundary && !point.highlight ? outsideOpacity : .9} />)}
      {medianPath && <path ref={line} className="ca-medline" d={medianPath} />}
      {/* Simple charts name the line where it ends instead of carrying a legend. */}
      {simple && medianPath && smooth[n - 1] != null && <text className="ca-medline-label" x={x(n - 1) - 12} y={y(smooth[n - 1]!) + (smooth[n - 1]! > 8 ? 16 : -9)} textAnchor="end">{t('codeAnalysis.recentMedian')} {fmtScore(smooth[n - 1]!)}</text>}
      {(selectionMode === 'tap' || !onSelect || simple ? [] : marks).map(mark => {
        const up = mark.kind === 'peak', colour = up ? 'var(--ca-P)' : 'var(--ca-B)'
        const text = `${up ? '▲' : '▼'} ${fmtScore(mark.value)}`
        return <g key={`${mark.kind}${mark.index}`} className="ca-mark" role="button" tabIndex={0} aria-label={`${up ? t('codeAnalysis.peak') : t('codeAnalysis.valley')} ${fmtScore(mark.value)}`}
          onClick={event => { event.stopPropagation(); onSelect?.(mark.index, mark) }}
          onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); event.stopPropagation(); onSelect?.(mark.index, mark) } }}>
          <circle cx={x(mark.index)} cy={y(mark.value)} r="14" fill="transparent" />
          <circle cx={x(mark.index)} cy={y(mark.value)} r="5" fill="var(--app-bg)" stroke={colour} strokeWidth="2.5" />
          <text x={x(mark.index)} y={up ? y(mark.value) - 11 : y(mark.value) + 19} textAnchor="middle" fill={colour}>{text}</text>
        </g>
      })}
      {showCursor && current && selected != null && <g pointerEvents="none">
        <line x1={x(selected)} x2={x(selected)} y1={T - 6} y2={H - B} stroke="#fff" strokeOpacity=".35" strokeDasharray="3 3" />
        <circle cx={x(selected)} cy={y(current.value)} r={radius + 4} fill="none" stroke="#fff" strokeWidth="2" />
      </g>}
    </svg>}
  </div>{width > 0 && renderTimeline?.(date => timeX(date) * width / W, width)}</>
}

const HOUR = 60 * 60 * 1000
const DAY = 24 * HOUR

function calendarTicks(start: number, end: number, width: number, language: string) {
  const target = Math.max(2, Math.floor(width / 82))
  const span = end - start
  const ticks: number[] = []
  let format: Intl.DateTimeFormatOptions

  if (span >= 60 * DAY) {
    const first = new Date(start), last = new Date(end)
    const firstMonth = first.getUTCFullYear() * 12 + first.getUTCMonth()
    const lastMonth = last.getUTCFullYear() * 12 + last.getUTCMonth()
    const desired = Math.max(1, (lastMonth - firstMonth) / target)
    const step = [1, 2, 3, 6, 9, 12].find(value => value >= desired) ?? Math.ceil(desired / 12) * 12
    for (let month = Math.ceil(firstMonth / step) * step; month <= lastMonth; month += step) {
      const at = Date.UTC(Math.floor(month / 12), month % 12, 1)
      if (at >= start && at <= end) ticks.push(at)
    }
    format = step >= 12 ? { year: 'numeric' } : {
      month: 'short', year: first.getUTCFullYear() !== last.getUTCFullYear() ? '2-digit' : undefined,
    }
  } else {
    const minute = HOUR / 60
    const desired = span / target
    const daily = span >= 2 * DAY
    const steps = daily ? [1, 2, 3, 5, 7, 14, 28].map(value => value * DAY) :
      [1, 5, 15, 30, 60, 300, 900, 1800, 3600, 10800, 21600, 43200, 86400].map(value => value * 1000)
    const step = steps.find(value => value >= desired) ?? steps[steps.length - 1]
    for (let at = Math.ceil(start / step) * step; at <= end; at += step) ticks.push(at)
    format = daily ? { day: 'numeric', month: 'short' } :
      { hour: '2-digit', minute: '2-digit', second: step < minute ? '2-digit' : undefined, hourCycle: 'h23' }
  }
  const formatter = new Intl.DateTimeFormat(language, { ...format, timeZone: 'UTC' })
  return (ticks.length ? ticks : [start]).map(at => ({ at, text: formatter.format(at) }))
}

function prefersReducedMotion() {
  return typeof window !== 'undefined' && Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)
}
