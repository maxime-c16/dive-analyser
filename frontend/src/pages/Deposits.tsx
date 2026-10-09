import React, { useCallback, useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Check, CheckCheck, Film, Pencil } from 'lucide-react'
import {
  acceptBatch,
  batchReviewPath,
  editPendingDive,
  getBatch,
  listPendingBatches,
  type BatchDetail,
  type PendingBatch,
  type ReviewDive,
} from '../services/depositsApi'

function DiveRow({
  dive,
  selected,
  onToggle,
  onChanged,
}: {
  dive: ReviewDive
  selected: boolean
  onToggle: () => void
  onChanged: (next: ReviewDive) => void
}) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState(false)
  const [code, setCode] = useState(dive.dive_code)
  const [height, setHeight] = useState(dive.height)
  const [notes, setNotes] = useState(dive.notes ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)

  const save = async () => {
    setBusy(true)
    setError(false)
    try {
      const next = await editPendingDive(dive.id, {
        dive_code: code.toUpperCase(),
        height: height.toLowerCase(),
        notes: notes || null,
      })
      onChanged(next)
      setEditing(false)
    } catch {
      setError(true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <article className="border border-app bg-app-panel p-4" aria-label={dive.dive_code}>
      <div className="flex items-start gap-3">
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggle}
          aria-label={t('deposits.selectClip', { code: dive.dive_code })}
          className="mt-1 h-5 w-5"
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-lg font-semibold text-app-text">
              {dive.dive_code} · {dive.height}
            </h3>
            {dive.deposited_by && (
              <span className="text-xs text-app-muted">
                {t('deposits.depositedBy', { name: dive.deposited_by })}
              </span>
            )}
          </div>
          {(dive.performance || dive.phase1_performance) && (
            <p className="mt-1 text-sm text-app-muted">
              {dive.phase1_performance
                ? `${dive.phase1_performance}/${dive.phase2_performance}`
                : dive.performance}
            </p>
          )}
          {dive.evaluator_note && (
            <p className="mt-2 border-l-2 border-app-accent pl-3 text-sm italic leading-6 text-app-muted">
              « {dive.evaluator_note} »
            </p>
          )}
          {dive.notes && (
            <p className="mt-2 text-sm leading-6 text-app-text">
              <span className="font-medium">{t('deposits.yourNote')} </span>
              {dive.notes}
            </p>
          )}
          {editing ? (
            <div className="mt-3 grid gap-2">
              <label className="grid gap-1 text-sm">
                {t('deposits.code')}
                <input value={code} onChange={(e) => setCode(e.target.value)} className="border border-app bg-app-panel-elevated p-2" />
              </label>
              <label className="grid gap-1 text-sm">
                {t('deposits.height')}
                <input value={height} onChange={(e) => setHeight(e.target.value)} className="border border-app bg-app-panel-elevated p-2" />
              </label>
              <label className="grid gap-1 text-sm">
                {t('deposits.note')}
                <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} className="border border-app bg-app-panel-elevated p-2" />
              </label>
              <div className="flex gap-2">
                <button type="button" onClick={save} disabled={busy} className="touch-target border border-app bg-app-panel-elevated px-3 py-2 text-sm disabled:opacity-60">
                  {t('deposits.save')}
                </button>
                <button type="button" onClick={() => setEditing(false)} className="touch-target px-3 py-2 text-sm text-app-muted">
                  {t('deposits.cancel')}
                </button>
              </div>
              {error && <p className="text-sm text-red-500">{t('deposits.errorAction')}</p>}
            </div>
          ) : (
            <div className="mt-3 flex flex-wrap gap-2">
              <Link
                to={`/dives?clip=${dive.id}`}
                className="touch-target inline-flex items-center gap-2 border border-app bg-app-panel-elevated px-3 py-2 text-sm"
              >
                <Film className="h-4 w-4" aria-hidden />
                {t('deposits.watch')}
              </Link>
              <button
                type="button"
                onClick={() => {
                  setCode(dive.dive_code)
                  setHeight(dive.height)
                  setNotes(dive.notes ?? '')
                  setEditing(true)
                }}
                className="touch-target inline-flex items-center gap-2 border border-app px-3 py-2 text-sm text-app-muted"
              >
                <Pencil className="h-4 w-4" aria-hidden />
                {t('deposits.edit')}
              </button>
            </div>
          )}
        </div>
      </div>
    </article>
  )
}

