/**
 * Owner space (Mes évaluations) and personal jury history (Mes jugements).
 * Owned requests list active/suspended states with community aggregates
 * (never an official score); suspended requests show "Évaluation fermée"
 * and never a replay/poster — the owner keeps their normal Library access.
 * My ratings keep the frozen dive context; the Show panel button RENDERS the
 * stored panel (names, scores, comments, retry on failure) — no media URL is
 * ever rendered here. Both lists page with Précédent/Suivant (never silently
 * replacing pages without a way back).
 */
import { scoreNumber } from './scoreFormatting'
import { useCallback, useEffect, useState, type CSSProperties } from 'react'
import { ScoreCard } from './ScoreCards'
import WarmUp from './EvaluationWarmUp'
import { points } from './JudgeTable'
import { useTranslation } from 'react-i18next'
import {
  getMyRatings,
  getOwnedRequests,
  getResults,
  type JuryResults,
  type MyRatingItem,
  type OwnerRequestSummary,
} from '../../services/evaluationApi'

const PAGE = 10

function usePagedLoader<T>(
  loader: (limit: number, offset: number) => Promise<{ items: T[]; total: number }>,
) {
  const [state, setState] = useState<
    { kind: 'loading' } | { kind: 'error' } | { kind: 'loaded'; items: T[]; total: number; offset: number }
  >({ kind: 'loading' })
  const [busy, setBusy] = useState(false)

  const load = useCallback(async (offset: number) => {
    setBusy(true)
    try {
      const page = await loader(PAGE, offset)
      setState({ kind: 'loaded', items: page.items, total: page.total, offset })
    } catch {
      setState({ kind: 'error' })
    } finally {
      setBusy(false)
    }
  }, [loader])

  useEffect(() => {
    void load(0)
  }, [load])

  return { state, busy, load }
}

function Pager({
  total, offset, count, busy, onOffset,
}: {
  total: number
  offset: number
  count: number
  busy: boolean
  onOffset: (offset: number) => void
}) {
  const { t } = useTranslation()
  if (total <= count) return null
  return (
    <div className="eval-pager">
      <button type="button" disabled={busy || offset === 0} onClick={() => onOffset(Math.max(0, offset - PAGE))}>
        {t('evaluations.previous')}
      </button>
      <button
        type="button"
        disabled={busy || offset + count >= total}
        onClick={() => onOffset(offset + PAGE)}
      >
        {t('evaluations.next')}
      </button>
    </div>
  )
}

export function OwnedRequests() {
  const { t, i18n } = useTranslation()
  const loader = useCallback((limit: number, offset: number) => getOwnedRequests(limit, offset), [])
  const { state, busy, load } = usePagedLoader<OwnerRequestSummary>(loader)

  if (state.kind === 'loading') return <WarmUp />
  if (state.kind === 'error')
    return (
      <div className="eval-state" role="alert">
        <p>{t('evaluations.ownedError')}</p>
        <button type="button" onClick={() => void load(0)}>{t('evaluations.retry')}</button>
      </div>
    )
  return (
    <div className="eval-owned">
      <p className="eval-status" role="status">{t('evaluations.ownedCount', { count: state.total })}</p>
      {state.items.length === 0 && <p>{t('evaluations.ownedEmpty')}</p>}
      <ul className="eval-owned-list">
        {state.items.map((row) => (
          <li key={row.request_id} className="eval-owned-item">
            <header>
              <strong>{row.dive.dive_code}</strong>
              <span>{row.dive.height} · {row.dive.platform_type}</span>
              <span className={`eval-badge ${row.active ? 'is-active' : 'is-closed'}`}>
                {row.active ? t('evaluations.ownedActive') : t('evaluations.ownedClosed')}
              </span>
            </header>
            {row.prompt && <p className="eval-owned-prompt">{row.prompt}</p>}
            <footer>
              <span role="status">
                {t('evaluations.panelSummary', {
                  count: row.rating_count,
                  mean: scoreNumber(row.mean_score, i18n.language),
                })}
              </span>
              {/* Owner keeps playable access through the normal Library
                  transport; a suspended request stays here in text only. */}
              <OwnedPanelLink requestId={row.request_id} />
            </footer>
          </li>
        ))}
      </ul>
      <Pager total={state.total} offset={state.offset} count={state.items.length} busy={busy} onOffset={(offset) => void load(offset)} />
    </div>
  )
}

const PANEL_PAGE = 50

/** Panel rows paged by 50 with a continuation; count/mean always aggregate
 * the WHOLE panel server-side. */
