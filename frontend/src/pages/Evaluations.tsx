/**
 * Évaluations space (issue #68): one row of three tabs. "Judge" has no lobby:
 * when the server overview says today's dives are waiting, the stage opens
 * straight away; closing it lands on the judges' table (today's carnets,
 * judging style, next hand). A paused session is not re-launched until the
 * member leaves the page. A started session is mounted/unmounted so leaving
 * it clears its draft and evaluation-scope media references.
 */
import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../contexts/AuthContext'
import { OwnedRequests, MyJudgements } from '../components/evaluation/EvaluationSpaces'
import '../components/evaluation/evaluations.css'
import '../components/evaluation/evaluationA.css'
import '../components/evaluation/evaluationHub.css'
import AutomaticScores from '../components/evaluation/AutomaticScores'
import JudgeTable from '../components/evaluation/JudgeTable'
import { getEvaluationOverview, type EvaluationOverview } from '../services/evaluationApi'

const JurySession = lazy(() => import('../components/evaluation/JurySession'))

type Tab = 'judge' | 'dives' | 'history'
const TABS: Array<{ key: Tab; label: string }> = [
  { key: 'judge', label: 'evaluations.judgeSection' },
  { key: 'dives', label: 'evaluations.tabMyDives' },
  { key: 'history', label: 'evaluations.tabHistory' },
]
/* Links and saved tab contexts from the previous two-level layout. */
const LEGACY: Record<string, Tab> = { automatic: 'judge', jury: 'judge', community: 'dives', mine: 'dives', judgements: 'history' }

type Active =
  | { kind: 'daily'; resumeStackId?: number; doneBefore: number }
  | { kind: 'extra' }
  | { kind: 'requests' }

export default function Evaluations() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const [search, setSearch] = useSearchParams()
  const requested = search.get('tab') ?? ''
  const tab: Tab = TABS.some(item => item.key === requested) ? requested as Tab : LEGACY[requested] ?? 'judge'
  const setTab = (value: Tab) => setSearch(previous => { const next = new URLSearchParams(previous); next.set('tab', value); return next })
  const [judging, setJudging] = useState(false)
  // Survives tab switches inside the page, resets when the member leaves it.
  const [paused, setPaused] = useState(false)

  useEffect(() => {
    document.title = `${t('evaluations.title')} · Dive Analyser`
    return () => {
      document.title = 'Dive Analyser'
    }
  }, [t])

  return (
    <div className="evaluations-page" data-judging={judging ? 'true' : undefined}>
      <h1 className="evaluations-title">{t('evaluations.title')}</h1>
      <Tabs tab={tab} onTab={setTab} />
      <div key={tab} className="evaluations-body" role="tabpanel" id={`evaluations-panel-${tab}`} aria-labelledby={`evaluations-tab-${tab}`}>
        {tab === 'judge' && <JudgeHub paused={paused} onPause={() => setPaused(true)} onStageChange={setJudging} onHistory={() => setTab('history')} />}
        {tab === 'dives' && (
          <>
            <AutomaticScores />
            <section className="eval-section">
              <h2>{t('evaluations.tabMine')}</h2>
              <p className="eval-note">{t('evaluations.requestDiveHint')}</p>
              <OwnedRequests />
            </section>
          </>
        )}
        {tab === 'history' && <MyJudgements />}
      </div>
      {!user && <p className="eval-error" role="alert">{t('evaluations.signInNeeded')}</p>}
    </div>
  )
}

