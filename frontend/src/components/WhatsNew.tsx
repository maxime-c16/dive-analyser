import { useTranslation } from 'react-i18next'
import React, { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { Sparkles, X } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'

export type UpdateNote = { id: string; date: string; title: string; body: string }
type Manifest = { schema: number; frontend_sha: string; notes: UpdateNote[] }
type ReadState = { seen: string[]; lastShown: number }
const DAY = 24 * 60 * 60 * 1000
const buildSha = import.meta.env.VITE_APP_SHA || 'dev'
const Context = createContext({ open: () => {}, unread: false })

export function parseManifest(value: unknown): Manifest | null {
  if (!value || typeof value !== 'object') return null
  const m = value as Manifest
  if (m.schema !== 1 || typeof m.frontend_sha !== 'string' || !Array.isArray(m.notes) || m.notes.length > 100) return null
  const ids = new Set<string>()
  for (const n of m.notes) {
    if (!n || typeof n.id !== 'string' || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(n.id) || ids.has(n.id)
      || typeof n.title !== 'string' || !n.title.trim() || n.title.length > 100
      || typeof n.body !== 'string' || !n.body.trim() || n.body.length > 600
      || typeof n.date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(n.date)) return null
    ids.add(n.id)
  }
  return m
}

export function readState(key: string): ReadState | null {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return { seen: [], lastShown: 0 }
    const state = JSON.parse(raw) as ReadState
    if (!Array.isArray(state.seen) || !state.seen.every(id => typeof id === 'string')
      || !Number.isFinite(state.lastShown) || state.lastShown < 0) return null
    return state
  } catch { return null }
}

export function WhatsNewProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()
  // Account changes remount all request/state boundaries, including pending fetches.
  return user ? <AccountUpdates key={user.user_id} accountId={user.user_id}>{children}</AccountUpdates> : <>{children}</>
}

