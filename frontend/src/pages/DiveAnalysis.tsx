import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { CalendarRange, ChevronLeft, ChevronRight, Copy, Film, RotateCcw, SlidersHorizontal, X } from 'lucide-react'
import { differenceInCalendarDays, format, parseISO, subMonths } from 'date-fns'
import DiveVideoPlayer from '../components/DiveVideoPlayer'
import PersonalDiveValuePanel from '../components/PersonalDiveValuePanel'
import {
  getDiveAnalysis,
  getDivers,
  getTrainingPeriods,
  type ContextDimension,
  type DiveAnalysis as AnalysisData,
  type DiveAnalysisFilters,
  type DiveAttempt,
  type Diver,
  type PhaseSeries,
  type TrainingPeriod,
} from '../services/diveAnalysisApi'
import { getRepresentatives, type RepresentativeCard } from '../services/representativeMediaApi'
import { getPersonalDiveValues, type PersonalDiveValue } from '../services/personalDiveValueApi'
import { usePreservedSearchParams } from '../hooks/usePreservedSearchParams'
import { DIVE_POSITION_NAMES, divePositionName } from '../utils/divePosition'

const MODIFIERS = ['DB', 'SD', 'HU']
const DIMENSIONS: ContextDimension[] = ['modifier', 'height', 'position', 'sync', 'diver', 'training_period']
const ACTIVE_MEDIA = new Set(['queued', 'waiting_for_mac', 'claimed', 'materializing', 'exporting', 'transcoding', 'uploading', 'verifying'])
const SAMPLE_LABELS: Record<string, string> = { no_data: 'No data', insufficient: 'Insufficient', exploratory: 'Exploratory', moderate_sample: 'Moderate sample', stronger_descriptive_sample: 'Stronger descriptive sample' }
const SCORE_LABELS = new Map([[0, 'F'], [2, 'B'], [4.5, 'M'], [7, 'G'], [10, 'P']])
// These are the only search parameters that change the server-side analysis.
// Presentation state stays in the URL too, but must not tear down the page by
// starting another analytics request whenever a chart control changes.
const ANALYSIS_FILTER_KEYS = new Set([
  'date_from', 'date_to', 'height', 'platform_type', 'position', 'modifiers',
  'modifier_mode', 'is_sync', 'diver_scope', 'diver_ids', 'training_period_ids',
  'success_threshold', 'weighting',
])
type SplitMode = 'none' | 'height' | 'position' | 'modifier' | 'sync' | 'diver'
type ChartView = 'session' | 'attempts' | 'range'
type TimelinePoint = {
  id: number
  date: string
  score: number
  rolling: number | null
  sync?: boolean
  ready?: boolean
  label: string
  sessionId: number
  height: string
  position: string | null
  modifiers: string[]
  diver: string
  mediaStatus: string
  rangeMin?: number
  rangeMax?: number
  sessionAttemptCount?: number
}

export function filtersFromSearchParams(params: URLSearchParams): DiveAnalysisFilters {
  return {
    date_from: params.get('date_from') || undefined,
    date_to: params.get('date_to') || undefined,
    height: params.get('height') || undefined,
    platform_type: params.get('platform_type') || undefined,
    position: params.get('position') || undefined,
    modifiers: params.getAll('modifiers'),
    modifier_mode: (params.get('modifier_mode') as DiveAnalysisFilters['modifier_mode']) || 'any',
    is_sync: params.has('is_sync') ? params.get('is_sync') === 'true' : undefined,
    diver_scope: (params.get('diver_scope') as DiveAnalysisFilters['diver_scope']) || (params.has('diver_ids') ? 'selected' : 'self'),
    diver_ids: params.getAll('diver_ids').map(Number).filter(Number.isFinite),
    training_period_ids: params.getAll('training_period_ids').map(Number).filter(Number.isFinite),
    success_threshold: (params.get('success_threshold') as 'M' | 'G' | 'P') || 'G',
    weighting: (params.get('weighting') as 'attempts' | 'sessions') || 'attempts',
  }
}

function analysisFilterSearchKey(params: URLSearchParams) {
  const filtered = new URLSearchParams()
  params.forEach((value, key) => {
    if (ANALYSIS_FILTER_KEYS.has(key)) filtered.append(key, value)
  })
  return filtered.toString()
}

const scoreText = (value: number | null | undefined) => value == null ? '-' : value.toFixed(1)
const dateInput = (date: Date) => format(date, 'yyyy-MM-dd')
const unique = <T,>(values: T[]) => [...new Set(values.filter((value) => value !== null && value !== undefined && value !== '') as T[])]
const percentageText = (value: number | null | undefined) => value == null ? '-' : `${value.toFixed(1)}%`

function countBy<T extends string>(values: T[]) {
  return values.reduce<Record<string, number>>((counts, value) => {
    counts[value] = (counts[value] || 0) + 1
    return counts
  }, {})
}

function deltaText(current: number | null | undefined, previous: number | null | undefined, suffix = '') {
  if (current == null || previous == null) return 'Previous unavailable'
  const delta = current - previous
  if (Math.abs(delta) < 0.05) return `No change${suffix}`
  return `${delta > 0 ? '+' : ''}${delta.toFixed(1)}${suffix} vs previous`
}

function buildTimelinePoint(attempt: DiveAttempt): TimelinePoint {
  return {
    id: attempt.id,
    date: attempt.dive_datetime,
    score: attempt.performance_numeric,
    rolling: attempt.rolling_median,
    sync: attempt.is_sync,
    ready: attempt.media.status === 'ready',
    sessionId: attempt.session_id,
    height: attempt.height,
    position: attempt.position,
    modifiers: attempt.modifiers,
    diver: attempt.diver?.display_name || 'Unassigned',
    mediaStatus: attempt.media.status,
    label: `${format(parseISO(attempt.dive_datetime), 'd MMM yyyy, HH:mm')}, score ${attempt.performance_numeric.toFixed(1)} / ${attempt.performance}, ${attempt.height}, ${divePositionName(attempt.position, attempt.dive_code)}, ${attempt.modifiers.join(', ') || 'no modifiers'}, ${attempt.is_sync ? 'SYNC' : 'Individual'}, media ${attempt.media.status}`,
  }
}

function sessionSummaries(points: TimelinePoint[]): TimelinePoint[] {
  const grouped = new Map<number, TimelinePoint[]>()
  points.forEach((point) => grouped.set(point.sessionId, [...(grouped.get(point.sessionId) || []), point]))
  return [...grouped.entries()].map(([sessionId, sessionPoints]) => {
    const ordered = [...sessionPoints].sort((a, b) => a.score - b.score)
    const medianPoint = ordered[Math.floor(ordered.length / 2)]
    const median = medianPoint.score
    const midpoint = sessionPoints[Math.floor(sessionPoints.length / 2)]
    const rollingValues = sessionPoints.map((point) => point.rolling).filter((value): value is number => value != null)
    return {
      ...midpoint,
      id: medianPoint.id,
      sessionId,
      score: median,
      rolling: rollingValues.length ? rollingValues[Math.floor(rollingValues.length / 2)] : null,
      sync: sessionPoints.some((point) => point.sync),
      ready: sessionPoints.some((point) => point.ready),
      rangeMin: ordered[0].score,
      rangeMax: ordered[ordered.length - 1].score,
      sessionAttemptCount: sessionPoints.length,
      label: `${format(parseISO(midpoint.date), 'd MMM yyyy')}, session ${sessionId}, range ${ordered[0].score.toFixed(1)} to ${ordered[ordered.length - 1].score.toFixed(1)}, median ${median.toFixed(1)}, ${sessionPoints.length} attempts`,
    }
  }).sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime())
}

function rangeBucketDays(points: TimelinePoint[]) {
  if (points.length < 2) return 7
  const times = points.map((point) => new Date(point.date).getTime())
  const spanDays = Math.max((Math.max(...times) - Math.min(...times)) / 86_400_000, 1)
  const idealDays = spanDays / 10
  const candidates = [7, 14, 21, 28, 42, 56, 84, 112, 168, 224, 365]
  return candidates.reduce((best, candidate) => Math.abs(candidate - idealDays) < Math.abs(best - idealDays) ? candidate : best, candidates[0])
}