export function OwnedPanelLink({ requestId, automatic = false }: { requestId: number; automatic?: boolean }) {
  const { t, i18n } = useTranslation()
  const [state, setState] = useState<
    | { kind: 'closed' }
    | { kind: 'error' }
    | { kind: 'open'; rows: JuryResults['ratings']; total: number; offset: number }
  >({ kind: 'closed' })
  const [busy, setBusy] = useState(false)

  const fetchPage = useCallback(async (offset: number, accumulate: boolean) => {
    setBusy(true)
    try {
      const page = await getResults(requestId, PANEL_PAGE, offset, automatic)
      setState((previous) => {
        if (previous.kind === 'open' && accumulate) {
          const seen = new Set(previous.rows.map((row) => row.id))
          const rows = [...previous.rows, ...page.ratings.filter((row) => !seen.has(row.id))]
          // Next fetch resumes at the number of rows already fetched.
          return { kind: 'open', rows, total: page.rating_count, offset: rows.length }
        }
        return { kind: 'open', rows: page.ratings, total: page.rating_count, offset: page.ratings.length }
      })
    } catch {
      setState({ kind: 'error' })
    } finally {
      setBusy(false)
    }
  }, [requestId, automatic])

  const toggle = () => {
    if (state.kind === 'open') {
      setState({ kind: 'closed' })
      return
    }
    void fetchPage(0, false)
  }

  return (
    <span className="eval-owned-panel">
      <button type="button" onClick={toggle} aria-expanded={state.kind === 'open'} disabled={busy}>
        {state.kind === 'open' ? t('evaluations.hidePanel') : t('evaluations.showPanel')}
      </button>
      {state.kind === 'error' && (
        <span role="alert" className="eval-error">
          {t('evaluations.panelError')}{' '}
          <button type="button" onClick={() => void fetchPage(0, false)}>{t('evaluations.retry')}</button>
        </span>
      )}
      {state.kind === 'open' && (
        <>
          <ul className="eval-panel-list">
            {state.rows.map((rating) => (
              <li key={rating.id} className="eval-panel-note">
                <ScoreCard scoreHalfSteps={rating.score_half_steps} ariaLabel={scoreNumber(rating.score_half_steps / 2, i18n.language)} />
                <strong>{scoreNumber(rating.score_half_steps / 2, i18n.language)}</strong> {rating.author ?? '—'}
                {rating.comment ? <p className="eval-panel-comment">{rating.comment}</p> : null}
              </li>
            ))}
            {state.rows.length === 0 && <li>{t('evaluations.panelEmpty')}</li>}
          </ul>
          {state.rows.length < state.total && (
            <button type="button" disabled={busy} onClick={() => void fetchPage(state.rows.length, true)}>
              {t('evaluations.more')}
            </button>
          )}
        </>
      )}
    </span>
  )
}

/** Use the other-voter aggregate; older servers only send the overall mean. */
export function othersMean(row: Pick<MyRatingItem, 'score_half_steps' | 'rating_count' | 'mean_score' | 'panel_mean'>): number | null {
  if (row.panel_mean !== undefined) return row.panel_mean
  if (row.mean_score === null || row.rating_count < 2) return null
  return Math.round(((row.mean_score * row.rating_count - row.score_half_steps / 2) / (row.rating_count - 1)) * 10) / 10
}

