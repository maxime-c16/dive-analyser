/**
 * My public dives: the community mean, judge count, and daily-selection switch.
 * The long rules stay one tap away instead of above every list.
 */
import { scoreNumber } from './scoreFormatting'
import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { OwnedPanelLink } from './EvaluationSpaces'
import WarmUp from './EvaluationWarmUp'
import { useTranslation } from 'react-i18next'
import { getAutomaticScores, loadAutomaticIdentities, setAutomaticExclusion, type AutomaticScore } from '../../services/evaluationApi'
import { Link } from 'react-router-dom'
import { format, parseISO } from 'date-fns'
import { appLocale } from '../../utils/dateLocale'
import DiveThumbnail from '../DiveThumbnail'

type Sort = 'recent' | 'top' | 'votes'
const SORTS: Sort[] = ['recent', 'top', 'votes']

export default function AutomaticScores() {
  const { t, i18n } = useTranslation()
  const [items, setItems] = useState<AutomaticScore[]>([])
  const [offset, setOffset] = useState(0)
  const [total, setTotal] = useState(0)
  const [error, setError] = useState(false)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<number | null>(null)
  const [retry, setRetry] = useState(0)
  const [sort, setSort] = useState<Sort>('recent')
  useEffect(() => {
    let live = true
    const controller = new AbortController()
    setLoading(true); setError(false)
    getAutomaticScores(offset).then(data => {
      if (!live) return
      setItems(data.items); setTotal(data.total)
      void loadAutomaticIdentities(data.items, (id, identity) => {
        if (live) setItems(rows => rows.map(row => row.dive_id === id ? { ...row, identity } : row))
      }, controller.signal)
    })
      .catch(() => { if (live) setError(true) }).finally(() => { if (live) setLoading(false) })
    return () => { live = false; controller.abort() }
  }, [offset, retry])
  async function toggle(item: AutomaticScore) {
    setBusy(item.dive_id); setError(false)
    try {
      await setAutomaticExclusion(item.dive_id, !item.excluded)
      setItems(rows => rows.map(row => row.dive_id === item.dive_id ? { ...row, excluded: !item.excluded } : row))
    } catch { setError(true) } finally { setBusy(null) }
  }
  // Sorting re-orders the loaded page only; paging stays server-ordered.
  const sorted = useMemo(() => sort === 'recent' ? items : [...items].sort((a, b) => sort === 'top'
    ? (b.mean_score ?? -1) - (a.mean_score ?? -1) || b.rating_count - a.rating_count
    : b.rating_count - a.rating_count || (b.mean_score ?? -1) - (a.mean_score ?? -1)), [items, sort])
  return <section className="eval-owned eval-board">
    <header className="eval-board-head">
      <h2>{t('evaluations.tabCommunity')}</h2>
      <div className="eval-sort" role="group" aria-label={t('evaluations.sortAria')}>
        {SORTS.map(value => <button key={value} type="button" aria-pressed={sort === value} onClick={() => setSort(value)}>{t(`evaluations.sort.${value}`)}</button>)}
      </div>
    </header>
    {error && <div role="alert"><p>{t('evaluations.loadError')}</p><button className="eval-pass" onClick={() => setRetry(n => n + 1)}>{t('evaluations.retry')}</button></div>}
    {loading ? <WarmUp /> : <>
      {!items.length && <p>{t('evaluations.noPublicDives')}</p>}
      <ul className="eval-board-list">{sorted.map((item, index) => <li key={item.dive_id} className="eval-board-row" data-excluded={item.excluded ? 'true' : undefined} style={{ '--i': index } as CSSProperties}>
        <Link className="eval-attempt-preview" to={`/dives?clip=${item.dive_id}`} aria-label={`${item.dive_code} · ${item.height}`}>
          {item.identity?.video_uuid ? <DiveThumbnail compact dive={item.identity} /> : <span aria-hidden>{item.dive_code}</span>}
        </Link>
        <div className="eval-board-main">
          <div className="eval-attempt-heading">
            {item.mean_score !== null && <strong className="eval-mean" aria-hidden>{scoreNumber(item.mean_score, i18n.language)}</strong>}
            <Link to={`/dives?clip=${item.dive_id}`} className="eval-dive-link"><span>{item.dive_code} · {item.height}</span><small className="eval-attempt-id">#{item.dive_id}</small></Link>
          </div>
          {item.identity?.dive_datetime && <time className="eval-attempt-date" dateTime={item.identity.dive_datetime}>{format(parseISO(item.identity.dive_datetime), items.filter(row => row.identity?.dive_datetime === item.identity?.dive_datetime).length > 1 ? 'd MMM yyyy' : 'd MMM yyyy · HH:mm:ss', { locale: appLocale() })}</time>}
          <p className="sr-only">{t('evaluations.communityScore', { score: scoreNumber(item.mean_score, i18n.language), count: item.rating_count })}</p>
          <span className="eval-pips" aria-hidden>
            <em>{item.rating_count ? t('evaluations.judgesCount', { count: item.rating_count }) : t('evaluations.awaitingReviews')}</em>
          </span>
          <OwnedPanelLink requestId={item.dive_id} automatic />
        </div>
        <label className="eval-switch">
          <input type="checkbox" role="switch" checked={!item.excluded} disabled={busy !== null} onChange={() => void toggle(item)}
            aria-label={t('evaluations.inSelections')} />
          <span aria-hidden />
          <small>{t('evaluations.inSelections')}</small>
        </label>
      </li>)}</ul>
      <div className="eval-judge-actions">
        {offset > 0 && <button className="eval-pass" onClick={() => setOffset(n => Math.max(0, n - 20))}>{t('evaluations.previousPage')}</button>}
        {offset + items.length < total && <button className="eval-pass" onClick={() => setOffset(n => n + 20)}>{t('evaluations.more')}</button>}
      </div>
    </>}
    <details className="eval-rules">
      <summary>{t('evaluations.rulesSummary')}</summary>
      <p className="eval-note">{t('evaluations.communityNote')}</p>
    </details>
  </section>
}