function periodRangeSummaries(points: TimelinePoint[]): TimelinePoint[] {
  if (!points.length) return []
  const orderedByDate = [...points].sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime())
  const start = new Date(orderedByDate[0].date).getTime()
  const bucketDays = rangeBucketDays(orderedByDate)
  const bucketMs = bucketDays * 86_400_000
  const grouped = new Map<number, TimelinePoint[]>()
  orderedByDate.forEach((point) => {
    const bucket = Math.floor((new Date(point.date).getTime() - start) / bucketMs)
    grouped.set(bucket, [...(grouped.get(bucket) || []), point])
  })
  return [...grouped.entries()].map(([bucket, periodPoints]) => {
    const orderedByScore = [...periodPoints].sort((a, b) => a.score - b.score)
    const medianPoint = orderedByScore[Math.floor(orderedByScore.length / 2)]
    const periodStart = new Date(start + bucket * bucketMs)
    const periodEnd = new Date(start + (bucket + 1) * bucketMs)
    return {
      ...medianPoint,
      date: new Date(start + (bucket + 0.5) * bucketMs).toISOString(),
      score: medianPoint.score,
      rangeMin: orderedByScore[0].score,
      rangeMax: orderedByScore[orderedByScore.length - 1].score,
      sessionAttemptCount: periodPoints.length,
      label: `${format(periodStart, 'd MMM yyyy')} to ${format(periodEnd, 'd MMM yyyy')}, range ${orderedByScore[0].score.toFixed(1)} to ${orderedByScore[orderedByScore.length - 1].score.toFixed(1)}, median ${medianPoint.score.toFixed(1)}, ${periodPoints.length} attempts`,
    }
  })
}

function groupPoints(points: TimelinePoint[], split: SplitMode) {
  if (split === 'none') return [{ label: 'Combined', points }]
  const grouped = new Map<string, TimelinePoint[]>()
  points.forEach((point) => {
    const labels = split === 'modifier'
      ? (point.modifiers.length ? point.modifiers : ['No modifier'])
      : [split === 'height' ? point.height : split === 'position' ? divePositionName(point.position) : split === 'sync' ? (point.sync ? 'SYNC' : 'Individual') : point.diver]
    labels.forEach((label) => grouped.set(label, [...(grouped.get(label) || []), point]))
  })
  return [...grouped.entries()].map(([label, group]) => ({ label, points: group }))
}

function timeTicks(minTime: number, maxTime: number) {
  const days = Math.max(differenceInCalendarDays(new Date(maxTime), new Date(minTime)), 1)
  const steps = days > 540 ? 5 : days > 180 ? 4 : days > 60 ? 3 : 2
  return Array.from({ length: steps + 1 }, (_, index) => minTime + ((maxTime - minTime) * index) / steps)
}

function PointTimeline({
  points,
  label,
  selectedId,
  onSelect,
  view,
  splitBy,
}: {
  points: TimelinePoint[]
  label: string
  selectedId?: number
  onSelect?: (id: number, trigger: Element) => void
  view: ChartView
  splitBy: SplitMode
}) {
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const [chartWidth, setChartWidth] = useState(640)
  const height = splitBy === 'none' ? 360 : 420, pad = { left: 54, right: 24, top: 26, bottom: 48 }
  const svgRef = useRef<SVGSVGElement>(null)
  useEffect(() => {
    const container = chartContainerRef.current
    if (!container) return
    const updateWidth = () => setChartWidth(Math.max(320, Math.round(container.clientWidth)))
    updateWidth()
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', updateWidth)
      return () => window.removeEventListener('resize', updateWidth)
    }
    const observer = new ResizeObserver(updateWidth)
    observer.observe(container)
    return () => observer.disconnect()
  }, [])
  const width = chartWidth
  const rangeView = view === 'range'
  // Summarize after splitting so a mixed-height or mixed-SYNC session never
  // contributes one range to the wrong comparison lane.
  const groups = groupPoints(points, splitBy)
    .map((group) => ({ ...group, points: view === 'attempts' ? group.points : rangeView ? periodRangeSummaries(group.points) : sessionSummaries(group.points) }))
    .filter((group) => group.points.length)
  const visiblePoints = groups.flatMap((group) => group.points)
  if (!visiblePoints.length) return <div className="flex h-64 items-center justify-center text-sm text-app-muted">No scored attempts are available for this series.</div>
  const times = visiblePoints.map((point) => new Date(point.date).getTime())
  const minTime = Math.min(...times), maxTime = Math.max(...times)
  const plotHeight = height - pad.top - pad.bottom
  const laneHeight = splitBy === 'none' ? plotHeight : plotHeight / groups.length
  const x = (value: number) => pad.left + ((value - minTime) / Math.max(maxTime - minTime, 1)) * (width - pad.left - pad.right)
  const laneTop = (index: number) => pad.top + index * laneHeight
  const y = (value: number, index = 0) => laneTop(index) + ((10 - value) / 10) * (laneHeight - 14) + 7
  const ticks = timeTicks(minTime, maxTime)
  const selectNearest = (event: React.MouseEvent<SVGSVGElement>) => {
    if (!onSelect || !svgRef.current) return
    const box = svgRef.current.getBoundingClientRect()
    const clickX = (event.clientX - box.left) * width / box.width
    const clickY = (event.clientY - box.top) * height / box.height
    const all = groups.flatMap((group, lane) => group.points.map((point) => ({ point, lane })))
    const nearest = all.reduce<{ point: TimelinePoint; lane: number; distance: number }>((best, item) => {
      const distance = (x(new Date(item.point.date).getTime()) - clickX) ** 2 + (y(item.point.score, item.lane) - clickY) ** 2
      return distance < best.distance ? { ...item, distance } : best
    }, { point: visiblePoints[0], lane: 0, distance: Number.POSITIVE_INFINITY })
    onSelect(nearest.point.id, svgRef.current)
  }
  return <div ref={chartContainerRef} className="min-w-0">
    <div className="min-w-0">
      <svg ref={svgRef} viewBox={`0 0 ${width} ${height}`} className="block h-auto w-full" role="img" aria-label={label} onClick={selectNearest} data-testid="attempt-progression-chart">
        {groups.map((group, lane) => {
          const trendPath = !rangeView ? group.points.filter((point) => point.rolling != null).map((point, index) => `${index ? 'L' : 'M'} ${x(new Date(point.date).getTime())} ${y(point.rolling!, lane)}`).join(' ') : ''
          return <g key={group.label}>
            {splitBy !== 'none' && <text x={pad.left} y={laneTop(lane) + 14} fill="#edf2f4" fontSize="12" fontWeight="600">{group.label} · {group.points.length}</text>}
            {[0, 2, 4.5, 7, 10].map((score) => <g key={`${group.label}-${score}`}><line x1={pad.left} x2={width - pad.right} y1={y(score, lane)} y2={y(score, lane)} stroke={score === 4.5 ? 'rgba(237,242,244,.22)' : 'rgba(126,146,156,.16)'} /><text x={pad.left - 12} y={y(score, lane) + 4} fill="#98a2aa" textAnchor="end" fontSize="11">{SCORE_LABELS.get(score) || score}</text></g>)}
            {trendPath && <path d={trendPath} fill="none" stroke="#8ed7ff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" data-testid="rolling-median-line" />}
            {group.points.map((point, index) => {
              const cx = x(new Date(point.date).getTime())
              const jitter = view === 'attempts' && group.points.length > 90 ? ((index % 5) - 2) * 1.8 : 0
              const cy = y(point.score, lane) + jitter
              return <g key={`${group.label}-${point.id}`} role={onSelect ? 'button' : undefined} tabIndex={onSelect ? 0 : undefined} aria-label={point.label} onClick={(event) => { event.stopPropagation(); onSelect?.(point.id, event.currentTarget) }} onKeyDown={(event) => { if (onSelect && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); onSelect(point.id, event.currentTarget) } }} className={onSelect ? 'cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-app-accent' : ''}>
                {rangeView ? <>
                  <line x1={cx} x2={cx} y1={y(point.rangeMax ?? point.score, lane)} y2={y(point.rangeMin ?? point.score, lane)} stroke="#54beab" strokeWidth="3" strokeLinecap="round" data-testid="session-range" />
                  <circle cx={cx} cy={y(point.rangeMax ?? point.score, lane)} r="5" fill="#54beab" />
                  <circle cx={cx} cy={y(point.rangeMin ?? point.score, lane)} r="5" fill="#8eafb0" />
                  <circle cx={cx} cy={cy} r="8" fill="transparent" />
                  <circle cx={cx} cy={cy} r={selectedId === point.id ? 6 : 5} fill="#54beab" stroke="#edf2f4" strokeWidth="3"><title>{point.label}</title></circle>
                </> : <>
                  <circle cx={cx} cy={cy} r={view === 'session' ? 10 : 9} fill="transparent" />
                  <circle cx={cx} cy={cy} r={selectedId === point.id ? 6 : view === 'session' ? 5 : 4} fill={point.sync ? '#e3b15f' : '#54beab'} opacity={view === 'attempts' ? 0.74 : 0.95} stroke={point.ready ? '#edf2f4' : '#0d1113'} strokeWidth={point.ready ? 2 : 1}><title>{point.label}</title></circle>
                </>}
              </g>
            })}
          </g>
        })}
        {ticks.map((tick, index) => <g key={`${tick}-${index}`}><line x1={x(tick)} x2={x(tick)} y1={pad.top} y2={height - pad.bottom + 8} stroke="rgba(126,146,156,.12)" /><text x={x(tick)} y={height - 18} fill="#98a2aa" fontSize="11" textAnchor="middle">{format(new Date(tick), differenceInCalendarDays(new Date(maxTime), new Date(minTime)) > 365 ? 'MMM yyyy' : 'd MMM')}</text></g>)}
      </svg>
    </div>
    <div className="mt-3 flex flex-wrap gap-4 text-xs text-app-muted" aria-label="Chart legend">
      {rangeView ? <>
        <span className="inline-flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full bg-[#54beab]" />Max</span>
        <span className="inline-flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full border-2 border-white/90 bg-[#54beab]" />Median</span>
        <span className="inline-flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full bg-[#8eafb0]" />Min</span>
        <span>One vertical range per adaptive time period · select a median to open an exact attempt</span>
      </> : <>
        <span className="inline-flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full bg-[#54beab]" />Individual attempt</span>
        <span className="inline-flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full bg-[#e3b15f]" />SYNC attempt</span>
        <span className="inline-flex items-center gap-2"><span className="h-0.5 w-8 rounded bg-[#8ed7ff]" />Rolling 5-attempt median</span>
        <span className="inline-flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full border-2 border-white/90" />Video ready outline</span>
      </>}
    </div>
  </div>
}

