import React, { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getPushConfig } from '../services/notificationsApi'
import {
  disablePushDevice,
  enablePushDevice,
  getExistingPushSubscription,
  isIosDevice,
  pushSupported,
} from '../services/pushSubscription'

type Status = 'checking' | 'on' | 'off' | 'unsupported'

/**
 * Explicit per-device Web Push opt-in (PR3 notifications-push).
 *
 * Lives in the Account → Notifications section. Permission is requested
 * only from the "Enable" click handler below — mounting this section never
 * prompts. Push mirrors only the in-app alert types the user leaves on
 * (the server fans out created inbox rows), so this toggle cannot spam.
 */
export default function PushOptInSection() {
  const { t } = useTranslation()
  const [status, setStatus] = useState<Status>('checking')
  const [unsupportedReason, setUnsupportedReason] = useState<'browser' | 'server' | null>(null)
  const [publicKey, setPublicKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [blocked, setBlocked] = useState(false)
  const [error, setError] = useState('')
  const [showIosHint] = useState(() => isIosDevice())

  useEffect(() => {
    let alive = true
    void (async () => {
      if (!pushSupported()) {
        if (alive) {
          setUnsupportedReason('browser')
          setStatus('unsupported')
        }
        return
      }
      try {
        if (typeof Notification !== 'undefined' && Notification.permission === 'denied') {
          if (alive) setBlocked(true)
        }
      } catch {
        // Permission inspection is best-effort.
      }
      try {
        const config = await getPushConfig()
        if (!alive) return
        if (!config.publicKey) {
          setUnsupportedReason('server')
          setStatus('unsupported')
          return
        }
        setPublicKey(config.publicKey)
        const existing = await getExistingPushSubscription()
        if (!alive) return
        setStatus(existing ? 'on' : 'off')
      } catch {
        if (!alive) return
        setStatus('off')
        setError(t('account.pushError'))
      }
    })()
    return () => {
      alive = false
    }
  }, [t])

  const enable = async () => {
    if (!publicKey || busy) return
    setBusy(true)
    setError('')
    setBlocked(false)
    try {
      await enablePushDevice(publicKey)
      setStatus('on')
    } catch (err) {
      const code = err instanceof Error ? err.message : ''
      if (code === 'permission-denied') {
        setBlocked(true)
      } else if (code === 'push-unsupported') {
        setUnsupportedReason('browser')
        setStatus('unsupported')
      } else {
        setError(t('account.pushError'))
      }
    } finally {
      setBusy(false)
    }
  }

  const disable = async () => {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      // Server is the source of truth: disablePushDevice() resolves true
      // only after the server-side DELETE succeeds (a failed local
      // unsubscribe still resolves true once the server row is gone, since
      // no more pushes can leave the server). False means the server still
      // holds the endpoint, so stay "on" with a visible error + retry.
      const ok = await disablePushDevice()
      if (!ok) {
        setError(t('account.pushError'))
        return
      }
      setStatus('off')
    } catch {
      setError(t('account.pushError'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-4 border-t border-app pt-4">
      <h3 className="text-sm font-semibold text-app-text">{t('account.pushTitle')}</h3>
      <p className="mt-1 text-xs text-app-muted">{t('account.pushDesc')}</p>
      {status === 'checking' && (
        <p role="status" className="mt-2 text-xs text-app-muted">
          {t('common.loading')}
        </p>
      )}
      {status === 'unsupported' && (
        <p role="note" className="mt-2 text-sm text-app-muted">
          {unsupportedReason === 'server'
            ? t('account.pushUnsupportedServer')
            : t('account.pushUnsupportedBrowser')}
        </p>
      )}
      {(status === 'on' || status === 'off') && (
        <div className="mt-2 flex items-center justify-between gap-4 py-2">
          <p role="status" className="text-sm text-app-text">
            {busy
              ? t('account.pushWorking')
              : status === 'on'
                ? t('account.pushOn')
                : t('account.pushOff')}
          </p>
          {status === 'on' ? (
            <button
              type="button"
              onClick={() => void disable()}
              disabled={busy}
              className="touch-target border border-app bg-app-panel-elevated px-4 py-2.5 text-sm font-medium text-app-text disabled:opacity-60"
            >
              {t('account.pushDisable')}
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void enable()}
              disabled={busy}
              className="touch-target border border-app-accent bg-app-accent/10 px-4 py-2.5 text-sm font-semibold text-app-accent disabled:opacity-60"
            >
              {t('account.pushEnable')}
            </button>
          )}
        </div>
      )}
      {blocked && (status === 'on' || status === 'off') && (
        <p role="alert" className="mt-2 text-sm text-amber-200">
          {t('account.pushBlocked')}
        </p>
      )}
      {error && (
        <p role="alert" className="mt-2 text-sm text-red-400">
          {error}
        </p>
      )}
      {showIosHint && status !== 'checking' && (
        <p className="mt-2 text-xs leading-5 text-app-muted">{t('account.pushIosHint')}</p>
      )}
    </div>
  )
}
