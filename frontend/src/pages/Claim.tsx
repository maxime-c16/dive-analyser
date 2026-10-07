import React, { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Gift } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { peekClaim, redeemClaim } from '../services/depositsApi'

/**
 * Public magic-link landing ("Récupérer mes plongeons").
 * The GET preview never consumes the token (email prefetchers); the
 * explicit button POST redeems it and signs the recipient in.
 */
export default function Claim() {
  const { t } = useTranslation()
  const { token = '' } = useParams()
  const navigate = useNavigate()
  const { refresh } = useAuth()
  const [state, setState] = useState<'loading' | 'ready' | 'invalid'>('loading')
  const [pending, setPending] = useState(0)
  const [batchId, setBatchId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)

  useEffect(() => {
    let live = true
    peekClaim(token)
      .then((data) => {
        if (!live) return
        setBatchId(data.batch_id)
        setPending(data.pending)
        setState('ready')
      })
      .catch(() => {
        if (live) setState('invalid')
      })
    return () => {
      live = false
    }
  }, [token])

  const redeem = async () => {
    setBusy(true)
    setError(false)
    try {
      const data = await redeemClaim(token)
      await refresh()
      navigate(`/deposits/${encodeURIComponent(data.batch_id)}`, { replace: true })
    } catch {
      setError(true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-app px-4">
      <div className="app-panel w-full max-w-md p-8 text-center">
        <Gift className="mx-auto h-10 w-10 text-app-accent" aria-hidden />
        <h1 className="mt-4 text-2xl font-semibold text-app-text">{t('claim.title')}</h1>
        {state === 'loading' && <p className="mt-2 text-sm text-app-muted">{t('common.loading')}</p>}
        {state === 'invalid' && (
          <>
            <p className="mt-2 text-sm leading-6 text-app-muted">{t('claim.invalid')}</p>
            <Link to="/login" className="touch-target mt-6 inline-flex border border-app bg-app-panel-elevated px-4 py-2 text-sm text-app-text">
              {t('claim.backToLogin')}
            </Link>
          </>
        )}
        {state === 'ready' && (
          <>
            <p className="mt-2 text-sm leading-6 text-app-muted">
              {t('claim.ready', { count: pending })}
            </p>
            <p className="mt-1 font-mono text-xs text-app-muted">{batchId.slice(0, 8)}</p>
            <button
              type="button"
              onClick={redeem}
              disabled={busy}
              className="touch-target mt-6 inline-flex w-full items-center justify-center bg-app-accent px-4 py-3 text-base font-semibold text-white disabled:opacity-60"
            >
              {busy ? t('claim.signingIn') : t('claim.cta')}
            </button>
            {error && <p className="mt-3 text-sm text-red-500">{t('claim.error')}</p>}
          </>
        )}
      </div>
    </div>
  )
}
