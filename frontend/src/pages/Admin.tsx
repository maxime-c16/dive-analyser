import { useCallback, useEffect, useRef, useState } from 'react'
import { Activity, AlertTriangle, CheckCircle2, Database, HardDrive, Loader2, Mail, Radio, RefreshCw, Server, Users, Video } from 'lucide-react'
import { getOperationsStatus, type OperationsStatus } from '../services/operationsApi'
import { useAuth } from '../contexts/AuthContext'
import { useNavigate, useSearchParams } from 'react-router-dom'
import AdminUsers from '../components/AdminUsers'
import HeldBatchEmails from '../components/HeldBatchEmails'

function bytes(value?: number | null) {
  if (value == null) return 'Unknown'
  if (value < 1024 ** 2) return `${Math.round(value / 1024)} KiB`
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MiB`
  return `${(value / 1024 ** 3).toFixed(1)} GiB`
}

function stamp(value?: string | null) {
  if (!value) return 'Not recorded'
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

function title(value: string) { return value.replace(/_/g, ' ') }

function Tone({ state }: { state: string }) {
  const healthy = ['ok', 'current', 'ready', 'running', 'complete', 'enabled'].includes(state)
  const caution = ['paused', 'stale', 'permission_required', 'query_timeout', 'sync_incomplete'].includes(state)
  const active = ['running', 'claimed', 'materializing', 'exporting', 'transcoding', 'uploading', 'verifying'].includes(state)
  const Icon = active ? Loader2 : healthy ? CheckCircle2 : caution ? AlertTriangle : Activity
  const color = healthy ? 'text-app-accent' : caution ? 'text-amber-300' : 'text-app-muted'
  return <span data-ops-active={active || undefined} className={`inline-flex items-center gap-1.5 text-xs font-medium ${color}`}><Icon aria-hidden className={`h-3.5 w-3.5 ${active ? 'ops-running-icon' : ''}`} />{title(state)}{active && <span className="sr-only"> actively updating</span>}</span>
}

function Metric({ label, value, detail }: { label: string; value: string | number; detail: string }) {
  return <div className="border border-app bg-app-panel p-4"><div className="text-[11px] font-semibold uppercase tracking-[0.13em] text-app-muted">{label}</div><div className="mt-2 text-2xl font-semibold tabular-nums text-app-text">{value}</div><div className="mt-1 text-xs leading-5 text-app-muted">{detail}</div></div>
}

function Progress({ done, total }: { done: number; total: number }) {
  const percent = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0
  return <div className="mt-3"><div className="flex justify-between text-xs text-app-muted"><span>{done.toLocaleString()} of {total.toLocaleString()}</span><span>{percent}%</span></div><div className="mt-1 h-1.5 overflow-hidden bg-app-panel-elevated"><div className="h-full bg-app-accent transition-[width] duration-500" style={{ width: `${percent}%` }} /></div></div>
}

export default function Admin() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [search, setSearch] = useSearchParams()
  const directorySearch = search.toString()
  const manage = useCallback((id: number) => navigate(`/admin/users/${id}?return=${encodeURIComponent(`/admin?${directorySearch}`)}`), [navigate, directorySearch])
  const directoryChange = useCallback((query: string, status: string, offset: number) => {
    setSearch(previous => { const next = new URLSearchParams(previous); for (const [key, value] of Object.entries({ q: query, status: status === 'all' ? '' : status, offset: offset ? String(offset) : '' })) { if (value) next.set(key, value); else next.delete(key) }; return next }, { replace: true })
  }, [setSearch])
  const [tab, setTab] = useState<'users' | 'emails' | 'system'>('users')
  const [status, setStatus] = useState<OperationsStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const refreshSystem = useRef<(() => Promise<void>) | null>(null)

  async function refresh(signal?: AbortSignal, silent = false) {
    if (!silent) { setLoading(true); setError(null) }
    try {
      const next = await getOperationsStatus(signal)
      if (!signal?.aborted) setStatus(next)
    }
    catch (reason) { if (!signal?.aborted && (reason as Error).name !== 'AbortError') setError(reason instanceof Error ? reason.message : 'Unable to load operations status') }
    finally { if (!signal?.aborted && !silent) setLoading(false) }
  }

  useEffect(() => {
    if (tab !== 'system') return
    const controller = new AbortController()
    let timeout: ReturnType<typeof window.setTimeout> | undefined
    let inFlight: Promise<void> | undefined
    function poll(silent = false): Promise<void> {
      if (controller.signal.aborted) return Promise.resolve()
      if (inFlight) return inFlight
      window.clearTimeout(timeout)
      inFlight = refresh(controller.signal, silent).finally(() => {
        inFlight = undefined
        if (!controller.signal.aborted) {
          timeout = window.setTimeout(() => { void poll(true) }, 15_000)
        }
      })
      return inFlight
    }
    refreshSystem.current = () => poll()
    void poll()
    return () => { refreshSystem.current = null; controller.abort(); window.clearTimeout(timeout) }
  }, [tab])

  const primary = status?.agents.find((agent) => agent.agent_id === 'mac-media-01') ?? status?.agents[0]
  const storage = primary?.storage_status
  const active = status?.media.active_jobs ?? []
  const runningWorkflows = status?.workflows.filter((workflow) => workflow.status === 'running') ?? []

  return <div className="ops-workspace mx-auto max-w-[1420px] space-y-6">
    <header className="border-b border-app pb-5">
      <div><h1 className="text-3xl font-semibold tracking-tight text-app-text">Administration</h1></div>
      <nav aria-label="Administration sections" className="mt-4 flex gap-2">
        <button
          type="button"
          onClick={() => setTab('users')}
          aria-current={tab === 'users' ? 'true' : undefined}
          className={`touch-target inline-flex items-center gap-2 border px-4 text-sm font-medium ${
            tab === 'users' ? 'border-app-strong bg-app-panel text-app-text' : 'border-app text-app-muted hover:text-app-text'
          }`}
        >
          <Users className="h-4 w-4" aria-hidden />
          Users
        </button>
        <button
          type="button"
          onClick={() => setTab('emails')}
          aria-current={tab === 'emails' ? 'true' : undefined}
          className={`touch-target inline-flex items-center gap-2 border px-4 text-sm font-medium ${
            tab === 'emails' ? 'border-app-strong bg-app-panel text-app-text' : 'border-app text-app-muted hover:text-app-text'
          }`}
        >
          <Mail className="h-4 w-4" aria-hidden />
          Emails
        </button>
        <button
          type="button"
          onClick={() => setTab('system')}
          aria-current={tab === 'system' ? 'true' : undefined}
          className={`touch-target inline-flex items-center gap-2 border px-4 text-sm font-medium ${
            tab === 'system' ? 'border-app-strong bg-app-panel text-app-text' : 'border-app text-app-muted hover:text-app-text'
          }`}
        >
          <Server className="h-4 w-4" aria-hidden />
          System
        </button>
      </nav>
    </header>

    {tab === 'users' ? (
      <AdminUsers currentUserId={user?.user_id} onManage={manage} initialQuery={search.get('q') ?? ''} initialStatus={search.get('status') === 'disabled' ? 'disabled' : search.get('status') === 'active' ? 'active' : 'all'} initialOffset={Math.max(0, Number(search.get('offset')) || 0)} onDirectoryChange={directoryChange} />
    ) : tab === 'emails' ? (
      <HeldBatchEmails />
    ) : (
    <>
    <div className="sm:flex sm:items-end sm:justify-between">
      <h2 className="text-xl font-semibold text-app-text">Operations</h2>
      <button type="button" onClick={() => void refreshSystem.current?.()} disabled={loading} className="touch-target mt-4 inline-flex items-center justify-center gap-2 border border-app-strong bg-app-panel px-4 text-sm font-medium text-app-text disabled:opacity-50 sm:mt-0"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} /> Refresh</button>
    </div>

    {error && <div role="alert" className="flex gap-3 border border-amber-700/60 bg-amber-950/20 p-4 text-sm text-amber-100"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />{error}</div>}
    {loading && !status && <div className="border border-app bg-app-panel p-10 text-center text-sm text-app-muted">Loading…</div>}

    {status && <>
      <section aria-label="Application health" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="Application" value="Healthy" detail={`${status.application.api_title} · v${status.application.api_version}`} />
        <Metric label="Database" value={status.dependencies.database === 'ok' ? 'Connected' : title(status.dependencies.database)} detail="Snapshot query completed" />
        <Metric label="Media activity" value={status.dependencies.active_media_jobs} detail={status.dependencies.active_media_jobs ? 'Controlled leased jobs' : runningWorkflows.length ? 'Run active; awaiting next lease' : 'No active media jobs'} />
        <Metric label="Personal Dive Value" value={status.application.personal_dive_value_enabled ? 'Enabled' : 'Disabled'} detail="Backend feature flag" />
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.25fr_.75fr]">
        <article className="border border-app bg-app-panel"><div className="border-b border-app px-4 py-4"><div className="flex items-center gap-2"><Radio className="h-4 w-4 text-app-accent" /><h2 className="font-semibold text-app-text">Media node</h2></div></div>
          {primary ? <div className="divide-y divide-[var(--app-border)]"><div className="grid gap-4 p-4 sm:grid-cols-2"><div><div className="text-xs uppercase tracking-wide text-app-muted">Worker</div><div className="mt-1 font-medium text-app-text">{primary.hostname}</div><div className="mt-1"><Tone state={primary.heartbeat_state} /></div></div><div><div className="text-xs uppercase tracking-wide text-app-muted">Photos access</div><div className="mt-1"><Tone state={primary.photos_access_status} /></div><div className="mt-1 text-xs text-app-muted">Last query {stamp(primary.last_successful_photos_query_at)}</div></div></div>
            <div className="grid gap-px bg-[var(--app-border)] sm:grid-cols-3"><Metric label="Leasing" value={primary.leasing_enabled ? 'Enabled' : 'Disabled'} detail={primary.capabilities.join(' · ') || 'No capabilities'} /><Metric label="Internal free" value={bytes(storage?.internal?.free_bytes ?? primary.internal_free_bytes)} detail={storage?.internal?.processing_stopped ? 'Processing stop active' : storage?.internal?.historical_recall_paused ? 'Historical recall paused' : 'Storage gate open'} /><Metric label="Managed sources" value={bytes(storage?.managed_sources?.total_bytes)} detail={`${bytes(storage?.managed_sources?.quota_bytes)} quota`} /></div>
            {storage?.managed_sources && <div className="grid grid-cols-2 gap-3 p-4 text-xs text-app-muted sm:grid-cols-4"><span>Permanent <b className="block pt-1 text-sm font-medium text-app-text">{bytes(storage.managed_sources.permanent_bytes)}</b></span><span>Recent <b className="block pt-1 text-sm font-medium text-app-text">{bytes(storage.managed_sources.recent_bytes)}</b></span><span>Temporary <b className="block pt-1 text-sm font-medium text-app-text">{bytes(storage.managed_sources.temporary_bytes)}</b></span><span>Diagnostics <b className="block pt-1 text-sm font-medium text-app-text">{bytes(storage.managed_sources.diagnostic_bytes)}</b></span></div>}</div> : <div className="p-5 text-sm text-app-muted">No media agent is registered.</div>}
        </article>

        <article className="border border-app bg-app-panel"><div className="border-b border-app px-4 py-4"><div className="flex items-center gap-2"><Video className="h-4 w-4 text-app-accent" /><h2 className="font-semibold text-app-text">Active work</h2></div></div>
          {active.length ? <div className="divide-y divide-[var(--app-border)]">{active.map((job) => <div key={job.id} data-ops-active="true" className="p-4"><div className="flex items-center justify-between gap-3"><div><div className="font-medium text-app-text">{title(job.rendition)}</div><div className="mt-1 text-xs text-app-muted">Job #{job.id} · {job.claimed_by ?? 'Unassigned'}</div></div><Tone state={job.status} /></div><Progress done={job.progress} total={100} /></div>)}</div> : runningWorkflows.length ? <div className="p-5"><div className="flex items-center gap-2 font-medium text-app-text"><Loader2 aria-hidden className="ops-running-icon h-4 w-4 text-app-accent" />Workflow active, awaiting the next lease</div><p className="mt-2 text-sm leading-6 text-app-muted">{runningWorkflows.map((workflow) => workflow.target_rendition ? `${title(workflow.target_rendition)} ${workflow.label}` : workflow.label).join(' · ')} remains running.</p></div> : <div className="p-5 text-sm text-app-muted">No active media job or running workflow.</div>}
        </article>
      </section>

      <section className="border border-app bg-app-panel"><div className="border-b border-app px-4 py-4"><div className="flex items-center gap-2"><HardDrive className="h-4 w-4 text-app-accent" /><h2 className="font-semibold text-app-text">Durable media cache</h2></div></div><div className="grid gap-px bg-[var(--app-border)] sm:grid-cols-3">{status.media.cache.filter((entry) => entry.status === 'ready').map((entry) => <Metric key={`${entry.rendition}-${entry.status}`} label={title(entry.rendition)} value={entry.count.toLocaleString()} detail={`${bytes(entry.bytes)} ready cache`} />)}</div><div className="flex flex-wrap gap-2 px-4 py-3 text-xs text-app-muted">{Object.entries(status.media.jobs_by_status).map(([key, count]) => <span key={key} className="border border-app px-2 py-1"><b className="text-app-text">{count}</b> {title(key)}</span>)}</div></section>

      <section className="border border-app bg-app-panel"><div className="border-b border-app px-4 py-4"><div className="flex items-center gap-2"><Server className="h-4 w-4 text-app-accent" /><h2 className="font-semibold text-app-text">Controlled workflows</h2></div></div><div className="grid gap-px bg-[var(--app-border)] lg:grid-cols-2">{status.workflows.map((workflow) => <article key={`${workflow.kind}-${workflow.id}`} className="bg-app-panel p-4"><div className="flex items-start justify-between gap-3"><div><h3 className="font-medium text-app-text">{workflow.target_rendition ? `${title(workflow.target_rendition)} · ${workflow.label}` : workflow.label}</h3><p className="mt-1 text-xs text-app-muted">Run #{workflow.id} · {title(workflow.kind)}</p></div><Tone state={workflow.status} /></div><Progress done={workflow.completed_items} total={workflow.total_items} /><div className="mt-3 grid grid-cols-3 gap-2 text-xs text-app-muted"><span>Ready <b className="block text-sm text-app-text">{workflow.ready_items}</b></span><span>Unavailable <b className="block text-sm text-app-text">{workflow.unavailable_items}</b></span><span>Skipped <b className="block text-sm text-app-text">{workflow.skipped_items}</b></span></div>{workflow.pause_reason && <p className="mt-3 border-l-2 border-amber-400 pl-2 text-xs text-amber-200">Paused: {title(workflow.pause_reason)}</p>}</article>)}</div></section>

      <section className="border border-app bg-app-panel"><div className="border-b border-app px-4 py-4"><h2 className="font-semibold text-app-text">Representative coverage</h2></div><div className="grid gap-px bg-[var(--app-border)] sm:grid-cols-2 lg:grid-cols-4"><Metric label="Dive codes" value={status.representatives.codes.total} detail={`${status.representatives.codes.fully_ready} fully ready`} /><Metric label="Partial coverage" value={status.representatives.codes.partially_ready} detail={`${status.representatives.codes.zero_ready} with no ready representative`} /><Metric label="Ready attempts" value={status.representatives.representatives.ready} detail={`${status.representatives.representatives.replacement_available} replacements available`} /><Metric label="Proxy coverage" value={status.representatives.renditions.proxy_ready} detail={`${status.representatives.renditions.poster_ready} posters ready`} /></div></section>

      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-app pt-4 text-xs text-app-muted"><span>Generated {stamp(status.generated_at)}</span></footer>
    </>}
    </>
    )}
  </div>
}