function AccountUpdates({ accountId, children }: { accountId: number; children: React.ReactNode }) {
  const { t } = useTranslation()
  const key = `dive-analyser:updates:v1:${accountId}`
  const [manifest, setManifest] = useState<Manifest | null>(null)
  const [state, setState] = useState(() => readState(key))
  const [toast, setToast] = useState<UpdateNote[] | null>(null)
  const [panel, setPanel] = useState<Manifest | null>(null)
  const [tick, setTick] = useState(0)
  const toastRef = useRef(toast)
  toastRef.current = toast
  const compatible = !manifest?.frontend_sha || buildSha === 'dev' || manifest.frontend_sha === buildSha
  const unread = !!manifest?.notes.some(note => !state?.seen.includes(note.id))

  useEffect(() => {
    if (toast && (!compatible || toast.some(note => !manifest?.notes.some(active => active.id === note.id)))) setToast(null)
  }, [manifest, compatible, toast])

  useEffect(() => {
    const abort = new AbortController()
    let loading = false
    const load = async () => {
      if (loading || document.visibilityState === 'hidden') return
      loading = true
      try {
        const response = await fetch('/api/v1/updates', { credentials: 'same-origin', cache: 'no-store', signal: abort.signal })
        if (!response.ok) {
          if (!abort.signal.aborted) { setManifest(null); setToast(null) }
          return
        }
        const parsed = parseManifest(await response.json())
        if (parsed && !abort.signal.aborted) setManifest(parsed)
      } catch { /* Updates never block the workspace. */ }
      finally { loading = false }
    }
    const refresh = () => { void load(); setTick(n => n + 1) }
    const storage = (event: StorageEvent) => {
      if (event.key === key || event.key === null) {
        const next = readState(key)
        setState(next)
        if (next && toastRef.current?.every(note => next.seen.includes(note.id))) setToast(null)
      }
    }
    const playing = () => setToast(null)
    refresh()
    const timer = window.setInterval(refresh, 60_000)
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', refresh)
    window.addEventListener('storage', storage)
    document.addEventListener('play', playing, true)
    return () => {
      abort.abort(); clearInterval(timer)
      window.removeEventListener('focus', refresh)
      document.removeEventListener('visibilitychange', refresh)
      window.removeEventListener('storage', storage)
      document.removeEventListener('play', playing, true)
    }
  }, [key])

  useEffect(() => {
    if (!manifest || !compatible || toast || panel || document.visibilityState === 'hidden') return
    // Web Locks serializes the persistent cooldown claim across tabs. Without
    // durable storage/locks, keep manual history and suppress automatic hints.
    if (!navigator.locks) return
    let cancelled = false
    void navigator.locks.request(key, () => {
      if (cancelled || document.visibilityState === 'hidden'
        || Array.from(document.querySelectorAll('video')).some(video => !video.paused)
        || document.querySelector('[role="dialog"]')) return
      const latest = readState(key)
      if (!latest || Date.now() - latest.lastShown < DAY) return
      const pending = manifest.notes.filter(note => !latest.seen.includes(note.id))
      if (!pending.length) return
      const claimed = { ...latest, lastShown: Date.now() }
      try {
        localStorage.setItem(key, JSON.stringify(claimed))
        setState(claimed)
        setToast(pending)
      } catch { /* No repeated hints when persistence is unavailable. */ }
    }).catch(() => {})
    return () => { cancelled = true }
  }, [manifest, compatible, toast, panel, tick, key])

  const acknowledge = (notes: UpdateNote[]) => {
    const save = () => {
      const latest = readState(key)
      if (!latest) return
      const next = { ...latest, seen: Array.from(new Set([...latest.seen, ...notes.map(note => note.id)])) }
      try { localStorage.setItem(key, JSON.stringify(next)); setState(next) } catch { setState(null) }
    }
    // Reads and cooldown claims use the same cross-tab lock so neither can
    // overwrite the other tab's newly acknowledged IDs or display timestamp.
    if (navigator.locks) void navigator.locks.request(key, save).catch(() => setState(null))
    else save()
  }
  const dismiss = () => { if (toast) acknowledge(toast); setToast(null) }
  const open = () => {
    const snapshot = manifest || { schema: 1, frontend_sha: '', notes: [] }
    setPanel(snapshot)
    if (compatible) acknowledge(snapshot.notes)
    setToast(null)
  }
  // Freeze the catalog while reading; newly arrived notes stay unread.
  const openToast = () => {
    if (!toast || !compatible) { open(); return }
    acknowledge(toast)
    setPanel({ schema: 1, frontend_sha: manifest?.frontend_sha || '', notes: [...toast, ...(manifest?.notes.filter(note => !toast.some(t => t.id === note.id)) || [])] })
    setToast(null)
  }
  const closePanel = useCallback(() => setPanel(null), [])

  return <Context.Provider value={{ open, unread: unread || !compatible }}>
    {children}
    {toast && compatible && <div role="status" className="fixed bottom-5 left-4 right-4 z-40 border border-app-strong border-l-2 border-l-[var(--app-accent)] bg-app-panel p-5 shadow-2xl sm:left-auto sm:right-6 sm:w-[410px]">
      <div className="flex items-start justify-between gap-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold"><Sparkles className="h-4 w-4 shrink-0 text-app-accent" />{t('whatsNew.updateHeadline')}</h2>
        <button aria-label={t('whatsNew.dismissHint')} onClick={dismiss} className="-mr-2 -mt-2 flex h-11 w-11 shrink-0 items-center justify-center bg-transparent text-app-muted"><X className="h-5 w-5" /></button>
      </div>
      <p className="mb-4 mt-2 text-sm text-app-muted">{toast.length === 1 ? toast[0].title : t('whatsNew.improvementsReady', { count: toast.length })}</p>
      <button onClick={openToast} className="min-h-11 bg-app-accent px-4 text-sm font-semibold text-[#0d211c]">{t('whatsNew.seeWhatsNew')}</button>
    </div>}
    {panel && <UpdatePanel manifest={panel} compatible={buildSha === 'dev' || !panel.frontend_sha || panel.frontend_sha === buildSha} close={closePanel} />}
  </Context.Provider>
}

