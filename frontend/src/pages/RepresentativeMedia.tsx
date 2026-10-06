import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { appLanguage } from '../utils/dateLocale'
import { Link } from 'react-router-dom'
import { AlertTriangle, Film, RefreshCw, Search, ShieldAlert } from 'lucide-react'
import {
  getMacMediaStatus,
  getRepresentativeCoverage,
  getReplacementCandidates,
  getRepresentatives,
  replaceRepresentative,
  type MacMediaStatus,
  type RepresentativeCoverage,
  type ReplacementCandidate,
  type RepresentativeCard,
  type RepresentativeGallery,
  type RepresentativeRole,
} from '../services/representativeMediaApi'
import { usePreservedSearchParams } from '../hooks/usePreservedSearchParams'
import { useAuth } from '../contexts/AuthContext'
import { mediaStatusLabel } from '../utils/mediaStatus'

const ROLE_ORDER: RepresentativeRole[] = ['low', 'median', 'high']
const VIABILITY_KEYS = new Set([
  'ready',
  'previously_successful',
  'untested',
  'retryable_failure',
  'known_placeholder_failure',
  'permanently_unavailable',
])

function formatDate(value: string) {
  return new Intl.DateTimeFormat(appLanguage(), { day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(value))
}

function stateClass(state: string) {
  if (state === 'ready') return 'text-app-accent'
  if (state === 'partial') return 'text-amber-300'
  if (state.includes('replacement') || state === 'unavailable') return 'text-red-300'
  return 'text-app-muted'
}

function RepresentativeCardView({
  code,
  rep,
  onFindReplacement,
  readOnly,
}: {
  code: string
  rep: RepresentativeCard
  onFindReplacement: (code: string, role: RepresentativeRole) => void
  readOnly: boolean
}) {
  const { t } = useTranslation()
  const failure = rep.media.failure
  const posterReady = rep.media.renditions.poster.status === 'ready'
  const proxyReady = rep.media.renditions.proxy_360p.status === 'ready'
  const mediaLabel = proxyReady
    ? t('repMedia.mediaVideoReady')
    : posterReady
      ? t('repMedia.mediaPosterOnly')
      : failure
        ? t('repMedia.mediaUnavailable')
        : t('repMedia.mediaMissing')
  return (
    <article className="border border-app bg-app-panel-elevated">
      <div className="flex items-start justify-between gap-3 border-b border-app px-4 py-3">
        <h3 className="font-semibold text-app-text">{rep.label}</h3>
        <span className={`text-xs font-medium ${stateClass(rep.media.state)}`}>{mediaLabel}</span>
      </div>
      {rep.media.poster_url ? (
        <img src={rep.media.poster_url} alt={t('repMedia.posterAlt', { code, label: rep.label })} className="aspect-video w-full object-cover" />
      ) : (
        <div className="flex aspect-video items-center justify-center bg-black/35 text-xs text-app-muted">{t('analysis.noPoster')}</div>
      )}
      <div className="space-y-3 p-4 text-sm">
        <div>
          <div className="text-xl font-semibold text-app-text">{rep.attempt.score_10.toFixed(1)} <span className="text-sm font-normal text-app-muted">/ {rep.attempt.performance}</span></div>
          <div className="mt-1 text-app-muted">{formatDate(rep.attempt.dive_datetime)} · {rep.attempt.height} · {rep.attempt.is_sync ? 'SYNC' : t('analysis.individual')}</div>
          <div className="mt-1 text-app-muted">{rep.attempt.diver?.display_name || t('analysis.unassigned')} · {rep.attempt.modifiers.join(', ') || t('analysis.noModifiers')}</div>
        </div>
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="border border-app p-2"><span className="text-app-muted">{t('analysis.poster')}</span><div className="mt-1 text-app-text">{mediaStatusLabel(rep.media.renditions.poster.status)}</div></div>
          <div className="border border-app p-2"><span className="text-app-muted">{t('analysis.proxy')}</span><div className="mt-1 text-app-text">{mediaStatusLabel(rep.media.renditions.proxy_360p.status)}</div></div>
        </div>
        {failure && (
          <details className="border border-app p-3">
            <summary className="cursor-pointer text-sm text-red-300">{failure.message}</summary>
            <p className="mt-2 text-xs leading-5 text-app-muted">{failure.detail}</p>
            {failure.code === 'materialization_only_placeholders' && (
              <p className="mt-2 text-xs leading-5 text-app-muted">{t('repMedia.findOrRetry')}</p>
            )}
            {(failure.code === 'permission_required' || failure.code === 'photos_access_denied' || failure.code === 'osxphotos_export_timeout' || failure.code === 'osxphotos_export_failed') && (
              <p className="mt-2 text-xs leading-5 text-app-muted">{t('repMedia.checkPermissions')}</p>
            )}
          </details>
        )}
        <div className="flex flex-wrap gap-2 pt-1">
          {rep.media.playback_url && <a href={rep.media.playback_url} className="touch-target inline-flex items-center gap-2 border border-app-accent bg-app-accent px-3 py-1.5 text-xs font-semibold text-black"><Film className="h-3.5 w-3.5" />{t('repMedia.play')}</a>}
          <Link to={`/dives/analysis/${code}?attempt=${rep.attempt.id}`} className="touch-target inline-flex items-center border border-app px-3 py-1.5 text-xs text-app-muted">{t('analysis.openAttempt')}</Link>
          {(rep.media.state === 'partial' || rep.media.state === 'missing') && <Link to={`/dives/analysis/${code}?attempt=${rep.attempt.id}`} className="touch-target inline-flex items-center border border-app px-3 py-1.5 text-xs text-app-muted">{t('repMedia.prepareOne')}</Link>}
          {rep.replacement.available && !readOnly && <button type="button" onClick={() => onFindReplacement(code, rep.role)} className="touch-target border border-app px-3 py-1.5 text-xs text-app-muted">{t('analysis.findReplacement')}</button>}
        </div>
      </div>
    </article>
  )
}

function CandidatePanel({
  selected,
  candidates,
  loading,
  onClose,
  onReplace,
}: {
  selected: { code: string; role: RepresentativeRole } | null
  candidates: ReplacementCandidate[]
  loading: boolean
  onClose: () => void
  onReplace: (candidate: ReplacementCandidate, prepare: boolean) => void
}) {
  const { t } = useTranslation()
  if (!selected) return null
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/55" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <aside role="dialog" aria-modal="true" aria-label={t('repMedia.candidatesAria')} className="h-full w-full max-w-xl overflow-y-auto border-l border-app bg-app-panel p-4 sm:p-5">
        <div className="flex items-start justify-between gap-3 border-b border-app pb-4">
          <div>
            <h2 className="text-xl font-semibold text-app-text">{t('repMedia.candidates')}</h2>
            <p className="mt-1 text-sm text-app-muted">{selected.code} · {t(`repMedia.role.${selected.role}`)}</p>
          </div>
          <button type="button" onClick={onClose} className="border border-app px-3 py-1.5 text-sm text-app-muted">{t('common.close')}</button>
        </div>
        <div className="mt-5 space-y-3">
          {loading && <p className="text-sm text-app-muted">{t('common.loading')}</p>}
          {!loading && !candidates.length && <p className="text-sm text-app-muted">{t('repMedia.noCandidates')}</p>}
          {candidates.map((candidate) => (
            <div key={candidate.candidate.id} className="border border-app p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="font-semibold text-app-text">{candidate.candidate.score_10.toFixed(1)} / {candidate.candidate.performance}</div>
                  <div className="mt-1 text-sm text-app-muted">{formatDate(candidate.candidate.dive_datetime)} · {candidate.candidate.height} · {candidate.candidate.is_sync ? 'SYNC' : t('analysis.individual')}</div>
                  <div className="mt-1 text-xs text-app-muted">{t('repMedia.scoreDistance')} {candidate.similarity.score_distance.toFixed(1)} · {VIABILITY_KEYS.has(candidate.media_viability) ? t(`repMedia.viability.${candidate.media_viability}`) : candidate.media_viability}</div>
                  <div className="mt-1 text-xs text-app-muted">{candidate.ready_renditions.length ? t('repMedia.alreadyReady', { renditions: candidate.ready_renditions.join(', ') }) : t('repMedia.noCachedRendition')} · {t('analysis.attempts')} {candidate.materialization_history.attempt_count}</div>
                </div>
                <div className="text-right text-xs text-app-muted">
                  <div>{candidate.similarity.height_match ? t('repMedia.heightMatch') : t('repMedia.heightDiffers')}</div>
                  <div>{candidate.similarity.modifier_match ? t('repMedia.modifiersMatch') : t('repMedia.modifiersDiffer')}</div>
                </div>
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <button type="button" onClick={() => onReplace(candidate, false)} className="border border-app-accent px-3 py-1.5 text-xs text-app-accent">{t('repMedia.useWithoutPreparing')}</button>
                <button type="button" onClick={() => onReplace(candidate, true)} className="border border-app px-3 py-1.5 text-xs text-app-muted">{t('repMedia.useAndPrepare')}</button>
              </div>
            </div>
          ))}
        </div>
      </aside>
    </div>
  )
}