function Distribution({ attempts }: { attempts: DiveAttempt[] }) {
  const levels = [{ label: 'F', value: 0 }, { label: 'B', value: 2 }, { label: 'M', value: 4.5 }, { label: 'G', value: 7 }, { label: 'P', value: 10 }]
  const counts = levels.map((level) => ({ ...level, count: attempts.filter((item) => item.performance === level.label).length }))
  const maximum = Math.max(...counts.map((item) => item.count), 1)
  return <div className="grid min-h-56 min-w-0 grid-cols-5 items-end gap-1 pt-6 sm:min-h-64 sm:gap-4" aria-label="Score distribution">{counts.map((item) => <div key={item.label} className="flex min-w-0 flex-col items-center gap-2"><span className="text-xs tabular-nums text-app-muted">{item.count}</span><div className="w-full max-w-16 bg-app-panel-elevated" style={{ height: `${Math.max((item.count / maximum) * 168, item.count ? 5 : 0)}px` }} /><span className="text-base font-semibold text-app-text">{item.label}</span><span className="text-[11px] text-app-muted">{item.value}</span></div>)}</div>
}

function PeriodComparison({ current, previous }: { current: AnalysisData['summary']; previous: NonNullable<AnalysisData['comparison']['previous']> }) {
  const rows: Array<[string, string | number, string | number, string | number]> = [
    ['Attempts', current.attempt_count, previous.attempt_count, current.attempt_count - previous.attempt_count],
    ['Sessions', current.session_count, previous.session_count, current.session_count - previous.session_count],
    ['Median', scoreText(current.median), scoreText(previous.median), deltaText(current.median, previous.median)],
    ['Avg DD', scoreText(current.average_dd), scoreText(previous.average_dd), deltaText(current.average_dd, previous.average_dd)],
    ['Average', scoreText(current.average), scoreText(previous.average), deltaText(current.average, previous.average)],
    ['IQR', scoreText(current.iqr), scoreText(previous.iqr), deltaText(current.iqr, previous.iqr)],
    ['Success', percentageText(current.success_rate), percentageText(previous.success_rate), current.success_rate != null && previous.success_rate != null ? `${(current.success_rate - previous.success_rate).toFixed(1)} pts` : '-'],
  ]
  return <><div className="mt-4 grid gap-2 sm:hidden">{rows.map(([label, selected, earlier, change]) => <article key={label} className="grid grid-cols-[1fr_auto] gap-x-4 border border-app bg-app-panel-elevated p-3 text-sm"><span className="font-medium text-app-text">{label}</span><span className="font-semibold text-app-accent">{change}</span><span className="mt-2 text-xs text-app-muted">Selected {selected}</span><span className="mt-2 text-right text-xs text-app-muted">Previous {earlier}</span></article>)}</div><div className="mt-5 hidden min-w-0 gap-px overflow-x-auto text-sm sm:grid"><div className="grid min-w-[860px] grid-cols-4"><div className="p-3 text-app-muted">Measure</div><div className="p-3 text-app-muted">Selected period</div><div className="p-3 text-app-muted">Previous equal period</div><div className="p-3 text-app-muted">Change</div>{rows.flatMap(([label, currentValue, previousValue, change]) => [<div key={`${label}-l`} className="border-t border-app p-3 text-app-muted">{label}</div>, <div key={`${label}-c`} className="border-t border-app p-3 text-app-text">{currentValue}</div>, <div key={`${label}-p`} className="border-t border-app p-3 text-app-text">{previousValue}</div>, <div key={`${label}-d`} className="border-t border-app p-3 text-app-text">{change}</div>])}</div></div></>
}

function ContextBreakdown({ rows }: { rows: AnalysisData['breakdowns'][ContextDimension] }) {
  return <><div className="grid gap-2 p-3 sm:hidden">{rows.map((row) => <article key={`${row.context}-${row.context_id}`} className="border border-app bg-app-panel-elevated p-3"><div className="flex items-start justify-between gap-3"><div><h3 className="font-medium text-app-text">{row.context}</h3><p className="mt-1 text-xs text-app-muted">{row.attempt_count} attempts · {row.session_count} sessions · {SAMPLE_LABELS[row.sample_label]}</p></div><span className="text-sm font-semibold text-app-accent">{scoreText(row.median)}</span></div><dl className="mt-3 grid grid-cols-2 gap-2 text-xs"><div><dt className="text-app-muted">Average execution</dt><dd className="mt-1 text-app-text">{scoreText(row.average)}</dd></div><div><dt className="text-app-muted">Avg DD</dt><dd className="mt-1 text-app-text">{scoreText(row.average_dd)}</dd></div><div><dt className="text-app-muted">Success</dt><dd className="mt-1 text-app-text">{percentageText(row.success_rate)}</dd></div><div><dt className="text-app-muted">DD coverage</dt><dd className="mt-1 text-app-text">{percentageText(row.dd_coverage_rate)}</dd></div></dl></article>)}</div><div className="hidden overflow-x-auto sm:block"><table className="w-full min-w-[900px] text-left text-sm"><thead className="text-xs text-app-muted"><tr>{['Context', 'Attempts', 'Median', 'Average', 'Avg DD', 'DD coverage', 'Success', 'Sample'].map((heading) => <th key={heading} className="border-b border-app px-5 py-3 font-medium">{heading}</th>)}</tr></thead><tbody>{rows.map((row) => <tr key={`${row.context}-${row.context_id}`} className="border-b border-app last:border-0"><td className="px-5 py-3 font-medium text-app-text">{row.context}</td><td className="px-5 py-3 text-app-text">{row.attempt_count}</td><td className="px-5 py-3 text-app-text">{scoreText(row.median)}</td><td className="px-5 py-3 text-app-text">{scoreText(row.average)}</td><td className="px-5 py-3 text-app-text">{scoreText(row.average_dd)}</td><td className="px-5 py-3 text-app-text">{percentageText(row.dd_coverage_rate)}</td><td className="px-5 py-3 text-app-text">{percentageText(row.success_rate)}</td><td className="px-5 py-3 text-app-muted">{SAMPLE_LABELS[row.sample_label]}</td></tr>)}</tbody></table></div></>
}