export function WhatsNewButton({ compact = false }: { compact?: boolean }) {
  const { open, unread } = useContext(Context)
  const { t } = useTranslation()
  return <button data-testid="whats-new-button" aria-label={t('whatsNew.buttonAria')} onClick={open} className={`flex min-h-11 items-center gap-2 border border-app px-3 text-sm text-app-accent ${compact ? '' : 'w-full text-left'}`}>
    <Sparkles className="h-4 w-4 shrink-0" /><span className={compact ? 'hidden sm:inline' : ''}>{t('whatsNew.title')}</span>{unread && <span aria-label={t('whatsNew.unread')} className="ml-auto h-1.5 w-1.5 shrink-0 rounded-full bg-app-accent" />}
  </button>
}

function UpdatePanel({ manifest, compatible, close }: { manifest: Manifest; compatible: boolean; close: () => void }) {
  const { t } = useTranslation()
  const ref = useRef<HTMLElement>(null)
  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null
    const root = document.getElementById('root')
    const oldInert = root?.inert
    const overflow = document.body.style.overflow
    if (root) root.inert = true
    document.body.style.overflow = 'hidden'
    ref.current?.querySelector<HTMLButtonElement>('button')?.focus()
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); close() }
      if (event.key !== 'Tab') return
      const targets = Array.from(ref.current?.querySelectorAll<HTMLElement>('button, a[href]') || [])
      const first = targets[0], last = targets[targets.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }
    document.addEventListener('keydown', keyboard)
    return () => {
      if (root) root.inert = oldInert || false
      document.body.style.overflow = overflow
      document.removeEventListener('keydown', keyboard)
      if (previousFocus?.isConnected) previousFocus.focus()
      else {
        // Language-agnostic: the button label is localized, so target the test id.
        const historyButton = Array.from(root?.querySelectorAll<HTMLButtonElement>('[data-testid="whats-new-button"]') || [])
          .find(button => button.getClientRects().length > 0)
        ;(historyButton || document.getElementById('main-content'))?.focus()
      }
    }
  }, [close])
  return createPortal(<div className="fixed inset-0 z-[70]">
    <div className="absolute inset-0 bg-black/60" onClick={close} aria-hidden="true" />
    <section ref={ref} role="dialog" aria-modal="true" aria-labelledby="updates-title" className="absolute inset-y-0 right-0 w-full overflow-y-auto border-l border-app-strong bg-app-panel p-6 shadow-2xl sm:w-[450px] sm:p-8">
      <div className="mb-8 flex items-center justify-between"><h2 id="updates-title" className="text-xs font-semibold uppercase tracking-[0.16em] text-app-muted">{t('whatsNew.title')}</h2><button aria-label={t('whatsNew.close')} onClick={close} className="flex h-11 w-11 items-center justify-center bg-transparent text-app-muted"><X className="h-5 w-5" /></button></div>
      {!compatible ? <><h3 className="mb-3 text-2xl font-semibold">{t('whatsNew.newerVersion')}</h3><p className="text-sm text-app-muted">{t('whatsNew.reloadHint')}</p><button className="mt-6 min-h-11 bg-app-accent px-4 font-semibold text-[#0d211c]" onClick={() => window.location.reload()}>{t('whatsNew.reloadApp')}</button></>
        : manifest.notes.length ? manifest.notes.map((note, index) => <article key={note.id} className="border-b border-app py-6 first:pt-0">
          <p className="mb-3 text-[11px] uppercase tracking-[0.14em] text-app-accent">{note.date}{index === 0 ? ` · ${t('whatsNew.latestUpdate')}` : ''}</p>
          <h3 className={`${index === 0 ? 'text-2xl' : 'text-lg'} mb-3 font-semibold`}>{note.title}</h3><p className="whitespace-pre-line text-sm leading-6 text-app-muted">{note.body}</p>
        </article>) : <p className="text-sm text-app-muted">{t('whatsNew.noNotes')}</p>}
      <button onClick={close} className="mt-6 min-h-11 w-full bg-app-accent px-4 text-sm font-semibold text-[#0d211c]">{t('whatsNew.gotIt')}</button>
    </section>
  </div>, document.body)
}
