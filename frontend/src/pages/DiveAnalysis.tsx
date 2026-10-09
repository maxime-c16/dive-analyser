import { useModalOverlay } from '../utils/overlays'
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, CalendarRange, ChevronDown, ChevronLeft, ChevronRight, Copy, Film, RotateCcw, X } from 'lucide-react'
import { differenceInCalendarDays, format, parseISO, subMonths } from 'date-fns'
import SendDiveButton from '../components/messages/SendDiveButton'
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
import { useAuth } from '../contexts/AuthContext'
import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
import { appLocale } from '../utils/dateLocale'
import { confidenceLevelLabel, signalLabel } from '../utils/personalValue'
import { mediaStatusLabel } from '../utils/mediaStatus'
import { DIVE_POSITION_CODES, divePositionName } from '../utils/divePosition'
import { platformTypeName } from '../utils/attemptPresentation'

const MODIFIERS = ['DB', 'SD', 'HU']
const DIMENSIONS: ContextDimension[] = ['modifier', 'height', 'position', 'sync', 'diver', 'training_period']
const ACTIVE_MEDIA = new Set(['queued', 'waiting_for_mac', 'claimed', 'materializing', 'exporting', 'transcoding', 'uploading', 'verifying'])

/**
 * Sample-size labels; resolved in the active language at render time.
 */
const SAMPLE_LABEL_KEYS: Record<string, string> = { no_data: 'noData', insufficient: 'insufficient', exploratory: 'exploratory', moderate_sample: 'moderateSample', stronger_descriptive_sample: 'strongerSample' }
const sampleLabel = (value: string) => i18n.t(`analysis.sample.${SAMPLE_LABEL_KEYS[value] ?? 'noData'}`)
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

export function filtersFromSearchParams(
  params: URLSearchParams,
  defaultScope: DiveAnalysisFilters['diver_scope'] = 'self',
): DiveAnalysisFilters {
  return {
    date_from: params.get('date_from') || undefined,
    date_to: params.get('date_to') || undefined,
    height: params.get('height') || undefined,
    platform_type: params.get('platform_type') || undefined,
    position: params.get('position') || undefined,
    modifiers: params.getAll('modifiers'),
    modifier_mode: (params.get('modifier_mode') as DiveAnalysisFilters['modifier_mode']) || 'any',
    is_sync: params.has('is_sync') ? params.get('is_sync') === 'true' : undefined,
    diver_scope: (params.get('diver_scope') as DiveAnalysisFilters['diver_scope']) || (params.has('diver_ids') ? 'selected' : defaultScope),
    diver_ids: params.getAll('diver_ids').map(Number).filter(Number.isFinite),
    training_period_ids: params.getAll('training_period_ids').map(Number).filter(Number.isFinite),
    success_threshold: (params.get('success_threshold') as 'M' | 'G' | 'P') || 'G',
    weighting: (params.get('weighting') as 'attempts' | 'sessions') || 'attempts',
  }
}

/**
 * UI-U7 selected-attempt contract.
 *
 * `?attempt=<id>` identifies the reviewed clip that opened this Analysis
 * page. It is presentation-only context: it selects labels and the return
 * destination, never scientific computation. Only a positive integer that
 * resolves to an attempt in the loaded code-level result is honored;
 * anything else is treated as absent (never associated with a wrong clip).
 */
export function parseAttemptParam(value: string | null): number | null {
  if (value == null || !/^[1-9][0-9]*$/.test(value.trim())) return null
  const id = Number(value.trim())
  return Number.isSafeInteger(id) ? id : null
}

/**
 * UI-U7 progressive disclosure: one collapsible analysis section.
 * Collapsed content is not mounted until opened, so secondary charts never
 * cost render time on the first screen.
 */
