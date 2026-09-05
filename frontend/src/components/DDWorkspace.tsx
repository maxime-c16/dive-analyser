import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { AlertTriangle, ArrowUpRight, BookOpenCheck, Loader2 } from 'lucide-react'
import { DDOverview, getDDOverview } from '../services/ddApi'
import { divePositionName } from '../utils/divePosition'

type Props = { compact?: boolean }

function number(value: number | null) {
  return value == null ? '—' : value.toFixed(1)
}

function DDWorkspace({ compact = false }: Props) {
  const [scope, setScope] = useState<'self' | 'all'>('self')
  const [data, setData] = useState<DDOverview | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setError(null)
    getDDOverview(scope).then((result) => {
      if (!cancelled) setData(result)
    }).catch(() => {
      if (!cancelled) setError('Difficulty data could not be loaded.')
    })
    return () => { cancelled = true }
  }, [scope])

  if (!data && !error) {
    return <section className="border border-app bg-app-panel p-5" aria-label="Loading degree of difficulty"><div className="flex items-center gap-2 text-app-muted"><Loader2 className="h-4 w-4 animate-spin" /> Loading live degree-of-difficulty data</div></section>
  }
  if (error || !data) {
    return <section className="border border-app bg-app-panel p-5 text-app-muted">{error}</section>
  }

  const chart = data.timeline.map((point) => ({ ...point, label: new Date(`${point.month}-01T12:00:00`).toLocaleDateString(undefined, { month: 'short', year: '2-digit' }) }))
  const summary = data.summary
  const topInventory = compact ? data.inventory.slice(0, 4) : data.inventory.slice(0, 12)

  return (
    <section className="border border-app bg-app-panel" aria-labelledby="dd-workspace-title">
      <header className="border-b border-app px-4 py-4 sm:px-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex items-center gap-2 text-app-accent"><BookOpenCheck className="h-4 w-4" /><span className="text-xs font-semibold uppercase tracking-[0.14em]">Live rulebook calculation</span></div>
            <h2 id="dd-workspace-title" className="mt-2 text-xl font-semibold text-app-text sm:text-2xl">Degree of difficulty</h2>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-app-muted">Calculated from the versioned World Aquatics component formula for each recorded dive and board height. Execution score is not used.</p>
          </div>
          <label className="text-sm text-app-muted">View
            <select aria-label="Difficulty scope" value={scope} onChange={(event) => setScope(event.target.value as 'self' | 'all')} className="app-input ml-2 mt-1 w-full py-1 text-sm sm:mt-0 sm:w-auto">
              <option value="self">My dives</option>
              <option value="all">All divers</option>
            </select>
          </label>
        </div>
      </header>

      <div className="grid grid-cols-2 border-b border-app sm:grid-cols-4">
        {[
          ['Defined attempts', `${summary.defined_attempt_count} of ${summary.attempt_count}`, `${summary.unique_dive_count} dive and board combinations`],
          ['Median DD', number(summary.median_dd), 'Typical recorded difficulty'],
          ['Highest DD', number(summary.max_dd), 'Highest formula-defined attempt'],
          ['Not defined', String(summary.undefined_attempt_count), summary.undefined_attempt_count ? 'Straight jumps or invalid combinations excluded' : 'All attempts are defined'],
        ].map(([label, value, note]) => <div key={label} className="min-w-0 border-b border-r border-app px-4 py-4 last:border-r-0 sm:border-b-0 sm:px-5"><div className="text-xs font-medium uppercase tracking-[0.1em] text-app-muted">{label}</div><div className="mt-2 whitespace-normal break-words text-xl font-semibold leading-tight text-app-text sm:text-2xl">{value}</div><div className="mt-1 text-xs leading-5 text-app-muted">{note}</div></div>)}
      </div>

      <div className={compact ? 'p-4' : 'grid gap-6 p-4 sm:p-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(19rem,.8fr)]'}>
        <div className="min-w-0">
          <div className="mb-3 flex items-baseline justify-between gap-3"><div><h3 className="font-semibold text-app-text">Monthly difficulty range</h3><p className="mt-1 text-sm text-app-muted">Median and highest formula-defined DD per month.</p></div><span className="shrink-0 text-xs text-app-muted">{chart.length} months</span></div>
          <div className="h-60 min-w-0 sm:h-72">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chart} margin={{ top: 12, right: 8, left: -20, bottom: 0 }}>
                <defs><linearGradient id="ddMedianFill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#54beab" stopOpacity={0.3} /><stop offset="100%" stopColor="#54beab" stopOpacity={0} /></linearGradient></defs>
                <CartesianGrid stroke="rgba(82,96,105,.35)" vertical={false} />
                <XAxis dataKey="label" tick={{ fill: '#98a2aa', fontSize: 11 }} tickLine={false} axisLine={false} minTickGap={28} />
                <YAxis domain={['dataMin - 0.2', 'dataMax + 0.2']} tick={{ fill: '#98a2aa', fontSize: 11 }} tickLine={false} axisLine={false} allowDecimals />
                <Tooltip contentStyle={{ background: '#15191c', border: '1px solid rgba(126,146,156,.7)', borderRadius: 0 }} labelStyle={{ color: '#edf2f4' }} formatter={(value: number, name: string) => [value.toFixed(1), name === 'median_dd' ? 'Median DD' : 'Highest DD']} />
                <Area type="stepAfter" dataKey="max_dd" stroke="#c9d4d6" strokeWidth={1.5} fill="none" name="max_dd" />
                <Area type="monotone" dataKey="median_dd" stroke="#54beab" strokeWidth={3} fill="url(#ddMedianFill)" name="median_dd" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-2 text-xs leading-5 text-app-muted">The pale line is the monthly maximum; the green area is the monthly median. No arbitrary difficulty bands are applied.</p>
        </div>

        {!compact && <aside className="border-t border-app pt-5 lg:border-l lg:border-t-0 lg:pl-6 lg:pt-0"><h3 className="font-semibold text-app-text">Board-height context</h3><p className="mt-1 text-sm leading-6 text-app-muted">DD changes with the official board-height table.</p><dl className="mt-4 space-y-3">{data.height_breakdown.map((item) => <div key={item.height} className="flex items-end justify-between border-b border-app pb-3"><div><dt className="font-medium text-app-text">{item.height}</dt><dd className="mt-1 text-xs text-app-muted">{item.attempt_count} attempts</dd></div><dd className="text-right"><div className="text-sm font-semibold text-app-text">Median {item.median_dd.toFixed(1)}</div><div className="mt-1 text-xs text-app-muted">Max {item.max_dd.toFixed(1)}</div></dd></div>)}</dl></aside>}
      </div>

      {!compact && <div className="border-t border-app p-4 sm:p-6"><div className="flex flex-wrap items-end justify-between gap-3"><div><h3 className="font-semibold text-app-text">Recorded DD inventory</h3><p className="mt-1 text-sm text-app-muted">Each value links to the exact canonical dive analysis.</p></div><span className="text-xs text-app-muted">{data.reference.label}</span></div><div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">{topInventory.map((item) => <Link key={`${item.dive_code}-${item.height}`} to={`/dives/analysis/${item.dive_code}`} className="group border border-app bg-app-panel-elevated p-3 transition-colors hover:border-app-strong"><div className="flex items-start justify-between gap-3"><div><div className="font-mono text-lg font-semibold text-app-text">{item.dive_code}</div><div className="mt-1 text-xs text-app-muted">{divePositionName(null, item.dive_code)} · {item.height} · {item.attempt_count} attempts</div></div><div className="flex items-center gap-1 text-app-accent"><span className="font-semibold">{item.dd_value.toFixed(1)}</span><ArrowUpRight className="h-4 w-4" /></div></div></Link>)}</div></div>}

      {summary.legacy_mismatch_count > 0 && <div className="flex gap-3 border-t border-app bg-app-panel-elevated px-4 py-3 text-sm text-app-muted sm:px-6"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" /><p>{summary.legacy_mismatch_count} stored legacy DD values differ from the formula result. They are visible for audit only and are being reconciled; the view above uses the live formula.</p></div>}
      {data.undefined_reasons.length > 0 && <div className="border-t border-app px-4 py-3 text-xs leading-5 text-app-muted sm:px-6">Excluded from official DD: {data.undefined_reasons.map((item) => `${item.attempt_count} ${item.reason.toLowerCase()}`).join(' · ')}</div>}
    </section>
  )
}

export default DDWorkspace