function dayLabel(iso: string, t: (key: string) => string, locale: string): string {
  const date = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`)
  const start = (value: Date) => new Date(value.getFullYear(), value.getMonth(), value.getDate()).getTime()
  const days = Math.round((start(new Date()) - start(date)) / 86_400_000)
  if (days === 0) return t('sessions.today')
  if (days === 1) return t('sessions.yesterday')
  return date.toLocaleDateString(locale, { weekday: 'long', day: 'numeric', month: 'long' })
}

export function MyJudgements() {
  const { t, i18n } = useTranslation()
  const loader = useCallback((limit: number, offset: number) => getMyRatings(limit, offset), [])
  const { state, busy, load } = usePagedLoader<MyRatingItem>(loader)

  if (state.kind === 'loading') return <WarmUp />
  if (state.kind === 'error')
    return (
      <div className="eval-state" role="alert">
        <p>{t('evaluations.judgedError')}</p>
        <button type="button" onClick={() => void load(0)}>{t('evaluations.retry')}</button>
      </div>
    )
  const days: Array<{ label: string; rows: MyRatingItem[] }> = []
  for (const row of state.items) {
    const label = dayLabel(row.created_at, t, i18n.language)
    if (days[days.length - 1]?.label === label) days[days.length - 1].rows.push(row)
    else days.push({ label, rows: [row] })
  }
  let index = 0
  return (
    <div className="eval-judged eval-history">
      <p className="eval-status" role="status">{t('evaluations.judgedCount', { count: state.total })}</p>
      {state.items.length === 0 && <p className="eval-empty-pool">{t('evaluations.judgedEmpty')}</p>}
      {days.map((day) => (
        <section key={day.label} className="eval-history-day">
          <h3>{day.label}</h3>
          <ul className="eval-history-list">
            {day.rows.map((row) => <HistoryRow key={`${row.kind ?? 'request'}-${row.request_id}`} row={row} index={index++} />)}
          </ul>
        </section>
      ))}
      <Pager total={state.total} offset={state.offset} count={state.items.length} busy={busy} onOffset={(offset) => void load(offset)} />
    </div>
  )
}

function HistoryRow({ row, index }: { row: MyRatingItem; index: number }) {
  const { t, i18n } = useTranslation()
  const [open, setOpen] = useState(false)
  const mine = row.score_half_steps / 2
  const panel = othersMean(row)
  const delta = panel === null ? null : Math.round((mine - panel) * 10) / 10
  return (
    <li className="eval-history-row" style={{ '--i': index } as CSSProperties} data-open={open ? 'true' : undefined}>
      <button type="button" className="eval-history-summary" aria-expanded={open} onClick={() => setOpen(value => !value)}>
        <ScoreCard scoreHalfSteps={row.score_half_steps} ariaLabel={t('evaluations.myCardAria', { score: scoreNumber(row.score_half_steps / 2, i18n.language) })} />
        <span className="eval-history-text">
          <strong>{row.dive.dive_name || row.dive.dive_code}</strong>
          <span>{row.dive.dive_code} · {row.dive.height}{row.kind === 'request' ? ` · ${t('evaluations.kindRequest')}` : ''}</span>
          <span className="eval-panel-chip">{panel === null ? t('evaluations.firstJudge') : t('evaluations.panelChip', { mean: points(panel, i18n.language) })}</span>
        </span>
        {delta !== null && <span className="eval-delta" data-sign={delta > 0 ? 'up' : delta < 0 ? 'down' : 'even'}>{points(delta, i18n.language, true)}</span>}
      </button>
      {row.comment && <p className="eval-panel-comment">“{row.comment}”</p>}
      {open && <MyPanel requestId={row.request_id} automatic={row.kind === 'automatic'} />}
    </li>
  )
}

/** The stored panel of a dive I judged, loaded when its row opens: names,
 * scores, comments — kept accessible after the video was revoked; errors get
 * their own retry. */
function MyPanel({ requestId, automatic = false }: { requestId: number; automatic?: boolean }) {
  const { t, i18n } = useTranslation()
  const [state, setState] = useState<
    | { kind: 'loading' }
    | { kind: 'error' }
    | { kind: 'open'; rows: JuryResults['ratings']; myId: number | null; total: number }
  >({ kind: 'loading' })
  const [busy, setBusy] = useState(false)

  const fetchPage = useCallback(async (offset: number) => {
    setBusy(true)
    try {
      const page = await getResults(requestId, PANEL_PAGE, offset, automatic)
      setState((previous) => {
        if (previous.kind === 'open' && offset > 0) {
          const seen = new Set(previous.rows.map((row) => row.id))
          return { kind: 'open', rows: [...previous.rows, ...page.ratings.filter((row) => !seen.has(row.id))], myId: page.my_rating?.id ?? previous.myId, total: page.rating_count }
        }
        return { kind: 'open', rows: page.ratings, myId: page.my_rating?.id ?? null, total: page.rating_count }
      })
    } catch {
      setState({ kind: 'error' })
    } finally {
      setBusy(false)
    }
  }, [requestId, automatic])
  useEffect(() => { void fetchPage(0) }, [fetchPage])

  if (state.kind === 'loading') return <WarmUp />
  if (state.kind === 'error')
    return (
      <p role="alert" className="eval-error">
        {t('evaluations.panelError')}{' '}
        <button type="button" onClick={() => void fetchPage(0)}>{t('evaluations.retry')}</button>
      </p>
    )
  return (
    <div className="eval-history-panel">
      <ul className="eval-history-jury">
        {state.rows.map((rating, index) => (
          <li key={rating.id} style={{ '--i': index } as CSSProperties} data-mine={state.myId === rating.id ? 'true' : undefined}>
            <ScoreCard scoreHalfSteps={rating.score_half_steps} ariaLabel={scoreNumber(rating.score_half_steps / 2, i18n.language)} />
            <span>{state.myId === rating.id ? t('evaluations.you') : rating.author ?? '—'}</span>
            {/* My own comment is already quoted on the row. */}
            {rating.comment && state.myId !== rating.id ? <p className="eval-panel-comment">{rating.comment}</p> : null}
          </li>
        ))}
        {state.rows.length === 0 && <li>{t('evaluations.panelEmpty')}</li>}
      </ul>
      {state.rows.length > 0 && state.rows.every((rating) => rating.id === state.myId) && <p className="eval-note">{t('evaluations.panelAlone')}</p>}
      {state.rows.length < state.total && (
        <button type="button" disabled={busy} onClick={() => void fetchPage(state.rows.length)}>
          {t('evaluations.more')}
        </button>
      )}
    </div>
  )
}