function AnalysisSection({ id, title, caption, defaultOpen = false, children }: { id: string; title: string; caption?: string; defaultOpen?: boolean; children: React.ReactNode }) {
  const [open, setOpen] = useState(defaultOpen)
  const panelId = `analysis-section-panel-${id}`
  const buttonId = `analysis-section-button-${id}`
  return <section aria-labelledby={buttonId} className="border border-app bg-app-panel">
    <h2>
      <button type="button" id={buttonId} aria-expanded={open} aria-controls={panelId} onClick={() => setOpen((value) => !value)} className="touch-target flex w-full items-center justify-between gap-3 px-4 py-3 text-left sm:px-5">
        <span className="min-w-0"><span className="font-semibold text-app-text">{title}</span>{caption && <span className="mt-1 block text-xs font-normal leading-5 text-app-muted">{caption}</span>}</span>
        <ChevronDown aria-hidden="true" className={`h-4 w-4 shrink-0 text-app-muted transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
    </h2>
    {open && <div id={panelId} className="border-t border-app p-4 sm:p-5">{children}</div>}
  </section>
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
  if (current == null || previous == null) return i18n.t('analysis.previousUnavailable')
  const delta = current - previous
  if (Math.abs(delta) < 0.05) return `${i18n.t('analysis.noChange')}${suffix}`
  return `${delta > 0 ? '+' : ''}${delta.toFixed(1)}${suffix} ${i18n.t('analysis.vsPrevious')}`
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
    diver: attempt.diver?.display_name || i18n.t('analysis.unassigned'),
    mediaStatus: attempt.media.status,
    label: i18n.t('analysis.pointLabel', {
      date: format(parseISO(attempt.dive_datetime), 'd MMM yyyy, HH:mm', { locale: appLocale() }),
      score: `${attempt.performance_numeric.toFixed(1)} / ${attempt.performance}`,
      height: attempt.height,
      position: divePositionName(attempt.position, attempt.dive_code),
      modifiers: attempt.modifiers.join(', ') || i18n.t('analysis.noModifiers'),
      context: attempt.is_sync ? 'SYNC' : i18n.t('analysis.individual'),
      media: mediaStatusLabel(attempt.media.status),
    }),
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
      label: i18n.t('analysis.sessionLabel', {
        date: format(parseISO(midpoint.date), 'd MMM yyyy', { locale: appLocale() }),
        session: sessionId,
        min: ordered[0].score.toFixed(1),
        max: ordered[ordered.length - 1].score.toFixed(1),
        median: median.toFixed(1),
        attempts: sessionPoints.length,
      }),
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
      label: i18n.t('analysis.periodLabel', {
        start: format(periodStart, 'd MMM yyyy', { locale: appLocale() }),
        end: format(periodEnd, 'd MMM yyyy', { locale: appLocale() }),
        min: orderedByScore[0].score.toFixed(1),
        max: orderedByScore[orderedByScore.length - 1].score.toFixed(1),
        median: medianPoint.score.toFixed(1),
        attempts: periodPoints.length,
      }),
    }
  })
}

function groupPoints(points: TimelinePoint[], split: SplitMode) {
  if (split === 'none') return [{ label: i18n.t('analysis.combined'), points }]
  const grouped = new Map<string, TimelinePoint[]>()
  points.forEach((point) => {
    const labels = split === 'modifier'
      ? (point.modifiers.length ? point.modifiers : [i18n.t('analysis.noModifier')])
      : [split === 'height' ? point.height : split === 'position' ? divePositionName(point.position) : split === 'sync' ? (point.sync ? 'SYNC' : i18n.t('analysis.individual')) : point.diver]
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
  if (!visiblePoints.length) return <div className="flex h-64 items-center justify-center text-sm text-app-muted">{i18n.t('analysis.noScoredAttempts')}</div>
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
  // UI-U7 accessibility: when points are focusable labeled controls the svg
  // itself must not pose as one image (axe nested-interactive). The point
  // labels plus the text summary below carry the meaning instead. Read-only
  // timelines keep role="img" with their label.
  return <div ref={chartContainerRef} className="min-w-0">
    <div className="min-w-0">
      <svg ref={svgRef} viewBox={`0 0 ${width} ${height}`} className="block h-auto w-full" role={onSelect ? undefined : 'img'} aria-label={onSelect ? undefined : label} onClick={selectNearest} data-testid="attempt-progression-chart">
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
        {ticks.map((tick, index) => <g key={`${tick}-${index}`}><line x1={x(tick)} x2={x(tick)} y1={pad.top} y2={height - pad.bottom + 8} stroke="rgba(126,146,156,.12)" /><text x={x(tick)} y={height - 18} fill="#98a2aa" fontSize="11" textAnchor="middle">{format(new Date(tick), differenceInCalendarDays(new Date(maxTime), new Date(minTime)) > 365 ? 'MMM yyyy' : 'd MMM', { locale: appLocale() })}</text></g>)}
      </svg>
    </div>
    <div className="mt-3 flex flex-wrap gap-4 text-xs text-app-muted" aria-label={i18n.t('analysis.chartLegend')}>
      {rangeView ? <>
        <span className="inline-flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full bg-[#54beab]" />{i18n.t('analysis.legendMax')}</span>
        <span className="inline-flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full border-2 border-white/90 bg-[#54beab]" />{i18n.t('analysis.legendMedian')}</span>
        <span className="inline-flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full bg-[#8eafb0]" />{i18n.t('analysis.legendMin')}</span>
        <span>{i18n.t('analysis.legendRangeHint')}</span>
      </> : <>
        <span className="inline-flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full bg-[#54beab]" />{i18n.t('analysis.legendIndividual')}</span>
        <span className="inline-flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full bg-[#e3b15f]" />{i18n.t('analysis.legendSync')}</span>
        <span className="inline-flex items-center gap-2"><span className="h-0.5 w-8 rounded bg-[#8ed7ff]" />{i18n.t('analysis.legendRolling')}</span>
        <span className="inline-flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full border-2 border-white/90" />{i18n.t('analysis.legendReady')}</span>
      </>}
    </div>
  </div>
}

function Distribution({ attempts }: { attempts: DiveAttempt[] }) {
  const levels = [{ label: 'F', value: 0 }, { label: 'B', value: 2 }, { label: 'M', value: 4.5 }, { label: 'G', value: 7 }, { label: 'P', value: 10 }]
  const counts = levels.map((level) => ({ ...level, count: attempts.filter((item) => item.performance === level.label).length }))
  const maximum = Math.max(...counts.map((item) => item.count), 1)
  return <div className="grid min-h-56 min-w-0 grid-cols-5 items-end gap-1 pt-6 sm:min-h-64 sm:gap-4" aria-label={i18n.t('analysis.scoreDistribution')}>{counts.map((item) => <div key={item.label} className="flex min-w-0 flex-col items-center gap-2"><span className="text-xs tabular-nums text-app-muted">{item.count}</span><div className="w-full max-w-16 bg-app-panel-elevated" style={{ height: `${Math.max((item.count / maximum) * 168, item.count ? 5 : 0)}px` }} /><span className="text-base font-semibold text-app-text">{item.label}</span><span className="text-[11px] text-app-muted">{item.value}</span></div>)}</div>
}

function PeriodComparison({ current, previous }: { current: AnalysisData['summary']; previous: NonNullable<AnalysisData['comparison']['previous']> }) {
  const rows: Array<[string, string | number, string | number, string | number]> = [
    [i18n.t('analysis.attempts'), current.attempt_count, previous.attempt_count, current.attempt_count - previous.attempt_count],
    [i18n.t('analysis.sessionsLabel'), current.session_count, previous.session_count, current.session_count - previous.session_count],
    [i18n.t('analysis.median'), scoreText(current.median), scoreText(previous.median), deltaText(current.median, previous.median)],
    [i18n.t('dashboard.avgDD'), scoreText(current.average_dd), scoreText(previous.average_dd), deltaText(current.average_dd, previous.average_dd)],
    [i18n.t('analysis.average'), scoreText(current.average), scoreText(previous.average), deltaText(current.average, previous.average)],
    [i18n.t('analysis.iqr'), scoreText(current.iqr), scoreText(previous.iqr), deltaText(current.iqr, previous.iqr)],
    [i18n.t('analysis.success'), percentageText(current.success_rate), percentageText(previous.success_rate), current.success_rate != null && previous.success_rate != null ? `${(current.success_rate - previous.success_rate).toFixed(1)} ${i18n.t('analysis.points')}` : '-'],
  ]
  return <><div className="mt-4 grid gap-2 sm:hidden">{rows.map(([label, selected, earlier, change]) => <article key={label} className="grid grid-cols-[1fr_auto] gap-x-4 border border-app bg-app-panel-elevated p-3 text-sm"><span className="font-medium text-app-text">{label}</span><span className="font-semibold text-app-accent">{change}</span><span className="mt-2 text-xs text-app-muted">{i18n.t('analysis.selected')} {selected}</span><span className="mt-2 text-right text-xs text-app-muted">{i18n.t('analysis.previous')} {earlier}</span></article>)}</div><div className="mt-5 hidden min-w-0 gap-px overflow-x-auto text-sm sm:grid"><div className="grid min-w-[860px] grid-cols-4"><div className="p-3 text-app-muted">{i18n.t('analysis.measure')}</div><div className="p-3 text-app-muted">{i18n.t('analysis.selectedPeriod')}</div><div className="p-3 text-app-muted">{i18n.t('analysis.previousPeriod')}</div><div className="p-3 text-app-muted">{i18n.t('analysis.change')}</div>{rows.flatMap(([label, currentValue, previousValue, change]) => [<div key={`${label}-l`} className="border-t border-app p-3 text-app-muted">{label}</div>, <div key={`${label}-c`} className="border-t border-app p-3 text-app-text">{currentValue}</div>, <div key={`${label}-p`} className="border-t border-app p-3 text-app-text">{previousValue}</div>, <div key={`${label}-d`} className="border-t border-app p-3 text-app-text">{change}</div>])}</div></div></>
}

function ContextBreakdown({ rows }: { rows: AnalysisData['breakdowns'][ContextDimension] }) {
  return <><div className="grid gap-2 p-3 sm:hidden">{rows.map((row) => <article key={`${row.context}-${row.context_id}`} className="border border-app bg-app-panel-elevated p-3"><div className="flex items-start justify-between gap-3"><div><h3 className="font-medium text-app-text">{row.context}</h3><p className="mt-1 text-xs text-app-muted">{row.attempt_count} {i18n.t('analysis.attempts')} · {row.session_count} {i18n.t('analysis.sessionsLabel')} · {sampleLabel(row.sample_label)}</p></div><span className="text-sm font-semibold text-app-accent">{scoreText(row.median)}</span></div><dl className="mt-3 grid grid-cols-2 gap-2 text-xs"><div><dt className="text-app-muted">{i18n.t('analysis.averageExecution')}</dt><dd className="mt-1 text-app-text">{scoreText(row.average)}</dd></div><div><dt className="text-app-muted">{i18n.t('dashboard.avgDD')}</dt><dd className="mt-1 text-app-text">{scoreText(row.average_dd)}</dd></div><div><dt className="text-app-muted">{i18n.t('analysis.success')}</dt><dd className="mt-1 text-app-text">{percentageText(row.success_rate)}</dd></div><div><dt className="text-app-muted">{i18n.t('analysis.ddCoverage')}</dt><dd className="mt-1 text-app-text">{percentageText(row.dd_coverage_rate)}</dd></div></dl></article>)}</div><div className="hidden overflow-x-auto sm:block"><table className="w-full min-w-[900px] text-left text-sm"><thead className="text-xs text-app-muted"><tr>{[i18n.t('analysis.context'), i18n.t('analysis.attempts'), i18n.t('analysis.median'), i18n.t('analysis.average'), i18n.t('dashboard.avgDD'), i18n.t('analysis.ddCoverage'), i18n.t('analysis.success'), i18n.t('analysis.sampleHeading')].map((heading) => <th key={heading} className="border-b border-app px-5 py-3 font-medium">{heading}</th>)}</tr></thead><tbody>{rows.map((row) => <tr key={`${row.context}-${row.context_id}`} className="border-b border-app last:border-0"><td className="px-5 py-3 font-medium text-app-text">{row.context}</td><td className="px-5 py-3 text-app-text">{row.attempt_count}</td><td className="px-5 py-3 text-app-text">{scoreText(row.median)}</td><td className="px-5 py-3 text-app-text">{scoreText(row.average)}</td><td className="px-5 py-3 text-app-text">{scoreText(row.average_dd)}</td><td className="px-5 py-3 text-app-text">{percentageText(row.dd_coverage_rate)}</td><td className="px-5 py-3 text-app-text">{percentageText(row.success_rate)}</td><td className="px-5 py-3 text-app-muted">{sampleLabel(row.sample_label)}</td></tr>)}</tbody></table></div></>
}

function PhasePanel({ name, phase, attempts, view }: { name: string; phase: PhaseSeries; attempts: DiveAttempt[]; view: ChartView }) {
  const attemptsById = useMemo(() => new Map(attempts.map((attempt) => [attempt.id, attempt])), [attempts])
  const points = phase.points.map((point) => {
    const attempt = attemptsById.get(point.attempt_id)
    return { id: point.attempt_id, date: point.dive_datetime, score: point.score, rolling: point.rolling_median, label: `${name}, ${format(parseISO(point.dive_datetime), 'd MMM yyyy', { locale: appLocale() })}, ${point.score.toFixed(1)}`, sessionId: attempt?.session_id ?? point.attempt_id, height: attempt?.height || '', position: attempt?.position || null, modifiers: attempt?.modifiers || [], diver: attempt?.diver?.display_name || '', mediaStatus: attempt?.media.status || '' }
  })
  return <section className="border border-app bg-app-panel"><div className="flex items-start justify-between border-b border-app px-5 py-4"><div><h3 className="font-semibold text-app-text">{name}</h3><p className="mt-1 text-xs text-app-muted">{phase.available_count} {i18n.t('analysis.scored')} · {phase.missing_count} {i18n.t('analysis.missing')}</p></div><div className="text-right text-sm"><div className="font-semibold text-app-text">{i18n.t('analysis.median')} {scoreText(phase.summary.median)}</div><div className="text-xs text-app-muted">{i18n.t('analysis.previous')} {scoreText(phase.previous_summary.median)}</div></div></div><div className="p-3"><PointTimeline points={points} label={view === 'range' ? `${name} performance range per session` : `${name} score progression`} view={view} splitBy="none" /></div></section>
}

function AttemptDrawer({ attempt, attempts, onClose, onMove, returnFocus }: { attempt: DiveAttempt; attempts: DiveAttempt[]; onClose: () => void; onMove: (attempt: DiveAttempt) => void; returnFocus: React.MutableRefObject<Element | null> }) {
  const asideRef = useRef<HTMLElement>(null), index = attempts.findIndex((item) => item.id === attempt.id)
  const recent = attempts.slice(Math.max(0, index - 4), index + 1).map((item) => item.performance_numeric), recentMedian = [...recent].sort((a, b) => a - b)[Math.floor(recent.length / 2)]
  const overlayRef = useRef<HTMLDivElement>(null)
  useModalOverlay(asideRef, { isolationRef: overlayRef, onClose, fallbackFocus: () => returnFocus.current as HTMLElement | null })
  return <div ref={overlayRef} className="fixed inset-0 z-50 flex justify-end bg-black/55" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><aside ref={asideRef} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="attempt-title" className="h-full w-full max-w-2xl overflow-y-auto border-l border-app bg-app-panel p-4 outline-none sm:p-7">
    <div className="flex items-start justify-between gap-4"><div><h2 id="attempt-title" className="text-2xl font-semibold text-app-text">{attempt.dive_code} · {attempt.performance_numeric.toFixed(1)}</h2><p className="mt-1 text-sm text-app-muted">{format(parseISO(attempt.dive_datetime), 'd MMMM yyyy, HH:mm', { locale: appLocale() })} · {i18n.t('analysis.sessionN', { id: attempt.session_id })}</p></div><button type="button" onClick={onClose} className="border border-app bg-transparent p-2 text-app-muted" aria-label={i18n.t('analysis.closeAttempt')}><X className="h-4 w-4" /></button></div>
    <div className="mt-6 aspect-video overflow-hidden border border-app bg-black" aria-label={i18n.t('analysis.mediaFor', { code: attempt.dive_code, id: attempt.id })}>{attempt.video_uuid ? <DiveVideoPlayer diveCode={attempt.dive_code} height={attempt.height} videoUuid={attempt.video_uuid} /> : <div className="flex h-full items-center justify-center text-sm text-app-muted">{i18n.t('analysis.noLinkedAsset')}</div>}</div>
    <SendDiveButton key={attempt.id} diveId={attempt.id} inline />
    <dl className="mt-6 grid grid-cols-2 border-y border-app text-sm sm:grid-cols-3">{[
      [i18n.t('analysis.rating'), `${attempt.performance} · ${attempt.performance_numeric.toFixed(1)}`], [i18n.t('analysis.phaseScores'), attempt.phase1_performance && attempt.phase2_performance ? `${attempt.phase1_performance} / ${attempt.phase2_performance}` : i18n.t('attemptDetail.singleRating')],
      [i18n.t('attemptDetail.height'), attempt.height], [i18n.t('attemptDetail.platform'), platformTypeName(attempt.platform_type)], [i18n.t('analysis.position'), divePositionName(attempt.position, attempt.dive_code)], [i18n.t('analysis.context'), attempt.is_sync ? 'SYNC' : i18n.t('analysis.individual')], [i18n.t('analysis.modifiers'), attempt.modifiers.join(', ') || i18n.t('analysis.none')],
      [i18n.t('analysis.diver'), attempt.diver?.display_name || i18n.t('analysis.unassigned')], [i18n.t('analysis.trainingPeriods'), attempt.training_periods.map((period) => period.name).join(', ') || i18n.t('analysis.none')], [i18n.t('attemptDetail.officialDD'), attempt.official_dd?.toFixed(1) || '-'],
      [i18n.t('attemptDetail.media'), mediaStatusLabel(attempt.media.status)], [i18n.t('analysis.recent5Median'), recentMedian?.toFixed(1) || '-'], [i18n.t('analysis.fromRolling'), attempt.rolling_median == null ? '-' : (attempt.performance_numeric - attempt.rolling_median).toFixed(1)],
    ].map(([term, value]) => <div key={term} className="border-b border-app p-3"><dt className="text-xs text-app-muted">{term}</dt><dd className="mt-1 font-medium text-app-text">{value}</dd></div>)}</dl>
    <PersonalDiveValuePanel attemptId={attempt.id} onOpenAttempt={(id) => { const next = attempts.find((item) => item.id === id); if (next) onMove(next) }} />
    <div className="mt-6 space-y-4 text-sm"><div><h3 className="font-semibold text-app-text">{i18n.t('attemptDetail.rawCaption')}</h3><p className="mt-2 whitespace-pre-wrap text-app-muted">{attempt.raw_caption || i18n.t('attemptDetail.noCaption')}</p></div>{attempt.notes && <div><h3 className="font-semibold text-app-text">{i18n.t('attemptDetail.notes')}</h3><p className="mt-2 text-app-muted">{attempt.notes}</p></div>}</div>
    <div className="mt-8 flex items-center justify-between border-t border-app pt-4"><button type="button" aria-label={i18n.t('analysis.openPrevious')} disabled={index <= 0} onClick={() => onMove(attempts[index - 1])} className="flex items-center gap-2 border border-app bg-transparent text-sm disabled:opacity-30"><ChevronLeft className="h-4 w-4" /> {i18n.t('analysis.previous')}</button><Link to={`/sessions?session=${attempt.session_id}`} className="text-sm text-app-accent">{i18n.t('analysis.openSession')}</Link><button type="button" aria-label={i18n.t('analysis.openNext')} disabled={index >= attempts.length - 1} onClick={() => onMove(attempts[index + 1])} className="flex items-center gap-2 border border-app bg-transparent text-sm disabled:opacity-30">{i18n.t('analysis.next')} <ChevronRight className="h-4 w-4" /></button></div>
  </aside></div>
}

function PersonalValueHistory({ values, attempts, onOpen }: { values: PersonalDiveValue[]; attempts: DiveAttempt[]; onOpen: (attempt: DiveAttempt, trigger: Element) => void }) {
  const rows = values.map((value) => ({ value, attempt: attempts.find((attempt) => attempt.id === value.attempt_id) })).filter((row): row is { value: PersonalDiveValue; attempt: DiveAttempt } => Boolean(row.attempt && row.value.value != null))
  if (!rows.length) return null
  const notable = [...rows].sort((left, right) => (right.value.value || 0) - (left.value.value || 0)).slice(0, 5)
  return <div aria-labelledby="personal-history-heading"><div className="flex flex-wrap items-end justify-between gap-3"><div><h3 id="personal-history-heading" className="font-semibold text-app-text">{i18n.t('dashboard.personalDiveValue')}</h3></div><span className="text-xs text-app-muted">{rows.length} {i18n.t('dashboard.latestEligibleAttempts')}</span></div><div className="grid gap-5 p-4 lg:grid-cols-[1.1fr_.9fr]"><div className="min-w-0"><div className="flex h-32 items-end gap-1 border-b border-app pb-2" role="img" aria-label={i18n.t('analysis.pdvHistoryAlt', { count: rows.length, min: Math.min(...rows.map((row) => row.value.value || 0)).toFixed(0), max: Math.max(...rows.map((row) => row.value.value || 0)).toFixed(0) })}>{rows.map(({ value, attempt }) => <button key={attempt.id} type="button" aria-label={i18n.t('analysis.pdvPoint', { date: format(parseISO(attempt.dive_datetime), 'd MMM yyyy', { locale: appLocale() }), value: value.value, signal: signalLabel(value.primary_signal, i18n.t('analysis.emerging')) })} onClick={(event) => onOpen(attempt, event.currentTarget)} className="group min-w-2 flex-1 border-0 bg-transparent p-0"><span className="block w-full bg-app-accent/75 transition-colors group-hover:bg-app-accent" style={{ height: `${Math.max(5, value.value || 0)}%` }} /></button>)}</div><div className="mt-2 flex justify-between text-[11px] text-app-muted"><span>{format(parseISO(rows[0].attempt.dive_datetime), 'd MMM yyyy', { locale: appLocale() })}</span><span>{i18n.t('analysis.pdvScale')}</span><span>{format(parseISO(rows[rows.length - 1].attempt.dive_datetime), 'd MMM yyyy', { locale: appLocale() })}</span></div></div><ol className="grid gap-2" aria-label={i18n.t('analysis.pdvNotable')}>{notable.map(({ value, attempt }, index) => <li key={attempt.id}><button type="button" onClick={(event) => onOpen(attempt, event.currentTarget)} className="touch-target flex w-full items-center justify-between gap-3 border border-app bg-app-panel-elevated px-3 text-left"><div><span className="text-xs text-app-muted">{index === 0 ? i18n.t('analysis.mostNotable') : signalLabel(value.primary_signal, i18n.t('analysis.historicalSignal'))}</span><div className="mt-1 text-sm font-medium text-app-text">{format(parseISO(attempt.dive_datetime), 'd MMM yyyy', { locale: appLocale() })} · {i18n.t('analysis.execution')} {attempt.performance_numeric.toFixed(1)} · DD {attempt.official_dd?.toFixed(1) || '—'}</div></div><div className="text-right"><div className="text-lg font-semibold tabular-nums text-app-text">{value.value}</div><div className="text-[11px] text-app-muted">{confidenceLevelLabel(value.confidence.level)}</div></div></button></li>)}</ol></div></div>
}

export default function DiveAnalysis() {
  useTranslation() // subscribe so i18n.t() output follows language changes
  const { diveCode = '' } = useParams(), navigate = useNavigate(), location = useLocation(), [searchParams, setSearchParams] = usePreservedSearchParams()
  const { user } = useAuth()
  // Friends see everyone's dives by default (no diver bindings held).
  const defaultScope = (!user || user.divers?.length) ? 'self' : 'all'
  const [data, setData] = useState<AnalysisData | null>(null), [divers, setDivers] = useState<Diver[]>([]), [periods, setPeriods] = useState<TrainingPeriod[]>([])
  const [representatives, setRepresentatives] = useState<RepresentativeCard[]>([])
  const [personalValues, setPersonalValues] = useState<PersonalDiveValue[] | null>(null)
  const [loading, setLoading] = useState(true), [refreshing, setRefreshing] = useState(false), [error, setError] = useState<string | null>(null), [selected, setSelected] = useState<DiveAttempt | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [contextDimension, setContextDimension] = useState<ContextDimension>('modifier'), [equivalentOnly, setEquivalentOnly] = useState(false), [codeInput, setCodeInput] = useState(diveCode.toUpperCase())
  const returnFocus = useRef<Element | null>(null)
  const loadedDiveCode = useRef<string | null>(null)
  const dataFilterKey = useMemo(() => analysisFilterSearchKey(searchParams), [searchParams])
  const filters = useMemo(() => filtersFromSearchParams(new URLSearchParams(dataFilterKey), defaultScope), [dataFilterKey, defaultScope])
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
  }, [diveCode, dataFilterKey, filters, reloadKey])
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
  // UI-U7: `?attempt=` is selected-review context only. It never opens the
  // attempt drawer on arrival: the first screen stays the calm aggregate
  // summary, and the drawer opens only from explicit user action.

  const updateFilter = (key: string, value?: string | boolean) => { const next = new URLSearchParams(searchParams); value === undefined || value === '' ? next.delete(key) : next.set(key, String(value)); setSearchParams(next) }
  const updateMulti = (key: string, values: Array<string | number>) => { const next = new URLSearchParams(searchParams); next.delete(key); values.filter(Boolean).forEach((value) => next.append(key, String(value))); setSearchParams(next) }
  const toggleModifier = (modifier: string) => { const values = new Set(searchParams.getAll('modifiers')); values.has(modifier) ? values.delete(modifier) : values.add(modifier); updateMulti('modifiers', [...values]) }
  const setPeriod = (months: number) => { const end = new Date(), next = new URLSearchParams(searchParams); next.set('date_from', dateInput(subMonths(end, months))); next.set('date_to', dateInput(end)); setSearchParams(next) }
  const openAttempt = (attempt: DiveAttempt, trigger: Element) => { returnFocus.current = trigger; setSelected(attempt) }
  const setChartParam = (key: string, value: string) => { const next = new URLSearchParams(searchParams); value === 'none' || value === '' ? next.delete(key) : next.set(key, value); setSearchParams(next) }
  const retryAnalysis = () => { setError(null); setReloadKey((key) => key + 1) }
  const submitCode = (event: React.FormEvent) => {
    event.preventDefault()
    // A code switch is a different workspace: never carry the selected
    // attempt across codes, where the id could resolve to another clip.
    const next = new URLSearchParams(searchParams)
    next.delete('attempt')
    navigate(`/dives/analysis/${codeInput.trim().toUpperCase()}?${next}`)
  }

  // Selected-review context (UI-U7 §14): the attempt id from the URL resolves
  // against the loaded code-level result. Unresolvable ids stay unresolved.
  const requestedAttemptId = parseAttemptParam(searchParams.get('attempt'))
  const selectedAttempt = data && requestedAttemptId != null ? data.attempts.find((item) => item.id === requestedAttemptId) ?? null : null
  const attemptMismatch = data != null && requestedAttemptId != null && selectedAttempt == null
  // Exact Viewer return intent carried by the Viewer → Analysis entry link.
  // Only same-app Library destinations are honored.
  const locationState = location.state as { returnTo?: unknown } | null
  const returnTo = typeof locationState?.returnTo === 'string' && locationState.returnTo.startsWith('/dives') ? locationState.returnTo : null
  const backIsClip = returnTo != null || selectedAttempt != null
  const backLabel = backIsClip ? i18n.t('analysis.backToClip') : i18n.t('notFound.backToLibrary')
  const backHref = returnTo ?? (selectedAttempt ? `/dives?clip=${selectedAttempt.id}` : `/dives?q=${encodeURIComponent(diveCode.toUpperCase())}`)
  const goBack = () => navigate(backHref)
  const hasAttempts = (data?.summary.attempt_count ?? 0) > 0
  const bestAttempt = data?.summary.best_attempt_id != null ? data.attempts.find((item) => item.id === data.summary.best_attempt_id) ?? null : null

  const attempts = data?.attempts || []
  const readyCount = attempts.filter((attempt) => attempt.media.status === 'ready').length
  const timelinePoints = attempts.map(buildTimelinePoint)
  const comparisonRows = data?.breakdowns[contextDimension] || []
  const heightCounts = countBy(attempts.map((attempt) => attempt.height))
  const positionCounts = countBy(attempts.map((attempt) => divePositionName(attempt.position, attempt.dive_code)))
  const syncCounts = countBy(attempts.map((attempt) => attempt.is_sync ? 'SYNC' : i18n.t('analysis.individual')))
  const modifierCounts = countBy(attempts.flatMap((attempt) => attempt.modifiers.length ? attempt.modifiers : [i18n.t('analysis.noModifier')]))
  const heights = unique(attempts.map((attempt) => attempt.height))
  const positions = unique(attempts.map((attempt) => divePositionName(attempt.position, attempt.dive_code)))
  const syncStates = unique(attempts.map((attempt) => attempt.is_sync ? 'SYNC' : i18n.t('analysis.individual')))
  const diverScopeText = filters.diver_scope === 'all' ? i18n.t('analysis.allDivers') : filters.diver_scope === 'selected' ? i18n.t('analysis.selectedDiversCount', { count: filters.diver_ids?.length || 0 }) : i18n.t('dives.myDives')
  const dateRange = i18n.t('analysis.dateRange', { from: filters.date_from || (data?.sample.first_attempt_at ? format(parseISO(data.sample.first_attempt_at), 'yyyy-MM-dd') : i18n.t('analysis.first')), to: filters.date_to || (data?.sample.last_attempt_at ? format(parseISO(data.sample.last_attempt_at), 'yyyy-MM-dd') : i18n.t('analysis.latest')) })
  const aggregateScope = data ? i18n.t('analysis.aggregateScope', { code: data.dive_code, scope: diverScopeText, attempts: data.summary.attempt_count }) : ''
  const mixedContext = attempts.length > 0 && (heights.length > 1 || positions.length > 1 || syncStates.length > 1 || Object.keys(modifierCounts).length > 1)

  return <div className="mx-auto w-full max-w-[1480px] space-y-6">
    <button type="button" onClick={goBack} data-testid="analysis-back" className="touch-target inline-flex items-center gap-2 border border-app bg-app-panel px-3 py-1.5 text-sm text-app-text"><ArrowLeft className="h-4 w-4" aria-hidden="true" />{backLabel}</button>
    <header className="flex flex-col gap-4 border-b border-app pb-5 md:flex-row md:items-end md:justify-between"><div><div className="flex items-center gap-3"><h1 className="text-3xl font-semibold tracking-tight text-app-text">{diveCode.toUpperCase()}</h1></div><p className="mt-2 text-sm text-app-muted" aria-live="polite" data-testid="analysis-scope">{data?.sample.attempt_count ?? 0} {i18n.t('analysis.attempts')} {i18n.t('analysis.in')} {data?.sample.session_count ?? 0} {i18n.t('analysis.sessionsLabel')} · {readyCount} {i18n.t('analysis.cachedClips')} · {dateRange}</p>{selectedAttempt && <p className="mt-2 text-sm text-app-text" data-testid="analysis-attempt-context">{i18n.t('analysis.thisAttempt')} · {format(parseISO(selectedAttempt.dive_datetime), 'd MMM yyyy, HH:mm', { locale: appLocale() })} · {selectedAttempt.height} · {divePositionName(selectedAttempt.position, selectedAttempt.dive_code)} · {i18n.t('analysis.execution')} {selectedAttempt.performance_numeric.toFixed(1)}</p>}{attemptMismatch && <p className="mt-2 text-sm text-app-muted" data-testid="analysis-attempt-mismatch">{i18n.t('analysis.attemptNotInScope', { code: diveCode.toUpperCase() })}</p>}</div><form className="flex gap-2" onSubmit={submitCode}><label className="sr-only" htmlFor="analysis-code">{i18n.t('analysis.diveCode')}</label><input id="analysis-code" value={codeInput} onChange={(event) => setCodeInput(event.target.value)} className="app-input w-32 uppercase" /><button className="border border-app-accent bg-transparent text-sm text-app-accent">{i18n.t('analysis.analyze')}</button></form></header>

    <AnalysisSection id="filters" title={i18n.t('analysis.filters')}><div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8">
      <label className="text-xs text-app-muted">{i18n.t('analysis.dateFrom')}<input type="date" value={searchParams.get('date_from') || ''} onChange={(event) => updateFilter('date_from', event.target.value)} className="app-input mt-1 w-full text-sm" /></label><label className="text-xs text-app-muted">{i18n.t('analysis.dateTo')}<input type="date" value={searchParams.get('date_to') || ''} onChange={(event) => updateFilter('date_to', event.target.value)} className="app-input mt-1 w-full text-sm" /></label>
      <label className="text-xs text-app-muted">{i18n.t('attemptDetail.height')}<select value={filters.height || ''} onChange={(event) => updateFilter('height', event.target.value)} className="app-input mt-1 w-full text-sm"><option value="">{i18n.t('analysis.any')}</option>{['1m', '3m', '5m', '7m', '10m'].map((value) => <option key={value}>{value}</option>)}</select></label><label className="text-xs text-app-muted">{i18n.t('analysis.position')}<select value={filters.position || ''} onChange={(event) => updateFilter('position', event.target.value)} className="app-input mt-1 w-full text-sm"><option value="">{i18n.t('analysis.allPositions')}</option>{DIVE_POSITION_CODES.map((code) => <option key={code} value={code}>{i18n.t(`jargon.positions.${code}`)}</option>)}</select></label>
      <label className="text-xs text-app-muted">SYNC<select value={searchParams.get('is_sync') || ''} onChange={(event) => updateFilter('is_sync', event.target.value)} className="app-input mt-1 w-full text-sm"><option value="">{i18n.t('analysis.any')}</option><option value="false">{i18n.t('analysis.individual')}</option><option value="true">SYNC</option></select></label><label className="text-xs text-app-muted">{i18n.t('analysis.modifierMatch')}<select value={filters.modifier_mode} onChange={(event) => updateFilter('modifier_mode', event.target.value)} className="app-input mt-1 w-full text-sm"><option value="any">{i18n.t('analysis.modifierAny')}</option><option value="all">{i18n.t('analysis.modifierAll')}</option><option value="none">{i18n.t('analysis.noModifiers')}</option></select></label>
      <label className="text-xs text-app-muted">{i18n.t('analysis.diverScope')}<select value={filters.diver_scope || 'self'} onChange={(event) => { const next = new URLSearchParams(searchParams); next.delete('diver_ids'); event.target.value === 'self' ? next.delete('diver_scope') : next.set('diver_scope', event.target.value); setSearchParams(next) }} className="app-input mt-1 w-full text-sm"><option value="self">{i18n.t('dives.myDives')}</option><option value="all">{i18n.t('analysis.allDivers')}</option><option value="selected">{i18n.t('analysis.selectedDivers')}</option></select></label>
      <label className="text-xs text-app-muted">{i18n.t('analysis.selectedDivers')}<select multiple disabled={filters.diver_scope !== 'selected'} value={(filters.diver_ids || []).map(String)} onChange={(event) => updateMulti('diver_ids', [...event.currentTarget.selectedOptions].map((option) => option.value))} className="app-input mt-1 h-20 w-full text-sm disabled:opacity-45">{divers.map((diver) => <option key={diver.id} value={diver.id}>{diver.display_name}{diver.is_primary_user ? ` (${i18n.t('analysis.primary')})` : ''}</option>)}</select></label>
      <label className="text-xs text-app-muted">{i18n.t('analysis.trainingPeriod')}<select multiple value={(filters.training_period_ids || []).map(String)} onChange={(event) => updateMulti('training_period_ids', [...event.currentTarget.selectedOptions].map((option) => option.value))} className="app-input mt-1 h-20 w-full text-sm"><option value="">{i18n.t('analysis.allPeriods')}</option>{periods.map((period) => <option key={period.id} value={period.id}>{period.name}</option>)}</select></label>
    </div><div className="mt-4 flex flex-wrap items-center gap-2 border-t border-app pt-4">{MODIFIERS.map((modifier) => <button type="button" aria-pressed={filters.modifiers?.includes(modifier)} key={modifier} onClick={() => toggleModifier(modifier)} className={`touch-target border px-3 py-1.5 text-sm ${filters.modifiers?.includes(modifier) ? 'border-app-accent text-app-accent' : 'border-app bg-transparent text-app-muted'}`}>{modifier}</button>)}<span className="mx-2 h-5 border-l border-app" /><button type="button" onClick={() => setPeriod(3)} className="touch-target border border-app bg-transparent px-3 py-1.5 text-sm text-app-muted">{i18n.t('analysis.last3Months')}</button><button type="button" onClick={() => setPeriod(6)} className="touch-target border border-app bg-transparent px-3 py-1.5 text-sm text-app-muted">{i18n.t('analysis.last6Months')}</button><label className="ml-2 flex items-center gap-2 text-sm text-app-muted">{i18n.t('analysis.weighting')}<select aria-label={i18n.t('analysis.weightingAria')} value={filters.weighting} onChange={(event) => updateFilter('weighting', event.target.value)} className="app-input py-1.5 text-sm"><option value="attempts">{i18n.t('analysis.byAttempts')}</option><option value="sessions">{i18n.t('analysis.bySessionMedians')}</option></select></label><button type="button" onClick={() => setSearchParams(new URLSearchParams())} className="ml-auto flex items-center gap-2 border-0 bg-transparent px-2 text-sm text-app-muted"><RotateCcw className="h-4 w-4" /> {i18n.t('dives.resetFilters')}</button></div><p className="mt-3 text-xs text-app-muted">{i18n.t('analysis.weightingHint')}</p><div className="mt-4 flex flex-wrap gap-2 border-t border-app pt-4"><button type="button" onClick={() => setSearchParams(new URLSearchParams())} className="touch-target inline-flex items-center gap-2 border border-app bg-transparent px-3 py-1.5 text-xs text-app-muted"><RotateCcw className="h-3.5 w-3.5" />{i18n.t('analysis.resetAll')}</button><button type="button" onClick={() => navigator.clipboard?.writeText(window.location.href)} className="touch-target inline-flex items-center gap-2 border border-app bg-transparent px-3 py-1.5 text-xs text-app-muted"><Copy className="h-3.5 w-3.5" />{i18n.t('analysis.copyLink')}</button></div></AnalysisSection>

    {loading && !data && <div className="border-y border-app py-20 text-center text-sm text-app-muted" role="status">{i18n.t('common.loading')}</div>}
    {refreshing && data && <div className="sticky top-0 z-30 border border-app-accent/40 bg-app-panel/95 px-4 py-2 text-center text-xs text-app-muted backdrop-blur" role="status">{i18n.t('repMedia.refreshing')}</div>}
    {error && <div className="border border-red-900/60 bg-red-950/30 p-4 text-sm text-red-300" role="alert"><p>{error}</p><button type="button" onClick={retryAnalysis} data-testid="analysis-retry" className="touch-target mt-3 inline-flex items-center gap-2 border border-red-300/50 bg-transparent px-3 py-1.5 text-sm text-red-200">{i18n.t('common.retry')}</button></div>}
    {data && data.summary.attempt_count === 0 && !loading && !error && <div className="border border-app bg-app-panel p-8 text-center" role="status" data-testid="analysis-unavailable"><h2 className="font-semibold text-app-text">{i18n.t('analysis.noAttemptsInView')}</h2><p className="mt-2 text-sm text-app-muted">{i18n.t('analysis.noAttemptsMatch', { code: diveCode.toUpperCase() })}</p><button type="button" onClick={() => setSearchParams(new URLSearchParams())} className="touch-target mt-4 inline-flex items-center gap-2 border border-app bg-transparent px-3 py-1.5 text-sm text-app-text"><RotateCcw className="h-4 w-4" aria-hidden="true" />{i18n.t('dives.clearFilters')}</button></div>}
    {data && hasAttempts && <>
      {selectedAttempt && <AnalysisSection id="selected-attempt" title={i18n.t('analysis.selectedAttempt')} defaultOpen>
        <dl className="grid grid-cols-2 gap-px text-sm sm:grid-cols-4">{[
          [i18n.t('analysis.execution'), `${selectedAttempt.performance} · ${selectedAttempt.performance_numeric.toFixed(1)}`],
          [i18n.t('dashboard.date'), format(parseISO(selectedAttempt.dive_datetime), 'd MMM yyyy, HH:mm', { locale: appLocale() })],
          [i18n.t('attemptDetail.height'), selectedAttempt.height],
          [i18n.t('analysis.position'), divePositionName(selectedAttempt.position, selectedAttempt.dive_code)],
          [i18n.t('analysis.context'), selectedAttempt.is_sync ? 'SYNC' : i18n.t('analysis.individual')],
          [i18n.t('analysis.modifiers'), selectedAttempt.modifiers.join(', ') || i18n.t('analysis.none')],
          [i18n.t('analysis.diver'), selectedAttempt.diver?.display_name || i18n.t('analysis.unassigned')],
          [i18n.t('attemptDetail.media'), mediaStatusLabel(selectedAttempt.media.status)],
        ].map(([term, value]) => <div key={term} className="bg-app-panel-elevated p-3"><dt className="text-xs text-app-muted">{term}</dt><dd className="mt-1 font-medium text-app-text">{value}</dd></div>)}</dl>
        <div className="mt-4"><button type="button" onClick={(event) => openAttempt(selectedAttempt, event.currentTarget)} className="touch-target border border-app bg-transparent px-3 py-1.5 text-sm text-app-text">{i18n.t('analysis.openAttemptDetails')}</button></div>
      </AnalysisSection>}
      <section aria-label={i18n.t('analysis.keySummary')} data-testid="analysis-key-summary"><p className="text-xs text-app-muted">{aggregateScope}</p><div className="mt-2 grid grid-cols-2 gap-px border border-app bg-app-panel lg:grid-cols-4">{[
        [i18n.t('analysis.attempts'), `${data.summary.attempt_count}`, `${data.summary.session_count} ${i18n.t('analysis.sessionsLabel')} · ${data.summary.scored_attempt_count} ${i18n.t('analysis.scored')}`],
        [i18n.t('analysis.medianExecution'), scoreText(data.summary.median), `${deltaText(data.summary.median, data.comparison.previous?.median)} · ${i18n.t('analysis.avg')} ${scoreText(data.summary.average)}`],
        [i18n.t('analysis.consistency'), `IQR ${scoreText(data.summary.iqr)}`, data.summary.iqr != null && data.summary.iqr >= 2 ? i18n.t('analysis.highVariability') : i18n.t('analysis.tighterSpread')],
        [i18n.t('analysis.trend'), i18n.t(`analysis.trendDirection.${data.trend.direction}`, { defaultValue: data.trend.direction.replace(/_/g, ' ') })],
      ].map(([term, value, note]) => <div key={term} className="bg-app-panel p-4"><div className="text-xs text-app-muted">{term}</div><div className="mt-2 text-xl font-semibold capitalize text-app-text">{value}</div><div className="mt-1 text-xs leading-5 text-app-muted">{note}</div></div>)}</div></section>
      {data.insights.length > 0 && <section className="border border-app bg-app-panel p-5" aria-labelledby="analysis-insights-heading"><h2 id="analysis-insights-heading" className="font-semibold text-app-text">{i18n.t('analysis.whatChanged')}</h2><div className="mt-4 grid gap-3 sm:grid-cols-2">{data.insights.slice(0, 4).map((insight, index) => <div key={`${insight.type}-${index}`} className="border-l border-app-accent/70 bg-app-panel-elevated px-4 py-3"><div className="flex items-center justify-between gap-4"><h3 className="text-sm font-semibold text-app-text">{insight.title}</h3><span className="text-[11px] text-app-muted">{sampleLabel(insight.confidence)}</span></div><p className="mt-1 text-sm leading-6 text-app-muted">{insight.message}</p></div>)}</div></section>}

      {/* UI-U7: headline metrics live in the key summary (first screen) and the Comparison section. */}

      {personalValues && attempts.length > 0 && <AnalysisSection id="personal-value" title={i18n.t('analysis.personalReviewPriority')}><PersonalValueHistory values={personalValues} attempts={data.attempts} onOpen={openAttempt} /></AnalysisSection>}

      {hasAttempts && representatives.length > 0 && <AnalysisSection id="representatives" title={i18n.t('analysis.repAttempts')}><div className="mb-4"><Link to={`/media/representatives?dive_code=${encodeURIComponent(data.dive_code)}`} className="touch-target inline-flex items-center text-sm text-app-accent">{i18n.t('analysis.openRepGallery')}</Link></div><div className="grid gap-4 lg:grid-cols-3">{['low', 'median', 'high'].map((role) => {
        const rep = representatives.find((item) => item.role === role)
        if (!rep) return <div key={role} className="border border-app p-4 text-sm text-app-muted">{i18n.t(role === 'median' ? 'analysis.noTypicalRep' : 'analysis.noBandRep', { band: role })}</div>
        const linkedAttempt = data.attempts.find((item) => item.id === rep.attempt.id)
        return <article key={role} className="border border-app bg-app-panel-elevated"><div className="flex items-start justify-between gap-3 border-b border-app px-4 py-3"><h3 className="font-semibold text-app-text">{i18n.t(`repMedia.role.${rep.role}`)}</h3><span className="text-xs text-app-muted">{mediaStatusLabel(rep.media.state)}</span></div>{rep.media.poster_url ? <img src={rep.media.poster_url} alt={i18n.t('repMedia.posterAlt', { code: data.dive_code, label: i18n.t(`repMedia.role.${rep.role}`) })} className="aspect-video w-full object-cover" /> : <div className="flex aspect-video items-center justify-center bg-black/35 text-xs text-app-muted">{i18n.t('analysis.noPoster')}</div>}<div className="space-y-3 p-4 text-sm"><div><div className="text-xl font-semibold text-app-text">{rep.attempt.score_10.toFixed(1)} <span className="text-sm font-normal text-app-muted">/ {rep.attempt.performance}</span></div><div className="mt-1 text-app-muted">{format(parseISO(rep.attempt.dive_datetime), 'd MMM yyyy', { locale: appLocale() })} · {rep.attempt.height} · {rep.attempt.is_sync ? 'SYNC' : i18n.t('analysis.individual')}</div></div>{rep.media.failure && <p className="text-xs leading-5 text-red-300">{rep.media.failure.message}</p>}<div className="flex flex-wrap gap-2">{rep.media.playback_url && <a href={rep.media.playback_url} className="touch-target inline-flex items-center border border-app-accent px-3 py-1.5 text-xs text-app-accent">{i18n.t('analysis.play')}</a>}<button type="button" onClick={(event) => linkedAttempt ? openAttempt(linkedAttempt, event.currentTarget) : navigate(`/dives/analysis/${data.dive_code}?attempt=${rep.attempt.id}`)} className="touch-target border border-app px-3 py-1.5 text-xs text-app-muted">{i18n.t('analysis.openAttempt')}</button>{rep.replacement.available && <Link to={`/media/representatives?dive_code=${encodeURIComponent(data.dive_code)}&selection_band=${rep.role}`} className="touch-target inline-flex items-center border border-app px-3 py-1.5 text-xs text-app-muted">{i18n.t('analysis.findReplacement')}</Link>}</div></div></article>
      })}</div></AnalysisSection>}

      <AnalysisSection id="progression" title={i18n.t('analysis.progression')}><div className="mb-4 grid grid-cols-2 gap-3 text-xs sm:flex sm:flex-wrap sm:gap-2"><label className="text-app-muted">{i18n.t('analysis.view')}<select aria-label={i18n.t('analysis.chartView')} value={chartView} onChange={(event) => setChartParam('chart_view', event.target.value)} className="app-input mt-1 w-full py-1 text-xs sm:ml-2 sm:mt-0 sm:w-auto"><option value="session">{i18n.t('analysis.sessionSummary')}</option><option value="range">{i18n.t('analysis.performanceRange')}</option><option value="attempts">{i18n.t('analysis.allAttempts')}</option></select></label><label className="text-app-muted">{i18n.t('analysis.splitBy')}<select aria-label={i18n.t('analysis.splitByAria')} value={splitBy} onChange={(event) => setChartParam('split_by', event.target.value)} className="app-input mt-1 w-full py-1 text-xs sm:ml-2 sm:mt-0 sm:w-auto"><option value="none">{i18n.t('analysis.none')}</option><option value="height">{i18n.t('attemptDetail.height')}</option><option value="position">{i18n.t('analysis.position')}</option><option value="modifier">{i18n.t('analysis.modifier')}</option><option value="sync">SYNC</option><option value="diver">{i18n.t('analysis.diver')}</option></select></label></div><div><PointTimeline points={timelinePoints} label={chartView === 'range' ? i18n.t('analysis.rangeByPeriod') : i18n.t('analysis.scoreProgression')} selectedId={selected?.id} view={chartView} splitBy={splitBy} onSelect={(id, trigger) => { const attempt = data.attempts.find((item) => item.id === id); if (attempt) openAttempt(attempt, trigger) }} /><p className="sr-only">{i18n.t('analysis.scoresRange', { min: scoreText(data.summary.minimum), max: scoreText(data.summary.maximum), median: scoreText(data.summary.median), spread: data.summary.iqr != null && data.summary.iqr >= 2 ? i18n.t('analysis.spreadWide') : i18n.t('analysis.spreadModerate'), attempts: data.summary.attempt_count })}</p></div></AnalysisSection>

      <AnalysisSection id="comparison" title={i18n.t('analysis.comparisonHistory')}>
        <div className="mb-6"><h3 className="font-semibold text-app-text">{mixedContext ? i18n.t('analysis.mixedContext') : i18n.t('analysis.equivalentContext')}</h3><dl className="mt-4 grid grid-cols-2 gap-px text-sm sm:grid-cols-3 lg:grid-cols-6">{[
          [i18n.t('analysis.heights'), Object.entries(heightCounts).map(([k, v]) => `${k} ${v}`).join(' · ') || '-'],
          [i18n.t('analysis.positions'), Object.entries(positionCounts).map(([k, v]) => `${k} ${v}`).join(' · ') || '-'],
          [i18n.t('analysis.context'), Object.entries(syncCounts).map(([k, v]) => `${k} ${v}`).join(' · ') || '-'],
          [i18n.t('analysis.modifiers'), Object.entries(modifierCounts).slice(0, 4).map(([k, v]) => `${k} ${v}`).join(' · ') || '-'],
          [i18n.t('analysis.success'), data.summary.success_rate == null ? '-' : `${percentageText(data.summary.success_rate)} · ${i18n.t('analysis.threshold')} ${data.summary.success_threshold}`],
          [i18n.t('analysis.difficulty'), `DD ${scoreText(data.summary.average_dd)} · ${percentageText(data.summary.dd_coverage_rate)} ${i18n.t('analysis.coverage')}`],
        ].map(([term, value]) => <div key={term} className="bg-app-panel-elevated p-3"><dt className="text-xs text-app-muted">{term}</dt><dd className="mt-1 font-medium text-app-text">{value}</dd></div>)}</dl><div className="mt-4 flex flex-wrap items-center gap-2"><button type="button" onClick={() => setChartParam('split_by', 'height')} className="touch-target border border-app bg-transparent px-3 py-1.5 text-xs text-app-muted">{i18n.t('analysis.splitByHeight')}</button><button type="button" onClick={() => updateFilter('is_sync', 'false')} className="touch-target border border-app bg-transparent px-3 py-1.5 text-xs text-app-muted">{i18n.t('dives.contextIndividual')}</button><button type="button" onClick={() => setChartParam('split_by', 'position')} className="touch-target border border-app bg-transparent px-3 py-1.5 text-xs text-app-muted">{i18n.t('analysis.splitByPosition')}</button>{bestAttempt && <button type="button" onClick={(event) => openAttempt(bestAttempt, event.currentTarget)} className="touch-target border border-app bg-transparent px-3 py-1.5 text-xs text-app-muted">{i18n.t('analysis.reviewBest', { score: scoreText(data.summary.maximum) })}</button>}</div></div>
        <div className="mb-6"><h3 className="font-semibold text-app-text">{i18n.t('analysis.periodComparison')}</h3><div className="mt-2">{data.comparison.previous ? <PeriodComparison current={data.summary} previous={data.comparison.previous} /> : <div className="mt-8 text-sm text-app-muted"><CalendarRange className="mb-3 h-5 w-5" />{i18n.t('analysis.pickDateRange')}</div>}</div></div>

      <div className="grid min-w-0 gap-6 xl:grid-cols-[.9fr_1.1fr]"><div className="min-w-0"><h3 className="font-semibold text-app-text">{i18n.t('analysis.scoreDistribution')}</h3><Distribution attempts={data.attempts} /></div><div className="min-w-0"><div className="flex flex-wrap items-center gap-3"><h3 className="mr-auto font-semibold text-app-text">{i18n.t('analysis.contextBreakdown')}</h3>{DIMENSIONS.map((dimension) => <button type="button" key={dimension} aria-pressed={contextDimension === dimension} onClick={() => setContextDimension(dimension)} className={`touch-target border-0 bg-transparent px-1 py-1 text-sm capitalize ${contextDimension === dimension ? 'text-app-accent' : 'text-app-muted'}`}>{i18n.t(`analysis.dimension.${dimension}`)}</button>)}<label className="flex items-center gap-2 text-xs text-app-muted"><input type="checkbox" checked={equivalentOnly} onChange={(event) => setEquivalentOnly(event.target.checked)} /> {i18n.t('analysis.equivalentOnly')}</label></div><ContextBreakdown rows={comparisonRows} /></div></div></AnalysisSection>

      <AnalysisSection id="phases" title={i18n.t('analysis.phaseAnalysis')}><div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between"><div><p className="text-xs text-app-muted">{data.phases.total_attempts} {i18n.t('analysis.totalAttempts')}</p></div><div className="flex items-end justify-between gap-3 sm:justify-end"><label className="text-xs text-app-muted">{i18n.t('analysis.view')}<select aria-label={i18n.t('analysis.phaseChartView')} value={phaseView} onChange={(event) => setChartParam('phase_view', event.target.value)} className="app-input mt-1 block w-full py-1 text-xs sm:w-auto"><option value="attempts">{i18n.t('analysis.allAttempts')}</option><option value="session">{i18n.t('analysis.sessionSummary')}</option><option value="range">{i18n.t('analysis.performanceRange')}</option></select></label></div></div><div className="grid gap-6 lg:grid-cols-2"><PhasePanel name={i18n.t('jargon.phaseN', { n: 1 })} phase={data.phases.phases.phase1} attempts={data.attempts} view={phaseView} /><PhasePanel name={i18n.t('jargon.phaseN', { n: 2 })} phase={data.phases.phases.phase2} attempts={data.attempts} view={phaseView} /></div></AnalysisSection>

      <AnalysisSection id="attempts" title={i18n.t('analysis.attemptsToReview')}><div className="grid gap-2 p-3 sm:hidden">{[...data.attempts].reverse().map((attempt) => <button key={attempt.id} type="button" onClick={(event) => openAttempt(attempt, event.currentTarget)} className="touch-target border border-app bg-app-panel-elevated p-3 text-left"><div className="flex items-start justify-between gap-3"><div><div className="font-semibold text-app-text">{attempt.performance_numeric.toFixed(1)} <span className="font-normal text-app-muted">/ {attempt.performance}</span></div><p className="mt-1 text-xs text-app-muted">{format(parseISO(attempt.dive_datetime), 'd MMM yyyy', { locale: appLocale() })} · {attempt.height} · {attempt.is_sync ? 'SYNC' : i18n.t('analysis.individual')}</p></div><span className={`text-xs ${attempt.media.status === 'ready' ? 'text-app-accent' : 'text-app-muted'}`}>{mediaStatusLabel(attempt.media.status)}</span></div><p className="mt-2 truncate text-xs text-app-muted">{attempt.modifiers.join(', ') || i18n.t('analysis.noModifiers')} · {attempt.diver?.display_name || i18n.t('analysis.unassigned')}</p></button>)}</div><div className="hidden overflow-x-auto sm:block"><table className="w-full min-w-[940px] text-left text-sm"><thead className="text-xs text-app-muted"><tr>{[i18n.t('dashboard.date'), i18n.t('attemptDetail.score'), i18n.t('attemptDetail.phases'), i18n.t('attemptDetail.height'), i18n.t('analysis.modifiers'), i18n.t('analysis.context'), i18n.t('analysis.diver'), i18n.t('analysis.period'), i18n.t('attemptDetail.media')].map((heading) => <th key={heading} className="border-b border-app px-4 py-3 font-medium">{heading}</th>)}</tr></thead><tbody>{[...data.attempts].reverse().map((attempt) => <tr key={attempt.id} tabIndex={0} onClick={(event) => openAttempt(attempt, event.currentTarget)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openAttempt(attempt, event.currentTarget) } }} className="cursor-pointer border-b border-app hover:bg-app-panel-elevated focus:bg-app-panel-elevated focus:outline-none"><td className="px-4 py-3 text-app-text">{format(parseISO(attempt.dive_datetime), 'd MMM yyyy', { locale: appLocale() })}</td><td className="px-4 py-3 font-semibold text-app-text">{attempt.performance_numeric.toFixed(1)} <span className="font-normal text-app-muted">/ {attempt.performance}</span></td><td className="px-4 py-3 text-app-muted">{attempt.phase1_performance && attempt.phase2_performance ? `${attempt.phase1_performance} / ${attempt.phase2_performance}` : '-'}</td><td className="px-4 py-3 text-app-text">{attempt.height}</td><td className="px-4 py-3 text-app-muted">{attempt.modifiers.join(', ') || '-'}</td><td className="px-4 py-3 text-app-muted">{attempt.is_sync ? 'SYNC' : i18n.t('analysis.individual')}</td><td className="px-4 py-3 text-app-muted">{attempt.diver?.display_name || i18n.t('analysis.unassigned')}</td><td className="px-4 py-3 text-app-muted">{attempt.training_periods.map((period) => period.name).join(', ') || '-'}</td><td className="px-4 py-3"><span className={`inline-flex items-center gap-2 ${attempt.media.status === 'ready' ? 'text-app-accent' : ACTIVE_MEDIA.has(attempt.media.status) ? 'text-amber-300' : 'text-app-muted'}`}><Film className="h-4 w-4" />{mediaStatusLabel(attempt.media.status)}</span></td></tr>)}</tbody></table></div>{!data.attempts.length && <div className="p-8 text-center text-sm text-app-muted">{i18n.t('analysis.noAttemptsWithFilters')}</div>}</AnalysisSection>
    </>}
    {selected && data && <AttemptDrawer attempt={selected} attempts={data.attempts} onClose={() => setSelected(null)} onMove={setSelected} returnFocus={returnFocus} />}
  </div>
}
