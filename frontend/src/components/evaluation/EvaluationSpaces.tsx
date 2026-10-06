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
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  getMyRatings,
  getOwnedRequests,
  getResults,
  type JuryResults,
  type MyRatingItem,
  type OwnerRequestSummary,
} from '../../services/evaluationApi'

function scoreLabel(half: number): string {
  return (half / 2).toFixed(1)
}

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
  const { t } = useTranslation()
  const loader = useCallback((limit: number, offset: number) => getOwnedRequests(limit, offset), [])
  const { state, busy, load } = usePagedLoader<OwnerRequestSummary>(loader)

  if (state.kind === 'loading') return <p className="eval-status" role="status">{t('common.loading')}</p>
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
                  mean: row.mean_score !== null ? row.mean_score.toFixed(1) : '—',
                })}
              </span>
              {/* Owner keeps playable access through the normal Library
                  transport; a suspended request stays here in text only. */}
              <OwnedPanelLink request={row} />
            </footer>
          </li>
        ))}
      </ul>
      <Pager total={state.total} offset={state.offset} count={state.items.length} busy={busy} onOffset={(offset) => void load(offset)} />
    </div>
  )
}

function OwnedPanelLink({ request }: { request: OwnerRequestSummary }) {
  const { t } = useTranslation()
  const [results, setResults] = useState<JuryResults | null>(null)
  const [error, setError] = useState(false)
  const toggle = async () => {
    if (results) {
      setResults(null)
      return
    }
    setError(false)
    try {
      setResults(await getResults(request.request_id))
    } catch {
      setError(true)
    }
  }
  return (
    <span className="eval-owned-panel">
      <button type="button" onClick={() => void toggle()} aria-expanded={results !== null}>
        {results ? t('evaluations.hidePanel') : t('evaluations.showPanel')}
      </button>
      {error && (
        <span role="alert" className="eval-error">
          {t('evaluations.panelError')}{' '}
          <button type="button" onClick={() => void toggle()}>{t('evaluations.retry')}</button>
        </span>
      )}
      {results && (
        <ul className="eval-panel-list">
          {results.ratings.map((rating) => (
            <li key={rating.id}>
              <strong>{scoreLabel(rating.score_half_steps)}</strong> {rating.author ?? '—'}
              {rating.comment ? <p className="eval-panel-comment">{rating.comment}</p> : null}
            </li>
          ))}
          {results.ratings.length === 0 && <li>{t('evaluations.panelEmpty')}</li>}
        </ul>
      )}
    </span>
  )
}

export function MyJudgements() {
  const { t } = useTranslation()
  const loader = useCallback((limit: number, offset: number) => getMyRatings(limit, offset), [])
  const { state, busy, load } = usePagedLoader<MyRatingItem>(loader)

  if (state.kind === 'loading') return <p className="eval-status" role="status">{t('common.loading')}</p>
  if (state.kind === 'error')
    return (
      <div className="eval-state" role="alert">
        <p>{t('evaluations.judgedError')}</p>
        <button type="button" onClick={() => void load(0)}>{t('evaluations.retry')}</button>
      </div>
    )
  return (
    <div className="eval-judged">
      <p className="eval-status" role="status">{t('evaluations.judgedCount', { count: state.total })}</p>
      {state.items.length === 0 && <p>{t('evaluations.judgedEmpty')}</p>}
      <ul className="eval-judged-list">
        {state.items.map((row) => (
          <li key={row.request_id} className="eval-judged-item">
            <header>
              <strong>{row.dive.dive_name || row.dive.dive_code}</strong>
              <span>{row.dive.dive_code} · {row.dive.height} · {row.dive.platform_type}</span>
            </header>
            <div className="eval-judged-body">
              <span className="eval-judged-score" role="status">{scoreLabel(row.score_half_steps)}</span>
              {row.comment && <p className="eval-panel-comment">{row.comment}</p>}
            </div>
            <footer>
              <span>{t('evaluations.panelSummary', { count: row.rating_count, mean: row.mean_score !== null ? row.mean_score.toFixed(1) : '—' })}</span>
              <MyPanelLink requestId={row.request_id} />
            </footer>
          </li>
        ))}
      </ul>
      <Pager total={state.total} offset={state.offset} count={state.items.length} busy={busy} onOffset={(offset) => void load(offset)} />
    </div>
  )
}

/** The stored panel of a request I judged: names, scores, comments — kept
 * accessible after the video was revoked; errors get their own retry. */
function MyPanelLink({ requestId }: { requestId: number }) {
  const { t } = useTranslation()
  const [results, setResults] = useState<JuryResults | null>(null)
  const [error, setError] = useState(false)
  const [busy, setBusy] = useState(false)

  const toggle = async () => {
    if (results) {
      setResults(null)
      return
    }
    setError(false)
    setBusy(true)
    try {
      setResults(await getResults(requestId))
    } catch {
      setError(true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <span className="eval-owned-panel">
      <button type="button" onClick={() => void toggle()} aria-expanded={results !== null} disabled={busy}>
        {results ? t('evaluations.hidePanel') : t('evaluations.showPanel')}
      </button>
      {error && (
        <span role="alert" className="eval-error">
          {t('evaluations.panelError')}{' '}
          <button type="button" onClick={() => void toggle()}>{t('evaluations.retry')}</button>
        </span>
      )}
      {results && (
        <ul className="eval-panel-list">
          {results.ratings.map((rating) => (
            <li key={rating.id}>
              <strong>{scoreLabel(rating.score_half_steps)}</strong> {rating.author ?? '—'}{' '}
              {results.my_rating && rating.id === results.my_rating.id ? <em>({t('evaluations.you')})</em> : null}
              {rating.comment ? <p className="eval-panel-comment">{rating.comment}</p> : null}
            </li>
          ))}
          {results.ratings.length === 0 && <li>{t('evaluations.panelEmpty')}</li>}
        </ul>
      )}
    </span>
  )
}
