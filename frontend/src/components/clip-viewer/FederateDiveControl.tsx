import { useEffect, useState } from 'react'
import i18n from '../../i18n'
import { api } from '../../services/api'
import type { Attempt } from '../../utils/attemptPresentation'

type Status = {
  enabled_global: boolean
  federate_enabled: boolean
  visibility: 'public' | 'private'
  eligible: boolean
  reason: string
  preview: { text: string; includes_video: boolean }
}

/**
 * Eligibility reasons resolve in the active language at render time (see
 * `reasonLabel`); the API `reason` keys stay canonical.
 */
const REASON_KEYS: Record<string, string> = {
  global_opt_in_off: 'globalOff',
  dive_is_private: 'divePrivate',
  per_dive_opt_in_off: 'optInOff',
  eligible: 'eligible',
}

const reasonLabel = (reason: string) => {
  const key = REASON_KEYS[reason]
  return key ? i18n.t(`fedUI.reason.${key}`) : reason
}

/**
 * Per-dive fediverse override (Option 1: manual cross-post only).
 * - Only public dives can opt in; private is always blocked server-side too.
 * - Poster + caption only: no video and no Share/video link (a Share link
 *   plays the original video).
 * - Wraps cleanly on phones/tablets: no hover-only affordances, full-width
 *   warning text, touch-sized toggle.
 */
export default function FederateDiveControl({
  attempt,
  onUpdate,
}: {
  attempt: Attempt
  onUpdate: (attempt: Attempt) => void
}) {
  const [status, setStatus] = useState<Status | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)
  const isPublic = (attempt.visibility ?? 'public') === 'public'

  useEffect(() => {
    let alive = true
    setStatus(null)
    setError('')
    api
      .get<Status>(`/api/v1/dives/${attempt.id}/fediverse`)
      .then(({ data }) => {
        if (alive) {
          setStatus(data)
          if (data.federate_enabled !== !!attempt.federate_enabled) {
            onUpdate({ ...attempt, federate_enabled: data.federate_enabled })
          }
        }
      })
      .catch(() => {
        if (alive) setError(i18n.t('fedUI.errorStatus'))
      })
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt.id, attempt.visibility])

  async function setOptIn(next: boolean) {
    setBusy(true)
    setError('')
    setCopied(false)
    try {
      const { data } = await api.put<Status>(`/api/v1/dives/${attempt.id}/fediverse`, {
        federate_enabled: next,
      })
      setStatus(data)
      onUpdate({ ...attempt, federate_enabled: data.federate_enabled })
    } catch (err: unknown) {
      const response = (err as { response?: { status?: number; data?: { detail?: string } } }).response
      if (response?.status === 422 && /public/i.test(response?.data?.detail ?? '')) {
        setError(i18n.t('fedUI.onlyPublic'))
      } else if (response?.status === 403) {
        setError(i18n.t('fedUI.reason.globalOff'))
      } else {
        setError(i18n.t('diveManagement.errorSave'))
      }
    } finally {
      setBusy(false)
    }
  }

  async function copyCrossPost() {
    setError('')
    try {
      const { data } = await api.post<{ text: string }>(
        `/api/v1/dives/${attempt.id}/fediverse/cross-post`,
      )
      await navigator.clipboard.writeText(data.text)
      setCopied(true)
    } catch {
      setError(i18n.t('fedUI.errorCrossPost'))
    }
  }

  const checked = status?.federate_enabled ?? !!attempt.federate_enabled

  return (
    <div className="mt-3 w-full rounded border border-app bg-app-panel-elevated p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-medium text-app-text">{i18n.t('fedUI.title')}</div>
          <div className="text-xs text-app-muted">{i18n.t('fedUI.subtitle')}</div>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={checked}
          aria-label={i18n.t('fedUI.switchAria')}
          disabled={busy || !isPublic}
          onClick={() => void setOptIn(!checked)}
          title={!isPublic ? i18n.t('fedUI.onlyPublic') : undefined}
          className={`relative inline-flex h-6 w-11 shrink-0 touch-target items-center rounded-full border transition-colors ${
            checked ? 'border-app-accent bg-app-accent' : 'border-app bg-app-panel-elevated'
          } disabled:opacity-50`}
        >
          <span
            aria-hidden
            className={`inline-block h-4 w-4 rounded-full bg-[var(--app-text)] transition-transform ${
              checked ? 'translate-x-5' : 'translate-x-1'
            }`}
          />
        </button>
      </div>

      <p role="note" className="mt-2 text-xs leading-5 text-app-muted">
        {status ? reasonLabel(status.reason) : isPublic ? i18n.t('fedUI.checking') : i18n.t('fedUI.reason.divePrivate')}
        {' '}{i18n.t('fedUI.neverPublishesNote')}
      </p>

      {status?.eligible && (
        <button
          type="button"
          disabled={busy}
          onClick={() => void copyCrossPost()}
          className="touch-target mt-2 inline-flex w-full items-center justify-center gap-2 border border-app-strong bg-app-panel px-3 py-2 text-xs font-semibold text-app-text disabled:opacity-60 sm:w-auto"
        >
          {copied ? i18n.t('fedUI.copied') : i18n.t('fedUI.copyText')}
        </button>
      )}
      {copied && (
        <p role="status" className="mt-1 text-xs text-app-muted">
          {i18n.t('fedUI.copiedNote')}
        </p>
      )}
      {error && (
        <p role="alert" className="mt-1 text-xs text-red-300">
          {error}
        </p>
      )}
    </div>
  )
}
