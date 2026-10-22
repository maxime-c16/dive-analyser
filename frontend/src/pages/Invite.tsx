import React, { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Gift, UserPlus } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import SignupClubSelect from '../components/SignupClubSelect'
import PageLoading from '../components/PageLoading'
import {
  inviteTokenFromHash,
  peekInvite,
  registerWithInvite,
  type InviteRegistrationError,
} from '../services/inviteApi'

/**
 * Public invitation landing ("crée ton compte, tes plongeons t'attendent").
 *
 * The token lives in the URL fragment (`/invite#t=…`) so it never reaches
 * server logs; the preview POST never consumes it (email prefetchers) and
 * only the explicit submit creates the account and claims the diver.
 *
 * This is the one signup path that binds a REAL diver name: an administrator
 * minted the link for that specific diver, so the clips already tied to the
 * name become the new account's. Open registration (`/register`) keeps
 * minting collision-proof `member-<id>-<hex>` placeholders instead.
 */
export default function Invite() {
  const { t } = useTranslation()
  const location = useLocation()
  const token = inviteTokenFromHash(location.hash)
  const navigate = useNavigate()
  const { refresh } = useAuth()

  const [state, setState] = useState<'loading' | 'ready' | 'invalid'>('loading')
  const [diverName, setDiverName] = useState('')
  const [expiresAt, setExpiresAt] = useState<string | null>(null)

  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [clubId, setClubId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let live = true
    if (!token) {
      setState('invalid')
      return () => {
        live = false
      }
    }
    peekInvite(token)
      .then((data) => {
        if (!live) return
        setDiverName(data.diver_name ?? '')
        setExpiresAt(data.expires_at)
        setState('ready')
      })
      .catch(() => {
        if (live) setState('invalid')
      })
    return () => {
      live = false
    }
  }, [token])

  function messageFor(error: InviteRegistrationError): string {
    if (error.code === 'diver_claimed') return t('invite.errorClaimed')
    if (error.code === 'email_taken') return t('invite.errorExists')
    if (error.code === 'rate_limited') return t('invite.errorTooMany')
    if (error.code === 'club_unavailable') return t('invite.errorClub')
    if (error.code === 'link_invalid' || error.status === 404) return t('invite.errorLink')
    return t('invite.errorFailed')
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    if (password !== confirm) {
      setError(t('invite.errorMismatch'))
      return
    }
    if (password.length < 10) {
      setError(t('invite.errorTooShort'))
      return
    }
    setBusy(true)
    try {
      await registerWithInvite(token, {
        email,
        password,
        display_name: displayName || undefined,
        ...(clubId !== null ? { club_id: clubId } : {}),
      })
      setPassword('')
      setConfirm('')
      await refresh()
      navigate('/dives', { replace: true })
    } catch (reason) {
      setError(messageFor(reason as InviteRegistrationError))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-app px-4">
      <div className="w-full max-w-sm border border-app bg-app-panel p-8">
        <div className="mb-2 flex items-center gap-2">
          <Gift className="h-5 w-5 text-app-accent" />
          <span className="text-lg font-semibold text-app-text">Dive Analyser</span>
        </div>

        {state === 'loading' && <PageLoading />}

        {state === 'invalid' && (
          <>
            <p className="mb-6 text-sm text-app-muted">{t('invite.invalid')}</p>
            <p className="mb-6 border border-amber-700/60 bg-amber-950/20 p-3 text-sm text-amber-100">
              {t('invite.invalidHint')}
            </p>
            <Link
              to="/login"
              className="touch-target inline-flex w-full items-center justify-center gap-2 border border-app-strong bg-app-panel px-4 py-2.5 text-sm font-semibold text-app-text"
            >
              {t('invite.backToLogin')}
            </Link>
          </>
        )}

        {state === 'ready' && (
          <form onSubmit={submit}>
            <p className="mb-1 text-sm text-app-muted">{t('invite.subtitle')}</p>
            <p className="mb-6 text-lg font-semibold text-app-text">
              {diverName || t('invite.unknownDiver')}
            </p>
            {expiresAt && (
              <p className="mb-6 text-xs text-app-muted">
                {t('invite.expiresOn', {
                  date: new Date(expiresAt).toLocaleDateString(),
                })}
              </p>
            )}

            <label htmlFor="invite-email" className="mb-1 block text-xs font-medium uppercase tracking-wide text-app-muted">
              {t('login.email')}
            </label>
            <input
              type="email"
              id="invite-email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="you@example.com"
              autoComplete="username"
              className="mb-4 w-full border border-app bg-app-panel-elevated px-3 py-2.5 text-sm text-app-text placeholder:text-app-muted focus:outline-none focus:ring-1 focus:ring-app-accent"
              required
            />

            <label htmlFor="invite-display-name" className="mb-1 block text-xs font-medium uppercase tracking-wide text-app-muted">
              {t('register.displayName')}{' '}
              <span className="normal-case">({t('common.optional')})</span>
            </label>
            <input
              type="text"
              id="invite-display-name"
              value={displayName}
              onChange={e => setDisplayName(e.target.value)}
              placeholder="Alex"
              autoComplete="nickname"
              maxLength={120}
              className="mb-4 w-full border border-app bg-app-panel-elevated px-3 py-2.5 text-sm text-app-text placeholder:text-app-muted focus:outline-none focus:ring-1 focus:ring-app-accent"
            />

            <label htmlFor="invite-password" className="mb-1 block text-xs font-medium uppercase tracking-wide text-app-muted">
              {t('login.password')}{' '}
              <span className="normal-case">
                (10+ {t('common.characters')})
              </span>
            </label>
            <input
              type="password"
              id="invite-password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="••••••••••"
              autoComplete="new-password"
              minLength={10}
              className="mb-4 w-full border border-app bg-app-panel-elevated px-3 py-2.5 text-sm text-app-text placeholder:text-app-muted focus:outline-none focus:ring-1 focus:ring-app-accent"
              required
            />

            <label htmlFor="invite-confirm" className="mb-1 block text-xs font-medium uppercase tracking-wide text-app-muted">
              {t('register.confirmPassword')}
            </label>
            <input
              type="password"
              id="invite-confirm"
              value={confirm}
              onChange={e => setConfirm(e.target.value)}
              placeholder="••••••••••"
              autoComplete="new-password"
              className="mb-5 w-full border border-app bg-app-panel-elevated px-3 py-2.5 text-sm text-app-text placeholder:text-app-muted focus:outline-none focus:ring-1 focus:ring-app-accent"
              required
            />

            <SignupClubSelect id="invite-club" value={clubId} onChange={setClubId} />

            {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

            <button
              type="submit"
              disabled={busy}
              className="touch-target inline-flex w-full items-center justify-center gap-2 border border-app-strong bg-app-panel px-4 py-2.5 text-sm font-semibold text-app-text disabled:opacity-60"
            >
              <UserPlus className="h-4 w-4" />
              {busy ? t('invite.creating') : t('invite.submit')}
            </button>

            <p className="mt-5 text-center text-sm text-app-muted">
              {t('register.alreadyHaveAccount')}{' '}
              <Link to="/login" className="text-app-accent hover:underline">
                {t('login.submit')}
              </Link>
            </p>
          </form>
        )}
      </div>
    </div>
  )
}
