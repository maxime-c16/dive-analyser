import { useEffect, useState } from 'react'
import { AlertTriangle, Database, HardDrive, Image, RefreshCw } from 'lucide-react'
import { getCatalogSummary, getLatestCatalogRun, getMediaAgents, getRecallManifest, planCatalogPopulation, planRecallBatch, recallOne, startCatalog, type CatalogPopulationPlan, type CatalogRun, type CatalogSummary, type MediaAgentStatus, type RecallBatchPlan, type RecallItem } from '../services/mediaRecallApi'

function bytes(value?: number | null) {
  if (value == null) return 'Unknown'
  return `${(value / 1024 ** 3).toFixed(1)} GiB`
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(value))
}

export default function MediaRecall() {
  const [agents, setAgents] = useState<MediaAgentStatus[]>([])
  const [items, setItems] = useState<RecallItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busyUuid, setBusyUuid] = useState<string | null>(null)
  const [plan, setPlan] = useState<RecallBatchPlan | null>(null)
  const [catalogRun, setCatalogRun] = useState<CatalogRun | null>(null)
  const [catalogSummary, setCatalogSummary] = useState<CatalogSummary | null>(null)
  const [populationPlan, setPopulationPlan] = useState<CatalogPopulationPlan | null>(null)

  async function refresh() {
    setLoading(true)
    setError(null)
    try {
      const [nextAgents, nextItems, nextCatalogRun, nextCatalogSummary] = await Promise.all([getMediaAgents(), getRecallManifest(25), getLatestCatalogRun(), getCatalogSummary()])
      setAgents(nextAgents)
      setItems(nextItems)
      setCatalogRun(nextCatalogRun)
      setCatalogSummary(nextCatalogSummary)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to load recall operations')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void refresh() }, [])

  async function handleRecall(item: RecallItem) {
    setBusyUuid(item.video_uuid)
    setError(null)
    try {
      await recallOne(item)
      await refresh()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to request this source')
    } finally {
      setBusyUuid(null)
    }
  }

  const primary = agents.find((agent) => agent.agent_id === 'mac-media-01') ?? agents[0]
  const storage = primary?.storage_status
  const catalogActive = catalogRun?.status === 'requested' || catalogRun?.status === 'cataloging'

  async function handleStartCatalog() {
    setError(null)
    try {
      setCatalogRun(await startCatalog())
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to start catalog')
    }
  }

  return (
    <div className="mx-auto max-w-[1320px] space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-app pb-5">
        <h1 className="text-2xl font-semibold text-app-text">Media recall</h1>
        <button type="button" onClick={() => void refresh()} className="flex items-center gap-2 border border-app bg-app-panel px-3 py-2 text-sm text-app-text" disabled={loading}>
          <RefreshCw className="h-4 w-4" /> Refresh
        </button>
      </header>

      {error && <div role="alert" className="border border-amber-700/60 bg-amber-950/20 px-4 py-3 text-sm text-amber-200">{error}</div>}

      <section aria-label="Mac media node status" className="border border-app bg-app-panel">
        <div className="grid gap-px bg-[var(--app-border)] sm:grid-cols-2 lg:grid-cols-4">
          <div className="bg-app-panel p-4"><div className="text-sm text-app-muted">Worker</div><div className="mt-1 font-medium text-app-text">{primary?.hostname ?? 'Not registered'}</div><div className="mt-1 text-xs text-app-muted">{primary?.leasing_enabled ? 'Leasing enabled' : 'Leasing disabled'}</div></div>
          <div className="bg-app-panel p-4"><div className="text-sm text-app-muted">Photos access</div><div className="mt-1 font-medium text-app-text">{primary?.photos_access_status ?? 'Unknown'}</div><div className="mt-1 text-xs text-app-muted">Last query {primary?.last_successful_photos_query_at ? formatDate(primary.last_successful_photos_query_at) : 'not recorded'}</div></div>
          <div className="bg-app-panel p-4"><div className="text-sm text-app-muted">Managed sources</div><div className="mt-1 font-medium text-app-text">{bytes(storage?.managed_sources.total_bytes)} / {bytes(storage?.managed_sources.quota_bytes)}</div><div className="mt-1 text-xs text-app-muted">Permanent {bytes(storage?.managed_sources.permanent_bytes)} · Recent {bytes(storage?.managed_sources.recent_bytes)}</div></div>
          <div className="bg-app-panel p-4"><div className="text-sm text-app-muted">Internal free</div><div className="mt-1 font-medium text-app-text">{bytes(storage?.internal.free_bytes ?? primary?.internal_free_bytes)}</div><div className="mt-1 text-xs text-app-muted">Emergency stop below 18 GiB</div></div>
        </div>
      </section>

      {(primary?.photos_access_status !== 'ok' || storage?.internal.historical_recall_paused) && (
        <div className="flex gap-3 border border-amber-700/50 bg-amber-950/15 px-4 py-3 text-sm text-amber-100">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{primary?.photos_access_status !== 'ok' ? `Recall remains disabled while Photos access is ${primary?.photos_access_status ?? 'unknown'}.` : 'Historical recall is paused by the internal free-space gate.'}</span>
        </div>
      )}

      <section aria-label="Captioned media catalog" className="border border-app bg-app-panel">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-app px-4 py-3">
          <h2 className="font-semibold text-app-text">Captioned video catalog</h2>
          <button type="button" onClick={() => void handleStartCatalog()} disabled={catalogActive || primary?.photos_access_status !== 'ok'} className="border border-app-strong px-3 py-2 text-sm text-app-text disabled:cursor-not-allowed disabled:opacity-40">{catalogActive ? 'Catalog running' : 'Start catalog'}</button>
        </div>
        <div className="grid gap-px bg-[var(--app-border)] sm:grid-cols-2 lg:grid-cols-5">
          <div className="bg-app-panel p-4"><div className="text-sm text-app-muted">Run state</div><div className="mt-1 font-medium text-app-text">{catalogRun?.status ?? 'Not started'}</div><div className="mt-1 text-xs text-app-muted">Revision {catalogRun?.catalog_revision ?? '—'}</div></div>
          <div className="bg-app-panel p-4"><div className="text-sm text-app-muted">Observed</div><div className="mt-1 font-medium text-app-text">{catalogSummary?.total ?? catalogRun?.observed_count ?? 0}</div><div className="mt-1 text-xs text-app-muted">Checkpoint {catalogRun?.checkpoint ?? 0}</div></div>
          <div className="bg-app-panel p-4"><div className="text-sm text-app-muted">Eligible</div><div className="mt-1 font-medium text-app-text">{catalogSummary?.eligibility.eligible ?? catalogRun?.eligible_count ?? 0}</div><div className="mt-1 text-xs text-app-muted">Mapped and parseable</div></div>
          <div className="bg-app-panel p-4"><div className="text-sm text-app-muted">Playable</div><div className="mt-1 font-medium text-app-text">{catalogSummary?.media.ready ?? 0}</div><div className="mt-1 text-xs text-app-muted">Poster + proxy ready</div></div>
          <div className="bg-app-panel p-4"><div className="text-sm text-app-muted">Excluded</div><div className="mt-1 font-medium text-app-text">{catalogSummary?.eligibility.excluded ?? catalogRun?.excluded_count ?? 0}</div></div>
        </div>
        {catalogRun?.pause_reason && <div className="border-t border-app px-4 py-3 text-sm text-amber-200">Paused: {catalogRun.pause_reason.split('_').join(' ')}</div>}
      </section>

      <section className="border border-app bg-app-panel p-4">
        <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="font-semibold text-app-text">Rolling population plan</h2><button type="button" disabled={!catalogSummary?.catalog_revision} onClick={() => void planCatalogPopulation().then(setPopulationPlan).catch((e) => setError(String(e)))} className="border border-app-strong px-3 py-2 text-sm text-app-text disabled:opacity-40">Plan population</button></div>
        {populationPlan && <div className="mt-4 grid gap-3 border-t border-app pt-4 text-sm sm:grid-cols-2 lg:grid-cols-5"><div><span className="text-app-muted">Eligible</span><div>{populationPlan.total_eligible_assets}</div></div><div><span className="text-app-muted">Already ready</span><div>{populationPlan.already_fully_ready}</div></div><div><span className="text-app-muted">Rolling peak</span><div>{bytes(populationPlan.estimated_mac_rolling_peak_bytes)}</div></div><div><span className="text-app-muted">Projected free</span><div>{bytes(populationPlan.projected_free_bytes_at_peak)}</div></div><div><span className="text-app-muted">Execution</span><div>{populationPlan.execution_allowed ? 'Allowed' : `Paused: ${populationPlan.blocked_reasons.join(', ').split('_').join(' ')}`}</div></div></div>}
      </section>

      <section className="border border-app bg-app-panel p-4">
        <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="font-semibold text-app-text">Zero-ready Typical plan</h2><button type="button" onClick={() => void planRecallBatch().then(setPlan).catch((e) => setError(String(e)))} className="border border-app-strong px-3 py-2 text-sm text-app-text">Plan bounded batch</button></div>
        {plan && <div className="mt-4 grid gap-3 text-sm sm:grid-cols-4"><div><span className="text-app-muted">Items</span><div>{plan.items.length}</div></div><div><span className="text-app-muted">Peak</span><div>{bytes(plan.estimated_temporary_peak_bytes)}</div></div><div><span className="text-app-muted">Projected free</span><div>{bytes(plan.projected_free_bytes)}</div></div><div><span className="text-app-muted">Gate</span><div>{plan.quota_result}</div></div></div>}
      </section>

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-app-text">Bounded recall manifest</h2>
          <span className="text-sm text-app-muted">{items.length} items shown</span>
        </div>
        <div className="space-y-3 sm:hidden">
          {items.map((item) => <article key={item.video_uuid} className="border border-app bg-app-panel p-4">
            <div className="flex items-start justify-between gap-3"><div><h3 className="font-semibold text-app-text">{item.dive_code}</h3><p className="mt-1 text-xs text-app-muted">{item.role === 'median' ? 'Typical' : item.role ?? item.height ?? 'Attempt'} · {item.diver ?? 'Unknown diver'} · {formatDate(item.date)}</p></div><span className="text-xs text-app-muted">{item.source_readiness}</span></div>
            <p className="mt-3 text-sm text-app-muted">{item.reason.split('_').join(' ')}</p>
            <div className="mt-3 grid grid-cols-2 gap-2 text-xs"><div className="border border-app p-2"><span className="text-app-muted">Poster</span><div className="mt-1 text-app-text">{item.media_readiness.poster}</div></div><div className="border border-app p-2"><span className="text-app-muted">Video</span><div className="mt-1 text-app-text">{item.media_readiness.proxy_360p}</div></div></div>
            <button type="button" disabled={busyUuid === item.video_uuid || item.media_readiness.poster === 'ready' || primary?.photos_access_status !== 'ok' || Boolean(storage?.internal.processing_stopped)} onClick={() => void handleRecall(item)} className="touch-target mt-4 w-full border border-app-strong bg-app-panel-elevated px-3 text-sm text-app-text disabled:cursor-not-allowed disabled:opacity-40">{busyUuid === item.video_uuid ? 'Requesting…' : 'Recall one'}</button>
          </article>)}
        </div>
        <div className="mobile-scroll-region hidden overflow-x-auto border border-app sm:block">
          <table className="w-full min-w-[880px] border-collapse text-left text-sm">
            <thead className="bg-app-panel-elevated text-app-muted"><tr><th className="px-4 py-3 font-medium">Dive</th><th className="px-4 py-3 font-medium">Reason</th><th className="px-4 py-3 font-medium">Source</th><th className="px-4 py-3 font-medium">Media</th><th className="px-4 py-3 font-medium">Date</th><th className="px-4 py-3 text-right font-medium">Action</th></tr></thead>
            <tbody className="divide-y divide-[var(--app-border)]">
              {items.map((item) => (
                <tr key={item.video_uuid} className="bg-app hover:bg-app-panel/60">
                  <td className="px-4 py-3"><div className="font-medium text-app-text">{item.dive_code}</div><div className="text-xs text-app-muted">{item.role === 'median' ? 'Typical' : item.role ?? item.height ?? 'Attempt'} · {item.diver ?? 'Unknown diver'}</div></td>
                  <td className="px-4 py-3 text-app-muted">{item.reason.split('_').join(' ')}</td>
                  <td className="px-4 py-3"><span className="inline-flex items-center gap-2 text-app-text"><Database className="h-4 w-4 text-app-muted" />{item.source_readiness}</span></td>
                  <td className="px-4 py-3 text-app-muted"><span className="mr-3 inline-flex items-center gap-1"><Image className="h-4 w-4" />{item.media_readiness.poster}</span><span className="inline-flex items-center gap-1"><HardDrive className="h-4 w-4" />{item.media_readiness.proxy_360p}</span></td>
                  <td className="px-4 py-3 text-app-muted">{formatDate(item.date)}</td>
                  <td className="px-4 py-3 text-right"><button type="button" disabled={busyUuid === item.video_uuid || item.media_readiness.poster === 'ready' || primary?.photos_access_status !== 'ok' || Boolean(storage?.internal.processing_stopped)} onClick={() => void handleRecall(item)} className="touch-target border border-app-strong bg-app-panel px-3 py-1.5 text-sm text-app-text disabled:cursor-not-allowed disabled:opacity-40">{busyUuid === item.video_uuid ? 'Requesting…' : 'Recall one'}</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!loading && items.length === 0 && <div className="border border-app p-8 text-center text-sm text-app-muted">No recall items.</div>}
        {loading && <div className="border border-app p-8 text-center text-sm text-app-muted">Loading…</div>}
      </section>
    </div>
  )
}