function PhasePanel({ name, phase, attempts, view }: { name: string; phase: PhaseSeries; attempts: DiveAttempt[]; view: ChartView }) {
  const attemptsById = useMemo(() => new Map(attempts.map((attempt) => [attempt.id, attempt])), [attempts])
  const points = phase.points.map((point) => {
    const attempt = attemptsById.get(point.attempt_id)
    return { id: point.attempt_id, date: point.dive_datetime, score: point.score, rolling: point.rolling_median, label: `${name}, ${format(parseISO(point.dive_datetime), 'd MMM yyyy')}, ${point.score.toFixed(1)}`, sessionId: attempt?.session_id ?? point.attempt_id, height: attempt?.height || '', position: attempt?.position || null, modifiers: attempt?.modifiers || [], diver: attempt?.diver?.display_name || '', mediaStatus: attempt?.media.status || '' }
  })
  const description = view === 'range' ? 'adaptive-period minimum, median, and maximum' : view === 'session' ? 'session median' : 'rolling five-attempt median'
  return <section className="border border-app bg-app-panel"><div className="flex items-start justify-between border-b border-app px-5 py-4"><div><h3 className="font-semibold text-app-text">{name}</h3><p className="mt-1 text-xs text-app-muted">{phase.available_count} scored · {phase.missing_count} missing · {description}</p></div><div className="text-right text-sm"><div className="font-semibold text-app-text">Median {scoreText(phase.summary.median)}</div><div className="text-xs text-app-muted">Previous {scoreText(phase.previous_summary.median)}</div></div></div><div className="p-3"><PointTimeline points={points} label={view === 'range' ? `${name} performance range per session` : `${name} score progression`} view={view} splitBy="none" /></div></section>
}

function AttemptDrawer({ attempt, attempts, onClose, onMove, returnFocus }: { attempt: DiveAttempt; attempts: DiveAttempt[]; onClose: () => void; onMove: (attempt: DiveAttempt) => void; returnFocus: React.MutableRefObject<Element | null> }) {
  const asideRef = useRef<HTMLElement>(null), index = attempts.findIndex((item) => item.id === attempt.id)
  const recent = attempts.slice(Math.max(0, index - 4), index + 1).map((item) => item.performance_numeric), recentMedian = [...recent].sort((a, b) => a - b)[Math.floor(recent.length / 2)]
  useEffect(() => {
    const panel = asideRef.current
    panel?.focus()
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
      if (event.key === 'Tab' && panel) {
        const focusable = [...panel.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], video, [tabindex="0"]')]
        if (!focusable.length) return
        const first = focusable[0], last = focusable[focusable.length - 1]
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
      }
    }
    document.addEventListener('keydown', keydown)
    return () => { document.removeEventListener('keydown', keydown); (returnFocus.current as HTMLElement | null)?.focus() }
  }, [onClose, returnFocus])
  return <div className="fixed inset-0 z-50 flex justify-end bg-black/55" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><aside ref={asideRef} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="attempt-title" className="h-full w-full max-w-2xl overflow-y-auto border-l border-app bg-app-panel p-4 outline-none sm:p-7">
    <div className="flex items-start justify-between gap-4"><div><h2 id="attempt-title" className="text-2xl font-semibold text-app-text">{attempt.dive_code} · {attempt.performance_numeric.toFixed(1)}</h2><p className="mt-1 text-sm text-app-muted">{format(parseISO(attempt.dive_datetime), 'd MMMM yyyy, HH:mm')} · Session {attempt.session_id}</p></div><button type="button" onClick={onClose} className="border border-app bg-transparent p-2 text-app-muted" aria-label="Close attempt details"><X className="h-4 w-4" /></button></div>
    <div className="mt-6 aspect-video overflow-hidden border border-app bg-black" aria-label={`Media for ${attempt.dive_code} attempt ${attempt.id}`}>{attempt.video_uuid ? <DiveVideoPlayer diveCode={attempt.dive_code} height={attempt.height} videoUuid={attempt.video_uuid} /> : <div className="flex h-full items-center justify-center text-sm text-app-muted">No linked Photos asset</div>}</div>
    <dl className="mt-6 grid grid-cols-2 border-y border-app text-sm sm:grid-cols-3">{[
      ['Rating', `${attempt.performance} · ${attempt.performance_numeric.toFixed(1)}`], ['Phase scores', attempt.phase1_performance && attempt.phase2_performance ? `${attempt.phase1_performance} / ${attempt.phase2_performance}` : 'Single rating'],
      ['Height', attempt.height], ['Platform', attempt.platform_type], ['Position', divePositionName(attempt.position, attempt.dive_code)], ['Context', attempt.is_sync ? 'SYNC' : 'Individual'], ['Modifiers', attempt.modifiers.join(', ') || 'None'],
      ['Diver', attempt.diver?.display_name || 'Unassigned'], ['Training periods', attempt.training_periods.map((period) => period.name).join(', ') || 'None'], ['Official DD', attempt.official_dd?.toFixed(1) || '-'],
      ['Media', attempt.media.status.replace(/_/g, ' ')], ['Recent 5 median', recentMedian?.toFixed(1) || '-'], ['From rolling median', attempt.rolling_median == null ? '-' : (attempt.performance_numeric - attempt.rolling_median).toFixed(1)],
    ].map(([term, value]) => <div key={term} className="border-b border-app p-3"><dt className="text-xs text-app-muted">{term}</dt><dd className="mt-1 font-medium text-app-text">{value}</dd></div>)}</dl>
    <PersonalDiveValuePanel attemptId={attempt.id} onOpenAttempt={(id) => { const next = attempts.find((item) => item.id === id); if (next) onMove(next) }} />
    <div className="mt-6 space-y-4 text-sm"><div><h3 className="font-semibold text-app-text">Raw caption</h3><p className="mt-2 whitespace-pre-wrap text-app-muted">{attempt.raw_caption || 'No caption preserved.'}</p></div>{attempt.notes && <div><h3 className="font-semibold text-app-text">Notes</h3><p className="mt-2 text-app-muted">{attempt.notes}</p></div>}</div>
    <div className="mt-8 flex items-center justify-between border-t border-app pt-4"><button type="button" aria-label="Open previous attempt" disabled={index <= 0} onClick={() => onMove(attempts[index - 1])} className="flex items-center gap-2 border border-app bg-transparent text-sm disabled:opacity-30"><ChevronLeft className="h-4 w-4" /> Previous</button><Link to={`/sessions?session=${attempt.session_id}`} className="text-sm text-app-accent">Open session</Link><button type="button" aria-label="Open next attempt" disabled={index >= attempts.length - 1} onClick={() => onMove(attempts[index + 1])} className="flex items-center gap-2 border border-app bg-transparent text-sm disabled:opacity-30">Next <ChevronRight className="h-4 w-4" /></button></div>
  </aside></div>
}

function PersonalValueHistory({ values, attempts, onOpen }: { values: PersonalDiveValue[]; attempts: DiveAttempt[]; onOpen: (attempt: DiveAttempt, trigger: Element) => void }) {
  const rows = values.map((value) => ({ value, attempt: attempts.find((attempt) => attempt.id === value.attempt_id) })).filter((row): row is { value: PersonalDiveValue; attempt: DiveAttempt } => Boolean(row.attempt && row.value.value != null))
  if (!rows.length) return null
  const notable = [...rows].sort((left, right) => (right.value.value || 0) - (left.value.value || 0)).slice(0, 5)
  return <section className="border border-app bg-app-panel" aria-labelledby="personal-history-heading"><div className="flex flex-wrap items-end justify-between gap-3 border-b border-app px-4 py-4 sm:px-5"><div><p className="text-xs font-semibold uppercase tracking-[.14em] text-app-accent">Personal review priority</p><h2 id="personal-history-heading" className="mt-1 font-semibold text-app-text">Attempts worth revisiting</h2><p className="mt-1 text-xs leading-5 text-app-muted">Personal Dive Value is contextual, not an official score. Bars show the available chronology; cards surface the strongest historical signals.</p></div><span className="text-xs text-app-muted">{rows.length} eligible attempts</span></div><div className="grid gap-5 p-4 lg:grid-cols-[1.1fr_.9fr]"><div className="min-w-0"><div className="flex h-32 items-end gap-1 border-b border-app pb-2" role="img" aria-label={`Personal Dive Value history for ${rows.length} attempts. Values range from ${Math.min(...rows.map((row) => row.value.value || 0)).toFixed(0)} to ${Math.max(...rows.map((row) => row.value.value || 0)).toFixed(0)}.`}>{rows.map(({ value, attempt }) => <button key={attempt.id} type="button" aria-label={`${format(parseISO(attempt.dive_datetime), 'd MMM yyyy')}: Personal Dive Value ${value.value}, ${value.primary_signal || 'emerging'}`} onClick={(event) => onOpen(attempt, event.currentTarget)} className="group min-w-2 flex-1 border-0 bg-transparent p-0"><span className="block w-full bg-app-accent/75 transition-colors group-hover:bg-app-accent" style={{ height: `${Math.max(5, value.value || 0)}%` }} /></button>)}</div><div className="mt-2 flex justify-between text-[11px] text-app-muted"><span>{format(parseISO(rows[0].attempt.dive_datetime), 'd MMM yyyy')}</span><span>Personal Dive Value / 100</span><span>{format(parseISO(rows[rows.length - 1].attempt.dive_datetime), 'd MMM yyyy')}</span></div></div><ol className="grid gap-2" aria-label="Notable Personal Dive Value attempts">{notable.map(({ value, attempt }, index) => <li key={attempt.id}><button type="button" onClick={(event) => onOpen(attempt, event.currentTarget)} className="touch-target flex w-full items-center justify-between gap-3 border border-app bg-app-panel-elevated px-3 text-left"><div><span className="text-xs text-app-muted">{index === 0 ? 'Most notable in this view' : value.primary_signal || 'Historical signal'}</span><div className="mt-1 text-sm font-medium text-app-text">{format(parseISO(attempt.dive_datetime), 'd MMM yyyy')} · execution {attempt.performance_numeric.toFixed(1)} · DD {attempt.official_dd?.toFixed(1) || '—'}</div></div><div className="text-right"><div className="text-lg font-semibold tabular-nums text-app-text">{value.value}</div><div className="text-[11px] text-app-muted">{value.confidence.level}</div></div></button></li>)}</ol></div></section>
}

