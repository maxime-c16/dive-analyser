import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
import { appLanguage } from '../utils/dateLocale'
import { photosAccessLabel } from '../utils/mediaStatus'
import { AlertTriangle, Database, HardDrive, Image, RefreshCw } from 'lucide-react'
import PageLoading from '../components/PageLoading'
import { getCatalogSummary, getLatestCatalogRun, getMediaAgents, getRecallManifest, planCatalogPopulation, planRecallBatch, recallOne, startCatalog, type CatalogPopulationPlan, type CatalogRun, type CatalogSummary, type MediaAgentStatus, type RecallBatchPlan, type RecallItem } from '../services/mediaRecallApi'

function bytes(value?: number | null) {
  if (value == null) return i18n.t('recall.unknown')
  const gib = (value / 1024 ** 3).toLocaleString(appLanguage(), { minimumFractionDigits: 1, maximumFractionDigits: 1, useGrouping: false })
  return i18n.t('recall.gib', { value: gib })
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat(appLanguage(), { dateStyle: 'medium' }).format(new Date(value))
}

export default function MediaRecall() {
  const { t } = useTranslation()
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
      setError(reason instanceof Error ? reason.message : t('recall.loadError'))
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
      setError(reason instanceof Error ? reason.message : t('recall.requestError'))
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
      setError(reason instanceof Error ? reason.message : t('recall.catalogStartError'))
    }
  }

  return (
    <div className="mx-auto max-w-[1320px] space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-app pb-5">
        <h1 className="text-2xl font-semibold text-app-text">{t('recall.title')}</h1>
        <button type="button" onClick={() => void refresh()} className="flex items-center gap-2 border border-app bg-app-panel px-3 py-2 text-sm text-app-text" disabled={loading}>
          <RefreshCw className="h-4 w-4" /> {t('recall.refresh')}
        </button>
      </header>

      {error && <div role="alert" className="border border-amber-700/60 bg-amber-950/20 px-4 py-3 text-sm text-amber-200">{error}</div>}

      <section aria-label={t('recall.nodeStatusAria')} className="border border-app bg-app-panel">
        <div className="grid gap-px bg-[var(--app-border)] sm:grid-cols-2 lg:grid-cols-4">
          <div className="bg-app-panel p-4"><div className="text-sm text-app-muted">{t('recall.worker')}</div><div className="mt-1 font-medium text-app-text">{primary?.hostname ?? t('recall.notRegistered')}</div><div className="mt-1 text-xs text-app-muted">{primary?.leasing_enabled ? t('recall.leasingEnabled') : t('recall.leasingDisabled')}</div></div>
          <div className="bg-app-panel p-4"><div className="text-sm text-app-muted">{t('recall.photosAccess')}</div><div className="mt-1 font-medium text-app-text">{primary ? photosAccessLabel(primary.photos_access_status) : t('recall.unknown')}</div><div className="mt-1 text-xs text-app-muted">{t('recall.lastQuery', { when: primary?.last_successful_photos_query_at ? formatDate(primary.last_successful_photos_query_at) : t('recall.notRecorded') })}</div></div>
          <div className="bg-app-panel p-4"><div className="text-sm text-app-muted">{t('recall.managedSources')}</div><div className="mt-1 font-medium text-app-text">{bytes(storage?.managed_sources.total_bytes)} / {bytes(storage?.managed_sources.quota_bytes)}</div><div className="mt-1 text-xs text-app-muted">{t('recall.permanentRecent', { permanent: bytes(storage?.managed_sources.permanent_bytes), recent: bytes(storage?.managed_sources.recent_bytes) })}</div></div>
          <div className="bg-app-panel p-4"><div className="text-sm text-app-muted">{t('recall.internalFree')}</div><div className="mt-1 font-medium text-app-text">{bytes(storage?.internal.free_bytes ?? primary?.internal_free_bytes)}</div><div className="mt-1 text-xs text-app-muted">{t('recall.emergencyStop')}</div></div>
        </div>
      </section>

      {(primary?.photos_access_status !== 'ok' || storage?.internal.historical_recall_paused) && (
        <div className="flex gap-3 border border-amber-700/50 bg-amber-950/15 px-4 py-3 text-sm text-amber-100">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{primary?.photos_access_status !== 'ok' ? t('recall.disabledWhilePhotos', { status: primary ? photosAccessLabel(primary.photos_access_status) : t('recall.unknownLower') }) : t('recall.historicalPaused')}</span>
        </div>
      )}

      <section aria-label={t('recall.catalogAria')} className="border border-app bg-app-panel">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-app px-4 py-3">
          <h2 className="font-semibold text-app-text">{t('recall.catalogTitle')}</h2>
          <button type="button" onClick={() => void handleStartCatalog()} disabled={catalogActive || primary?.photos_access_status !== 'ok'} className="border border-app-strong px-3 py-2 text-sm text-app-text disabled:cursor-not-allowed disabled:opacity-40">{catalogActive ? t('recall.catalogRunning') : t('recall.startCatalog')}</button>
        </div>
        <div className="grid gap-px bg-[var(--app-border)] sm:grid-cols-2 lg:grid-cols-5">
          <div className="bg-app-panel p-4"><div className="text-sm text-app-muted">{t('recall.runState')}</div><div className="mt-1 font-medium text-app-text">{catalogRun?.status ?? t('recall.notStarted')}</div><div className="mt-1 text-xs text-app-muted">{t('recall.revision', { revision: catalogRun?.catalog_revision ?? '—' })}</div></div>
          <div className="bg-app-panel p-4"><div className="text-sm text-app-muted">{t('recall.observed')}</div><div className="mt-1 font-medium text-app-text">{catalogSummary?.total ?? catalogRun?.observed_count ?? 0}</div><div className="mt-1 text-xs text-app-muted">{t('recall.checkpoint', { value: catalogRun?.checkpoint ?? 0 })}</div></div>
          <div className="bg-app-panel p-4"><div className="text-sm text-app-muted">{t('recall.eligible')}</div><div className="mt-1 font-medium text-app-text">{catalogSummary?.eligibility.eligible ?? catalogRun?.eligible_count ?? 0}</div><div className="mt-1 text-xs text-app-muted">{t('recall.mappedParseable')}</div></div>
          <div className="bg-app-panel p-4"><div className="text-sm text-app-muted">{t('recall.playable')}</div><div className="mt-1 font-medium text-app-text">{catalogSummary?.media.ready ?? 0}</div><div className="mt-1 text-xs text-app-muted">{t('recall.posterProxyReady')}</div></div>
          <div className="bg-app-panel p-4"><div className="text-sm text-app-muted">{t('recall.excluded')}</div><div className="mt-1 font-medium text-app-text">{catalogSummary?.eligibility.excluded ?? catalogRun?.excluded_count ?? 0}</div></div>
        </div>
        {catalogRun?.pause_reason && <div className="border-t border-app px-4 py-3 text-sm text-amber-200">{t('recall.paused', { reason: catalogRun.pause_reason.split('_').join(' ') })}</div>}
      </section>

      <section className="border border-app bg-app-panel p-4">
        <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="font-semibold text-app-text">{t('recall.populationTitle')}</h2><button type="button" disabled={!catalogSummary?.catalog_revision} onClick={() => void planCatalogPopulation().then(setPopulationPlan).catch((e) => setError(String(e)))} className="border border-app-strong px-3 py-2 text-sm text-app-text disabled:opacity-40">{t('recall.planPopulation')}</button></div>
        {populationPlan && <div className="mt-4 grid gap-3 border-t border-app pt-4 text-sm sm:grid-cols-2 lg:grid-cols-5"><div><span className="text-app-muted">{t('recall.eligible')}</span><div>{populationPlan.total_eligible_assets}</div></div><div><span className="text-app-muted">{t('recall.alreadyReady')}</span><div>{populationPlan.already_fully_ready}</div></div><div><span className="text-app-muted">{t('recall.rollingPeak')}</span><div>{bytes(populationPlan.estimated_mac_rolling_peak_bytes)}</div></div><div><span className="text-app-muted">{t('recall.projectedFree')}</span><div>{bytes(populationPlan.projected_free_bytes_at_peak)}</div></div><div><span className="text-app-muted">{t('recall.execution')}</span><div>{populationPlan.execution_allowed ? t('recall.allowed') : t('recall.paused', { reason: populationPlan.blocked_reasons.join(', ').split('_').join(' ') })}</div></div></div>}
      </section>

      <section className="border border-app bg-app-panel p-4">
        <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="font-semibold text-app-text">{t('recall.batchTitle')}</h2><button type="button" onClick={() => void planRecallBatch().then(setPlan).catch((e) => setError(String(e)))} className="border border-app-strong px-3 py-2 text-sm text-app-text">{t('recall.planBatch')}</button></div>
        {plan && <div className="mt-4 grid gap-3 text-sm sm:grid-cols-4"><div><span className="text-app-muted">{t('recall.items')}</span><div>{plan.items.length}</div></div><div><span className="text-app-muted">{t('recall.peak')}</span><div>{bytes(plan.estimated_temporary_peak_bytes)}</div></div><div><span className="text-app-muted">{t('recall.projectedFree')}</span><div>{bytes(plan.projected_free_bytes)}</div></div><div><span className="text-app-muted">{t('recall.gate')}</span><div>{plan.quota_result}</div></div></div>}
      </section>

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-app-text">{t('recall.manifestTitle')}</h2>
          <span className="text-sm text-app-muted">{t('recall.itemsShown', { count: items.length })}</span>
        </div>
        <div className="space-y-3 sm:hidden">
          {items.map((item) => <article key={item.video_uuid} className="border border-app bg-app-panel p-4">
            <div className="flex items-start justify-between gap-3"><div><h3 className="font-semibold text-app-text">{item.dive_code}</h3><p className="mt-1 text-xs text-app-muted">{item.role === 'median' ? t('recall.typical') : item.role ?? item.height ?? t('recall.attempt')} · {item.diver ?? t('recall.unknownDiver')} · {formatDate(item.date)}</p></div><span className="text-xs text-app-muted">{item.source_readiness}</span></div>
            <p className="mt-3 text-sm text-app-muted">{item.reason.split('_').join(' ')}</p>
            <div className="mt-3 grid grid-cols-2 gap-2 text-xs"><div className="border border-app p-2"><span className="text-app-muted">{t('recall.poster')}</span><div className="mt-1 text-app-text">{item.media_readiness.poster}</div></div><div className="border border-app p-2"><span className="text-app-muted">{t('recall.video')}</span><div className="mt-1 text-app-text">{item.media_readiness.proxy_360p}</div></div></div>
            <button type="button" disabled={busyUuid === item.video_uuid || item.media_readiness.poster === 'ready' || primary?.photos_access_status !== 'ok' || Boolean(storage?.internal.processing_stopped)} onClick={() => void handleRecall(item)} className="touch-target mt-4 w-full border border-app-strong bg-app-panel-elevated px-3 text-sm text-app-text disabled:cursor-not-allowed disabled:opacity-40">{busyUuid === item.video_uuid ? t('recall.requesting') : t('recall.recallOne')}</button>
          </article>)}
        </div>
        <div className="mobile-scroll-region hidden overflow-x-auto border border-app sm:block">
          <table className="w-full min-w-[880px] border-collapse text-left text-sm">
            <thead className="bg-app-panel-elevated text-app-muted"><tr><th className="px-4 py-3 font-medium">{t('recall.colDive')}</th><th className="px-4 py-3 font-medium">{t('recall.colReason')}</th><th className="px-4 py-3 font-medium">{t('recall.colSource')}</th><th className="px-4 py-3 font-medium">{t('recall.colMedia')}</th><th className="px-4 py-3 font-medium">{t('recall.colDate')}</th><th className="px-4 py-3 text-right font-medium">{t('recall.colAction')}</th></tr></thead>
            <tbody className="divide-y divide-[var(--app-border)]">
              {items.map((item) => (
                <tr key={item.video_uuid} className="bg-app hover:bg-app-panel/60">
                  <td className="px-4 py-3"><div className="font-medium text-app-text">{item.dive_code}</div><div className="text-xs text-app-muted">{item.role === 'median' ? t('recall.typical') : item.role ?? item.height ?? t('recall.attempt')} · {item.diver ?? t('recall.unknownDiver')}</div></td>
                  <td className="px-4 py-3 text-app-muted">{item.reason.split('_').join(' ')}</td>
                  <td className="px-4 py-3"><span className="inline-flex items-center gap-2 text-app-text"><Database className="h-4 w-4 text-app-muted" />{item.source_readiness}</span></td>
                  <td className="px-4 py-3 text-app-muted"><span className="mr-3 inline-flex items-center gap-1"><Image className="h-4 w-4" />{item.media_readiness.poster}</span><span className="inline-flex items-center gap-1"><HardDrive className="h-4 w-4" />{item.media_readiness.proxy_360p}</span></td>
                  <td className="px-4 py-3 text-app-muted">{formatDate(item.date)}</td>
                  <td className="px-4 py-3 text-right"><button type="button" disabled={busyUuid === item.video_uuid || item.media_readiness.poster === 'ready' || primary?.photos_access_status !== 'ok' || Boolean(storage?.internal.processing_stopped)} onClick={() => void handleRecall(item)} className="touch-target border border-app-strong bg-app-panel px-3 py-1.5 text-sm text-app-text disabled:cursor-not-allowed disabled:opacity-40">{busyUuid === item.video_uuid ? t('recall.requesting') : t('recall.recallOne')}</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!loading && items.length === 0 && <div className="border border-app p-8 text-center text-sm text-app-muted">{t('recall.noItems')}</div>}
        {loading && items.length === 0 && <PageLoading />}
      </section>
    </div>
  )
}
