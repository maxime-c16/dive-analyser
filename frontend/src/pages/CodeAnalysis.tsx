import React, { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { format, formatDistanceToNowStrict, parseISO } from 'date-fns'
import { ArrowLeft, Play } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import DiveThumbnail from '../components/DiveThumbnail'
import PageLoading from '../components/PageLoading'
import ScoreChart, { type ChartPoint } from '../components/code-analysis/ScoreChart'
import CommunityPanel, { diverName, useMedia, type CommunityRow } from '../components/code-analysis/CommunityPanel'
import MemberAvatar from '../components/MemberAvatar'
import { CountUp, RatingBar, ratingCounts, ScoreChip, Segmented, Sparkline } from '../components/code-analysis/parts'
import { diveCodeName } from '../i18n/diveNames'
import { clearLibraryCache, libraryKey } from '../services/libraryCache'
import { getCodeCommunity, type CodeCommunity } from '../services/codeCommunityApi'
import { clearCodeSummaryCache, getCodeAttempts, getCodeSummaries, peekCodeAttempts, peekCodeSummaries, type CodeSummary } from '../services/codeSummariesApi'
import { attemptScore, type Attempt } from '../utils/attemptPresentation'
import { DAY_MS, mean, median, quantile, recentTrend, rolling, scoreBand, smoothingWindow, type Extreme, fmtScore } from '../utils/codeStats'
import { appLocale } from '../utils/dateLocale'
import { ATHLETE_SCORE_10 } from '../utils/performanceScoring'

const ClipViewer = lazy(() => import('../components/clip-viewer/ClipViewer'))

const PERIODS = [['1m', 30], ['3m', 91], ['1y', 365], ['all', Infinity]] as const
type Period = (typeof PERIODS)[number][0]
type Mode = 'attempts' | 'sessions'
const isAnalyticsCode = (code: string) => !/^[1-4]00/.test(code)
const ts = (attempt: Attempt) => Date.parse(attempt.dive_datetime)

function groupSessions(items: Attempt[]) {
  const groups = new Map<number, Attempt[]>()
  items.forEach(item => groups.set(item.session_id, [...(groups.get(item.session_id) ?? []), item]))
  return [...groups.values()]
}

/** Nearest to the target score; ties prefer a dive with a thumbnail, then the most recent. */
function pick(items: Attempt[], better: (a: number, b: number) => boolean) {
  return items.reduce<Attempt | null>((kept, item) => {
    if (!kept) return item
    const a = attemptScore(item), b = attemptScore(kept)
    if (better(a, b)) return item
    if (a !== b) return kept
    if (Boolean(item.thumb_url) !== Boolean(kept.thumb_url)) return item.thumb_url ? item : kept
    return ts(item) > ts(kept) ? item : kept
  }, null)
}

function relatedCodes(code: string, summaries: CodeSummary[]) {
  const reasons = new Map<string, string>()
  const base = code.slice(0, -1)
  for (const other of summaries) {
    const candidate = other.dive_code
    if (candidate === code || !other.analytics) continue
    if (candidate.slice(0, -1) === base) reasons.set(candidate, 'position')
    else if (code[0] === '5' && candidate[0] === '5' && candidate.slice(0, 3) === code.slice(0, 3)) reasons.set(candidate, 'twists')
    else if (code[0] === '5' && candidate.length === 4 && candidate[0] === code[1] && candidate[2] === code[2]) reasons.set(candidate, 'noTwist')
    else if (code[0] !== '5' && candidate.length === code.length && candidate[0] === code[0] && candidate.slice(-1) === code.slice(-1)) reasons.set(candidate, 'group')
  }
  const byCode = new Map(summaries.map(item => [item.dive_code, item]))
  return [...reasons.entries()].map(([candidate, reason]) => ({ summary: byCode.get(candidate)!, reason }))
    .sort((a, b) => b.summary.attempt_count - a.summary.attempt_count).slice(0, 6)
}

export default function CodeAnalysis() {
  const { diveCode = '' } = useParams()
  const code = diveCode.toUpperCase()
  const { t, i18n } = useTranslation()
  const lang = i18n.language?.startsWith('fr') ? 'fr' : 'en'
  const { user } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  const state = location.state as { returnTo?: unknown } | null
  const returnTo = typeof state?.returnTo === 'string' && state.returnTo.startsWith('/dives') ? state.returnTo : null
  const returnScope = returnTo ? new URLSearchParams(returnTo.split('?')[1] ?? '').get('scope') : null
  // ?diver= shows another diver's public attempts on this code, read-only.
  const diverId = Number(params.get('diver')) || null
  const scope = diverId ? 'all' : params.get('scope') || returnScope || ((!user || user.is_admin) ? 'self' : 'all')
  const fromClip = Boolean(returnTo && /[?&]clip=/.test(returnTo))
  // Library reads carry the viewer's own private dives, and the community
  // response omits the viewer's own divers: every cache entry belongs to one
  // signed-in account (same viewer key as the Library snapshot cache).
  const viewerKey = libraryKey(user)

  const [attempts, setAttempts] = useState<Attempt[] | null>(() => peekCodeAttempts(code, scope, viewerKey))
  const [summaries, setSummaries] = useState<CodeSummary[] | null>(() => peekCodeSummaries({ diver_scope: scope }, viewerKey)?.codes ?? null)
  const [error, setError] = useState<string | null>(null)
  const [reload, setReload] = useState(0)
  const [playbackRate, setPlaybackRate] = useState(1)
  const [showAllSessions, setShowAllSessions] = useState(false)
  const [extreme, setExtreme] = useState<Extreme | null>(null)
  const [community, setCommunity] = useState<CodeCommunity | null>(null)
  // The community follows the height filter only: periods would empty sparse histories.
  const communityHeight = params.get('h') || ''
  const desktop = useMedia('(min-width: 1024px)')

  useEffect(() => {
    let live = true
    setAttempts(peekCodeAttempts(code, scope, viewerKey))
    setError(null)
    getCodeAttempts(code, scope, viewerKey).then(items => { if (live) setAttempts(items) }).catch(() => { if (live) setError(t('codeAnalysis.loadError')) })
    getCodeSummaries({ diver_scope: scope }, viewerKey).then(data => { if (live) setSummaries(data.codes) }).catch(() => undefined)
    return () => { live = false }
  }, [code, scope, reload, t, viewerKey])
  useEffect(() => {
    let live = true
    setCommunity(null)
    if (isAnalyticsCode(code)) getCodeCommunity(code, communityHeight, viewerKey).then(data => { if (live) setCommunity(data) }).catch(() => undefined)
    return () => { live = false }
  }, [code, communityHeight, viewerKey])

  const period = (params.get('period') as Period) || 'all'
  const height = params.get('h') || ''
  const month = params.get('month') || ''
  const mode: Mode = params.get('mode') === 'sessions' ? 'sessions' : 'attempts'
  const focusId = Number(params.get('attempt')) || null
  const selId = Number(params.get('sel')) || null
  const clipId = Number(params.get('clip')) || null

  const update = (patch: Record<string, string | null>, push = false) => {
    const next = new URLSearchParams(params)
    Object.entries(patch).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key))
    setParams(next, { replace: !push, state: push ? { ...(location.state as object | null), codeClipOpened: true } : location.state, preventScrollReset: true })
  }

  const all = useMemo(() => diverId ? (attempts ?? []).filter(item => item.diver_id === diverId) : attempts ?? [], [attempts, diverId])
  const now = Date.now()
  const items = useMemo(() => {
    const days = PERIODS.find(([key]) => key === period)?.[1] ?? Infinity
    return all.filter(item => now - ts(item) <= days * DAY_MS && (!height || item.height === height) && (!month || item.dive_datetime.startsWith(month)))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [all, period, height, month])
  // Grades drive every score view; ungraded dives stay visible in counts and lists only.
  const scored = useMemo(() => items.filter(item => item.performance), [items])
  const scores = useMemo(() => scored.map(attemptScore), [scored])
  const analytics = isAnalyticsCode(code)
  const heights = useMemo(() => [...new Set(all.map(item => item.height))], [all])
  const sessions = useMemo(() => groupSessions(items), [items])
  const scoredGroups = useMemo(() => groupSessions(scored), [scored])

  const points: ChartPoint[] = useMemo(() => {
    const monthLabel = (value: string) => format(parseISO(value), 'MMM yy', { locale: appLocale() }).replace('.', '')
    if (mode === 'sessions') return scoredGroups.map(group => {
      const values = group.map(attemptScore), mid = median(values) as number
      return { key: group[0].id, month: group[0].dive_datetime.slice(0, 7), monthLabel: monthLabel(group[0].dive_datetime), value: mid, band: scoreBand(mid), lo: Math.min(...values), hi: Math.max(...values) }
    })
    return scored.map(item => ({ key: item.id, month: item.dive_datetime.slice(0, 7), monthLabel: monthLabel(item.dive_datetime), value: attemptScore(item), band: item.performance || 'F' }))
  }, [scored, scoredGroups, mode])
  const smoothing = smoothingWindow(points.length, mode === 'sessions')

  const pointOf = (id: number | null) => id == null ? -1 : mode === 'sessions' ? scoredGroups.findIndex(group => group.some(item => item.id === id)) : scored.findIndex(item => item.id === id)
  const selectedIndex = points.length ? (() => { const index = pointOf(selId ?? focusId); return index >= 0 ? index : points.length - 1 })() : null

  const med = median(scores), q1 = quantile(scores, 0.25), q3 = quantile(scores, 0.75)
  const best = pick(scored, (a, b) => a > b)
  const latest = items[items.length - 1] ?? null
  const latestScored = scored[scored.length - 1] ?? null
  const typical = med == null ? null : pick(scored, (a, b) => Math.abs(a - med) < Math.abs(b - med))
  const lowRecent = pick(scored.slice(-30), (a, b) => a < b)
  const showReview = items.length >= 8 && lowRecent && q1 != null && q3 != null && attemptScore(lowRecent) < q1 - 0.5 * (q3 - q1) + 0.01 && lowRecent !== best
  const reps = ([['best', best], ['latest', latestScored], ['typical', typical], ...(showReview ? [['review', lowRecent]] : [])] as Array<[string, Attempt | null]>).filter((entry): entry is [string, Attempt] => Boolean(entry[1]))
  const trend = recentTrend(all.filter(item => item.performance), attemptScore, ts, now)
  const related = useMemo(() => summaries && !diverId ? relatedCodes(code, summaries) : [], [code, summaries, diverId])
  const diver = diverId ? community?.members.find(member => member.diver_id === diverId) ?? null : null
  // You in the community ranking: every graded attempt on YOUR divers only. The
  // page scope can be 'all', which also carries the other divers' public
  // attempts, and the community endpoint already excludes your divers —
  // counting them here too would rank the community aggregate as "you".
  const ownIds = useMemo(() => new Set((user?.divers ?? []).filter(diver => diver.access_kind === 'OWNER').map(diver => diver.diver_id)), [user])
  const meRow = useMemo<CommunityRow | null>(() => {
    const graded = all.filter(item => item.diver_id != null && ownIds.has(item.diver_id) && item.performance && (!communityHeight || item.height === communityHeight)).map(attemptScore)
    if (diverId || graded.length < 3 || !user) return null
    return { key: 'me', name: user.display_name, avatar: user, count: graded.length, median: median(graded) as number,
      q1: quantile(graded, 0.25) as number, q3: quantile(graded, 0.75) as number, series: rolling(graded.slice(-40), 5) }
  }, [all, diverId, user, communityHeight, ownIds])

  // The attempt the preview describes: the tapped point, or the best/worst inside a tapped peak/valley.
  const preview = useMemo(() => {
    if (selectedIndex == null) return null
    if (extreme && extreme.index === selectedIndex) {
      const pool = mode === 'sessions' ? scoredGroups.slice(Math.max(0, selectedIndex - smoothing + 1), selectedIndex + 1).flat() : scored.slice(Math.max(0, selectedIndex - smoothing + 1), selectedIndex + 1)
      return { attempt: pick(pool, extreme.kind === 'peak' ? (a, b) => a > b : (a, b) => a < b)!, pool }
    }
    const attempt = mode === 'sessions' ? pick(scoredGroups[selectedIndex] ?? [], (a, b) => a > b) : scored[selectedIndex]
    return attempt ? { attempt, pool: null as Attempt[] | null } : null
  }, [selectedIndex, extreme, items, sessions, mode, smoothing])

  const focus = focusId ? all.find(item => item.id === focusId) ?? null : null
  const date = (value: string, pattern = 'd MMM yyyy') => format(parseISO(value), pattern, { locale: appLocale() })
  const rank = (attempt: Attempt, pool: Attempt[]) => 1 + pool.filter(item => attemptScore(item) > attemptScore(attempt)).length
  const rankText = (value: number, total: number) => value === 1 ? t('codeAnalysis.rankFirst', { total }) : t('codeAnalysis.rankOf', { rank: value, total })
  const openClip = (id: number) => update({ clip: String(id) }, true)
  const closeClip = () => { if ((location.state as { codeClipOpened?: boolean } | null)?.codeClipOpened) navigate(-1); else update({ clip: null }) }
  // "Analyse" inside the viewer returns here focused on that dive once the viewer entry is gone.
  const pendingSelection = useRef<number | null>(null)
  useEffect(() => {
    if (clipId || pendingSelection.current == null) return
    const id = pendingSelection.current
    pendingSelection.current = null
    update({ sel: String(id) })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clipId])
  const viewerList = useMemo(() => [...items].reverse(), [items])
  const viewerAttempt = clipId ? all.find(item => item.id === clipId) ?? null : null

  const back = () => diverId
    ? ((location.state as { codeDiverOpened?: boolean } | null)?.codeDiverOpened ? navigate(-1) : update({ diver: null, clip: null, sel: null }))
    : returnTo ? navigate(returnTo) : navigate(`/dives?view=codes${scope !== 'self' ? `&scope=${scope}` : ''}`)
  const openDiver = (id: number, clip?: number) => navigate(`/dives/analysis/${encodeURIComponent(code)}?diver=${id}${clip ? `&clip=${clip}` : ''}`,
    { state: { ...(location.state as object | null), codeDiverOpened: true } })
  const communityPanel = !diverId && meRow && community && community.members.length > 0
    ? <CommunityPanel me={meRow} members={community.members} hidden={community.hidden_count} height={communityHeight}
        onWatch={(member, id) => openDiver(member.diver_id, id)} onAnalysis={member => openDiver(member.diver_id)} />
    : null

  if (!attempts && !error) return <div className="ca ca-page"><div className="ca-skeleton" style={{ height: 120 }} /><div className="ca-skeleton" style={{ height: 80 }} /><div className="ca-skeleton" style={{ height: 260 }} /></div>
  if (error && !attempts) return <div className="ca ca-page"><div className="ca-note" role="alert">{error} <button type="button" className="ca-btn" onClick={() => setReload(value => value + 1)}>{t('common.retry')}</button></div></div>

  const name = diveCodeName(code, lang)
  const dd = all.find(item => item.official_dd)?.official_dd
  const heightRows = heights.length > 1 ? heights.map(value => { const pool = all.filter(item => item.height === value); return { value, count: pool.length, median: median(pool.filter(item => item.performance).map(attemptScore)) as number } }).filter(row => row.count >= 3).sort((a, b) => b.count - a.count) : []
  const phased = items.filter(item => item.performance && item.phase1_performance && item.phase2_performance)
  const phaseRows = phased.length >= 5 ? (['phase1_performance', 'phase2_performance'] as const).map((key, index) => ({ key, label: t('codeAnalysis.phase', { n: index + 1 }), count: phased.length, median: median(phased.map(item => ({ F: 0, B: 2, M: 4.5, G: 7, P: 10 } as Record<string, number>)[item[key]!] ?? 0)) as number })) : []
  const shownSessions = [...sessions].reverse().slice(0, showAllSessions ? undefined : 6)

  const bar = (label: React.ReactNode, count: number, value: number, pressed?: boolean, onClick?: () => void) => {
    const content = <>
      <span>{label}<small>{t('codeAnalysis.attemptsShort', { count })}</small></span>
      <span className="ca-bar-track"><span className={`ca-bar-fill ca-r-${scoreBand(value)}`} style={{ width: `${Math.max(3, value * 10)}%` }} /></span>
      <b>{fmtScore(value)}</b>
    </>
    return onClick ? <button type="button" className="ca-bar" aria-pressed={pressed} onClick={onClick}>{content}</button> : <div className="ca-bar">{content}</div>
  }

  return <>
  <div className="ca ca-page ca-arrive">
    <div className="ca-span">
      <div className="ca-topbar"><button type="button" className="ca-back" onClick={back}><ArrowLeft className="h-4 w-4" aria-hidden="true" />{diverId ? ((location.state as { fromProfile?: boolean } | null)?.fromProfile ? t('common.back') : t('codeAnalysis.community.backToMine')) : fromClip ? t('analysis.backToClip') : t('notFound.backToLibrary')}</button>
      {diverId && <div className="ca-diver-chip">{diver && <MemberAvatar member={diver.account ?? { display_name: diverName(diver) }} size={32} />}<b>{diver ? diverName(diver) : '…'}</b></div>}</div>
      <div className="ca-hero">
        <div><h1 className="ca-hero-code">{code}</h1><p className="ca-hero-name">{name !== code ? name : ''}{dd ? ` · DD ${fmtScore(dd)}` : ''}</p></div>
        {analytics && <div className="ca-hero-trend">
          {trend == null ? latest && <><strong className="ca-flat">{formatDistanceToNowStrict(parseISO(all[all.length - 1].dive_datetime), { locale: appLocale() })}</strong><span>{t('codeAnalysis.sinceLastAttempt')}</span></> : <>
            <strong className={trend >= 0.5 ? 'ca-up' : trend <= -0.5 ? 'ca-down' : undefined}>{Math.abs(trend) < 0.5 ? t('codeAnalysis.stable') : `${trend > 0 ? '▲ +' : '▼ '}${fmtScore(trend)}`}</strong>
            <span>{trend >= 0.5 ? t('codeAnalysis.rising') : trend <= -0.5 ? t('codeAnalysis.falling') : t('codeAnalysis.median')} · {t('codeAnalysis.sixWeeks')}</span>
          </>}
        </div>}
      </div>
    </div>
    <div className="ca-span ca-scroll">
      <Segmented label={t('codeAnalysis.periodAria')} value={month ? null : period} onChange={value => update({ period: value === 'all' ? null : value, month: null, sel: null })}
        options={PERIODS.map(([key]) => [key, t(`codeAnalysis.period.${key}`)] as const)} />
      {heights.length > 1 && <span className="ca-divider" aria-hidden="true" />}
      {heights.length > 1 && heights.map(value => <button key={value} type="button" className="ca-pill" aria-pressed={height === value} onClick={() => update({ h: height === value ? null : value, sel: null })}>{value}</button>)}
      {month && <button type="button" className="ca-pill" aria-pressed="true" onClick={() => update({ month: null, sel: null })}>{format(parseISO(`${month}-01`), 'MMMM yyyy', { locale: appLocale() })} ✕</button>}
    </div>

    {!analytics && <div className="ca-span ca-note">{t('codeAnalysis.straightJump')}</div>}
    {!items.length ? <div className="ca-span ca-note">{t('codeAnalysis.emptyPeriod', { code })} <button type="button" className="ca-btn" onClick={() => update({ period: null, h: null, month: null })}>{t('codeAnalysis.showAll')}</button></div> : <>
      <div className="ca-main">
        {analytics && <div>
          <dl className="ca-kpis" style={{ margin: 0 }} aria-label={t('codeAnalysis.summary')}>
            <div className="ca-kpi"><dt>{t('codeAnalysis.average')}</dt><dd><CountUp value={mean(scores)} /></dd></div>
            <div className="ca-kpi"><dt>{t('codeAnalysis.median')}</dt><dd><CountUp value={med} /></dd></div>
            <div className="ca-kpi"><dt>{t('dives.best')}</dt><dd className="ca-t-P"><CountUp value={scores.length ? Math.max(...scores) : null} /></dd></div>
            <div className="ca-kpi"><dt>{t('codeAnalysis.success')}</dt><dd><CountUp value={scored.length ? 100 * scored.filter(item => attemptScore(item) >= ATHLETE_SCORE_10.G).length / scored.length : null} digits={0} suffix="%" /></dd></div>
          </dl>
          <div style={{ marginTop: 10 }}><RatingBar ratings={ratingCounts(items.map(item => item.performance))} /></div>
          <p className="ca-sample">{t('codeAnalysis.sample', { attempts: items.length, sessions: sessions.length, from: date(items[0].dive_datetime), to: date(latest!.dive_datetime) })}</p>
        </div>}

        {focus && analytics && (() => {
          const before = all.filter(item => ts(item) < ts(focus)), previous = before[before.length - 1]
          const delta = attemptScore(focus) - (median(all.filter(item => item.performance).map(attemptScore)) as number)
          const beaten = [...before].reverse().find(item => attemptScore(item) >= attemptScore(focus))
          const weeks = beaten ? Math.round((ts(focus) - ts(beaten)) / (7 * DAY_MS)) : null
          return <button type="button" className="ca-focus" onClick={() => openClip(focus.id)}>
            <span className="ca-thumb"><DiveThumbnail dive={focus} compact /></span>
            <span>
              <b className="text-app-text">{t('codeAnalysis.thisDive')} · <span className={`ca-t-${focus.performance}`}>{fmtScore(attemptScore(focus))}</span></b> <span className="ca-flat" style={{ fontSize: 12 }}>{date(focus.dive_datetime, 'd MMM · HH:mm')}</span>
              <span className="ca-focus-facts">
                <span className="ca-fact">{rankText(rank(focus, all), all.length)}</span>
                <span className={`ca-fact ${delta >= 0.25 ? 'ca-up' : delta <= -0.25 ? 'ca-down' : ''}`}>{delta >= 0 ? '+' : ''}{fmtScore(delta)} {t('codeAnalysis.vsMedian')}</span>
                {previous && <span className={`ca-fact ${attemptScore(focus) > attemptScore(previous) ? 'ca-up' : attemptScore(focus) < attemptScore(previous) ? 'ca-down' : ''}`}>{attemptScore(focus) > attemptScore(previous) ? '▲' : attemptScore(focus) < attemptScore(previous) ? '▼' : '='} {t('codeAnalysis.vsPreviousDive', { score: fmtScore(attemptScore(previous)) })}</span>}
                {!beaten && before.length > 0 && <span className="ca-fact ca-up">{t('codeAnalysis.record')}</span>}
                {weeks != null && weeks >= 3 && <span className="ca-fact ca-up">{t('codeAnalysis.bestSince', { count: weeks })}</span>}
              </span>
            </span>
          </button>
        })()}

        {analytics && <section className="ca-panel">
          <div className="ca-panel-h"><h2>{t('codeAnalysis.scores')}</h2>
            <Segmented label={t('codeAnalysis.chartModeAria')} value={mode} onChange={value => { setExtreme(null); update({ mode: value === 'attempts' ? null : value, sel: null }) }}
              options={[['attempts', t('codeAnalysis.modeAttempts')], ['sessions', t('codeAnalysis.modeSessions')]] as const} /></div>
          <ScoreChart points={points} smoothing={smoothing} selected={selectedIndex} label={t('codeAnalysis.chartLabel', { count: points.length, code })}
            onSelect={(index, mark) => {
              setExtreme(mark ?? null)
              const id = mode === 'sessions' ? scoredGroups[index]?.[0]?.id : scored[index]?.id
              if (id) update({ sel: String(id) })
            }} />
          <div className="ca-legend"><span><i />{t('codeAnalysis.legendMedian')}</span><span><i className="ca-legend-band" />{t('codeAnalysis.legendRange')}</span><span className="ca-t-P">▲ {t('codeAnalysis.peak')}</span><span className="ca-t-B">▼ {t('codeAnalysis.valley')}</span></div>
          {preview && <div className="ca-preview" key={`${preview.attempt.id}-${extreme?.index ?? ''}`}>
            <span className="ca-thumb"><DiveThumbnail dive={preview.attempt} compact /></span>
            <div style={{ minWidth: 0 }}>
              <div><span className={`ca-preview-score ca-t-${preview.attempt.performance}`}>{fmtScore(attemptScore(preview.attempt))}</span> <span className="ca-flat">{preview.attempt.performance}{preview.attempt.phase1_performance && preview.attempt.phase2_performance ? ` · ${preview.attempt.phase1_performance}/${preview.attempt.phase2_performance}` : ''}</span></div>
              <div className="ca-preview-sub">{date(preview.attempt.dive_datetime, 'd MMM · HH:mm')} · {preview.attempt.height} · {rankText(rank(preview.attempt, items), items.length)}</div>
              {preview.pool && extreme && <div className={`ca-preview-why ${extreme.kind === 'peak' ? 'ca-t-P' : 'ca-t-B'}`}>
                {t(extreme.kind === 'peak' ? 'codeAnalysis.peakExplain' : 'codeAnalysis.valleyExplain', { median: fmtScore(extreme.value), count: preview.pool.length, from: date(preview.pool[0].dive_datetime, 'd MMM'), to: date(preview.pool[preview.pool.length - 1].dive_datetime, 'd MMM') })}
              </div>}
            </div>
            <button type="button" className="ca-btn" onClick={() => openClip(preview.attempt.id)}><Play className="h-4 w-4" aria-hidden="true" />{t('codeAnalysis.watch')}</button>
          </div>}
        </section>}

        <div className="ca-two">
          {analytics && (heightRows.length > 0 || phaseRows.length > 0) && <section className="ca-panel">
            <div className="ca-panel-h"><h2>{t('codeAnalysis.context')}</h2><span>{t('codeAnalysis.median')}</span></div>
            <div className="ca-bars">
              {heightRows.map(row => <React.Fragment key={row.value}>{bar(row.value, row.count, row.median, height === row.value, () => update({ h: height === row.value ? null : row.value, sel: null }))}</React.Fragment>)}
              {phaseRows.map(row => <React.Fragment key={row.key}>{bar(row.label, row.count, row.median)}</React.Fragment>)}
            </div>
            {phaseRows.length === 2 && <p className="ca-sample">{phaseRows[1].median < phaseRows[0].median - 0.4 ? t('codeAnalysis.phase2Costs') : phaseRows[1].median > phaseRows[0].median + 0.4 ? t('codeAnalysis.phase1Costs') : t('codeAnalysis.phasesEven')}</p>}
          </section>}
          <section className="ca-panel">
            <div className="ca-panel-h"><h2>{t('codeAnalysis.sessions')}</h2><span>{sessions.length}</span></div>
            {shownSessions.map(group => { const mid = median(group.filter(item => item.performance).map(attemptScore)) as number; return <div key={group[0].session_id} className="ca-sess">
              <div className="ca-sess-date">{date(group[0].dive_datetime, 'd MMM')}<small>{t('codeAnalysis.attemptsShort', { count: group.length })} · {group[0].height}</small></div>
              <div className="ca-chips">{group.map(item => <ScoreChip key={item.id} id={item.id} performance={item.performance} score={attemptScore(item)} onOpen={openClip}
                label={t('dives.openAttemptFrom', { code, date: date(item.dive_datetime, 'd MMM HH:mm') })} />)}</div>
              <b className={analytics ? `ca-t-${scoreBand(mid)}` : undefined}>{analytics ? fmtScore(mid) : ''}</b>
            </div> })}
            {sessions.length > 6 && <button type="button" className="ca-btn" style={{ marginTop: 10, border: 0, padding: 0 }} onClick={() => setShowAllSessions(value => !value)}>
              {showAllSessions ? t('codeAnalysis.fewerSessions') : t('codeAnalysis.allSessions', { count: sessions.length })}</button>}
          </section>
        </div>
        {desktop && communityPanel}
        {analytics && !diverId && <Link to={`/dives/analysis/${encodeURIComponent(code)}/details`} state={location.state} className="ca-flat" style={{ fontSize: 13 }}>{t('codeAnalysis.details')}</Link>}
      </div>

      <div className="ca-aside">
        <section className="ca-panel">
          <div className="ca-panel-h"><h2>{t('codeAnalysis.representatives')}</h2></div>
          <div className="ca-reps">{reps.map(([role, attempt]) => <button key={role} type="button" className="ca-rep" onClick={() => openClip(attempt.id)}>
            <span className="ca-thumb" style={{ display: 'block' }}><DiveThumbnail dive={attempt} compact />{analytics && <span className={`ca-rep-badge ca-r-${attempt.performance}`}>{fmtScore(attemptScore(attempt))}</span>}</span>
            <span className="ca-rep-cap"><b>{t(`codeAnalysis.rep.${role}`)}</b><span>{date(attempt.dive_datetime, 'd MMM')}</span></span>
          </button>)}</div>
        </section>
        {!desktop && communityPanel}
        {related.length > 0 && <section className="ca-panel">
          <div className="ca-panel-h"><h2>{t('codeAnalysis.related')}</h2></div>
          <div className="ca-related">{related.map(({ summary, reason }) => <Link key={summary.dive_code} className="ca-rel" to={`/dives/analysis/${encodeURIComponent(summary.dive_code)}`} state={{ returnTo: returnTo ?? undefined }}>
            <span className="ca-rel-code">{summary.dive_code}</span>
            <span className="ca-rel-why">{t(`codeAnalysis.relation.${reason}`)}</span>
            <span className="ca-rel-foot"><span>{t('codeAnalysis.median')} <b>{fmtScore(summary.median)}</b><small>{t('codeAnalysis.attemptsShort', { count: summary.attempt_count })}</small></span><Sparkline values={summary.spark} width={56} height={22} /></span>
          </Link>)}</div>
        </section>}
      </div>
    </>}

  </div>
    {/* Outside the animated page: a transformed ancestor would anchor the fixed viewer to the page instead of the screen. */}
    {viewerAttempt && <Suspense fallback={<PageLoading message={t('dives.openingVideo')} />}>
      <ClipViewer attempt={viewerAttempt} attempts={viewerList.some(item => item.id === viewerAttempt.id) ? viewerList : [viewerAttempt]}
        onClose={closeClip} onMove={next => update({ clip: String(next.id) })}
        playbackRate={playbackRate} onPlaybackRateChange={setPlaybackRate}
        onAnalyse={next => { setExtreme(null); pendingSelection.current = next.id; closeClip() }}
        onUpdate={updated => { clearLibraryCache(); clearCodeSummaryCache(); setAttempts(current => current?.map(item => item.id === updated.id ? { ...item, ...updated } : item) ?? current) }}
        onDelete={() => { clearLibraryCache(); clearCodeSummaryCache(); setAttempts(current => current?.filter(item => item.id !== viewerAttempt.id) ?? current); update({ clip: null }) }} />
    </Suspense>}
  </>
}