export default function DiveAnalysis() {
  const { diveCode = '' } = useParams(), navigate = useNavigate(), [searchParams, setSearchParams] = usePreservedSearchParams()
  const [data, setData] = useState<AnalysisData | null>(null), [divers, setDivers] = useState<Diver[]>([]), [periods, setPeriods] = useState<TrainingPeriod[]>([])
  const [representatives, setRepresentatives] = useState<RepresentativeCard[]>([])
  const [personalValues, setPersonalValues] = useState<PersonalDiveValue[] | null>(null)
  const [loading, setLoading] = useState(true), [refreshing, setRefreshing] = useState(false), [error, setError] = useState<string | null>(null), [selected, setSelected] = useState<DiveAttempt | null>(null)
  const [contextDimension, setContextDimension] = useState<ContextDimension>('modifier'), [equivalentOnly, setEquivalentOnly] = useState(false), [codeInput, setCodeInput] = useState(diveCode.toUpperCase())
  const [filtersOpen, setFiltersOpen] = useState(() => window.matchMedia?.('(min-width: 640px)').matches ?? true)
  const returnFocus = useRef<Element | null>(null)
  const loadedDiveCode = useRef<string | null>(null)
  const dataFilterKey = useMemo(() => analysisFilterSearchKey(searchParams), [searchParams])
  const filters = useMemo(() => filtersFromSearchParams(new URLSearchParams(dataFilterKey)), [dataFilterKey])
  const chartView = ((searchParams.get('chart_view') as ChartView) || (data && data.summary.attempt_count > 120 ? 'session' : 'attempts')) as ChartView
  const phaseView = ((searchParams.get('phase_view') as ChartView) || 'attempts') as ChartView
  const splitBy = ((searchParams.get('split_by') as SplitMode) || 'none') as SplitMode

  useEffect(() => { Promise.all([getDivers(), getTrainingPeriods()]).then(([nextDivers, nextPeriods]) => { setDivers(nextDivers); setPeriods(nextPeriods) }).catch(() => undefined) }, [])
  useEffect(() => {
    let active = true
    const replacingDive = loadedDiveCode.current !== diveCode
    if (replacingDive) {
      // A route change is a different workspace, so never briefly show the
      // previous dive under the new code. Filter refreshes deliberately keep
      // the current workspace mounted.
      setData(null)
      setLoading(true)
    }
    else setRefreshing(true)
    getDiveAnalysis(diveCode, filters).then((result) => {
      if (active) {
        setData(result)
        loadedDiveCode.current = diveCode
        setError(null)
      }
    }).catch((reason) => { if (active) setError(reason.message) }).finally(() => {
      if (active) {
        setLoading(false)
        setRefreshing(false)
      }
    })
    return () => { active = false }
  }, [diveCode, dataFilterKey, filters])
  useEffect(() => {
    if (!data?.attempts.length) { setPersonalValues(null); return }
    const controller = new AbortController()
    getPersonalDiveValues(diveCode, Math.min(250, data.attempts.length), controller.signal)
      .then((result) => setPersonalValues(result.values))
      .catch(() => { if (!controller.signal.aborted) setPersonalValues(null) })
    return () => controller.abort()
  }, [diveCode, data?.attempts.length, dataFilterKey])
  useEffect(() => {
    let active = true
    const params = new URLSearchParams()
    params.set('dive_code', diveCode.toUpperCase())
    if (filters.diver_scope === 'all') params.set('diver_scope', 'all')
    if (filters.diver_scope === 'selected' && filters.diver_ids?.[0]) params.set('diver_id', String(filters.diver_ids[0]))
    const refresh = () => getRepresentatives(params)
      .then((result) => { if (active) setRepresentatives(result.dives[0]?.representatives || []) })
      .catch(() => { if (active) setRepresentatives([]) })
    refresh()
    // Keep the small representative panel aligned with asynchronous cache finalization.
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') refresh()
    }, 30_000)
    return () => { active = false; window.clearInterval(timer) }
  }, [diveCode, filters.diver_scope, filters.diver_ids])
  useEffect(() => {
    if (!data || selected) return
    const attemptId = Number(searchParams.get('attempt'))
    if (!attemptId) return
    const attempt = data.attempts.find((item) => item.id === attemptId)
    if (attempt) setSelected(attempt)
  }, [data, searchParams, selected])

  const updateFilter = (key: string, value?: string | boolean) => { const next = new URLSearchParams(searchParams); value === undefined || value === '' ? next.delete(key) : next.set(key, String(value)); setSearchParams(next) }
  const updateMulti = (key: string, values: Array<string | number>) => { const next = new URLSearchParams(searchParams); next.delete(key); values.filter(Boolean).forEach((value) => next.append(key, String(value))); setSearchParams(next) }
  const toggleModifier = (modifier: string) => { const values = new Set(searchParams.getAll('modifiers')); values.has(modifier) ? values.delete(modifier) : values.add(modifier); updateMulti('modifiers', [...values]) }
  const setPeriod = (months: number) => { const end = new Date(), next = new URLSearchParams(searchParams); next.set('date_from', dateInput(subMonths(end, months))); next.set('date_to', dateInput(end)); setSearchParams(next) }
  const openAttempt = (attempt: DiveAttempt, trigger: Element) => { returnFocus.current = trigger; setSelected(attempt) }
  const setChartParam = (key: string, value: string) => { const next = new URLSearchParams(searchParams); value === 'none' || value === '' ? next.delete(key) : next.set(key, value); setSearchParams(next) }

  const attempts = data?.attempts || []
  const readyCount = attempts.filter((attempt) => attempt.media.status === 'ready').length
  const timelinePoints = attempts.map(buildTimelinePoint)
  const comparisonRows = data?.breakdowns[contextDimension] || []
  const heightCounts = countBy(attempts.map((attempt) => attempt.height))
  const positionCounts = countBy(attempts.map((attempt) => divePositionName(attempt.position, attempt.dive_code)))
  const syncCounts = countBy(attempts.map((attempt) => attempt.is_sync ? 'SYNC' : 'Individual'))
  const modifierCounts = countBy(attempts.flatMap((attempt) => attempt.modifiers.length ? attempt.modifiers : ['No modifier']))
  const heights = unique(attempts.map((attempt) => attempt.height))
  const positions = unique(attempts.map((attempt) => divePositionName(attempt.position, attempt.dive_code)))
  const syncStates = unique(attempts.map((attempt) => attempt.is_sync ? 'SYNC' : 'Individual'))
  const periodsSelected = filters.training_period_ids?.length ? `${filters.training_period_ids.length} period${filters.training_period_ids.length > 1 ? 's' : ''}` : 'All periods'
  const diverScopeText = filters.diver_scope === 'all' ? 'All divers' : filters.diver_scope === 'selected' ? `${filters.diver_ids?.length || 0} selected diver${filters.diver_ids?.length === 1 ? '' : 's'}` : 'My dives'
  const dateRange = `${filters.date_from || (data?.sample.first_attempt_at ? format(parseISO(data.sample.first_attempt_at), 'yyyy-MM-dd') : 'first')} to ${filters.date_to || (data?.sample.last_attempt_at ? format(parseISO(data.sample.last_attempt_at), 'yyyy-MM-dd') : 'latest')}`
  const contextText = data ? `${data.dive_code} · ${diverScopeText} · ${data.summary.attempt_count} attempts · ${data.summary.session_count} sessions · ${heights.length === 1 ? heights[0] : `${heights.length || 0} heights`} · ${positions.length === 1 ? positions[0] : `${positions.length || 0} positions`} · ${syncStates.join(' + ') || 'Any context'} · ${filters.weighting === 'sessions' ? 'session-weighted' : 'attempt-weighted'}` : ''
  const mixedContext = attempts.length > 0 && (heights.length > 1 || positions.length > 1 || syncStates.length > 1 || Object.keys(modifierCounts).length > 1)

  return <div className="mx-auto w-full max-w-[1480px] space-y-6">
    <header className="flex flex-col gap-4 border-b border-app pb-5 md:flex-row md:items-end md:justify-between"><div><div className="flex items-center gap-3"><h1 className="text-3xl font-semibold tracking-tight text-app-text">{diveCode.toUpperCase()}</h1><span className="text-sm text-app-muted">Per-dive intelligence</span></div><p className="mt-2 text-sm text-app-muted" aria-live="polite">{data?.sample.attempt_count ?? 0} attempts in {data?.sample.session_count ?? 0} sessions · {readyCount} cached clips · {dateRange}</p></div><form className="flex gap-2" onSubmit={(event) => { event.preventDefault(); navigate(`/dives/analysis/${codeInput.trim().toUpperCase()}?${searchParams}`) }}><label className="sr-only" htmlFor="analysis-code">Dive code</label><input id="analysis-code" value={codeInput} onChange={(event) => setCodeInput(event.target.value)} className="app-input w-32 uppercase" /><button className="border border-app-accent bg-transparent text-sm text-app-accent">Analyze</button></form></header>

    {data && <section className="sticky top-14 z-20 border border-app bg-app/95 p-3 shadow-[0_12px_28px_rgba(0,0,0,.22)] backdrop-blur lg:top-0" aria-label="Active analytical context"><div className="flex flex-wrap items-center gap-2 sm:gap-3"><p className="mr-auto min-w-0 text-sm font-medium text-app-text">{contextText}</p><span className="hidden text-xs text-app-muted sm:inline">{periodsSelected}</span><button type="button" onClick={() => setSearchParams(new URLSearchParams())} className="touch-target inline-flex items-center gap-2 border border-app bg-transparent px-3 py-1.5 text-xs text-app-muted"><RotateCcw className="h-3.5 w-3.5" />Reset</button><a href="#filters" className="touch-target inline-flex items-center gap-2 border border-app bg-transparent px-3 py-1.5 text-xs text-app-muted"><SlidersHorizontal className="h-3.5 w-3.5" />Filters</a><button type="button" onClick={() => navigator.clipboard?.writeText(window.location.href)} className="touch-target inline-flex items-center gap-2 border border-app bg-transparent px-3 py-1.5 text-xs text-app-muted"><Copy className="h-3.5 w-3.5" />Link</button></div></section>}

    <section id="filters" className="border border-app bg-app-panel p-4" aria-label="Analysis filters"><div className="flex items-center justify-between gap-3 sm:hidden"><div><h2 className="font-semibold text-app-text">Analysis filters</h2><p className="mt-1 text-xs text-app-muted">Refine the dive history and comparison context.</p></div><button type="button" aria-expanded={filtersOpen} onClick={() => setFiltersOpen((open) => !open)} className="touch-target border border-app px-3 text-sm text-app-muted">{filtersOpen ? 'Hide' : 'Edit'}</button></div><div className={`${filtersOpen ? 'mt-4 block' : 'hidden'} sm:mt-0 sm:block`}><div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8">
      <label className="text-xs text-app-muted">Date from<input type="date" value={searchParams.get('date_from') || ''} onChange={(event) => updateFilter('date_from', event.target.value)} className="app-input mt-1 w-full text-sm" /></label><label className="text-xs text-app-muted">Date to<input type="date" value={searchParams.get('date_to') || ''} onChange={(event) => updateFilter('date_to', event.target.value)} className="app-input mt-1 w-full text-sm" /></label>
      <label className="text-xs text-app-muted">Height<select value={filters.height || ''} onChange={(event) => updateFilter('height', event.target.value)} className="app-input mt-1 w-full text-sm"><option value="">All</option>{['1m', '3m', '5m', '7m', '10m'].map((value) => <option key={value}>{value}</option>)}</select></label><label className="text-xs text-app-muted">Position<select value={filters.position || ''} onChange={(event) => updateFilter('position', event.target.value)} className="app-input mt-1 w-full text-sm"><option value="">All positions</option>{Object.entries(DIVE_POSITION_NAMES).map(([code, name]) => <option key={code} value={code}>{name}</option>)}</select></label>
      <label className="text-xs text-app-muted">SYNC<select value={searchParams.get('is_sync') || ''} onChange={(event) => updateFilter('is_sync', event.target.value)} className="app-input mt-1 w-full text-sm"><option value="">Any</option><option value="false">Individual</option><option value="true">SYNC</option></select></label><label className="text-xs text-app-muted">Modifier match<select value={filters.modifier_mode} onChange={(event) => updateFilter('modifier_mode', event.target.value)} className="app-input mt-1 w-full text-sm"><option value="any">Any selected</option><option value="all">All selected</option><option value="none">No modifiers</option></select></label>
      <label className="text-xs text-app-muted">Diver scope<select value={filters.diver_scope || 'self'} onChange={(event) => { const next = new URLSearchParams(searchParams); next.delete('diver_ids'); event.target.value === 'self' ? next.delete('diver_scope') : next.set('diver_scope', event.target.value); setSearchParams(next) }} className="app-input mt-1 w-full text-sm"><option value="self">My dives</option><option value="all">All divers</option><option value="selected">Selected divers</option></select></label>
      <label className="text-xs text-app-muted">Selected divers<select multiple disabled={filters.diver_scope !== 'selected'} value={(filters.diver_ids || []).map(String)} onChange={(event) => updateMulti('diver_ids', [...event.currentTarget.selectedOptions].map((option) => option.value))} className="app-input mt-1 h-20 w-full text-sm disabled:opacity-45">{divers.map((diver) => <option key={diver.id} value={diver.id}>{diver.display_name}{diver.is_primary_user ? ' (primary)' : ''}</option>)}</select></label>
      <label className="text-xs text-app-muted">Training period<select multiple value={(filters.training_period_ids || []).map(String)} onChange={(event) => updateMulti('training_period_ids', [...event.currentTarget.selectedOptions].map((option) => option.value))} className="app-input mt-1 h-20 w-full text-sm"><option value="">All periods</option>{periods.map((period) => <option key={period.id} value={period.id}>{period.name}</option>)}</select></label>
    </div><div className="mt-4 flex flex-wrap items-center gap-2 border-t border-app pt-4">{MODIFIERS.map((modifier) => <button type="button" aria-pressed={filters.modifiers?.includes(modifier)} key={modifier} onClick={() => toggleModifier(modifier)} className={`touch-target border px-3 py-1.5 text-sm ${filters.modifiers?.includes(modifier) ? 'border-app-accent text-app-accent' : 'border-app bg-transparent text-app-muted'}`}>{modifier}</button>)}<span className="mx-2 h-5 border-l border-app" /><button type="button" onClick={() => setPeriod(3)} className="touch-target border border-app bg-transparent px-3 py-1.5 text-sm text-app-muted">Last 3 months</button><button type="button" onClick={() => setPeriod(6)} className="touch-target border border-app bg-transparent px-3 py-1.5 text-sm text-app-muted">Last 6 months</button><label className="ml-2 flex items-center gap-2 text-sm text-app-muted">Weighting<select aria-label="Analysis weighting" value={filters.weighting} onChange={(event) => updateFilter('weighting', event.target.value)} className="app-input py-1.5 text-sm"><option value="attempts">By attempts</option><option value="sessions">By session medians</option></select></label><button type="button" onClick={() => setSearchParams(new URLSearchParams())} className="ml-auto flex items-center gap-2 border-0 bg-transparent px-2 text-sm text-app-muted"><RotateCcw className="h-4 w-4" /> Reset filters</button></div><p className="mt-3 text-xs text-app-muted">Attempt weighting gives every repetition equal influence. Session weighting gives each session median equal influence.</p></div></section>

    {loading && !data && <div className="border-y border-app py-20 text-center text-sm text-app-muted" role="status">Calculating filtered history...</div>}
    {refreshing && data && <div className="sticky top-0 z-30 border border-app-accent/40 bg-app-panel/95 px-4 py-2 text-center text-xs text-app-muted backdrop-blur" role="status">Updating this analysis without leaving your place…</div>}
    {error && <div className="border border-red-900/60 bg-red-950/30 p-4 text-sm text-red-300" role="alert">{error}</div>}
    {data && <>
      <section className="grid gap-4 xl:grid-cols-[1.05fr_.95fr]"><div className="border border-app bg-app-panel p-5"><h2 className="font-semibold text-app-text">What changed</h2><div className="mt-4 grid gap-3 sm:grid-cols-2">{data.insights.slice(0, 4).map((insight, index) => <div key={`${insight.type}-${index}`} className="border-l border-app-accent/70 bg-app-panel-elevated px-4 py-3"><div className="flex items-center justify-between gap-4"><h3 className="text-sm font-semibold text-app-text">{insight.title}</h3><span className="text-[11px] text-app-muted">{SAMPLE_LABELS[insight.confidence] || insight.confidence}</span></div><p className="mt-1 text-sm leading-6 text-app-muted">{insight.message}</p></div>)}</div></div><div className="border border-app bg-app-panel p-5"><h2 className="font-semibold text-app-text">{mixedContext ? 'Mixed comparison context' : 'Equivalent context'}</h2><p className="mt-2 text-sm leading-6 text-app-muted">{mixedContext ? 'This view combines conditions. Use the split control to compare groups before reading the overall trend as one story.' : 'The active filters describe one main context, so combined trend and summary metrics are easier to compare.'}</p><div className="mt-4 grid grid-cols-2 gap-3 text-sm"><div><div className="text-xs text-app-muted">Heights</div><div className="mt-1 text-app-text">{Object.entries(heightCounts).map(([k, v]) => `${k} ${v}`).join(' · ') || '-'}</div></div><div><div className="text-xs text-app-muted">Positions</div><div className="mt-1 text-app-text">{Object.entries(positionCounts).map(([k, v]) => `${k} ${v}`).join(' · ') || '-'}</div></div><div><div className="text-xs text-app-muted">Context</div><div className="mt-1 text-app-text">{Object.entries(syncCounts).map(([k, v]) => `${k} ${v}`).join(' · ') || '-'}</div></div><div><div className="text-xs text-app-muted">Modifiers</div><div className="mt-1 text-app-text">{Object.entries(modifierCounts).slice(0, 4).map(([k, v]) => `${k} ${v}`).join(' · ') || '-'}</div></div></div><div className="mt-4 flex flex-wrap gap-2"><button type="button" onClick={() => setChartParam('split_by', 'height')} className="border border-app bg-transparent px-3 py-1.5 text-xs text-app-muted">Split by height</button><button type="button" onClick={() => updateFilter('is_sync', 'false')} className="border border-app bg-transparent px-3 py-1.5 text-xs text-app-muted">Individual only</button><button type="button" onClick={() => setChartParam('split_by', 'position')} className="border border-app bg-transparent px-3 py-1.5 text-xs text-app-muted">Split by position</button></div></div></section>

      <section className="grid border-y border-app sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-7" aria-label="Headline metrics">{[
        ['Attempts', `${data.summary.attempt_count} attempts`, `${data.summary.session_count} sessions · ${data.summary.scored_attempt_count} scored`],
        ['Median', scoreText(data.summary.median), `${deltaText(data.summary.median, data.comparison.previous?.median)} · avg ${scoreText(data.summary.average)}`],
        ['Consistency', `IQR ${scoreText(data.summary.iqr)}`, `${deltaText(data.summary.iqr, data.comparison.previous?.iqr)} · ${data.summary.iqr != null && data.summary.iqr >= 2 ? 'High variability' : 'Tighter spread'}`],
        ['Success', percentageText(data.summary.success_rate), `${data.summary.success_rate == null ? '-' : Math.round((data.summary.success_rate / 100) * data.summary.scored_attempt_count)} of ${data.summary.scored_attempt_count} · threshold ${data.summary.success_threshold}`],
        ['Difficulty context', `DD ${scoreText(data.summary.average_dd)}`, `${percentageText(data.summary.dd_coverage_rate)} coverage · execution remains /10`],
        ['Best attempt', scoreText(data.summary.maximum), data.summary.best_attempt_id ? `View attempt ${data.summary.best_attempt_id}` : '-'],
        ['Performance level', data.trend.direction.replace(/_/g, ' '), `${SAMPLE_LABELS[data.trend.confidence] || data.trend.confidence} · ${data.trend.reason || 'Median movement is guarded by sample size and spread.'}`],
      ].map(([term, value, note]) => <div key={term} className="border-b border-app p-4 sm:border-r xl:border-b-0"><div className="text-xs text-app-muted">{term}</div><div className="mt-2 text-xl font-semibold capitalize text-app-text">{value}</div><div className="mt-1 text-xs leading-5 text-app-muted">{note}</div></div>)}</section>

      {personalValues && <PersonalValueHistory values={personalValues} attempts={data.attempts} onOpen={openAttempt} />}

      {representatives.length > 0 && <section className="border border-app bg-app-panel"><div className="flex flex-wrap items-center justify-between gap-3 border-b border-app px-5 py-4"><div><h2 className="font-semibold text-app-text">Representative attempts</h2><p className="mt-1 text-xs text-app-muted">Low, typical, and high examples selected from the recorded score distribution.</p></div><Link to={`/media/representatives?dive_code=${encodeURIComponent(data.dive_code)}`} className="touch-target inline-flex items-center text-sm text-app-accent">Open representative gallery</Link></div><div className="grid gap-4 p-4 lg:grid-cols-3">{['low', 'median', 'high'].map((role) => {
        const rep = representatives.find((item) => item.role === role)
        if (!rep) return <div key={role} className="border border-app p-4 text-sm text-app-muted">No {role === 'median' ? 'Typical' : role} representative selected.</div>
        const linkedAttempt = data.attempts.find((item) => item.id === rep.attempt.id)
        return <article key={role} className="border border-app bg-app-panel-elevated"><div className="flex items-start justify-between gap-3 border-b border-app px-4 py-3"><div><h3 className="font-semibold text-app-text">{rep.label}</h3><p className="mt-1 text-xs text-app-muted">Selected from the recorded score distribution</p></div><span className="text-xs text-app-muted">{rep.media.state.replace(/_/g, ' ')}</span></div>{rep.media.poster_url ? <img src={rep.media.poster_url} alt={`${data.dive_code} ${rep.label} representative poster`} className="aspect-video w-full object-cover" /> : <div className="flex aspect-video items-center justify-center bg-black/35 text-xs text-app-muted">No poster ready</div>}<div className="space-y-3 p-4 text-sm"><div><div className="text-xl font-semibold text-app-text">{rep.attempt.score_10.toFixed(1)} <span className="text-sm font-normal text-app-muted">/ {rep.attempt.performance}</span></div><div className="mt-1 text-app-muted">{format(parseISO(rep.attempt.dive_datetime), 'd MMM yyyy')} · {rep.attempt.height} · {rep.attempt.is_sync ? 'SYNC' : 'Individual'}</div></div>{rep.media.failure && <p className="text-xs leading-5 text-red-300">{rep.media.failure.message}</p>}<div className="flex flex-wrap gap-2">{rep.media.playback_url && <a href={rep.media.playback_url} className="touch-target inline-flex items-center border border-app-accent px-3 py-1.5 text-xs text-app-accent">Play</a>}<button type="button" onClick={(event) => linkedAttempt ? openAttempt(linkedAttempt, event.currentTarget) : navigate(`/dives/analysis/${data.dive_code}?attempt=${rep.attempt.id}`)} className="touch-target border border-app px-3 py-1.5 text-xs text-app-muted">Open attempt</button>{rep.replacement.available && <Link to={`/media/representatives?dive_code=${encodeURIComponent(data.dive_code)}&selection_band=${rep.role}`} className="touch-target inline-flex items-center border border-app px-3 py-1.5 text-xs text-app-muted">Find replacement</Link>}</div></div></article>
      })}</div></section>}

      <section className="border border-app bg-app-panel"><div className="flex flex-col gap-3 border-b border-app px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5"><div><h2 className="font-semibold text-app-text">Progression</h2><p className="mt-1 text-xs text-app-muted">{chartView === 'range' ? 'Each vertical range shows the lowest and highest score in an adaptive time period, with a dot for that period’s median.' : chartView === 'session' ? 'Session summary is selected for dense data; switch to all attempts for point-by-point review.' : 'All attempts are visible as scatter points. The line is only the rolling five-attempt median.'} This chart intentionally remains execution /10; use the DD context card when heights or difficulty vary.</p></div><div className="grid grid-cols-2 gap-3 text-xs sm:flex sm:flex-wrap sm:gap-2"><label className="text-app-muted">View<select aria-label="Chart view" value={chartView} onChange={(event) => setChartParam('chart_view', event.target.value)} className="app-input mt-1 w-full py-1 text-xs sm:ml-2 sm:mt-0 sm:w-auto"><option value="session">Session summary</option><option value="range">Performance range</option><option value="attempts">All attempts</option></select></label><label className="text-app-muted">Split by<select aria-label="Split progression by" value={splitBy} onChange={(event) => setChartParam('split_by', event.target.value)} className="app-input mt-1 w-full py-1 text-xs sm:ml-2 sm:mt-0 sm:w-auto"><option value="none">None</option><option value="height">Height</option><option value="position">Position</option><option value="modifier">Modifier</option><option value="sync">SYNC</option><option value="diver">Diver</option></select></label></div></div><div className="px-3 pb-5 pt-3 sm:px-4"><PointTimeline points={timelinePoints} label={chartView === 'range' ? 'Performance range by period' : 'Attempt score progression over time'} selectedId={selected?.id} view={chartView} splitBy={splitBy} onSelect={(id, trigger) => { const attempt = data.attempts.find((item) => item.id === id); if (attempt) openAttempt(attempt, trigger) }} /><p className="mt-4 text-sm leading-6 text-app-muted">Text summary: scores range from {scoreText(data.summary.minimum)} to {scoreText(data.summary.maximum)}, median {scoreText(data.summary.median)}, with {data.summary.iqr != null && data.summary.iqr >= 2 ? 'wide' : 'moderate'} spread across {data.summary.attempt_count} attempts.</p></div></section>

      <section className="border border-app bg-app-panel p-4 sm:p-5"><h2 className="font-semibold text-app-text">Period comparison</h2>{data.comparison.previous ? <PeriodComparison current={data.summary} previous={data.comparison.previous} /> : <div className="mt-8 text-sm text-app-muted"><CalendarRange className="mb-3 h-5 w-5" />Choose a bounded date range to compare it with the preceding period of equal duration.</div>}</section>

      <div className="grid min-w-0 gap-6 xl:grid-cols-[.9fr_1.1fr]"><section className="min-w-0 border border-app bg-app-panel p-4 sm:p-5"><h2 className="font-semibold text-app-text">Score distribution</h2><Distribution attempts={data.attempts} /></section><section className="min-w-0 border border-app bg-app-panel"><div className="flex flex-wrap items-center gap-3 border-b border-app px-4 py-4 sm:gap-4 sm:px-5"><div className="mr-auto"><h2 className="font-semibold text-app-text">Context breakdown</h2><p className="mt-1 text-xs text-app-muted">Separate populations, sorted by sample size. Small samples are descriptive only.</p></div>{DIMENSIONS.map((dimension) => <button type="button" key={dimension} aria-pressed={contextDimension === dimension} onClick={() => setContextDimension(dimension)} className={`touch-target border-0 bg-transparent px-1 py-1 text-sm capitalize ${contextDimension === dimension ? 'text-app-accent' : 'text-app-muted'}`}>{dimension.replace('_', ' ')}</button>)}<label className="flex items-center gap-2 text-xs text-app-muted"><input type="checkbox" checked={equivalentOnly} onChange={(event) => setEquivalentOnly(event.target.checked)} /> Equivalent contexts only</label></div>{equivalentOnly && <div className="border-b border-app px-5 py-3 text-xs text-app-muted">Constraints applied from active filters: height, position, platform, SYNC and selected modifier context.</div>}<ContextBreakdown rows={comparisonRows} /></section></div>

      <section aria-labelledby="phase-heading"><div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between"><div><h2 id="phase-heading" className="font-semibold text-app-text">Phase analysis</h2><p className="mt-1 text-xs text-app-muted">Existing phase labels are preserved; missing ratings are not treated as zero.</p></div><div className="flex items-end justify-between gap-3 sm:justify-end"><span className="text-xs text-app-muted">{data.phases.total_attempts} total attempts</span><label className="text-xs text-app-muted">View<select aria-label="Phase chart view" value={phaseView} onChange={(event) => setChartParam('phase_view', event.target.value)} className="app-input mt-1 block w-full py-1 text-xs sm:w-auto"><option value="attempts">All attempts</option><option value="session">Session summary</option><option value="range">Performance range</option></select></label></div></div><div className="grid gap-6 lg:grid-cols-2"><PhasePanel name="Phase 1" phase={data.phases.phases.phase1} attempts={data.attempts} view={phaseView} /><PhasePanel name="Phase 2" phase={data.phases.phases.phase2} attempts={data.attempts} view={phaseView} /></div></section>

      <section className="border border-app bg-app-panel"><div className="border-b border-app px-4 py-4 sm:px-5"><h2 className="font-semibold text-app-text">Attempts to review</h2><p className="mt-1 text-xs text-app-muted">Keyboard-accessible source list for every aggregate above.</p></div><div className="grid gap-2 p-3 sm:hidden">{[...data.attempts].reverse().map((attempt) => <button key={attempt.id} type="button" onClick={(event) => openAttempt(attempt, event.currentTarget)} className="touch-target border border-app bg-app-panel-elevated p-3 text-left"><div className="flex items-start justify-between gap-3"><div><div className="font-semibold text-app-text">{attempt.performance_numeric.toFixed(1)} <span className="font-normal text-app-muted">/ {attempt.performance}</span></div><p className="mt-1 text-xs text-app-muted">{format(parseISO(attempt.dive_datetime), 'd MMM yyyy')} · {attempt.height} · {attempt.is_sync ? 'SYNC' : 'Individual'}</p></div><span className={`text-xs ${attempt.media.status === 'ready' ? 'text-app-accent' : 'text-app-muted'}`}>{attempt.media.status.replace(/_/g, ' ')}</span></div><p className="mt-2 truncate text-xs text-app-muted">{attempt.modifiers.join(', ') || 'No modifiers'} · {attempt.diver?.display_name || 'Unassigned'}</p></button>)}</div><div className="hidden overflow-x-auto sm:block"><table className="w-full min-w-[940px] text-left text-sm"><thead className="text-xs text-app-muted"><tr>{['Date', 'Score', 'Phases', 'Height', 'Modifiers', 'Context', 'Diver', 'Period', 'Media'].map((heading) => <th key={heading} className="border-b border-app px-4 py-3 font-medium">{heading}</th>)}</tr></thead><tbody>{[...data.attempts].reverse().map((attempt) => <tr key={attempt.id} tabIndex={0} onClick={(event) => openAttempt(attempt, event.currentTarget)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openAttempt(attempt, event.currentTarget) } }} className="cursor-pointer border-b border-app hover:bg-app-panel-elevated focus:bg-app-panel-elevated focus:outline-none"><td className="px-4 py-3 text-app-text">{format(parseISO(attempt.dive_datetime), 'd MMM yyyy')}</td><td className="px-4 py-3 font-semibold text-app-text">{attempt.performance_numeric.toFixed(1)} <span className="font-normal text-app-muted">/ {attempt.performance}</span></td><td className="px-4 py-3 text-app-muted">{attempt.phase1_performance && attempt.phase2_performance ? `${attempt.phase1_performance} / ${attempt.phase2_performance}` : '-'}</td><td className="px-4 py-3 text-app-text">{attempt.height}</td><td className="px-4 py-3 text-app-muted">{attempt.modifiers.join(', ') || '-'}</td><td className="px-4 py-3 text-app-muted">{attempt.is_sync ? 'SYNC' : 'Individual'}</td><td className="px-4 py-3 text-app-muted">{attempt.diver?.display_name || 'Unassigned'}</td><td className="px-4 py-3 text-app-muted">{attempt.training_periods.map((period) => period.name).join(', ') || '-'}</td><td className="px-4 py-3"><span className={`inline-flex items-center gap-2 ${attempt.media.status === 'ready' ? 'text-app-accent' : ACTIVE_MEDIA.has(attempt.media.status) ? 'text-amber-300' : 'text-app-muted'}`}><Film className="h-4 w-4" />{attempt.media.status.replace(/_/g, ' ')}</span></td></tr>)}</tbody></table></div>{!data.attempts.length && <div className="p-8 text-center text-sm text-app-muted">No attempts match these filters. Try removing a modifier or extending the date range.</div>}</section>
      <div className="text-right text-[11px] text-app-muted">Analytics {data.analytics_version} · {data.observability.cache} · {data.observability.total_ms.toFixed(1)} ms</div>
    </>}
    {selected && data && <AttemptDrawer attempt={selected} attempts={data.attempts} onClose={() => setSelected(null)} onMove={setSelected} returnFocus={returnFocus} />}
  </div>
}
