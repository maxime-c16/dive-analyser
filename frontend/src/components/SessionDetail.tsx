import React, { useEffect, useRef, useState } from 'react'
import { X, TrendingUp, TrendingDown, Minus, Film } from 'lucide-react'
import { api } from '../services/api'
import { format, parseISO } from 'date-fns'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LineChart, Line
} from 'recharts'
import DiveVideoPlayer from './DiveVideoPlayer'
import i18n from '../i18n'
import { inertExcept, trapTabKey } from '../utils/a11y'
import { isSuccessfulPerformance, performanceScore10 } from '../utils/performanceScoring'

interface Dive {
  id: number
  dive_code: string
  performance: string
  performance_numeric: number
  height: string
  dive_datetime: string
  session_id: number
  direction: number | null
  is_sync: boolean
  platform_type: string
  official_dd?: number | null
  video_uuid?: string | null
  phase1_performance?: string | null
  phase2_performance?: string | null
}

interface Session {
  id: number
  date: string
  location?: string
  total_dives: number
  total_personal_dives: number
  avg_performance?: number
  success_rate?: number
  notes?: string
}

interface SessionDetailProps {
  session: Session
  previousSession?: Session
  onClose: () => void
  allSessions: Session[]
  diverScope: 'self' | 'all'
}

/**
 * Labels resolve at call time (via performanceConfig) so a language change
 * while the dialog is open re-renders in the new language; only language
 * agnostic styling lives in the static map.
 */
const PERFORMANCE_STYLES: { [key: string]: { color: string; bg: string } } = {
  P: { color: 'text-green-400', bg: 'bg-green-500/20' },
  G: { color: 'text-app-accent', bg: 'bg-app-accent-soft' },
  M: { color: 'text-amber-400', bg: 'bg-amber-500/20' },
  B: { color: 'text-orange-400', bg: 'bg-orange-500/20' },
  F: { color: 'text-red-400', bg: 'bg-red-500/20' },
}

const performanceConfig = (performance: string) => {
  const style = PERFORMANCE_STYLES[performance] || PERFORMANCE_STYLES.M
  return { ...style, label: i18n.t(`performance.${performance}`, { defaultValue: performance }) }
}

const DIRECTION_KEY_SUFFIX: { [key: number]: string } = { 1: '1', 2: '2', 3: '3', 4: '4', 5: '5' }
const directionName = (direction: number | null) =>
  direction && DIRECTION_KEY_SUFFIX[direction] ? i18n.t(`groups.${direction}`) : i18n.t('analysis.none')

const DIRECTION_COLORS: { [key: number]: string } = {
  1: '#3b82f6',
  2: '#10b981',
  3: '#f59e0b',
  4: '#f97316',
  5: '#ec4899',
}

