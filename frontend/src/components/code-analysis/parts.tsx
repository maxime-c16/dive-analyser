import React, { useLayoutEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import './codeAnalysis.css'
import { fmtScore } from '../../utils/codeStats'

const RATINGS = ['P', 'G', 'M', 'B', 'F'] as const

export function ratingCounts(performances: Array<string | null | undefined>): Partial<Record<(typeof RATINGS)[number], number>> {
  return Object.fromEntries(RATINGS.map(rating => [rating, performances.filter(value => value === rating).length]))
}

export function RatingBar({ ratings }: { ratings: Partial<Record<string, number>> }) {
  const counts = RATINGS.map(rating => [rating, ratings[rating] ?? 0] as const).filter(([, count]) => count)
  return <div className="ca-rbar" aria-hidden="true">{counts.map(([rating, count]) => <span key={rating} className={`ca-r-${rating}`} style={{ flex: count }} />)}</div>
}

export function ScoreChip({ id, performance, score, label, onOpen, current }: {
  id: number; performance: string | null | undefined; score: number; label: string; onOpen: (id: number) => void; current?: boolean
}) {
  return <button type="button" className={`ca-chip ca-r-${performance || 'F'}`} data-attempt-id={id} aria-label={label} title={label}
    aria-current={current || undefined} onClick={event => { event.stopPropagation(); onOpen(id) }}>{Math.round(score)}</button>
}

export function Sparkline({ values, width = 84, height = 30 }: { values: number[]; width?: number; height?: number }) {
  if (values.length < 2) return <svg className="ca-spark" width={width} height={height} aria-hidden="true" />
  const lo = Math.min(...values), hi = Math.max(...values), span = Math.max(1, hi - lo)
  const points = values.map((value, index) => [index / (values.length - 1) * (width - 4) + 2, height - 3 - (value - lo) / span * (height - 6)])
  const delta = values[values.length - 1] - values[0]
  const colour = delta >= 0.5 ? 'var(--ca-up)' : delta <= -0.5 ? 'var(--ca-down)' : 'var(--app-muted)'
  const [lastX, lastY] = points[points.length - 1]
  return <svg className="ca-spark" style={{ width, height }} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
    <polyline points={points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')} fill="none" stroke={colour} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
    <circle cx={lastX} cy={lastY} r="2.5" fill={colour} />
  </svg>
}

export function TrendBadge({ delta, long = false }: { delta: number | null | undefined; long?: boolean }) {
  const { t } = useTranslation()
  if (delta == null) return <span className="ca-trend ca-flat">{long ? t('codeAnalysis.trendTooOld') : '—'}</span>
  const tone = delta >= 0.5 ? 'up' : delta <= -0.5 ? 'down' : 'flat'
  const text = tone === 'flat' ? t('codeAnalysis.stable') : `${tone === 'up' ? '▲ +' : '▼ '}${fmtScore(delta)}`
  return <span className={`ca-trend ca-${tone}`}>{text}</span>
}

/** Pill segmented control whose thumb slides to the selected option. */
export function Segmented<T extends string>({ label, options, value, onChange }: {
  label: string; options: ReadonlyArray<readonly [T, string]>; value: T | null; onChange: (value: T) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [thumb, setThumb] = useState<{ left: number; width: number } | null>(null)
  useLayoutEffect(() => {
    const place = () => {
      const selected = ref.current?.querySelector<HTMLElement>('[aria-pressed=true]')
      setThumb(selected ? { left: selected.offsetLeft, width: selected.offsetWidth } : null)
    }
    place()
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(place)
    if (ref.current) observer?.observe(ref.current)
    return () => observer?.disconnect()
  }, [value])
  return <div ref={ref} className="ca-seg" role="group" aria-label={label}>
    {thumb && <span className="ca-seg-thumb" style={{ width: thumb.width, transform: `translateX(${thumb.left - 3}px)` }} aria-hidden="true" />}
    {options.map(([option, text]) => <button key={option} type="button" aria-pressed={option === value} onClick={() => onChange(option)}>{text}</button>)}
  </div>
}

/** Counts a number up once on first paint; static under reduced motion. */
export function CountUp({ value, digits = 1, suffix = '' }: { value: number | null; digits?: number; suffix?: string }) {
  const [shown, setShown] = useState(value)
  const played = useRef(false)
  useLayoutEffect(() => {
    if (value == null) { setShown(null); return }
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (played.current || reduce) { setShown(value); return }
    played.current = true
    let frame = 0, start: number | null = null
    const step = (time: number) => {
      start ??= time
      const progress = Math.min(1, (time - start) / 650)
      setShown(value * (1 - Math.pow(1 - progress, 3)))
      if (progress < 1) frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [value])
  return <>{shown == null ? '—' : `${digits === 1 ? fmtScore(shown) : shown.toFixed(digits)}${suffix}`}</>
}
