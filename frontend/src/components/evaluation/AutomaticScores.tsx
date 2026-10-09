import { useEffect, useState } from 'react'
import { OwnedPanelLink } from './EvaluationSpaces'
import { useTranslation } from 'react-i18next'
import { getAutomaticScores, setAutomaticExclusion, type AutomaticScore } from '../../services/evaluationApi'

export default function AutomaticScores() {
  const { t } = useTranslation()
  const [items, setItems] = useState<AutomaticScore[]>([])
  const [offset, setOffset] = useState(0)
  const [total, setTotal] = useState(0)
  const [error, setError] = useState(false)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<number | null>(null)
  const [retry, setRetry] = useState(0)
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
  return <section className="eval-owned">
    <p className="eval-note">{t('evaluations.communityNote')}</p>
    {error && <div role="alert"><p>{t('evaluations.loadError')}</p><button className="eval-pass" onClick={() => setRetry(n => n + 1)}>{t('evaluations.retry')}</button></div>}
    {loading ? <p role="status">{t('common.loading')}</p> : <>
      {!items.length && <p>{t('evaluations.noPublicDives')}</p>}
      <ul className="eval-panel-list">{items.map(item => <li key={item.dive_id}>
        <strong>{item.dive_code} · {item.height}</strong>
        <p>{t('evaluations.communityScore', { score: item.mean_score?.toFixed(1) ?? '—', count: item.rating_count })}</p>
        <button className="eval-pass" disabled={busy !== null} onClick={() => void toggle(item)} aria-pressed={item.excluded}>
          {t(item.excluded ? 'evaluations.includeAutomatic' : 'evaluations.excludeAutomatic')}
        </button>
        <OwnedPanelLink requestId={item.dive_id} automatic />
      </li>)}</ul>
      <div className="eval-judge-actions">
        {offset > 0 && <button className="eval-pass" onClick={() => setOffset(n => Math.max(0, n - 20))}>{t('evaluations.previousPage')}</button>}
        {offset + items.length < total && <button className="eval-pass" onClick={() => setOffset(n => n + 20)}>{t('evaluations.more')}</button>}
      </div>
    </>}
  </section>
}
