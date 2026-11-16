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
    <div className="clip-setting-card">
      <div className="clip-setting-card-row">
        <span className="clip-setting-card-title">{t('evaluations.label')}</span>
        <button
          type="button"
          role="switch"
          className="clip-switch"
          aria-label={t('evaluations.toggleAria')}
          aria-checked={!!current?.active}
          disabled={busy}
          onClick={() => void toggle(!current?.active)}
        >
          <span aria-hidden />
        </button>
      </div>
      {mediaPending && (
        <p role="status" className="clip-setting-card-copy">
          {t('evaluations.mediaPending')}{' '}
          <button type="button" className="clip-inline-link" disabled={checkingMedia} onClick={() => void retryMedia()}>
            {t('evaluations.mediaRetry')}
          </button>
        </p>
      )}
      {current?.active && (
        <label className="clip-field">
          <span className="clip-setting-card-copy">{t('evaluations.prompt')}</span>
          <textarea
            id="evaluation-prompt"
            aria-label={t('evaluations.prompt')}
            maxLength={EVALUATION_PROMPT_MAX}
            rows={2}
            value={draft}
            disabled={busy}
            placeholder={t('evaluations.promptPlaceholder')}
            onChange={(event) => setDraft(event.target.value)}
          />
        </label>
      )}
      {current?.active && (
        <button type="button" className="clip-secondary" disabled={busy} onClick={() => void savePrompt()}>
          {t('evaluations.savePrompt')}
        </button>
      )}
      {error && <p role="status" className="clip-editor-message is-error">{t('evaluations.error')}</p>}
    </div>
  )
}
