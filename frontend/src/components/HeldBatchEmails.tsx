import { useCallback, useEffect, useState } from 'react'
import { Loader2, Mail, Send, X } from 'lucide-react'
import {
  discardHeldEmails,
  listHeldEmails,
  releaseHeldEmails,
  type HeldEmail,
} from '../services/depositsApi'

function stamp(value?: string | null) {
  return value ? new Date(`${value}Z`).toLocaleString() : '—'
}

/**
 * Administration > Emails. Auto-ingested clips queue one "pick up your dives"
 * email per diver and park it here: nothing reaches a friend until an admin
 * confirms. Release schedules the email (the cron sends within ~15 minutes);
 * Skip drops it for good. Friends can still opt out in their profile.
 */
export default function HeldBatchEmails() {
  const [emails, setEmails] = useState<HeldEmail[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setEmails(await listHeldEmails())
      setError(null)
    } catch {
      setError('Unable to load the held emails.')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function act(kind: 'release' | 'discard', ids?: number[]) {
    setBusy(true)
    setNotice(null)
    try {
      const count = await (kind === 'release' ? releaseHeldEmails(ids) : discardHeldEmails(ids))
      setNotice(
        kind === 'release'
          ? `${count} email(s) confirmed — they go out within about 15 minutes.`
          : `${count} email(s) skipped.`,
      )
      await load()
    } catch {
      setError('The action failed. Nothing was sent.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section aria-label="Held batch emails" className="space-y-4">
      <div className="sm:flex sm:items-end sm:justify-between">
        <div>
          <h2 className="text-xl font-semibold text-app-text">Emails awaiting confirmation</h2>
          <p className="mt-1 max-w-2xl text-sm text-app-muted">
            New clips ingested automatically create one email per diver. Nothing is sent until you confirm.
          </p>
        </div>
        {emails && emails.length > 0 && (
          <div className="mt-4 flex gap-2 sm:mt-0">
            <button
              type="button"
              disabled={busy}
              onClick={() => void act('release')}
              className="touch-target inline-flex items-center gap-2 bg-app-accent px-4 text-sm font-semibold text-white disabled:opacity-50"
            >
              <Send className="h-4 w-4" aria-hidden /> Send all ({emails.length})
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => void act('discard')}
              className="touch-target inline-flex items-center gap-2 border border-app px-4 text-sm text-app-muted hover:text-app-text disabled:opacity-50"
            >
              <X className="h-4 w-4" aria-hidden /> Skip all
            </button>
          </div>
        )}
      </div>

      {error && <div role="alert" className="border border-amber-700/60 bg-amber-950/20 p-4 text-sm text-amber-100">{error}</div>}
      {notice && <div role="status" className="border border-app bg-app-panel p-3 text-sm text-app-text">{notice}</div>}
      {emails === null && !error && (
        <div className="flex items-center gap-2 p-6 text-sm text-app-muted"><Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading…</div>
      )}
      {emails && emails.length === 0 && (
        <div className="border border-app bg-app-panel p-8 text-center text-sm text-app-muted">No email is waiting for confirmation.</div>
      )}
      {emails && emails.length > 0 && (
        <ul className="divide-y divide-[var(--app-border)] border border-app bg-app-panel">
          {emails.map((email) => (
            <li key={email.id} className="flex flex-wrap items-center justify-between gap-3 p-4">
              <div className="flex min-w-0 items-center gap-3">
                <Mail className="h-5 w-5 shrink-0 text-app-accent" aria-hidden />
                <div className="min-w-0">
                  <div className="font-medium text-app-text">
                    {email.diver_name ?? 'Unknown diver'} · {email.clips} clip{email.clips === 1 ? '' : 's'}
                  </div>
                  <div className="truncate text-xs text-app-muted">
                    To {email.recipient_name ?? '—'} ({email.recipient_email ?? '—'}) · queued {stamp(email.queued_at)}
                  </div>
                </div>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void act('release', [email.id])}
                  className="touch-target inline-flex items-center gap-2 border border-app-strong bg-app-panel px-3 text-sm font-medium text-app-text disabled:opacity-50"
                >
                  <Send className="h-4 w-4" aria-hidden /> Send
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void act('discard', [email.id])}
                  className="touch-target inline-flex items-center gap-2 border border-app px-3 text-sm text-app-muted hover:text-app-text disabled:opacity-50"
                >
                  Skip
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
