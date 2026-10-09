import { useCallback, useEffect, useMemo, useState } from 'react'
import { Copy, Gift, Loader2, Mail, RefreshCw, UserPlus, X } from 'lucide-react'
import {
  createDiverInvite,
  listAllDivers,
  listLiveInvites,
  revokeDiverInvite,
  type AdminDiver,
  type AdminDiverInvite,
} from '../services/adminUsersApi'

/**
 * Admin invitations: mint a one-time signup link for a diver name that has
 * clips but no account yet.
 *
 * The raw token is returned exactly once, inside `invite_url`'s fragment —
 * the server only keeps its SHA-256 hash. So the link is shown here right
 * after creation (with a copy button) and never again; re-sending means
 * minting a fresh link, which supersedes the previous one.
 */

const inputCls =
  'border border-app bg-app-panel-elevated px-3 py-2 text-sm text-app-text placeholder:text-app-muted focus:outline-none focus:ring-1 focus:ring-app-accent disabled:opacity-50'
const buttonCls =
  'inline-flex items-center justify-center gap-2 border border-app-strong bg-app-panel px-3 py-2 text-sm font-semibold text-app-text hover:bg-app-panel-elevated disabled:cursor-not-allowed disabled:opacity-45'

function stamp(value: string | null) {
  if (!value) return '—'
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

function StatusBadge({ status }: { status: AdminDiverInvite['status'] }) {
  const tone =
    status === 'live'
      ? 'border-app-accent/50 text-app-accent'
      : status === 'used'
        ? 'border-app text-app-muted'
        : 'border-amber-700/50 text-amber-200'
  return <span className={`inline-flex items-center border px-2 py-0.5 text-xs ${tone}`}>{status}</span>
}

export default function AdminDiverInvites() {
  const [divers, setDivers] = useState<AdminDiver[]>([])
  const [invites, setInvites] = useState<AdminDiverInvite[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [query, setQuery] = useState('')

  // The just-minted link: the only place it can ever be read back.
  const [issued, setIssued] = useState<AdminDiverInvite | null>(null)
  const [copied, setCopied] = useState(false)
  const [email, setEmail] = useState('')

  const refresh = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    setError(null)
    try {
      const [directory, live] = await Promise.all([listAllDivers(), listLiveInvites({ limit: 100 })])
      setDivers(directory)
      setInvites(live.invites)
      setTotal(live.total)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to load invitations')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const unclaimed = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return divers
      .filter((d) => !d.bound_to_user)
      .filter((d) => !needle || `${d.display_name} ${d.canonical_name} ${d.diver_id}`.toLowerCase().includes(needle))
  }, [divers, query])

  async function issue(diverId: number) {
    setBusyId(diverId)
    setCopied(false)
    setError(null)
    try {
      const created = await createDiverInvite(diverId, email.trim() || undefined)
      setIssued(created)
      setEmail('')
      await refresh(true)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to create the invitation')
    } finally {
      setBusyId(null)
    }
  }

  async function revoke(inviteId: number) {
    setBusyId(inviteId)
    setError(null)
    try {
      await revokeDiverInvite(inviteId)
      setIssued((current) => (current?.invite_id === inviteId ? null : current))
      await refresh(true)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to revoke the invitation')
    } finally {
      setBusyId(null)
    }
  }

  async function copyLink() {
    const url = issued?.invite_url
    if (!url) return
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
    } catch {
      // Clipboard denied: surface the link so it is never lost.
      setCopied(false)
      setError(`Copy failed — link: ${url}`)
    }
  }

  return (
    <div className="space-y-6">
      <section className="border border-app bg-app-panel p-5">
        <div className="flex flex-wrap items-center gap-2">
          <UserPlus aria-hidden className="h-5 w-5 text-app-accent" />
          <h2 className="text-lg font-semibold text-app-text">Invite a diver</h2>
          <button
            type="button"
            className={`${buttonCls} ml-auto`}
            disabled={loading}
            onClick={() => void refresh()}
            aria-label="Refresh invitations"
          >
            <RefreshCw aria-hidden className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
        <p className="mt-2 text-sm text-app-muted">
          Send a friend a one-time link to create their account with the dives already tied to their
          name. The link works once and expires after seven days; creating a new link supersedes the
          previous one.
        </p>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <label className="sr-only" htmlFor="invite-email">
            Email the link to
          </label>
          <input
            id="invite-email"
            type="email"
            className={`${inputCls} min-w-[220px] flex-1`}
            placeholder="Optional — email the link to…"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            disabled={loading}
          />
          <label className="sr-only" htmlFor="invite-search">
            Find a diver
          </label>
          <input
            id="invite-search"
            type="search"
            className={`${inputCls} min-w-[220px] flex-1`}
            placeholder="Find a diver by name or ID"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            disabled={loading}
          />
        </div>

        {issued?.invite_url && (
          <div className="mt-4 border border-app-accent/50 bg-app-panel-elevated p-4">
            <div className="flex flex-wrap items-center gap-2">
              <Gift aria-hidden className="h-4 w-4 shrink-0 text-app-accent" />
              <strong className="text-sm text-app-text">
                Link ready for {issued.diver_name ?? `diver #${issued.diver_id}`}
              </strong>
              <button type="button" className={`${buttonCls} ml-auto`} onClick={() => void copyLink()}>
                <Copy aria-hidden className="h-4 w-4" />
                {copied ? 'Copied' : 'Copy link'}
              </button>
              <button
                type="button"
                className={buttonCls}
                onClick={() => {
                  setIssued(null)
                  setCopied(false)
                }}
                aria-label="Dismiss the new link"
              >
                <X aria-hidden className="h-4 w-4" />
              </button>
            </div>
            <p className="mt-2 break-all font-mono text-xs text-app-muted">{issued.invite_url}</p>
            {issued.email_sent === true && (
              <p className="mt-2 text-xs text-app-accent">
                <Mail aria-hidden className="mr-1 inline h-3.5 w-3.5" />
                Emailed to {email || 'the recipient'}.
              </p>
            )}
            {issued.email_sent === false && (
              <p className="mt-2 text-xs text-amber-200">
                Email not sent{issued.email_error ? ` — ${issued.email_error}` : ''}. Copy the link
                and share it another way.
              </p>
            )}
            <p className="mt-2 text-xs text-app-muted">
              This is the only time the link is shown — the server keeps only its hash. Copy it now.
            </p>
          </div>
        )}

        {error && <p role="alert" className="mt-3 text-sm text-red-400">{error}</p>}

        <ul className="mt-4 divide-y divide-[var(--app-border)]">
          {loading && !unclaimed.length && (
            <li className="py-6 text-sm text-app-muted">
              <Loader2 aria-hidden className="mr-2 inline h-4 w-4 animate-spin" />
              Loading diver names…
            </li>
          )}
          {!loading && !unclaimed.length && (
            <li className="py-6 text-sm text-app-muted">
              {query ? 'No diver matches your search.' : 'Every diver already has an account.'}
            </li>
          )}
          {unclaimed.map((diver) => (
            <li key={diver.diver_id} className="flex flex-wrap items-center gap-3 py-3">
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium text-app-text">{diver.display_name}</div>
                <div className="text-xs text-app-muted">
                  #{diver.diver_id} · {diver.canonical_name}
                  {diver.has_live_invite ? ' · link outstanding' : ''}
                  {!diver.active ? ' · inactive diver' : ''}
                </div>
              </div>
              <button
                type="button"
                className={buttonCls}
                disabled={busyId !== null || loading}
                onClick={() => void issue(diver.diver_id)}
              >
                {busyId === diver.diver_id ? (
                  <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
                ) : (
                  <UserPlus aria-hidden className="h-4 w-4" />
                )}
                Create link
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="border border-app bg-app-panel p-5">
        <h2 className="text-lg font-semibold text-app-text">Outstanding invitations</h2>
        <p className="mt-2 text-sm text-app-muted">
          Links that can still be used. Revoke one you no longer recognise.
        </p>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-app text-xs uppercase tracking-wide text-app-muted">
                <th className="py-2 pr-4">Diver</th>
                <th className="py-2 pr-4">Status</th>
                <th className="py-2 pr-4">Created</th>
                <th className="py-2 pr-4">Expires</th>
                <th className="py-2">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--app-border)]">
              {invites.map((invite) => (
                <tr key={invite.invite_id}>
                  <td className="py-2 pr-4 text-app-text">
                    {invite.diver_name ?? `#${invite.diver_id}`}
                  </td>
                  <td className="py-2 pr-4">
                    <StatusBadge status={invite.status} />
                  </td>
                  <td className="py-2 pr-4 text-app-muted">{stamp(invite.created_at)}</td>
                  <td className="py-2 pr-4 text-app-muted">{stamp(invite.expires_at)}</td>
                  <td className="py-2">
                    {invite.status === 'live' ? (
                      <button
                        type="button"
                        className={buttonCls}
                        disabled={busyId !== null}
                        onClick={() => void revoke(invite.invite_id)}
                      >
                        {busyId === invite.invite_id ? (
                          <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
                        ) : (
                          <X aria-hidden className="h-4 w-4" />
                        )}
                        Revoke
                      </button>
                    ) : (
                      <span className="text-app-muted">—</span>
                    )}
                  </td>
                </tr>
              ))}
              {!invites.length && (
                <tr>
                  <td colSpan={5} className="py-6 text-app-muted">
                    {loading ? 'Loading…' : 'No outstanding invitations.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {total > invites.length && (
          <p className="mt-3 text-xs text-app-muted">Showing {invites.length} of {total}.</p>
        )}
      </section>
    </div>
  )
}
