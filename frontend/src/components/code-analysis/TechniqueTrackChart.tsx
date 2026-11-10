import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../../services/api'
import { techniqueDate } from './techniqueDates'
import ScoreChart, { type ChartPoint } from './ScoreChart'
import { scoreBand } from '../../utils/codeStats'

type Boundary = { id: number; start_at: string; end_at: string | null; uncertain_until: string | null; label: string | null }
const time = (date: string) => Date.parse(date + 'Z')
export default function TechniqueTrackChart({ base, context, revision, selected, onSelect, onClear, selection }: { selection?: Boundary; onClear?: () => void; base: string; context: object; revision: number; selected: number | undefined; onSelect: (id: number) => void }) {
  const { t, i18n } = useTranslation()
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
      setPoints(data.items.map((r: { point_key: string; occurred_at: string; median: number; q1: number | null; q3: number | null; curve_median: number | null; curve_q1: number | null; curve_q3: number | null; segment: number }) => ({ key: r.point_key, segment: r.segment, occurredAt: time(r.occurred_at), month: r.occurred_at.slice(0, 7), monthLabel: techniqueDate(r.occurred_at, i18n.language).replace(/\s\d{4}$/, ''), value: r.median, band: scoreBand(r.median), lo: r.q1 ?? undefined, hi: r.q3 ?? undefined, curveMedian: r.curve_median, curveQ1: r.curve_q1, curveQ3: r.curve_q3 })))
    }).catch(() => { if (current) setError(t('technique.unavailable')) })
    return () => { current = false }
  }, [base, key, after, t])
  const selectedBoundary = selection ?? boundaries.find(b => b.id === selected)
  const last = points[points.length - 1]?.occurredAt
  const start = selectedBoundary ? time(selectedBoundary.start_at) : undefined
  const grouped = [...new Set(boundaries.map(b => b.start_at))].map(date => boundaries.filter(b => b.start_at === date))
  return <div className="th-chart"><div className="th-chart-selection" role="status"><div><strong>{selectedBoundary?.label ?? t('technique.allPeriods')}</strong><span>{selectedBoundary ? techniqueDate(selectedBoundary.start_at,i18n.language) : points[0] ? techniqueDate(new Date(points[0].occurredAt!).toISOString().replace(/Z$/,''),i18n.language) : ''} – {selectedBoundary?.end_at ? techniqueDate(selectedBoundary.end_at,i18n.language) : selectedBoundary ? t('technique.now') : last ? techniqueDate(new Date(last).toISOString().replace(/Z$/,''),i18n.language) : ''}</span></div>{onClear && <button disabled={!selectedBoundary} style={{visibility: selectedBoundary ? 'visible' : 'hidden'}} className="th-text-button" onClick={onClear}>{t('technique.allPeriods')}</button>}</div><ScoreChart timeScale selectionMode="tap" markers={grouped.map(group => ({ at: time(group[0].start_at), until: group[0].uncertain_until ? time(group[0].uncertain_until) : undefined }))} points={points.map((point, i) => ({ ...point, highlight: selected != null && pointEpisodes[i] === selected }))} smoothing={3} showCursor={false} selected={selected == null ? null : pointEpisodes.findIndex(id => id === selected)} onSelect={index => { const id = pointEpisodes[index]; if (id != null) onSelect(id) }} label={t('technique.ratingsDuring')} boundary={start != null ? { start, end: selectedBoundary?.end_at ? time(selectedBoundary.end_at) : last, uncertainUntil: selectedBoundary?.uncertain_until ? time(selectedBoundary.uncertain_until) : undefined } : undefined} />
    {(after || next) && <div className="th-pagination">{after && <button onClick={() => setAfter('')}>{t('common.back')}</button>}{next && <button onClick={() => setAfter(next!)}>{t('technique.moreHistory')}</button>}</div>}
  </div>
}