function BatchReview({ batchId, diverId }: { batchId: string; diverId: number | null }) {
  const { t } = useTranslation()
  const [batch, setBatch] = useState<BatchDetail | null>(null)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    setError(false)
    getBatch(batchId, diverId)
      .then((data) => {
        setBatch(data)
        setSelected(new Set())
      })
      .catch(() => setError(true))
      .finally(() => setLoading(false))
  }, [batchId, diverId])

  useEffect(() => {
    load()
  }, [load])

  const accept = async (ids?: number[]) => {
    setBusy(true)
    try {
      await acceptBatch(batchId, ids, diverId)
      load()
    } catch {
      setError(true)
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <p className="py-8 text-sm text-app-muted">{t('common.loading')}</p>
  if (error || !batch) return <p className="py-8 text-sm text-red-500">{t('deposits.errorLoad')}</p>
  if (batch.dives.length === 0) {
    return (
      <div className="app-panel mx-auto mt-10 max-w-lg p-8 text-center">
        <CheckCheck className="mx-auto h-8 w-8 text-app-accent" aria-hidden />
        <h1 className="mt-3 text-xl font-semibold">{t('deposits.allDone')}</h1>
        <Link to="/dives" className="touch-target mt-4 inline-block border border-app px-4 py-2 text-sm">
          {t('deposits.backToLibrary')}
        </Link>
      </div>
    )
  }

  const allIds = batch.dives.map((d) => d.id)
  const allSelected = allIds.every((id) => selected.has(id))

  return (
    <div>
      <header className="mb-5">
        <h1 className="text-2xl font-semibold">
          {t('deposits.titleBatch', { name: batch.diver_name ?? '', count: batch.dives.length })}
        </h1>
        <p className="mt-1 text-sm text-app-muted">{t('deposits.subtitle')}</p>
      </header>
      <div className="mb-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => accept()}
          disabled={busy}
          className="touch-target inline-flex items-center gap-2 bg-app-accent px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
        >
          <CheckCheck className="h-4 w-4" aria-hidden />
          {t('deposits.acceptAll')}
        </button>
        <button
          type="button"
          onClick={() => accept([...selected])}
          disabled={busy || selected.size === 0}
          className="touch-target inline-flex items-center gap-2 border border-app bg-app-panel px-4 py-2 text-sm disabled:opacity-60"
        >
          <Check className="h-4 w-4" aria-hidden />
          {t('deposits.acceptSelected', { count: selected.size })}
        </button>
        <button
          type="button"
          onClick={() => setSelected(allSelected ? new Set() : new Set(allIds))}
          className="touch-target px-3 py-2 text-sm text-app-muted"
        >
          {allSelected ? t('deposits.unselectAll') : t('deposits.selectAll')}
        </button>
      </div>
      <div className="grid gap-3">
        {batch.dives.map((dive) => (
          <DiveRow
            key={dive.id}
            dive={dive}
            selected={selected.has(dive.id)}
            onToggle={() =>
              setSelected((prev) => {
                const next = new Set(prev)
                if (next.has(dive.id)) next.delete(dive.id)
                else next.add(dive.id)
                return next
              })
            }
            onChanged={(next) =>
              setBatch((prev) =>
                prev ? { ...prev, dives: prev.dives.map((d) => (d.id === next.id ? next : d)) } : prev,
              )
            }
          />
        ))}
      </div>
    </div>
  )
}

function BatchList() {
  const { t } = useTranslation()
  const [batches, setBatches] = useState<PendingBatch[] | null>(null)

  useEffect(() => {
    let live = true
    listPendingBatches()
      .then((rows) => {
        if (live) setBatches(rows)
      })
      .catch(() => {
        if (live) setBatches([])
      })
    return () => {
      live = false
    }
  }, [])

  if (batches === null) return <p className="py-8 text-sm text-app-muted">{t('common.loading')}</p>
  return (
    <div>
      <header className="mb-5">
        <h1 className="text-2xl font-semibold">{t('deposits.title')}</h1>
        <p className="mt-1 text-sm text-app-muted">{t('deposits.subtitle')}</p>
      </header>
      {batches.length === 0 ? (
        <p className="text-sm text-app-muted">{t('deposits.empty')}</p>
      ) : (
        <div className="grid gap-3">
          {batches.map((batch) => (
            <Link
              key={`${batch.batch_id}:${batch.diver_id ?? ''}`}
              to={batchReviewPath(batch.batch_id, batch.diver_id)}
              className="block border border-app bg-app-panel p-4 hover:border-app-accent"
            >
              <span className="text-lg font-semibold">
                {t('deposits.batchRow', {
                  name: batch.diver_name ?? '',
                  count: batch.pending,
                })}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}

export default function Deposits() {
  const { batchId } = useParams()
  const [params] = useSearchParams()
  const diverParam = Number(params.get('diver'))
  const diverId = params.get('diver') !== null && Number.isInteger(diverParam) ? diverParam : null
  if (batchId) return <BatchReview batchId={batchId} diverId={diverId} />
  return <BatchList />
}
