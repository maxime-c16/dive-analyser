/**
 * My public dives as a scoreboard: the provisional community mean on a
 * split-flap tile, one pip per judge, and a switch for daily selections.
 * The long rules stay one tap away instead of above every list.
 */
import { scoreNumber } from './scoreFormatting'
import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { OwnedPanelLink } from './EvaluationSpaces'
import { useTranslation } from 'react-i18next'
import { getAutomaticScores, setAutomaticExclusion, type AutomaticScore } from '../../services/evaluationApi'

type Sort = 'recent' | 'top' | 'votes'
const SORTS: Sort[] = ['recent', 'top', 'votes']
const PIPS = 5

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
    setLoading(true); setError(false)
    getAutomaticScores(offset).then(data => { if (live) { setItems(data.items); setTotal(data.total) } })
      .catch(() => { if (live) setError(true) }).finally(() => { if (live) setLoading(false) })
    return () => { live = false }
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
    <details className="eval-rules">
      <summary>{t('evaluations.rulesSummary')}</summary>
      <p className="eval-note">{t('evaluations.communityNote')}</p>
    </details>
    {error && <div role="alert"><p>{t('evaluations.loadError')}</p><button className="eval-pass" onClick={() => setRetry(n => n + 1)}>{t('evaluations.retry')}</button></div>}
    {loading ? <p role="status">{t('common.loading')}</p> : <>
      {!items.length && <p>{t('evaluations.noPublicDives')}</p>}
      <ul className="eval-board-list">{sorted.map((item, index) => <li key={item.dive_id} className="eval-board-row" data-excluded={item.excluded ? 'true' : undefined} style={{ '--i': index } as CSSProperties}>
        <SplitFlap value={item.mean_score} />
        <div className="eval-board-main">
          <strong>{item.dive_code} · {item.height}</strong>
          <p className="sr-only">{t('evaluations.communityScore', { score: scoreNumber(item.mean_score, i18n.language), count: item.rating_count })}</p>
          <span className="eval-pips" aria-hidden>
            {Array.from({ length: Math.min(PIPS, item.rating_count) }, (_, n) => <i key={n} />)}
            {item.rating_count > PIPS && <b>+{item.rating_count - PIPS}</b>}
            <em>{t('evaluations.judgesCount', { count: item.rating_count })}</em>
          </span>
          <OwnedPanelLink requestId={item.dive_id} automatic />
        </div>
        <label className="eval-switch">
          <input type="checkbox" role="switch" checked={!item.excluded} disabled={busy !== null} onChange={() => void toggle(item)}
            aria-label={t(item.excluded ? 'evaluations.includeAutomatic' : 'evaluations.excludeAutomatic')} />
          <span aria-hidden />
          <small>{t('evaluations.inSelections')}</small>
        </label>
      </li>)}</ul>
      <div className="eval-judge-actions">
        {offset > 0 && <button className="eval-pass" onClick={() => setOffset(n => Math.max(0, n - 20))}>{t('evaluations.previousPage')}</button>}
        {offset + items.length < total && <button className="eval-pass" onClick={() => setOffset(n => n + 20)}>{t('evaluations.more')}</button>}
      </div>
    </>}
  </section>
}

/** Airport-board digits that rattle through a few values before landing. */
function SplitFlap({ value }: { value: number | null }) {
  const { i18n } = useTranslation()
  const target = value === null ? scoreNumber(0, i18n.language).replace(/\d/g, '–') : scoreNumber(value, i18n.language).padStart(4, ' ')
  const [shown, setShown] = useState(() => reducedMotion() || value === null ? target : scramble(target))
  useEffect(() => {
    if (reducedMotion() || value === null) { setShown(target); return }
    let ticks = 0
    const timer = window.setInterval(() => {
      ticks += 1
      if (ticks >= 7) { setShown(target); window.clearInterval(timer) } else setShown(scramble(target, ticks / 7))
    }, 70)
    return () => window.clearInterval(timer)
  }, [target, value])
  return (
    <span className="eval-flap" data-empty={value === null ? 'true' : undefined} aria-hidden>
      {[...shown].map((char, index) => <span key={index} data-char={char === '.' || char === ',' ? 'dot' : undefined}>{char.trim()}</span>)}
    </span>
  )
}

function scramble(target: string, settled = 0) {
  return [...target].map((char, index) => /\d/.test(char) && index / target.length >= settled ? String(Math.floor(Math.random() * 10)) : char).join('')
}

function reducedMotion() {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}
