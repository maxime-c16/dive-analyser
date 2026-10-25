import React, { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation, useNavigate } from 'react-router-dom'
import { format, parseISO } from 'date-fns'
import { diveCodeName } from '../../i18n/diveNames'
import { appLocale } from '../../utils/dateLocale'
import { DAY_MS, scoreBand, fmtScore } from '../../utils/codeStats'
import type { ActivityWindow, CodeSummaries, CodeSummary } from '../../services/codeSummariesApi'
import { Sparkline, TrendBadge } from './parts'

const STALE_DAYS = 45

function Delta({ current, previous, digits = 0 }: { current: number | null; previous: number | null; digits?: number }) {
  const { t } = useTranslation()
  if (current == null || previous == null) return null
  const delta = current - previous
  const tone = delta > 0 ? 'ca-up' : delta < 0 ? 'ca-down' : 'ca-flat'
  return <p className={tone}>{delta > 0 ? '▲ +' : delta < 0 ? '▼ ' : '= '}{Math.abs(delta) < 1e-9 ? '0' : delta.toFixed(digits)} {t('codeAnalysis.vsPrevious30')}</p>
}

/** Library › Progrès: what moved, what was dropped, and where the volume went. */
export default function ProgressHub({ data }: { data: CodeSummaries }) {
  const { t, i18n } = useTranslation()
  const lang = i18n.language?.startsWith('fr') ? 'fr' : 'en'
  const navigate = useNavigate()
  const location = useLocation()
  const [week, setWeek] = useState<number | null>(null)
  const open = (code: string, query = '') => navigate(`/dives/analysis/${encodeURIComponent(code)}${query}`, { state: { returnTo: `${location.pathname}${location.search}` } })
  const now = Date.parse(data.generated_at)
  const ranked = useMemo(() => data.codes.filter(code => code.analytics && code.scored_count >= 6), [data.codes])
  const rising = ranked.filter(code => (code.trend?.delta ?? 0) >= 0.5).sort((a, b) => b.trend!.delta - a.trend!.delta).slice(0, 4)
  const falling = ranked.filter(code => (code.trend?.delta ?? 0) <= -0.5).sort((a, b) => a.trend!.delta - b.trend!.delta).slice(0, 4)
  const stale = ranked.filter(code => code.attempt_count >= 15 && now - Date.parse(code.last_attempt_at) > STALE_DAYS * DAY_MS)
    .sort((a, b) => b.attempt_count - a.attempt_count).slice(0, 4)
  const months = data.activity.months
  const heatCodes = useMemo(() => data.codes.filter(code => code.analytics)
    .map(code => [code, months.reduce((sum, month) => sum + (code.months[month]?.count ?? 0), 0)] as const)
    .filter(([, count]) => count > 0).sort((a, b) => b[1] - a[1]).slice(0, 14).map(([code]) => code), [data.codes, months])
  const weeks = data.activity.weeks
  const maxWeek = Math.max(1, ...weeks.map(item => item.attempt_count))
  const monthName = (month: string) => format(parseISO(`${month}-01`), 'MMM', { locale: appLocale() }).replace('.', '')
  const { current, previous } = data.activity
  const kpi = (key: keyof ActivityWindow, label: string, digits = 0) => <div className="ca-hk">
    <dt>{label}</dt>
    <dd className={key === 'median' && current.median != null ? `ca-t-${scoreBand(current.median)}` : undefined}>{current[key] == null ? '—' : Number(current[key]).toFixed(digits)}</dd>
    <Delta current={current[key]} previous={previous[key]} digits={digits} />
  </div>
  const mover = (code: CodeSummary, side: React.ReactNode) => <button key={code.dive_code} type="button" className="ca-mv" onClick={() => open(code.dive_code)}>
    <span><span className="ca-mv-code">{code.dive_code}</span><small>{t('codeAnalysis.attemptsShort', { count: code.attempt_count })}</small></span>
    <span style={{ minWidth: 0 }}><small>{diveCodeName(code.dive_code, lang)}</small><Sparkline values={code.spark} width={110} height={24} /></span>
    <span style={{ textAlign: 'right' }}>{side}</span>
  </button>
  const selectedWeek = week != null ? weeks[week] : null
  return <div className="ca ca-hub ca-arrive">
    <dl className="ca-hub-kpis" style={{ margin: 0 }}>
      {kpi('attempt_count', t('codeAnalysis.kpi.attempts30'))}
      {kpi('session_count', t('codeAnalysis.kpi.sessions30'))}
      {kpi('code_count', t('codeAnalysis.kpi.codes30'))}
      {kpi('median', t('codeAnalysis.kpi.median30'), 1)}
    </dl>
    <div className="ca-movers">
      <section className="ca-panel"><div className="ca-panel-h"><h2>{t('codeAnalysis.rising')}</h2><span>{t('codeAnalysis.sixWeeks')}</span></div>
        {rising.length ? rising.map(code => mover(code, <TrendBadge delta={code.trend?.delta} />)) : <p className="ca-flat" style={{ margin: 0 }}>{t('codeAnalysis.nothingClear')}</p>}</section>
      <section className="ca-panel"><div className="ca-panel-h"><h2>{t('codeAnalysis.falling')}</h2></div>
        {falling.length ? falling.map(code => mover(code, <TrendBadge delta={code.trend?.delta} />)) : <p className="ca-flat" style={{ margin: 0 }}>{t('codeAnalysis.nothingClear')}</p>}</section>
      <section className="ca-panel"><div className="ca-panel-h"><h2>{t('codeAnalysis.resume')}</h2><span>{t('codeAnalysis.resumeHint', { days: STALE_DAYS })}</span></div>
        {stale.length ? stale.map(code => mover(code, <span className="ca-flat" style={{ fontSize: 12 }}>{format(parseISO(code.last_attempt_at), 'd MMM yy', { locale: appLocale() })}</span>)) : <p className="ca-flat" style={{ margin: 0 }}>{t('codeAnalysis.allCurrent')}</p>}</section>
    </div>
    {heatCodes.length > 0 && <section className="ca-panel"><div className="ca-panel-h"><h2>{t('codeAnalysis.heatTitle')}</h2><span>{t('codeAnalysis.heatHint')}</span></div>
      <div className="ca-heat-wrap"><table className="ca-heat">
        <thead><tr><th />{months.map(month => <th key={month} scope="col">{monthName(month)}</th>)}</tr></thead>
        <tbody>{heatCodes.map(code => <tr key={code.dive_code}>
          <th scope="row"><button type="button" onClick={() => open(code.dive_code)}>{code.dive_code}</button></th>
          {months.map(month => {
            const cell = code.months[month]
            if (!cell || cell.median == null) return <td key={month}><span /></td>
            return <td key={month}><button type="button" className={`ca-r-${scoreBand(cell.median)}`}
              aria-label={t('codeAnalysis.heatCell', { code: code.dive_code, month: monthName(month), count: cell.count, median: fmtScore(cell.median) })}
              title={t('codeAnalysis.heatCell', { code: code.dive_code, month: monthName(month), count: cell.count, median: fmtScore(cell.median) })}
              onClick={() => open(code.dive_code, `?month=${month}`)}>{fmtScore(cell.median)}</button></td>
          })}
        </tr>)}</tbody>
      </table></div></section>}
    <section className="ca-panel"><div className="ca-panel-h"><h2>{t('codeAnalysis.volume')}</h2>
      <span>{selectedWeek ? t('codeAnalysis.weekOf', { date: format(parseISO(selectedWeek.start), 'd MMM', { locale: appLocale() }), count: selectedWeek.attempt_count }) : t('codeAnalysis.weeks', { count: weeks.length })}</span></div>
      <div className="ca-vol">{weeks.map((item, index) => <button key={item.start} type="button" aria-pressed={week === index}
        aria-label={t('codeAnalysis.weekOf', { date: format(parseISO(item.start), 'd MMM', { locale: appLocale() }), count: item.attempt_count })}
        style={{ height: `${Math.max(2, item.attempt_count / maxWeek * 100)}%`, animationDelay: `${index * 15}ms` }} onClick={() => setWeek(week === index ? null : index)} />)}</div>
      {selectedWeek && <div className="ca-scroll" style={{ marginTop: 10 }}>
        {Object.entries(selectedWeek.codes).map(([code, count]) => <button key={code} type="button" className="ca-pill" onClick={() => open(code)}><span style={{ fontFamily: 'ui-monospace, monospace' }}>{code}</span> {count}</button>)}
        {!selectedWeek.attempt_count && <span className="ca-flat">{t('codeAnalysis.emptyWeek')}</span>}
      </div>}
    </section>
  </div>
}