export default function RepresentativeMedia() {
  const { t } = useTranslation()
  const [searchParams, setSearchParams] = usePreservedSearchParams()
  const { user } = useAuth()
  // Friends see everyone's dives by default; replacement is owner-only.
  const friend = user?.role === 'friend'
  const scopeDefault = searchParams.get('diver_scope') || (searchParams.get('diver_id') ? 'selected' : (friend ? 'all' : 'self'))
  const [data, setData] = useState<RepresentativeGallery | null>(null)
  const [coverage, setCoverage] = useState<RepresentativeCoverage | null>(null)
  const [macStatus, setMacStatus] = useState<MacMediaStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<{ code: string; role: RepresentativeRole } | null>(null)
  const [candidates, setCandidates] = useState<ReplacementCandidate[]>([])
  const [loadingCandidates, setLoadingCandidates] = useState(false)
  const query = useMemo(() => new URLSearchParams(searchParams), [searchParams])
  const sortMode = searchParams.get('sort') || 'needs_coverage'
  const hasLoaded = useRef(false)

  const load = (background = false) => {
    const firstLoad = !hasLoaded.current
    if (firstLoad) setLoading(true)
    else if (!background) setRefreshing(true)
    Promise.all([getRepresentatives(query), getRepresentativeCoverage(query), getMacMediaStatus()])
      .then(([result, coverageResult, macResult]) => {
        setData(result)
        setCoverage(coverageResult)
        setMacStatus(macResult)
        setError(null)
        hasLoaded.current = true
      })
      .catch((reason) => setError(reason.message))
      .finally(() => {
        if (firstLoad) setLoading(false)
        if (!background) setRefreshing(false)
      })
  }
  useEffect(() => {
    load()
    // Population finalizes media asynchronously. Refresh only while the tab is
    // visible so representative readiness changes appear without a manual reload.
    const refresh = window.setInterval(() => {
      if (document.visibilityState === 'visible') load(true)
    }, 30_000)
    return () => window.clearInterval(refresh)
  }, [query])

  const update = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams)
    value ? next.set(key, value) : next.delete(key)
    setSearchParams(next)
  }

  const findReplacement = async (code: string, role: RepresentativeRole) => {
    setSelected({ code, role })
    setCandidates([])
    setLoadingCandidates(true)
    try {
      const result = await getReplacementCandidates(code, role, query)
      setCandidates(result.candidates)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t('repMedia.loadCandidatesError'))
    } finally {
      setLoadingCandidates(false)
    }
  }

  const replace = async (candidate: ReplacementCandidate, prepare: boolean) => {
    if (!selected) return
    await replaceRepresentative(selected.code, selected.role, candidate.candidate.id, prepare, query)
    setSelected(null)
    setCandidates([])
    setLoadingCandidates(false)
    load()
  }

  return (
    <div className="mx-auto w-full max-w-[1480px] space-y-6">
      <header className="border-b border-app pb-5">
        <h1 className="text-3xl font-semibold tracking-tight text-app-text">{t('nav.representatives')}</h1>
      </header>

      {data && (
        <section className="grid gap-px border-y border-app sm:grid-cols-2 lg:grid-cols-5">
          {[
            [t('repMedia.summaryDiveCodes'), data.summary.canonical_dive_codes],
            [t('repMedia.summaryRepresentatives'), data.summary.representatives],
            [t('repMedia.summaryFullyReady'), data.summary.codes_fully_ready],
            [t('repMedia.summaryPartial'), data.summary.codes_partially_ready],
            [t('repMedia.summaryZeroReady'), data.summary.codes_zero_ready],
          ].map(([label, value]) => (
            <div key={label} className="bg-app-panel p-4"><div className="text-xs text-app-muted">{label}</div><div className="mt-2 text-2xl font-semibold text-app-text">{value}</div></div>
          ))}
        </section>
      )}

      {coverage && (
        <section className="grid gap-px border border-app md:grid-cols-4">
          <div className="bg-app-panel p-4">
            <div className="text-xs text-app-muted">{t('repMedia.auditZeroReady')}</div>
            <div className="mt-2 text-sm text-app-text">A {coverage.summary.zero_ready_categories.A || 0} · B {coverage.summary.zero_ready_categories.B || 0} · C {coverage.summary.zero_ready_categories.C || 0} · D {coverage.summary.zero_ready_categories.D || 0}</div>
          </div>
          <div className="bg-app-panel p-4">
            <div className="text-xs text-app-muted">{t('repMedia.auditPlaceholder')}</div>
            <div className="mt-2 text-sm text-app-text">{(coverage.summary.failure_breakdown.materialized_video_not_found || 0) + (coverage.summary.failure_breakdown.materialization_only_placeholders || 0)}</div>
          </div>
          <div className="bg-app-panel p-4">
            <div className="text-xs text-app-muted">{t('repMedia.auditViable')}</div>
            <div className="mt-2 text-sm text-app-text">{coverage.zero_ready_codes.reduce((total, item) => total + item.viable_replacement_candidates, 0)}</div>
          </div>
          <div className="bg-app-panel p-4">
            <div className="text-xs text-app-muted">{t('repMedia.auditPhotos')}</div>
            <div className={`mt-2 text-sm ${macStatus?.photos_access_status === 'ok' ? 'text-app-accent' : macStatus?.photos_access_status === 'unknown' || !macStatus ? 'text-app-muted' : 'text-amber-300'}`}>
              {macStatus?.photos_access_status || t('repMedia.photosUnknown')}
            </div>
          </div>
        </section>
      )}

      <section className="border border-app bg-app-panel p-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <label className="text-xs text-app-muted">{t('repMedia.filterDiveCode')}<input value={searchParams.get('dive_code') || ''} onChange={(event) => update('dive_code', event.target.value.toUpperCase())} className="app-input mt-1 w-full text-sm uppercase" placeholder="103B" /></label>
          <label className="text-xs text-app-muted">{t('repMedia.filterReadiness')}<select value={searchParams.get('readiness') || ''} onChange={(event) => update('readiness', event.target.value)} className="app-input mt-1 w-full text-sm"><option value="">{t('repMedia.all')}</option><option value="ready">{t('repMedia.readinessReady')}</option><option value="partial">{t('repMedia.readinessPartial')}</option><option value="replacement_available">{t('repMedia.readinessReplacementAvailable')}</option><option value="replacement_exhausted">{t('repMedia.readinessReplacementExhausted')}</option><option value="missing">{t('repMedia.readinessMissing')}</option></select></label>
          <label className="text-xs text-app-muted">{t('repMedia.filterRole')}<select value={searchParams.get('selection_band') || ''} onChange={(event) => update('selection_band', event.target.value)} className="app-input mt-1 w-full text-sm"><option value="">{t('repMedia.all')}</option><option value="low">{t('repMedia.role.low')}</option><option value="median">{t('repMedia.role.median')}</option><option value="high">{t('repMedia.role.high')}</option></select></label>
          <label className="text-xs text-app-muted">{t('repMedia.filterHeight')}<input value={searchParams.get('height') || ''} onChange={(event) => update('height', event.target.value)} className="app-input mt-1 w-full text-sm" placeholder="1m" /></label>
          <label className="text-xs text-app-muted">{t('repMedia.filterScope')}<select value={scopeDefault} onChange={(event) => { const next = new URLSearchParams(searchParams); next.delete('diver_id'); event.target.value === 'self' ? next.delete('diver_scope') : next.set('diver_scope', event.target.value); setSearchParams(next) }} className="app-input mt-1 w-full text-sm"><option value="self">{t('repMedia.scopeSelf')}</option><option value="all">{t('repMedia.scopeAll')}</option><option value="selected">{t('repMedia.scopeSelected')}</option></select></label>
          <label className="text-xs text-app-muted">{t('repMedia.filterDiverId')}<input disabled={scopeDefault !== 'selected'} value={searchParams.get('diver_id') || ''} onChange={(event) => update('diver_id', event.target.value)} className="app-input mt-1 w-full text-sm disabled:opacity-45" placeholder="1" /></label>
          <label className="text-xs text-app-muted">{t('repMedia.filterSort')}<select value={sortMode} onChange={(event) => update('sort', event.target.value)} className="app-input mt-1 w-full text-sm"><option value="needs_coverage">{t('repMedia.sortNeedsCoverage')}</option><option value="dive_code">{t('repMedia.filterDiveCode')}</option><option value="fully_ready">{t('repMedia.sortFullyReady')}</option><option value="recently_updated">{t('repMedia.sortRecentlyUpdated')}</option></select></label>
          <button type="button" onClick={() => load()} className="mt-5 inline-flex items-center justify-center gap-2 border border-app px-3 py-2 text-sm text-app-muted"><RefreshCw className="h-4 w-4" />{t('repMedia.refresh')}</button>
        </div>
      </section>

      {loading && !data && <div className="border-y border-app py-16 text-center text-sm text-app-muted">{t('common.loading')}</div>}
      {refreshing && data && <div className="sticky top-0 z-30 border border-app-accent/40 bg-app-panel/95 px-4 py-2 text-center text-xs text-app-muted backdrop-blur" role="status">{t('repMedia.refreshing')}</div>}
      {error && <div className="border border-red-900/60 bg-red-950/30 p-4 text-sm text-red-300">{error}</div>}

      {data && (
        <section className="space-y-5">
          {[...data.dives].sort((a, b) => {
            if (sortMode === 'dive_code') return a.dive_code.localeCompare(b.dive_code)
            if (sortMode === 'fully_ready') return Number(b.coverage.fully_ready) - Number(a.coverage.fully_ready) || a.dive_code.localeCompare(b.dive_code)
            if (sortMode === 'recently_updated') {
              const newest = (group: typeof a) => Math.max(...group.representatives.map((rep) => new Date(rep.attempt.dive_datetime).getTime()))
              return newest(b) - newest(a)
            }
            const playableA = a.coverage.proxy_ready
            const playableB = b.coverage.proxy_ready
            return playableA - playableB || a.coverage.poster_ready - b.coverage.poster_ready || a.dive_code.localeCompare(b.dive_code)
          }).map((group) => (
            <div key={group.dive_code} className="border border-app bg-app-panel">
              <div className="flex flex-wrap items-center gap-3 border-b border-app px-5 py-4">
                <Link to={`/dives/analysis/${group.dive_code}`} className="touch-target inline-flex items-center text-xl font-semibold text-app-text">{group.dive_code}</Link>
                <span className="text-sm text-app-muted">{t('repMedia.coverageLine', { poster: group.coverage.poster_ready, video: group.coverage.proxy_ready, total: group.coverage.total })}</span>
                {!group.coverage.fully_ready && <span className="ml-auto inline-flex items-center gap-2 text-xs text-app-muted"><ShieldAlert className="h-4 w-4" />{t('repMedia.coverageIncomplete')}</span>}
              </div>
              <div className="grid gap-4 p-4 lg:grid-cols-3">
                {ROLE_ORDER.map((role) => {
                  const rep = group.representatives.find((item) => item.role === role)
                  return rep ? <RepresentativeCardView key={role} code={group.dive_code} rep={rep} onFindReplacement={findReplacement} readOnly={!user?.is_admin} /> : <div key={role} className="border border-app p-4 text-sm text-app-muted"><AlertTriangle className="mb-3 h-4 w-4" />{t('repMedia.noRepresentative', { role: t(`repMedia.role.${role}`) })}</div>
                })}
              </div>
            </div>
          ))}
          {!data.dives.length && <div className="border border-app p-8 text-center text-sm text-app-muted"><Search className="mx-auto mb-3 h-5 w-5" />{t('repMedia.noMatches')}</div>}
        </section>
      )}

      <CandidatePanel selected={selected} candidates={candidates} loading={loadingCandidates} onClose={() => { setSelected(null); setLoadingCandidates(false) }} onReplace={replace} />
    </div>
  )
}