/** Underline tabs with an indicator that glides to the selected tab. */
function Tabs({ tab, onTab }: { tab: Tab; onTab: (tab: Tab) => void }) {
  const { t } = useTranslation()
  const listRef = useRef<HTMLDivElement>(null)
  const [indicator, setIndicator] = useState<{ left: number; width: number } | null>(null)
  useLayoutEffect(() => {
    const place = () => {
      const button = listRef.current?.querySelector<HTMLButtonElement>('[aria-selected="true"]')
      if (button) setIndicator({ left: button.offsetLeft, width: button.offsetWidth })
    }
    place()
    // Labels and fonts can settle after the first paint: follow the row's size.
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(place)
    if (listRef.current) observer?.observe(listRef.current)
    window.addEventListener('resize', place)
    return () => { observer?.disconnect(); window.removeEventListener('resize', place) }
  }, [tab, t])
  return (
    <div className="evaluations-tabs" role="tablist" aria-label={t('evaluations.tabsAria')} ref={listRef}>
      {TABS.map(({ key, label }) => (
        <button
          key={key}
          type="button"
          role="tab"
          id={`evaluations-tab-${key}`}
          aria-selected={tab === key}
          aria-controls={`evaluations-panel-${key}`}
          onClick={() => onTab(key)}
        >
          {t(label)}
        </button>
      ))}
      {indicator && <span className="evaluations-tab-indicator" aria-hidden style={{ transform: `translateX(${indicator.left}px)`, width: indicator.width }} />}
    </div>
  )
}

function JudgeHub({ paused, onPause, onStageChange, onHistory }: {
  paused: boolean
  onPause: () => void
  onStageChange: (judging: boolean) => void
  onHistory: () => void
}) {
  const { t } = useTranslation()
  const [overview, setOverview] = useState<EvaluationOverview | null>(null)
  const [failed, setFailed] = useState(false)
  const [active, setActive] = useState<Active | null>(null)

  const refresh = useCallback(() => {
    setFailed(false)
    getEvaluationOverview().then(setOverview).catch(() => setFailed(true))
  }, [])
  useEffect(refresh, [refresh])

  const resume = overview?.today.resume ?? null
  const daily = useCallback((): Active => resume
    ? { kind: 'daily', resumeStackId: resume.stack_id, doneBefore: resume.total - resume.remaining }
    : { kind: 'daily', doneBefore: 0 }, [resume])

  // No lobby: dives waiting today means the stage opens right away.
  const waiting = !!overview && (!!resume || !overview.today.daily)
  useEffect(() => {
    if (waiting && !paused && !active) setActive(daily())
  }, [waiting, paused, active, daily])

  const leave = useCallback(() => {
    onPause()
    setActive(null)
    onStageChange(false)
    setOverview(null)
    refresh()
  }, [onPause, onStageChange, refresh])

  if (active) {
    return (
      <Suspense fallback={<WarmUp />}>
        {active.kind === 'requests'
          ? <JurySession key="requests" autoStart onStageChange={onStageChange} onDone={leave} />
          : <JurySession
              key={active.kind}
              automatic
              autoStart
              daily={active.kind === 'daily'}
              resumeStackId={active.kind === 'daily' ? active.resumeStackId : undefined}
              doneBefore={active.kind === 'daily' ? active.doneBefore : 0}
              onStageChange={onStageChange}
              onDone={leave}
            />}
      </Suspense>
    )
  }
  if (failed) {
    return (
      <div className="eval-state" role="alert">
        <p>{t('evaluations.loadError')}</p>
        <button type="button" className="eval-start" onClick={refresh}>{t('evaluations.retry')}</button>
      </div>
    )
  }
  if (!overview || (waiting && !paused)) return <WarmUp />
  return (
    <JudgeTable
      overview={overview}
      onResume={() => setActive(daily())}
      onDeal={() => setActive({ kind: 'extra' })}
      onRequests={() => setActive({ kind: 'requests' })}
      onHistory={onHistory}
    />
  )
}

/** Three card backs bouncing on the springboard while the jury warms up. */
function WarmUp() {
  const { t } = useTranslation()
  return (
    <div className="eval-warmup" role="status">
      <span className="eval-warmup-cards" aria-hidden><i /><i /><i /></span>
      <span className="eval-warmup-board" aria-hidden />
      <p>{t('evaluations.warmUp')}</p>
    </div>
  )
}
