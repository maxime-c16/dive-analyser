import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { attemptScore, type Attempt } from '../../utils/attemptPresentation'
import { fmtScore, median, scoreBand, smoothingWindow } from '../../utils/codeStats'
import ScoreChart from './ScoreChart'
import { compareTechniqueHistoryOrder, techniqueDate, techniqueHistoryOrder, techniqueTimestamp } from './techniqueDates'

export type ScorePanel = {
  header: ReactNode
  content: ReactNode
  corrections?: { attempts: Attempt[]; from?: number; until?: number }
}

type Correction = {
  id: number
  label: string | null
  start_at: string
  start_id: number
  end_at: string | null
  end_id: number | null
  uncertain_until: string | null
}

const targetSize = 44

export default function CorrectionScores({ attempts, corrections, from, until, loading }: {
  attempts: Attempt[]; corrections: Correction[]; from?: number; until?: number; loading?: boolean
}) {
  const { t, i18n } = useTranslation()
  const [selection, setSelection] = useState<number>()
  if (loading) return <p className="ca-correction-note" role="status">{t('technique.loadingRatings')}</p>
  if (from != null && until != null && from >= until) return <p className="ca-correction-note">{t('codeAnalysis.noCorrections')}</p>
  const entries = corrections.map(item => ({
    ...item, start: techniqueHistoryOrder(item.start_at, item.start_id),
    end: item.end_at ? techniqueHistoryOrder(item.end_at, item.end_id ?? 0) : undefined,
  })).filter(item =>
    (from == null || item.end == null || compareTechniqueHistoryOrder(item.end, { at: from, microseconds: 0, id: 0 }) > 0) &&
    (until == null || item.start.at < until),
  ).sort((a, b) => compareTechniqueHistoryOrder(a.start, b.start) || a.id - b.id)
  const active = entries.find(item => item.id === selection) ?? entries[entries.length - 1]
  const samples = attempts.filter(attempt => Boolean(attempt.performance)).map(attempt => ({
    ...techniqueHistoryOrder(attempt.history_occurred_at ?? attempt.dive_datetime, attempt.id), value: attemptScore(attempt),
  })).filter(dive => Number.isFinite(dive.at) && (from == null || dive.at >= from) && (until == null || dive.at < until))
    .sort(compareTechniqueHistoryOrder)
  const date = (at: number) => techniqueDate(new Date(at).toISOString(), i18n.language)
  const activeRange = active
    ? `${active.uncertain_until ? '≈ ' : ''}${date(active.start.at)} – ${active.end == null ? t('technique.now') : date(active.end.at)}`
    : ''
  if (!active && !samples.length) return <p className="ca-correction-note">{t('codeAnalysis.noCorrections')}</p>

  const times = [...samples.map(sample => sample.at), ...entries.flatMap(entry => entry.end == null ? [entry.start.at] : [entry.start.at, entry.end.at])]
  const start = Math.max(Math.min(...times), from ?? -Infinity)
  const end = Math.max(start, Math.min(Math.max(...times), until ?? Infinity))
  const month = new Intl.DateTimeFormat(i18n.language, {
    month: 'short',
    year: new Date(start).getUTCFullYear() !== new Date(end).getUTCFullYear() ? '2-digit' : undefined,
    timeZone: 'UTC',
  })
  const uncertainUntil = active?.uncertain_until
    ? Math.min(techniqueTimestamp(active.uncertain_until), active.end?.at ?? Infinity) : undefined
  const showUncertain = uncertainUntil != null && active != null && Math.min(uncertainUntil, end) > Math.max(start, active.start.at)
  const visibleStarts = entries.filter(entry => entry.start.at >= start && entry.start.at <= end)
  const during = (dive: typeof samples[number]) => Boolean(active &&
    compareTechniqueHistoryOrder(dive, active.start) >= 0 &&
    (active.end == null || compareTechniqueHistoryOrder(dive, active.end) < 0))
  const periodScores = samples.filter(during).map(sample => sample.value)
  const selectedMedian = median(periodScores)
  const points = samples.map(sample => ({
    key: sample.id, occurredAt: sample.at, month: '', monthLabel: '', value: sample.value,
    band: scoreBand(sample.value), highlight: during(sample),
  }))
  return <div className="ca-corrections">
    <ScoreChart timeScale timeDomain={{ start, end }} points={points} selected={null} showCursor={false} outsideOpacity={.55}
      smoothing={smoothingWindow(points.length, false)}
      label={active ? `${t('codeAnalysis.modeCorrections')}. ${active.label}. ${activeRange}` : t('codeAnalysis.modeCorrections')}
      boundary={active ? { start: active.start.at, end: active.end?.at, uncertainUntil } : undefined}
      renderTimeline={active && entries.length > 1 && visibleStarts.length ? (dateX, width) => {
        const groups: { x: number; entries: typeof entries }[] = []
        for (const entry of visibleStarts) {
          const x = Math.max(targetSize / 2, Math.min(width - targetSize / 2, dateX(entry.start.at)))
          const last = groups[groups.length - 1]
          if (last && x - last.x < targetSize + 4) last.entries.push(entry)
          else groups.push({ x, entries: [entry] })
        }
        return <div className="ca-correction-lane" role="group" aria-label={t('codeAnalysis.correctionStarts')}>
          {groups.map(group => {
            const first = group.entries[0], last = group.entries[group.entries.length - 1]
            const index = group.entries.findIndex(entry => entry.id === active.id)
            const selected = index >= 0
            const count = group.entries.length
            const firstDate = date(first.start.at), lastDate = date(last.start.at)
            const groupRange = firstDate === lastDate ? firstDate : `${firstDate} – ${lastDate}`
            const label = count === 1 ? `${first.label}, ${groupRange}` : selected
              ? t('codeAnalysis.correctionGroupPosition', { count, position: index + 1, dates: groupRange })
              : t('codeAnalysis.correctionGroup', { count, dates: groupRange })
            return <div key={first.id}>
              {last.start.at > first.start.at && <span aria-hidden="true" className="ca-correction-bracket"
                data-selected={selected} style={{ left: dateX(first.start.at), width: dateX(last.start.at) - dateX(first.start.at) }} />}
              <button type="button" style={{ left: group.x }} aria-pressed={selected} aria-label={label}
                title={label} onClick={() => setSelection(group.entries[(index + 1) % count].id)}>
                <span aria-hidden="true">{count === 1 ? '◆' : selected ? `${index + 1}/${count}` : count}</span>
                <small aria-hidden="true">{month.format((selected ? active : first).start.at)}</small>
              </button>
            </div>
          })}
        </div>
      } : undefined} />
    <div className="ca-legend">
      <span><i />{t('codeAnalysis.legendMedian')}</span>
      <span><i className="ca-legend-band" />{t('codeAnalysis.legendRange')}</span>
      {active && <span><i className="ca-legend-correction" />{t('codeAnalysis.legendCorrection')}</span>}
      {showUncertain && <span><i className="ca-legend-uncertain" />{t('codeAnalysis.legendUncertainCorrection')}</span>}
    </div>
    {entries.length > 1 && <label className="ca-correction-picker">
      {t('codeAnalysis.chooseCorrection')}
      <select value={active?.id} onChange={event => setSelection(Number(event.target.value))}>
        {entries.map(entry => <option key={entry.id} value={entry.id}>{date(entry.start.at)} · {entry.label}</option>)}
      </select>
    </label>}
    {active ? <div className="ca-correction-detail" aria-live="polite">
      <strong>{active.label}</strong>
      <span>{activeRange}</span>
      <span>{selectedMedian == null ? t('codeAnalysis.correctionNoPlottedScores') : t('codeAnalysis.correctionStats', { count: periodScores.length, median: fmtScore(selectedMedian) })}</span>
    </div> : <p className="ca-correction-note">{t('codeAnalysis.noCorrections')}</p>}
  </div>
}
