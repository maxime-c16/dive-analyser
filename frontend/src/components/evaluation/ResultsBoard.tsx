import { scoreNumber } from './scoreFormatting'
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { useModalOverlay } from '../../utils/overlays'
import { getResults, type JuryResults } from '../../services/evaluationApi'
import { ScoreCard } from './ScoreCards'

/** Four peer carnets at a time. Aggregate count/mean come from the server,
 * never from a partial page. Further pages are requested only on demand. */
export default function ResultsBoard({ results, score, automatic }: {
  results: JuryResults; score: number; automatic: boolean
}) {
  const { t, i18n } = useTranslation()
  const [rows, setRows] = useState(results.ratings)
  const [offset, setOffset] = useState(results.ratings.length)
  const [page, setPage] = useState(0)
  const [all, setAll] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  const alive = useRef(true)
  const dialog = useRef<HTMLDivElement>(null)
  const opener = useRef<HTMLButtonElement>(null)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  useModalOverlay(dialog, { enabled: all, layer: 90, onClose: () => setAll(false), returnFocus: () => opener.current })
  const myId = results.my_rating?.id
  const peers = rows.filter(row => row.id !== myId)
  const remaining = offset < results.rating_count
  async function more(advance: boolean) {
    if (busy || !remaining) return
    setBusy(true); setError(false)
    try {
      const next = await getResults(results.request_id, 50, offset, automatic)
      if (!alive.current) return
      setRows(previous => {
        const seen = new Set(previous.map(row => row.id))
        return [...previous, ...next.ratings.filter(row => !seen.has(row.id))]
      })
      setOffset(value => value + next.ratings.length)
      if (advance && next.ratings.length) setPage(value => value + 1)
    } catch { if (alive.current) setError(true) }
    finally { if (alive.current) setBusy(false) }
  }
  const nextPage = () => {
    if ((page + 1) * 4 + 4 <= peers.length || (!remaining && (page + 1) * 4 < peers.length)) setPage(value => value + 1)
    else void more(true)
  }
  const card = (row: JuryResults['ratings'][number], index: number, animate = false) => <figure className="eval-card-figure" key={row.id}>
    <ScoreCard scoreHalfSteps={row.score_half_steps} className={animate ? 'eval-card-raised' : ''} staggerMs={animate ? 240 + index * 90 : 0}
      ariaLabel={t('evaluations.cardAria', { score: scoreNumber(row.score_half_steps / 2, i18n.language) })} />
    <figcaption>{row.author ?? '—'}</figcaption>
  </figure>
  return <>
    <div className="eval-results-board">
      <figure className="eval-card-figure eval-card-mine-figure"><ScoreCard className="eval-card-raised" scoreHalfSteps={results.my_rating?.score_half_steps ?? score}
        ariaLabel={t('evaluations.myCardAria', { score: scoreNumber((results.my_rating?.score_half_steps ?? score) / 2, i18n.language) })} /><figcaption>{t('evaluations.you')}</figcaption></figure>
      <div className="eval-results-summary" role="status">{t('evaluations.panelSummary', { count: results.rating_count, mean: scoreNumber(results.mean_score, i18n.language) })}</div>
      <div className="eval-results-peers" key={page}>{peers.slice(page * 4, page * 4 + 4).map((row, i) => card(row, i, true))}</div>
      <div className="eval-jury-pagination">
        {peers.length > 4 || remaining ? <button type="button" disabled={page === 0 || busy} aria-label={t('evaluations.previous')} onClick={() => setPage(value => value - 1)}>‹</button> : null}
        <button type="button" ref={opener} onClick={() => setAll(true)}>{t('evaluations.allNotes', { count: results.rating_count })} ↗</button>
        {peers.length > 4 || remaining ? <button type="button" disabled={busy || (!remaining && (page + 1) * 4 >= peers.length)} aria-label={t('evaluations.nextPage')} onClick={nextPage}>›</button> : null}
      </div>
      {error && <p className="eval-error" role="alert">{t('evaluations.panelError')} <button type="button" onClick={() => void more(false)}>{t('evaluations.retry')}</button></p>}
    </div>
    {all && createPortal(<div className="eval-all-backdrop"><div ref={dialog} tabIndex={-1} className="eval-all-notes" role="dialog" aria-modal="true" aria-label={t('evaluations.allNotes', { count: results.rating_count })}>
      <header><div><strong>{t('evaluations.allNotes', { count: results.rating_count })}</strong><p>{t('evaluations.panelSummary', { count: results.rating_count, mean: scoreNumber(results.mean_score, i18n.language) })}</p></div><button type="button" onClick={() => setAll(false)} aria-label={t('common.close')}>×</button></header>
      <div className="eval-all-grid">{rows.map((row, i) => <div key={row.id}>{card(row, i)}{row.comment && <p>{row.comment}</p>}</div>)}</div>
      {(remaining || error) && <footer>{error && <p role="alert">{t('evaluations.panelError')}</p>}<button type="button" disabled={busy} onClick={() => void more(false)}>{t(error ? 'evaluations.retry' : 'evaluations.more')}</button></footer>}
    </div></div>, document.body)}
  </>
}