function SessionDetail({ session, previousSession, onClose, allSessions, diverScope }: SessionDetailProps) {
  const [dives, setDives] = useState<Dive[]>([])
  const [previousDives, setPreviousDives] = useState<Dive[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedDive, setSelectedDive] = useState<Dive | null>(null)
  const overlayRef = useRef<HTMLDivElement>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<Element | null>(null)

  // Modal focus contract (same primitives as the canonical ClipViewer):
  // background inert while open, Tab trapped inside the dialog, Escape
  // closes, focus returns to the opening control.
  useEffect(() => {
    triggerRef.current = document.activeElement
    const overlay = overlayRef.current
    const dialog = dialogRef.current
    const restoreInert = overlay ? inertExcept(overlay) : undefined
    dialog?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { onClose(); return }
      if (event.key === 'Tab' && dialog) trapTabKey(dialog, event)
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      restoreInert?.()
      ;(triggerRef.current as HTMLElement | null)?.focus?.()
    }
  }, [onClose])

  useEffect(() => {
    fetchSessionDives()
  }, [session.id, diverScope])

  const fetchSessionDives = async () => {
    try {
      setLoading(true)
      const response = await api.get('/api/v1/dives', {
        params: { session_id: session.id, limit: 100, diver_scope: diverScope },
      })
      setDives(response.data || [])

      if (previousSession) {
        const prevResponse = await api.get('/api/v1/dives', {
          params: { session_id: previousSession.id, limit: 100, diver_scope: diverScope },
        })
        setPreviousDives(prevResponse.data || [])
      }
    } catch (err) {
      console.error('Error fetching dives:', err)
      setError('sessionDetail.errorLoad')
    } finally {
      setLoading(false)
    }
  }

  // Calculate height distribution
  const heightDistribution = dives.reduce((acc, dive) => {
    const existing = acc.find(d => d.name === dive.height)
    if (existing) {
      existing.value += 1
    } else {
      acc.push({ name: dive.height, value: 1 })
    }
    return acc
  }, [] as Array<{ name: string; value: number }>)

  // Performance flow over time
  const performanceFlow = dives.map((dive, index) => ({
    index: index + 1,
    performance: performanceScore10(dive.performance, dive.phase1_performance, dive.phase2_performance),
    success: isSuccessfulPerformance(dive.performance) ? 1 : 0,
  }))

  // Calculate comparison metrics
  const calculateTrend = (current: number | undefined, previous: number | undefined) => {
    if (current == null || previous == null) return null
    const diff = current - previous
    return {
      value: Math.abs(diff),
      isPositive: diff > 0,
      isNeutral: diff === 0,
    }
  }

  const perfTrend = calculateTrend(session.avg_performance, previousSession?.avg_performance)
  const successTrend = calculateTrend(session.success_rate, previousSession?.success_rate)

  const TrendIndicator = ({ trend }: { trend: any }) => {
    if (!trend) return <span className="text-app-muted">-</span>
    if (trend.isNeutral) return <Minus className="w-4 h-4 text-app-muted" />
    return trend.isPositive
      ? <TrendingUp className="w-4 h-4 text-green-400" />
      : <TrendingDown className="w-4 h-4 text-red-400" />
  }

  return (
    <div ref={overlayRef} className="fixed inset-0 z-50 overflow-y-auto bg-black/80" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className="min-h-screen p-0 sm:flex sm:items-center sm:justify-center sm:p-4">
        <div ref={dialogRef} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="session-detail-title" className="min-h-screen w-full overflow-y-auto border border-app bg-app-panel outline-none sm:min-h-0 sm:max-h-[90vh] sm:max-w-4xl sm:rounded-lg">
          {/* Header */}
          <div className="sticky top-0 flex items-center justify-between border-b border-app bg-app-panel p-4 sm:p-6">
            <div>
              <h2 id="session-detail-title" className="text-2xl font-bold text-app-text">
                {format(parseISO(session.date), 'EEEE, MMMM d, yyyy')}
              </h2>
              <p className="text-app-muted text-sm mt-1">
                {session.location || format(parseISO(session.date), 'EEEE')} • {dives.length} {i18n.t('dashboard.dives')}
              </p>
            </div>
            <button
              type="button" onClick={onClose} aria-label={i18n.t('sessionDetail.close')}
              className="touch-target p-2 hover:bg-app-panel-elevated rounded-lg transition"
            >
              <X className="w-6 h-6 text-app-muted" />
            </button>
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-16">
              <div className="w-12 h-12 border-4 border-app-accent border-t-transparent rounded-full animate-spin"></div>
            </div>
          ) : error ? (
            <div className="bg-red-500/10 border border-red-500/30 rounded-lg m-6 p-4 text-red-400">
              {i18n.t(error ?? 'sessionDetail.errorLoad')}
            </div>
          ) : (
            <div className="p-6 space-y-8">
              {/* Session Stats Overview */}
              <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                <div className="bg-app-panel-elevated rounded-lg p-4">
                  <p className="text-app-muted text-xs uppercase">{i18n.t('dashboard.totalDives')}</p>
                  <p className="text-2xl font-bold text-app-text mt-2">{session.total_dives}</p>
                </div>
                <div className="bg-app-panel-elevated rounded-lg p-4">
                  <p className="text-app-muted text-xs uppercase">{i18n.t('dashboard.avgPerformance')} /10</p>
                  <div className="flex items-center gap-2 mt-2">
                    <p className="text-2xl font-bold text-app-accent">
                      {session.avg_performance?.toFixed(1) ?? '-'}
                    </p>
                    <span className="text-app-muted text-sm">/10</span>
                    <TrendIndicator trend={perfTrend} />
                  </div>
                </div>
                <div className="bg-app-panel-elevated rounded-lg p-4">
                  <p className="text-app-muted text-xs uppercase">{i18n.t('dashboard.successRate')}</p>
                  <div className="flex items-center gap-2 mt-2">
                    <p className="text-2xl font-bold text-green-400">{session.success_rate?.toFixed(0)}%</p>
                    <TrendIndicator trend={successTrend} />
                  </div>
                </div>
                <div className="bg-app-panel-elevated rounded-lg p-4">
                  <p className="text-app-muted text-xs uppercase">{i18n.t('dashboard.personal')}</p>
                  <p className="text-2xl font-bold text-app-accent mt-2">{session.total_personal_dives}</p>
                </div>
                <div className="bg-app-panel-elevated rounded-lg p-4">
                  <p className="text-app-muted text-xs uppercase">{i18n.t('sessionDetail.bestDive')}</p>
                  <p className="text-xl font-bold text-app-accent mt-2">
                    {dives.length > 0
                      ? `${Math.max(...dives.map(d => performanceScore10(d.performance, d.phase1_performance, d.phase2_performance))).toFixed(1)} / 10`
                      : '-'}
                  </p>
                </div>
              </div>

              {/* Dive Timeline & Video Player */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Dive Sequence (Left) */}
                <div className="lg:col-span-1">
                  <h3 className="text-xl font-semibold text-app-text mb-4">{i18n.t('sessionDetail.diveSequence')}</h3>
                  <div className="space-y-2 bg-app-panel-elevated rounded-lg p-4 max-h-96 overflow-y-auto">
                    {dives.map((dive, index) => (
                      <button
                        key={dive.id}
                        onClick={() => setSelectedDive(dive)}
                        className={`w-full text-left flex items-center gap-3 pb-3 px-3 py-2 rounded-lg transition border-b border-app last:border-b-0 ${
                          selectedDive?.id === dive.id
                            ? 'bg-app-accent-soft border-app-accent'
                            : 'hover:bg-app-panel-elevated'
                        }`}
                      >
                        <div className="font-bold text-app-muted min-w-6 text-sm">{index + 1}</div>
                        <div
                          className="w-3 h-3 rounded-full flex-shrink-0"
                          style={{ backgroundColor: dive.direction ? DIRECTION_COLORS[dive.direction] : '#98a2aa' }}
                          title={directionName(dive.direction)}
                        />
                        <div className="flex-1 min-w-0">
                          <span className="font-semibold text-app-text text-sm">{dive.dive_code}</span>
                          <span className="text-app-muted mx-1.5">•</span>
                          <span className="text-xs text-app-muted">{dive.height}</span>
                          {dive.is_sync && <span className="text-xs bg-app-accent-soft text-app-accent px-1.5 py-0.5 rounded ml-1">S</span>}
                        </div>
                        <div className="flex items-center gap-2">
                          {dive.video_uuid && (
                            <Film className="w-3.5 h-3.5 text-amber-400 flex-shrink-0" aria-label={i18n.t('sessionDetail.videoAvailable')} />
                          )}
                          <div className={`px-2 py-0.5 rounded text-xs font-semibold ${performanceConfig(dive.performance).bg}`}>
                            <span className={performanceConfig(dive.performance).color}>
                              {dive.performance}
                            </span>
                          </div>
                        </div>
                      </button>
                    ))}
                  </div>
                </div>

                {/* Video Player (Right) */}
                <div className="lg:col-span-2">
                  <h3 className="text-xl font-semibold text-app-text mb-4">{i18n.t('sessionDetail.videoPlayback')}</h3>
                  <div className="bg-black rounded-lg overflow-hidden h-96 flex items-center justify-center">
                    {selectedDive && selectedDive.video_uuid ? (
                      <DiveVideoPlayer
                        diveCode={selectedDive.dive_code}
                        height={selectedDive.height}
                        videoUuid={selectedDive.video_uuid}
                      />
                    ) : (
                      <div className="text-center text-app-muted">
                        <Film className="w-12 h-12 mx-auto mb-3 opacity-50" />
                        <p className="text-sm">{i18n.t('sessionDetail.noVideoSelected')}</p>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Analytics */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                {/* Execution flow with separate difficulty context */}
                <div className="bg-app-panel-elevated rounded-lg p-4">
                  <h4 className="text-lg font-semibold text-app-text mb-4">{i18n.t('sessionDetail.performanceFlow')}</h4>
                  {performanceFlow.length > 0 ? (
                    <ResponsiveContainer width="100%" height={200}>
                      <LineChart data={performanceFlow}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(82,96,105,.35)" />
                        <XAxis dataKey="index" stroke="#98a2aa" />
                        <YAxis stroke="#98a2aa" domain={[0, 10]} />
                        <Tooltip
                          contentStyle={{ backgroundColor: '#15191c', border: '1px solid rgba(82,96,105,.45)' }}
                          formatter={(value: number) => [value.toFixed(1), `${i18n.t('analysis.execution')} /10`]}
                          labelFormatter={(value) => `${i18n.t('analysis.attempts')} ${value}`}
                        />
                        <Line type="monotone" dataKey="performance" name={`${i18n.t('analysis.execution')} /10`} stroke="#54beab" strokeWidth={2} dot={{ fill: '#54beab', r: 3 }} />
                      </LineChart>
                    </ResponsiveContainer>
                  ) : (
                    <p className="py-8 text-center text-app-muted">{i18n.t('sessionDetail.noScoredAttempts')}</p>
                  )}
                </div>

                {/* Height Distribution */}
                <div className="bg-app-panel-elevated rounded-lg p-4">
                  <h4 className="text-lg font-semibold text-app-text mb-4">{i18n.t('sessionDetail.heightDistribution')}</h4>
                  {heightDistribution.length > 0 ? (
                    <ResponsiveContainer width="100%" height={200}>
                      <BarChart data={heightDistribution}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(82,96,105,.35)" />
                        <XAxis dataKey="name" stroke="#98a2aa" />
                        <YAxis stroke="#98a2aa" />
                        <Tooltip
                          contentStyle={{ backgroundColor: '#15191c', border: '1px solid rgba(82,96,105,.45)' }}
                          formatter={(value) => `${value} ${i18n.t('dashboard.dives')}`}
                        />
                        <Bar dataKey="value" fill="#54beab" radius={[8, 8, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  ) : (
                    <p className="text-app-muted text-center py-8">{i18n.t('sessionDetail.noHeightData')}</p>
                  )}
                </div>
              </div>

              {/* Comparison with Previous Session */}
              {previousSession && (
                <div className="bg-app-accent-soft border border-app-accent rounded-lg p-4">
                  <h4 className="text-lg font-semibold text-app-text mb-4">{i18n.t('sessionDetail.comparison')}</h4>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                    <div>
                      <p className="text-app-muted text-xs uppercase mb-2">{i18n.t('dashboard.totalDives')}</p>
                      <div className="flex items-center gap-2">
                        <span className="text-app-text font-bold">{session.total_dives}</span>
                        <span className="text-app-muted text-sm">vs {previousSession.total_dives}</span>
                        {session.total_dives > previousSession.total_dives && <TrendingUp className="w-4 h-4 text-green-400" />}
                        {session.total_dives < previousSession.total_dives && <TrendingDown className="w-4 h-4 text-red-400" />}
                      </div>
                    </div>
                    <div>
                      <p className="text-app-muted text-xs uppercase mb-2">{i18n.t('dashboard.avgPerformance')}</p>
                      <div className="flex items-center gap-2">
                        <span className="text-app-accent font-bold">{session.avg_performance?.toFixed(2)}</span>
                        <span className="text-app-muted text-sm">vs {previousSession.avg_performance?.toFixed(2)}</span>
                        {perfTrend && <TrendIndicator trend={perfTrend} />}
                      </div>
                    </div>
                    <div>
                      <p className="text-app-muted text-xs uppercase mb-2">{i18n.t('dashboard.successRate')}</p>
                      <div className="flex items-center gap-2">
                        <span className="text-green-400 font-bold">{session.success_rate?.toFixed(0)}%</span>
                        <span className="text-app-muted text-sm">vs {previousSession.success_rate?.toFixed(0)}%</span>
                        {successTrend && <TrendIndicator trend={successTrend} />}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Notes */}
              {session.notes && (
                <div className="bg-app-panel-elevated rounded-lg p-4">
                  <h4 className="text-lg font-semibold text-app-text mb-2">{i18n.t('attemptDetail.notes')}</h4>
                  <p className="text-app-text">{session.notes}</p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default SessionDetail
