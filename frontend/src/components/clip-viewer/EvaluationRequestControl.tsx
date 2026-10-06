import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { Attempt } from '../../utils/attemptPresentation'
import {
  EVALUATION_PROMPT_MAX,
  getEvaluationMediaStatus,
  putEvaluationRequest,
  prepareEvaluationMedia,
  type EvaluationMediaStatus,
  type EvaluationRequestSummary,
} from '../../services/evaluationApi'

/**
 * Owner-only toggle to request a community evaluation for this dive.
 * One request per dive (upsert server-side); visibility is never touched.
 * Activation reveals the jury comment; deactivation keeps the stored text
 * (only an explicit save replaces it). Media readiness is surfaced so a clip
 * still being prepared gets a visible state with retry instead of silence.
 */
export default function EvaluationRequestControl({
  attempt,
  onUpdate,
}: {
  attempt: Attempt
  onUpdate: (attempt: Attempt) => void
}) {
  const { t } = useTranslation()
  // Local mirror of the last accepted server state lets the control react
  // before (and even if) the parent splices the new attempt into the list.
  const [local, setLocal] = useState<EvaluationRequestSummary | null>(null)
  const current = attempt.evaluation_request ?? local
  const [draft, setDraft] = useState(current?.prompt ?? '')
  const [media, setMedia] = useState<EvaluationMediaStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [checkingMedia, setCheckingMedia] = useState(false)
  const [error, setError] = useState(false)

  // Reset the local editing state when the dive changes.
  useEffect(() => {
    setDraft(attempt.evaluation_request?.prompt ?? '')
    setMedia(null)
    setLocal(null)
    setError(false)
  }, [attempt.id])

  // Media readiness only matters for an active request.
  useEffect(() => {
    if (!current?.active) {
      setMedia(null)
      return
    }
    let alive = true
    getEvaluationMediaStatus(current.id)
      .then((status) => {
        if (alive) setMedia(status)
      })
      .catch(() => {
        if (alive) setMedia(null)
      })
    return () => {
      alive = false
    }
  }, [current?.id, current?.active])

  const mediaPending = useMemo(
    () => current?.active && media !== null && media.status !== 'ready',
    [current?.active, media],
  )

  async function toggle(active: boolean) {
    setError(false)
    setBusy(true)
    try {
      const body = active ? { active, prompt: draft.trim() || undefined } : { active }
      const next = await putEvaluationRequest(attempt.id, body)
      // The response carries the same fields the Library splices; build the
      // updated attempt locally so the parent list and cache stay consistent.
      onUpdate({ ...attempt, evaluation_request: next })
      setLocal(next)
      setDraft(next.prompt ?? '')
      if (next.active) getEvaluationMediaStatus(next.id).then(setMedia).catch(() => {})
    } catch {
      setError(true)
    } finally {
      setBusy(false)
    }
  }

  async function savePrompt() {
    setError(false)
    setBusy(true)
    try {
      const next = await putEvaluationRequest(attempt.id, { active: true, prompt: draft.trim() })
      onUpdate({ ...attempt, evaluation_request: next })
      setLocal(next)
    } catch {
      setError(true)
    } finally {
      setBusy(false)
    }
  }

  async function retryMedia() {
    if (!current?.active || checkingMedia) return
    setCheckingMedia(true)
    try {
      const status = await prepareEvaluationMedia(current.id)
      setMedia(status)
    } catch {
      // Preparation is best-effort; the retry stays available.
    } finally {
      setCheckingMedia(false)
    }
  }

  if (!attempt.video_uuid) return null
  return (
    <span className="flex flex-wrap items-center gap-2 text-sm">
      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          role="switch"
          aria-label={t('evaluations.toggleAria')}
          checked={!!current?.active}
          disabled={busy}
          onChange={(event) => void toggle(event.target.checked)}
        />
        {t('evaluations.label')}
      </label>
      {mediaPending && (
        <span role="status" className="text-xs text-app-muted">
          {t('evaluations.mediaPending')}{' '}
          <button type="button" className="underline" disabled={checkingMedia} onClick={() => void retryMedia()}>
            {t('evaluations.mediaRetry')}
          </button>
        </span>
      )}
      {current?.active && (
        <span className="w-full space-y-1">
          <label className="block text-xs text-app-muted" htmlFor="evaluation-prompt">
            {t('evaluations.prompt')}
          </label>
          <textarea
            id="evaluation-prompt"
            aria-label={t('evaluations.prompt')}
            maxLength={EVALUATION_PROMPT_MAX}
            rows={2}
            className="mt-1 block w-full border border-app bg-app-panel-elevated p-2 text-sm"
            value={draft}
            disabled={busy}
            placeholder={t('evaluations.promptPlaceholder')}
            onChange={(event) => setDraft(event.target.value)}
          />
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="touch-target border border-app px-2 text-xs"
              disabled={busy}
              onClick={() => void savePrompt()}
            >
              {t('evaluations.savePrompt')}
            </button>
          </div>
        </span>
      )}
      {error && (
        <span role="status" className="text-xs text-red-300">
          {t('evaluations.error')}
        </span>
      )}
    </span>
  )
}
