import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../../services/api'
import { techniqueDate } from './techniqueDates'
import ScoreChart, { type ChartPoint } from './ScoreChart'
import { scoreBand } from '../../utils/codeStats'

type Boundary = { id: number; start_at: string; end_at: string | null; uncertain_until: string | null; label: string | null }
type Row = {
  point_key: string; occurred_at: string; median: number; q1: number | null; q3: number | null
  curve_median: number | null; curve_q1: number | null; curve_q3: number | null
  segment: number; episode_id: number | null
}
type ChartPage = { items: Row[]; boundaries: Boundary[]; next: string | null; range: { start: string; end: string } | null }
type Props = { selection?: Boundary; onClear?: () => void; base: string; context: object; revision: number; selected?: number; onSelect: (id: number) => void }
const time = (date: string) => Date.parse(/(?:Z|[+-]\d\d:\d\d)$/.test(date) ? date : date + 'Z')

export default function TechniqueTrackChart(props: Props) {
  // Remount the page on edits and scope changes so old cursors and data cannot
  // be rendered with the new period dates.
  const key = JSON.stringify([props.base, props.context, props.revision, props.selected, props.selection])
  return <ChartView key={key} {...props} />
}

function ChartView({ base, context, selected, onSelect, onClear, selection }: Props) {
  const { t } = useTranslation()
  const [showAll, setShowAll] = useState(false)
  const episode = showAll ? undefined : selected
  return <ChartScope key={episode ?? 'all'} base={base} context={context} episode={episode}
    selection={showAll ? undefined : selection} onSelect={onSelect}
    switchLabel={selected != null ? t(showAll ? 'technique.thisPeriod' : 'technique.allPeriods') : undefined}
    onSwitch={onClear ?? (() => setShowAll(value => !value))} />
}

function ChartScope({ base, context, episode, selection, onSelect, switchLabel, onSwitch }: {
  base: string; context: object; episode?: number; selection?: Boundary; onSelect: Props['onSelect']; switchLabel?: string; onSwitch: () => void
}) {
  const { t, i18n } = useTranslation()
  const [after, setAfter] = useState('')
  const [result, setResult] = useState<{ after: string; page: ChartPage | null }>()
  const params = JSON.stringify({ ...context, after, episode_id: episode })

  useEffect(() => {
    const controller = new AbortController()
    api.post<ChartPage>(`${base}/track-chart`, JSON.parse(params), { signal: controller.signal }).then(({ data }) => {
      if (!controller.signal.aborted) setResult({ after, page: data })
    }).catch(() => {
      if (!controller.signal.aborted) setResult({ after, page: null })
    })
    return () => controller.abort()
  }, [base, params, after])

  const current = result?.after === after ? result : undefined
  const page = current?.page
  const rows = page?.items ?? []
  const period = page?.boundaries.find(boundary => boundary.id === episode) ?? selection
  const start = period?.start_at ?? page?.range?.start
  const end = period?.end_at ?? page?.range?.end ?? start
  const points: ChartPoint[] = rows.map(row => ({
    key: row.point_key, segment: row.segment, occurredAt: time(row.occurred_at),
    month: row.occurred_at.slice(0, 7), monthLabel: '', value: row.median, band: scoreBand(row.median),
    lo: row.q1 ?? undefined, hi: row.q3 ?? undefined,
    curveMedian: row.curve_median, curveQ1: row.curve_q1, curveQ3: row.curve_q3,
    highlight: episode != null && row.episode_id === episode,
  }))
  const date = (value: string) => techniqueDate(value, i18n.language)
  const label = period?.label ?? t('technique.allPeriods')
  return <div className="th-chart">
    <div className="th-chart-selection">
      <div><strong>{label}</strong>{start && end && <span>{date(start)} – {period && !period.end_at ? t('technique.now') : date(end)}</span>}</div>
      {switchLabel && <button className="th-text-button" onClick={onSwitch}>{switchLabel}</button>}
    </div>
    {!current ? <p role="status">{t('technique.loadingRatings')}</p> : !page ? <p role="alert">{t('technique.unavailable')}</p> : !points.length ? <p>{t('technique.noRatedDives')}</p> :
      <ScoreChart timeScale timeDomain={start && end ? {
        start: time(start), end: period && !period.end_at ? Math.max(time(end), Date.now()) : time(end),
      } : undefined}
        selectionMode="tap" markers={period ? undefined : page.boundaries.map(boundary => ({
          at: time(boundary.start_at), until: boundary.uncertain_until ? time(boundary.uncertain_until) : undefined,
        }))}
        points={points} smoothing={3} showCursor={false} selected={null}
        onSelect={index => { const id = rows[index]?.episode_id; if (id != null) onSelect(id) }}
        label={t('technique.ratingsDuring')}
        boundary={period ? { start: time(period.start_at), end: period.end_at ? time(period.end_at) : undefined, uncertainUntil: period.uncertain_until ? time(period.uncertain_until) : undefined } : undefined}
      />}
    {(after || page?.next) && <div className="th-pagination">
      {after && <button onClick={() => setAfter('')}>{t('common.back')}</button>}
      {page?.next && <button onClick={() => setAfter(page.next!)}>{t('technique.moreHistory')}</button>}
    </div>}
  </div>
}
