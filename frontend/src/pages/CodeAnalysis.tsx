import TechniqueWorkspace from '../components/code-analysis/TechniqueWorkspace'
import type { ScorePanel } from '../components/code-analysis/CorrectionScores'
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { loadChunk } from '../utils/chunkLoad'
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
import { MobileShellActions } from '../navigation/mobileShellActions'
import { ScoreChip, Segmented } from '../components/code-analysis/parts'
import { diveCodeName } from '../i18n/diveNames'
import { clearLibraryCache, libraryKey } from '../services/libraryCache'
import { getCodeCommunity, type CodeCommunity } from '../services/codeCommunityApi'
import { clearCodeSummaryCache, getCodeAttemptsResult, getCodeSummaries, peekCodeAttemptsResult, peekCodeSummaries, type CodeSummary } from '../services/codeSummariesApi'
import { attemptScore, type Attempt } from '../utils/attemptPresentation'
import { DAY_MS, median, quantile, recentTrend, rolling, scoreBand, smoothingWindow, type Extreme, fmtScore } from '../utils/codeStats'
import { appLocale } from '../utils/dateLocale'

const ClipViewer = lazy(() => loadChunk(() => import('../components/clip-viewer/ClipViewer')))

const PERIODS = [['1m', 30], ['3m', 91], ['1y', 365], ['all', Infinity]] as const
type Period = (typeof PERIODS)[number][0]
type Mode = 'attempts' | 'sessions' | 'corrections'
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
  // Too few graded dives make a median noise: drop them before keeping the six most practised.
  const byCode = new Map(summaries.map(item => [item.dive_code, item]))
  // Weakest first (ties: more graded dives), then the six to show: the list answers "what should I work on next".
  return [...reasons.entries()].map(([candidate, reason]) => ({ summary: byCode.get(candidate)!, reason })).filter(({ summary }) => summary.scored_count >= 5)
    .sort((a, b) => (a.summary.median ?? 0) - (b.summary.median ?? 0) || b.summary.scored_count - a.summary.scored_count).slice(0, 6)
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

  const [attempts, setAttempts] = useState<Attempt[] | null>(() => peekCodeAttemptsResult(code, scope, viewerKey, diverId)?.items ?? null)
  const [attemptsCapped, setAttemptsCapped] = useState<boolean>(() => peekCodeAttemptsResult(code, scope, viewerKey, diverId)?.capped ?? false)
  const [summaries, setSummaries] = useState<CodeSummary[] | null>(() => peekCodeSummaries({ diver_scope: scope }, viewerKey)?.codes ?? null)
  const [error, setError] = useState<string | null>(null)
  const [reload, setReload] = useState(0)
  const [playbackRate, setPlaybackRate] = useState(1)
  const [showAllSessions, setShowAllSessions] = useState(false)
  const [extreme, setExtreme] = useState<Extreme | null>(null)
  const [community, setCommunity] = useState<CodeCommunity | null>(null)
  const [heightSummaries, setHeightSummaries] = useState<CodeSummary[] | null>(null)
  // The community follows the height filter only: periods would empty sparse histories.
  const communityHeight = params.get('h') || ''
  const desktop = useMedia('(min-width: 1024px)')
  const [adjustmentSlot, setAdjustmentSlot] = useState<HTMLElement | null>(null)

  useEffect(() => {
    let live = true
    setAttempts(peekCodeAttemptsResult(code, scope, viewerKey, diverId)?.items ?? null)
    setAttemptsCapped(peekCodeAttemptsResult(code, scope, viewerKey, diverId)?.capped ?? false)
    setError(null)
    getCodeAttemptsResult(code, scope, viewerKey, diverId).then(result => { if (live) { setAttempts(result.items); setAttemptsCapped(result.capped) } }).catch(() => { if (live) setError(t('codeAnalysis.loadError')) })
    getCodeSummaries({ diver_scope: scope }, viewerKey).then(data => { if (live) setSummaries(data.codes) }).catch(() => undefined)
    // diverId participates: switching the selected diver on the same code
    // refetches the diver-scoped walk instead of leaving the previous
    // diver's rows mounted with an unchanged all-scope value.
    return () => { live = false }
  }, [code, scope, diverId, reload, t, viewerKey])
  // Nearby codes compare like with like: with a height filter, their medians come from that height only.
  useEffect(() => {
    let live = true
    setHeightSummaries(null)
    if (communityHeight && !diverId) getCodeSummaries({ diver_scope: scope, height: communityHeight }, viewerKey).then(data => { if (live) setHeightSummaries(data.codes) }).catch(() => undefined)
    return () => { live = false }
  }, [scope, communityHeight, diverId, viewerKey])
  useEffect(() => {
    let live = true
    setCommunity(null)
    if (isAnalyticsCode(code)) getCodeCommunity(code, communityHeight, viewerKey).then(data => { if (live) setCommunity(data) }).catch(() => undefined)
    return () => { live = false }
  }, [code, communityHeight, viewerKey])

  const height = params.get('h') || ''
  const month = params.get('month') || ''
  const canViewCorrections = Boolean(user && !diverId)
  const requestedMode = params.get('mode')
  const mode: Mode = requestedMode === 'sessions' ? 'sessions' : requestedMode === 'corrections' && canViewCorrections ? 'corrections' : 'attempts'
  const focusId = Number(params.get('attempt')) || null
  const selId = Number(params.get('sel')) || null
  const clipId = Number(params.get('clip')) || null

  const update = (patch: Record<string, string | null>, push = false) => {
    const next = new URLSearchParams(params)
    Object.entries(patch).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key))
    setParams(next, { replace: !push, state: push ? { ...(location.state as object | null), codeClipOpened: true } : location.state, preventScrollReset: true })
  }

  // The 'all' scope also carries strangers' public dives: this page keeps the divers you follow; strangers stay in the community panel.
  const followedIds = useMemo(() => new Set((user?.divers ?? []).map(diver => diver.diver_id)), [user])
  const all = useMemo(() => diverId ? (attempts ?? []).filter(item => item.diver_id === diverId)
    : scope === 'all' && followedIds.size ? (attempts ?? []).filter(item => item.diver_id != null && followedIds.has(item.diver_id)) : attempts ?? [],
  [attempts, diverId, scope, followedIds])
  const now = Date.now()
  // Default period adapts to the code: the shortest window holding 30 graded dives, so a busy code opens on recent work and a rare one on its whole history.
  // Arriving from a clip, the window must also contain that clip so the page describes it.
  const focusAt = useMemo(() => { const id = Number(params.get('attempt')) || null; const found = id ? all.find(item => item.id === id) : null; return found ? ts(found) : null }, [all, params])
  const defaultPeriod: Period = useMemo(() => (['3m', '1y'] as const).find(key => {
    const days = PERIODS.find(([value]) => value === key)![1]
    return all.filter(item => item.performance && now - ts(item) <= days * DAY_MS).length >= 30 && (focusAt == null || now - focusAt <= days * DAY_MS)
  }) ?? 'all',
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [all, focusAt])
  const requestedPeriod = params.get('period')
  const period: Period = PERIODS.find(([key]) => key === requestedPeriod)?.[0] ?? defaultPeriod
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
  // Full-scope total for the capped-window note (server summary, never the
  // bounded client list itself). In a selected-diver view the summaries
  // cover the WHOLE scope — the diver's own total is unavailable, so the
  // denominator is omitted instead of claiming a cross-population count.
  // In the all-scope view the denominator is likewise unavailable while the
  // matching per-code summary is pending or failed: a bounded, period-
  // filtered or empty items slice never poses as the whole-history total —
  // the count-free cap notice covers the gap until the summary matches.
  const attemptsTotal: number | null = useMemo(() => diverId ? null
    : summaries?.find(item => item.dive_code === code)?.attempt_count ?? null,
  [diverId, summaries, code])
  const sessions = useMemo(() => groupSessions(items), [items])
  const scoredGroups = useMemo(() => groupSessions(scored), [scored])

  const points: ChartPoint[] = useMemo(() => {
    const monthLabel = (value: string) => format(parseISO(value), 'MMM yy', { locale: appLocale() }).replace('.', '')
    if (mode === 'sessions') return scoredGroups.map(group => {
      const values = group.map(attemptScore), mid = median(values) as number
      return { key: group[0].id, occurredAt: ts(group[0]), month: group[0].dive_datetime.slice(0, 7), monthLabel: monthLabel(group[0].dive_datetime), value: mid, band: scoreBand(mid), lo: Math.min(...values), hi: Math.max(...values) }
    })
    return scored.map(item => ({ key: item.id, occurredAt: ts(item), month: item.dive_datetime.slice(0, 7), monthLabel: monthLabel(item.dive_datetime), value: attemptScore(item), band: item.performance || 'F' }))
  }, [scored, scoredGroups, mode, i18n.language])
  const smoothing = smoothingWindow(points.length, mode === 'sessions')
  // Calendar spacing once the history spans two months, so long breaks look long; shorter spans keep one slot per dive.
  const timeAxis = desktop && points.length > 1 && (points[points.length - 1].occurredAt ?? 0) - (points[0].occurredAt ?? 0) >= 60 * DAY_MS

  const pointOf = (id: number | null) => id == null ? -1 : mode === 'sessions' ? scoredGroups.findIndex(group => group.some(item => item.id === id)) : scored.findIndex(item => item.id === id)
  // A selection outside the filtered dives selects nothing rather than another dive.
  const selectedIndex = points.length ? (() => { const wanted = selId ?? focusId; const index = pointOf(wanted); return index >= 0 ? index : wanted == null ? points.length - 1 : null })() : null

  const med = median(scores)
  const best = pick(scored, (a, b) => a > b)
  const latest = items[items.length - 1] ?? null
  const latestScored = scored[scored.length - 1] ?? null
  const typical = med == null ? null : pick(scored, (a, b) => Math.abs(a - med) < Math.abs(b - med))
  const lowest = pick(scored, (a, b) => a < b)
  // Latest, best and lowest recent first: they answer "how was today" and "what to fix"; the median dive comes last.
  // Best and lowest come from the same filtered dives; a clip filling two roles shows once with both names.
  const reps = (([['latest', latestScored], ['best', best], ['review', lowest], ['typical', typical]] as Array<[string, Attempt | null]>)
    .reduce<Array<[string[], Attempt]>>((list, [role, attempt]) => {
      if (!attempt) return list
      const same = list.find(([, kept]) => kept.id === attempt.id)
      if (same) same[0].push(role); else list.push([[role], attempt])
      return list
    }, []))
  // The trend compares one height with itself: mixing heights turns a switch from 3m to 1m into a fake drop.
  const trendHeight = height || latest?.height || ''
  // Same evidence bar as the adjustment effects (8 graded dives per side); a month view has no "last 6 weeks".
  const trend = month ? null : recentTrend(all.filter(item => item.performance && (!trendHeight || item.height === trendHeight)), attemptScore, ts, now, 8)
  const nearbySource = communityHeight ? heightSummaries : summaries
  const related = useMemo(() => nearbySource && !diverId ? relatedCodes(code, nearbySource) : [], [code, nearbySource, diverId])
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

  // Same title row as the other pages: back pill, then the shell's notifications + account on mobile.
  const diverChip = diverId ? <div className="ca-diver-chip">{diver && <MemberAvatar member={diver.account ?? { display_name: diverName(diver) }} size={32} />}<b>{diver ? diverName(diver) : '…'}</b></div> : null
  const topbar = <>
    <div className="ca-topbar"><button type="button" className="ca-back" onClick={back}><ArrowLeft className="h-4 w-4" aria-hidden="true" /><span>{diverId ? ((location.state as { fromProfile?: boolean } | null)?.fromProfile ? t('common.back') : t('codeAnalysis.community.backToMine')) : fromClip ? t('analysis.backToClip') : t('notFound.backToLibrary')}</span></button>
      {diverChip}<span className="ca-topbar-fill" /><MobileShellActions /></div>
    {diverChip && <div className="ca-topbar-chip">{diverChip}</div>}
  </>

  if (!attempts && !error) return <div className="ca ca-page"><div className="ca-span">{topbar}</div><div className="ca-skeleton" style={{ height: 120 }} /><div className="ca-skeleton" style={{ height: 80 }} /><div className="ca-skeleton" style={{ height: 260 }} /></div>
  if (error && !attempts) return <div className="ca ca-page"><div className="ca-span">{topbar}</div><div className="ca-note" role="alert">{error} <button type="button" className="ca-btn" onClick={() => setReload(value => value + 1)}>{t('common.retry')}</button></div></div>

  const name = diveCodeName(code, lang)
  const dd = all.find(item => item.official_dd)?.official_dd
  const shownSessions = [...sessions].reverse().slice(0, showAllSessions ? undefined : 6)


  const calendarMonth = /^\d{4}-(0[1-9]|1[0-2])$/.test(month) ? new Date(`${month}-01T00:00:00Z`) : null
  const days = PERIODS.find(([key]) => key === period)?.[1] ?? Infinity
  const from = Math.max(calendarMonth?.getTime() ?? -Infinity, now - days * DAY_MS)
  const until = calendarMonth ? Date.UTC(calendarMonth.getUTCFullYear(), calendarMonth.getUTCMonth() + 1, 1) : undefined
  const scoreModes: Array<readonly [Mode, string]> = [['attempts', t('codeAnalysis.modeAttempts')], ['sessions', t('codeAnalysis.modeSessions')]]
  if (canViewCorrections) scoreModes.push(['corrections', t('codeAnalysis.modeCorrections')])
  const scorePanel: ScorePanel | undefined = analytics ? {
    header: <div className="ca-panel-h ca-scores-header"><h2>{t('codeAnalysis.scores')}</h2>
      <Segmented label={t('codeAnalysis.chartModeAria')} value={mode} onChange={value => { setExtreme(null); update({ mode: value === 'attempts' ? null : value, sel: null }) }}
        options={scoreModes} /></div>,
    corrections: mode === 'corrections' ? { attempts: all, from: Number.isFinite(from) ? from : undefined, until } : undefined,
    content: <>
      <ScoreChart simple timeScale={timeAxis} points={points} smoothing={smoothing} selected={selId == null && focusId == null ? null : selectedIndex} label={t('codeAnalysis.chartLabel', { count: points.length, code })}
        onSelect={(index, mark) => {
          setExtreme(mark ?? null)
          const id = mode === 'sessions' ? scoredGroups[index]?.[0]?.id : scored[index]?.id
          if (id) update({ sel: String(id) })
        }} />
      {preview && selId != null && <div aria-live="polite" className="ca-preview" key={`${preview.attempt.id}-${extreme?.index ?? ''}`}>
        <span className="ca-thumb"><DiveThumbnail dive={preview.attempt} compact /></span>
        <div style={{ minWidth: 0 }}>
          <div><span className={`ca-preview-score ca-t-${preview.attempt.performance}`}>{fmtScore(attemptScore(preview.attempt))}</span> <span className="ca-flat">{preview.attempt.performance}{preview.attempt.phase1_performance && preview.attempt.phase2_performance ? ` · ${preview.attempt.phase1_performance}/${preview.attempt.phase2_performance}` : ''}</span></div>
          <div className="ca-preview-sub">{date(preview.attempt.dive_datetime, 'd MMM · HH:mm')} · {preview.attempt.height} · {rankText(rank(preview.attempt, scored), scored.length)}</div>
          {preview.pool && extreme && <div className={`ca-preview-why ${extreme.kind === 'peak' ? 'ca-t-P' : 'ca-t-B'}`}>
            {t(extreme.kind === 'peak' ? 'codeAnalysis.peakExplain' : 'codeAnalysis.valleyExplain', { median: fmtScore(extreme.value), count: preview.pool.length, from: date(preview.pool[0].dive_datetime, 'd MMM'), to: date(preview.pool[preview.pool.length - 1].dive_datetime, 'd MMM') })}
          </div>}
        </div>
        <button type="button" className="ca-btn" onClick={() => openClip(preview.attempt.id)}><Play className="h-4 w-4" aria-hidden="true" />{t('codeAnalysis.watch')}</button>
      </div>}
    </>,
  } : undefined


  const focusCard = items.length > 0 && focus && analytics && (() => {
          // An ungraded clip has no score: show a dash and no rank or comparison.
          if (!focus.performance) return <button type="button" className="ca-focus" onClick={() => openClip(focus.id)}>
            <span className="ca-thumb"><DiveThumbnail dive={focus} compact /></span>
            <span><b className="text-app-text">{t('codeAnalysis.thisDive')} · <span className="ca-flat">—</span></b> <span className="ca-flat" style={{ fontSize: 12 }}>{date(focus.dive_datetime, 'd MMM · HH:mm')}</span></span>
          </button>
          // Same dives as the headline: the selected period and height. A clip outside them gets no rank or comparison.
          const graded = scored
          const inSample = graded.some(item => item.id === focus.id)
          const before = graded.filter(item => ts(item) < ts(focus)), previous = before[before.length - 1]
          const delta = attemptScore(focus) - (med ?? 0)
          const beaten = [...before].reverse().find(item => attemptScore(item) >= attemptScore(focus))
          const weeks = beaten ? Math.round((ts(focus) - ts(beaten)) / (7 * DAY_MS)) : null
          return <button type="button" className="ca-focus" onClick={() => openClip(focus.id)}>
            <span className="ca-thumb"><DiveThumbnail dive={focus} compact /></span>
            <span>
              <b className="text-app-text">{t('codeAnalysis.thisDive')} · <span className={`ca-t-${focus.performance}`}>{fmtScore(attemptScore(focus))}</span></b> <span className="ca-flat" style={{ fontSize: 12 }}>{date(focus.dive_datetime, 'd MMM · HH:mm')}</span>
              {inSample && <span className="ca-focus-facts">
                {<span className="ca-fact" title={t('codeAnalysis.rankTitle', { total: graded.length })}>{rankText(rank(focus, graded), graded.length)}</span>}
                {med != null && Math.abs(delta) >= 0.05 && <span className={`ca-fact ${delta >= 0.25 ? 'ca-up' : delta <= -0.25 ? 'ca-down' : ''}`}>{delta >= 0 ? '+' : ''}{fmtScore(delta)} {t('codeAnalysis.vsMedian')}</span>}
                {previous && Math.abs(attemptScore(focus) - attemptScore(previous)) >= 0.05 && <span className={`ca-fact ${attemptScore(focus) > attemptScore(previous) ? 'ca-up' : attemptScore(focus) < attemptScore(previous) ? 'ca-down' : ''}`}>{attemptScore(focus) > attemptScore(previous) ? '▲' : attemptScore(focus) < attemptScore(previous) ? '▼' : '='} {t('codeAnalysis.vsPreviousDive', { score: fmtScore(attemptScore(previous)) })}</span>}
                {!beaten && before.length > 0 && <span className="ca-fact ca-up">{t('codeAnalysis.record')}</span>}
                {weeks != null && weeks >= 3 && <span className="ca-fact ca-up">{t('codeAnalysis.bestSince', { count: weeks })}</span>}
              </span>}
            </span>
          </button>
        })()
  const sessionsPanel = <section className="ca-panel">
            <div className="ca-panel-h"><h2>{t('codeAnalysis.sessions')}</h2></div>
            {shownSessions.map(group => { const mid = median(group.filter(item => item.performance).map(attemptScore)) as number; return <div key={group[0].session_id} className="ca-sess">
              <div className="ca-sess-date">{date(group[0].dive_datetime, 'd MMM')}<small>{t('codeAnalysis.attemptsShort', { count: group.length })} · {[...new Set(group.map(item => item.height))].join(' · ')}</small></div>
              <div className="ca-chips">{group.map(item => <ScoreChip key={item.id} id={item.id} performance={item.performance} score={attemptScore(item)} onOpen={openClip}
                label={t('dives.openAttemptFrom', { code, date: date(item.dive_datetime, 'd MMM HH:mm') })} />)}</div>
              <b className={analytics ? `ca-t-${scoreBand(mid)}` : undefined}>{analytics ? fmtScore(mid) : ''}</b>
            </div> })}
            {sessions.length > 6 && <button type="button" className="ca-btn" style={{ marginTop: 10, border: 0, padding: 0 }} onClick={() => setShowAllSessions(value => !value)}>
              {showAllSessions ? t('codeAnalysis.fewerSessions') : t('codeAnalysis.allSessions', { count: sessions.length })}</button>}
          </section>
  const repsPanel = items.length > 0 && <section className="ca-panel">
          <div className="ca-panel-h"><h2>{t('codeAnalysis.representatives')}</h2></div>
          <div className="ca-reps">{reps.map(([roles, attempt]) => <button key={roles[0]} type="button" className="ca-rep" onClick={() => openClip(attempt.id)}>
            <span className="ca-thumb" style={{ display: 'block' }}><DiveThumbnail dive={attempt} compact />{analytics && <span className={`ca-rep-badge ca-r-${attempt.performance}`}>{fmtScore(attemptScore(attempt))}</span>}</span>
            <span className="ca-rep-cap"><b>{roles.map(role => t(`codeAnalysis.rep.${role}`)).join(' · ')}</b><span>{date(attempt.dive_datetime, parseISO(attempt.dive_datetime).getFullYear() === new Date().getFullYear() ? 'd MMM' : 'd MMM yyyy')}</span></span>
          </button>)}</div>
        </section>

  // Height pills carry that height's median over the selected period once it has 10 graded dives.
  const heightMedian = (value: string) => {
    const pool = all.filter(item => item.height === value && item.performance && now - ts(item) <= days * DAY_MS && (!month || item.dive_datetime.startsWith(month))).map(attemptScore)
    return pool.length >= 10 ? median(pool) as number : null
  }
  const filters = <div className="ca-span ca-filters">
      <Segmented label={t('codeAnalysis.periodAria')} value={month ? null : period} onChange={value => update({ period: value === defaultPeriod ? null : value, month: null, sel: null })}
        options={PERIODS.map(([key]) => [key, t(`codeAnalysis.period.${key}`)] as const)} />
      {heights.length > 1 && <div className="ca-heights">{heights.map(value => { const mid = analytics ? heightMedian(value) : null
        return <button key={value} type="button" className="ca-pill" aria-pressed={height === value} onClick={() => update({ h: height === value ? null : value, sel: null })}>
          {value}{mid != null && <small className={`ca-t-${scoreBand(mid)}`} aria-label={`${t('codeAnalysis.median')} ${fmtScore(mid)}`}>{fmtScore(mid)}</small>}
        </button> })}</div>}
      {month && <button type="button" className="ca-pill" aria-pressed="true" onClick={() => update({ month: null, sel: null })}>{format(parseISO(`${month}-01`), 'MMMM yyyy', { locale: appLocale() })} ✕</button>}
    </div>
  // The library total counts every visible diver; once strangers are filtered out it no longer describes this page.
  const strangersFiltered = !diverId && scope === 'all' && followedIds.size > 0
  const pageTotal = strangersFiltered ? null : attemptsTotal
  const cappedText = pageTotal === null ? t('codeAnalysis.cappedPlain') : t('codeAnalysis.cappedAria', { total: pageTotal })
  const notes = <>
    {!analytics && <div className="ca-span ca-note">{t('codeAnalysis.straightJump')}</div>}
    {!items.length && attemptsCapped && <div className="ca-span ca-note">{cappedText}</div>}
    {!items.length && mode !== 'corrections' && <div className="ca-span ca-note">{t('codeAnalysis.emptyPeriod', { code })} <button type="button" className="ca-btn" onClick={() => update({ period: defaultPeriod === 'all' ? null : 'all', h: null, month: null })}>{t('codeAnalysis.showAll')}</button></div>}
  </>
  // One label for the median and the trend: both say "all divers" as soon as either sample mixes divers.
  const multiDiver = new Set([...scored, ...all.filter(item => item.performance && (!trendHeight || item.height === trendHeight))].map(item => item.diver_id)).size > 1
  const trendClass = trend == null ? '' : trend >= 0.5 ? 'ca-up' : trend <= -0.5 ? 'ca-down' : 'ca-flat'
  const trendText = trend == null ? null : Math.abs(trend) < 0.5 ? t('codeAnalysis.stable') : `${trend > 0 ? '▲' : '▼'} ${fmtScore(Math.abs(trend))}`
  const verdict = analytics && med != null && <div className="ca-verdict">
    <p>{t(multiDiver ? 'codeAnalysis.allDiversMedian' : 'codeAnalysis.personalMedian')} <b className={`ca-t-${scoreBand(med)}`}>{fmtScore(med)}</b> · {attemptsCapped && pageTotal !== null
      ? t('codeAnalysis.shownOf', { count: items.length, total: pageTotal })
      : <span title={attemptsCapped ? cappedText : undefined}>{t('codeAnalysis.gradedCount', { count: scored.length })}</span>}</p>
    {trendText && <p title={t('codeAnalysis.trendTitle')}><b className={trendClass} aria-label={trend != null && Math.abs(trend) >= 0.5 ? `${t(trend > 0 ? 'codeAnalysis.rising' : 'codeAnalysis.falling')} ${fmtScore(Math.abs(trend))}` : undefined}>{trendText}</b> {heights.length > 1 && trendHeight ? t('codeAnalysis.trendScope', { height: trendHeight }) : t('codeAnalysis.trendVs')}</p>}
    {attemptsCapped && pageTotal === null && items.length > 0 && <p className="ca-sample">{cappedText}</p>}
  </div>
  const hero = <div className="ca-span"><div className="ca-hero"><div>
    <h1 className="ca-hero-code">{code}</h1>
    <p className="ca-hero-name">{name !== code ? name : ''}{dd ? <> · <span className="whitespace-nowrap">DD {fmtScore(dd)}</span></> : null}</p>
    {verdict}
  </div></div></div>
  // Nearby codes: all-history medians for this code and its neighbours, so the rows compare like with like.
  // The reference row comes from the same library summaries as its neighbours, so the panel compares like with like.
  const own = nearbySource?.find(item => item.dive_code === code)
  const nearbyRows = related
  const nearbyRow = (summary: CodeSummary, detail: string) => <>
    <span className="ca-near-code">{summary.dive_code}</span>
    <span className="ca-near-name"><span>{diveCodeName(summary.dive_code, lang)}</span><small>{detail}</small></span>
    <b className={summary.median != null ? `ca-t-${scoreBand(summary.median)}` : undefined}>{fmtScore(summary.median)}</b>
  </>
  const nearby = nearbyRows.length > 0 && <section className="ca-panel ca-nearby">
    <div className="ca-panel-h"><h2>{t('codeAnalysis.nearby')}</h2><span>{strangersFiltered ? (height ? t('codeAnalysis.nearbyCommunityHeight', { height }) : t('codeAnalysis.nearbyCommunity')) : height ? t('codeAnalysis.nearbyScopeHeight', { height }) : t('codeAnalysis.nearbyScope')}</span></div>
    <div className="ca-near">
      {own && <div className="ca-near-row is-self">{nearbyRow(own, t('codeAnalysis.gradedShort', { count: own.scored_count }))}</div>}
      {nearbyRows.map(({ summary, reason }) => <Link key={summary.dive_code} className="ca-near-row" to={`/dives/analysis/${encodeURIComponent(summary.dive_code)}?${new URLSearchParams({ ...(height ? { h: height } : {}), scope })}`} state={{ returnTo: returnTo ?? undefined }}>
        {nearbyRow(summary, `${t(`codeAnalysis.relation.${reason}`)} · ${t('codeAnalysis.gradedShort', { count: summary.scored_count })}`)}
      </Link>)}
    </div>
  </section>
  const workspace = user && !diverId
    ? <TechniqueWorkspace key={`${user.user_id}-${code}`} code={code} viewer={user.user_id} height={height} scores={scorePanel} layout={{ slot: adjustmentSlot, attempts: all }} />
    : scorePanel && <section className="ca-panel">{scorePanel.header}{scorePanel.content}</section>
  const slot = <div ref={setAdjustmentSlot} className="ca-slot" />
  const hasBody = items.length > 0 || Boolean(canViewCorrections && scorePanel)

  return <>
  <div className="ca ca-page ca-arrive">
    <div className="ca-lead"><div className="ca-span">{topbar}</div>{hero}{filters}{notes}</div>
    {/* Phones read top to bottom in DOM order (videos, chart, adjustments, sessions); desktop splits reading and watching into two columns. */}
    {hasBody && (desktop
      ? <>
          <div className="ca-main">{focusCard}{workspace}{items.length > 0 && sessionsPanel}{nearby}{communityPanel}</div>
          {items.length > 0 && <div className="ca-aside">{repsPanel}{slot}</div>}
        </>
      : <div className="ca-main">{focusCard}{repsPanel}{workspace}{slot}{items.length > 0 && sessionsPanel}{nearby}{communityPanel}</div>)}
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
