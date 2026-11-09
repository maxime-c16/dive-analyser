import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../../services/api'
import ScoreChart, { type ChartPoint } from './ScoreChart'
import { scoreBand } from '../../utils/codeStats'

type Boundary = { id: number; start_at: string; end_at: string | null; uncertain_until: string | null; label: string | null }
const time = (date: string) => Date.parse(date + 'Z')
export default function TechniqueTrackChart({ base, context, revision, selected, onSelect }: { base: string; context: object; revision: number; selected: number | undefined; onSelect: (id: number) => void }) {
  const { t } = useTranslation()
  const [points, setPoints] = useState<ChartPoint[]>([]), [after, setAfter] = useState(''), [next, setNext] = useState<string | null>(null)
  const [boundaries, setBoundaries] = useState<Boundary[]>([]), [pointEpisodes, setPointEpisodes] = useState<(number | null)[]>([])
  const [error, setError] = useState('')
  const key = JSON.stringify({ context, revision })
  useEffect(() => { setAfter('') }, [key])
  useEffect(() => {
    let current = true
    setPoints([]); setBoundaries([]); setError('')
    api.post(`${base}/track-chart`, { ...context, after }).then(({ data }) => {
      if (!current) return
      setNext(data.next); setBoundaries(data.boundaries); setPointEpisodes(data.items.map((r: { episode_id: number | null }) => r.episode_id))
      setPoints(data.items.map((r: { point_key: string; occurred_at: string; median: number; q1: number | null; q3: number | null; curve_median: number | null; curve_q1: number | null; curve_q3: number | null; segment: number }) => ({ key: r.point_key, segment: r.segment, occurredAt: time(r.occurred_at), month: r.occurred_at.slice(0, 7), monthLabel: r.occurred_at.slice(0, 10), value: r.median, band: scoreBand(r.median), lo: r.q1 ?? undefined, hi: r.q3 ?? undefined, curveMedian: r.curve_median, curveQ1: r.curve_q1, curveQ3: r.curve_q3 })))
    }).catch(() => { if (current) setError(t('technique.unavailable')) })
    return () => { current = false }
  }, [base, key, after, t])
  const selectedBoundary = boundaries.find(b => b.id === selected)
  const first = points[0]?.occurredAt, last = points[points.length - 1]?.occurredAt
  const start = selectedBoundary && (!first || (selectedBoundary.uncertain_until && time(selectedBoundary.uncertain_until) >= first)) ? time(selectedBoundary.start_at) : first
  const grouped = [...new Set(boundaries.map(b => b.start_at))].map(date => boundaries.filter(b => b.start_at === date))
  return <div>{error && <p role="alert">{error}</p>}<ScoreChart markers={grouped.map(group => ({ at: time(group[0].start_at), until: group[0].uncertain_until ? time(group[0].uncertain_until) : undefined }))} points={points.map((point, i) => ({ ...point, highlight: selected != null && pointEpisodes[i] === selected }))} smoothing={3} selected={selected == null ? null : pointEpisodes.findIndex(id => id === selected)} onSelect={index => { const id = pointEpisodes[index]; if (id != null) onSelect(id) }} label={t('technique.ratingsDuring')} boundary={start != null ? { start, end: last, uncertainUntil: selectedBoundary?.uncertain_until ? time(selectedBoundary.uncertain_until) : undefined } : undefined} />
    <div>{grouped.map(group => <button className="ca-btn" key={group[0].start_at} aria-pressed={group.some(b => b.id === selected)} onClick={() => { const i = group.findIndex(b => b.id === selected); onSelect(group[(i + 1) % group.length].id) }}>{group[0].start_at} · {group.length > 1 ? group.length : group[0].label ?? t('technique.unknown')}{group[0].uncertain_until ? ` ≈ ${group[0].uncertain_until}` : ''}</button>)}</div>
    <button className="ca-btn" disabled={!after} onClick={() => setAfter('')}>{t('common.back')}</button><button className="ca-btn" disabled={next === null} onClick={() => setAfter(next!)}>{t('technique.next')}</button>
  </div>
}
