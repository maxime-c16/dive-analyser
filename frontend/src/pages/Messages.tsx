import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Send, Plus } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import * as api from '../services/messagesApi'
import type { Conversation, Message } from '../services/messagesApi'
import MemberPicker from '../components/messages/MemberPicker'
import MessageBubble from '../components/messages/MessageBubble'
import MentionComposer from '../components/mentions/MentionComposer'
import { readMessageDraft, saveMessageDraft, readPendingSend, savePendingSend, completePendingSend, discardPendingSend } from '../navigation/messageDraft'
import { useMobileViewport, useBottomAction } from '../navigation/useMobileNavigation'
import '../navigation/messagesMobile.css'
import { emptyMentionValue, mentionPayload } from '../components/mentions/mentionValue'

function Thread({ id }: { id: number }) {
  const { user } = useAuth()
  const { t } = useTranslation()
  const [conversation, setConversation] = useState<Conversation | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [before, setBefore] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [busy, setBusy] = useState(false)
  const [body, setBody] = useState(() => readMessageDraft(user?.user_id, id))
  const viewport = useMobileViewport()
  useBottomAction(viewport.width < 768)
  const changeBody = (value: ReturnType<typeof emptyMentionValue>) => { if (!value.body) { sendKey.current = null; discardPendingSend(user?.user_id, id) } setBody(value); saveMessageDraft(user?.user_id, id, value) }
  const [retry, setRetry] = useState(0)
  const alive = useRef(true)
  const visible = useRef(new Set<number>())
  const received = useRef(new Set<number>())
  const read = useRef(new Set<number>())
  const pendingRead = useRef(false)
  const pendingLoad = useRef(false)
  const initialized = useRef(false)
  const mutation = useRef(0)
  const sendKey = useRef<{ value: string; key: string } | null>(readPendingSend(user?.user_id, id))
  const thread = useRef<HTMLElement>(null)
  const [top, setTop] = useState(0)
  useLayoutEffect(() => {
    if (viewport.width >= 768 || !thread.current) return
    window.scrollTo({ top: 0, behavior: 'instant' })
    const measure = () => { if (thread.current) setTop(thread.current.getBoundingClientRect().top + window.scrollY) }
    measure()
    const observer = new ResizeObserver(measure)
    const header = document.querySelector('.mobile-header')
    if (header) observer.observe(header)
    return () => observer.disconnect()
  }, [viewport.width])
  useEffect(() => {
    const completed = (event: Event) => {
      const sent = (event as CustomEvent).detail
      if (sent.account !== user?.user_id || sent.conversation !== id) return
      if (sendKey.current?.key !== sent.key) return
      sendKey.current = null
      setBody(previous => JSON.stringify(mentionPayload(previous)) === sent.value ? emptyMentionValue() : previous)
    }
    window.addEventListener('message-draft-sent', completed)
    return () => window.removeEventListener('message-draft-sent', completed)
  }, [id, user?.user_id])
  const end = useRef<HTMLDivElement>(null)
  const markVisibleRead = useCallback(async () => {
    if (!alive.current || pendingRead.current || document.visibilityState !== 'visible' || !document.hasFocus()) return
    const ids = [...visible.current].filter(i => !read.current.has(i)).slice(0, 50)
    if (!ids.length) return
    pendingRead.current = true
    try { await api.acknowledgeMessages(id, ids, true); ids.forEach(i => read.current.add(i)) }
    catch { /* Retry on visibility, focus or next poll; never fabricate a receipt. */ }
    finally { pendingRead.current = false }
    // An observer may discover another visible message while this batch is in flight.
    if (alive.current && ids.every(i => read.current.has(i))) queueMicrotask(() => { void markVisibleRead() })
  }, [id])
  const onVisible = useCallback((message: number, show: boolean) => {
    if (show) visible.current.add(message); else visible.current.delete(message)
    void markVisibleRead()
  }, [markVisibleRead])
  const load = useCallback(async (cursor?: number) => {
    if (pendingLoad.current) return
    pendingLoad.current = true
    const version = mutation.current
    try {
      const page = await api.getMessages(id, cursor)
      if (!alive.current) return
      setMessages(previous => {
        const merged = new Map(previous.map(m => [m.id, m]))
        // A local mutation completed after this read started wins until next poll.
        page.items.forEach(m => { if (version === mutation.current || !merged.has(m.id)) merged.set(m.id, m) })
        return [...merged.values()].sort((a, b) => a.id - b.id)
      })
      if (cursor || !initialized.current) setBefore(page.next_before)
      initialized.current = true
      const ids = page.items.filter(m => m.sender_id !== user?.user_id && !received.current.has(m.id)).map(m => m.id)
      if (ids.length) { await api.acknowledgeMessages(id, ids, false); ids.forEach(i => received.current.add(i)) }
      setError(false)
      void markVisibleRead()
    } catch { if (alive.current) setError(true) }
    finally { pendingLoad.current = false; if (alive.current) setLoading(false) }
  }, [id, user?.user_id, markVisibleRead])
  useEffect(() => {
    alive.current = true
    api.getConversation(id).then(c => { if (alive.current) setConversation(c) }).catch(() => { if (alive.current) setError(true) })
    void load()
    const timer = setInterval(() => { if (document.visibilityState === 'visible') void load() }, 3000)
    const focus = () => { void markVisibleRead(); void load() }
    window.addEventListener('focus', focus); document.addEventListener('visibilitychange', focus)
    return () => { alive.current = false; clearInterval(timer); window.removeEventListener('focus', focus); document.removeEventListener('visibilitychange', focus) }
  }, [id, retry, load, markVisibleRead])
  useEffect(() => { if (!loading) end.current?.scrollIntoView({ block: 'end' }) }, [loading])
  const peers = conversation?.members.filter(m => m.user_id !== user?.user_id) ?? []
  return <section ref={thread} className="message-thread flex min-h-0 flex-col rounded-xl border border-app bg-app-bg" style={{ '--message-viewport-height': `${viewport.height}px`, '--message-top': `${top}px` } as React.CSSProperties}>
    <header className="border-b border-app p-4"><Link to="/messages" className="mr-3 text-sm text-app-accent">← {t('messages.title')}</Link>{peers.map(m => <Link key={m.user_id} to={`/users/${m.user_id}`} className="font-semibold">{m.display_name} </Link>)}</header>
    {error && <p role="alert" className="p-3">{t('messages.error')} <button onClick={() => setRetry(n => n + 1)}>{t('common.retry')}</button></p>}
    <div className="message-history max-h-[60vh] min-h-[30vh] space-y-3 overflow-y-auto p-4" aria-label={t('messages.conversation')}>
      {loading && <p role="status">{t('common.loading')}</p>}
      {before && <button disabled={loading || busy} className="w-full p-2 text-sm text-app-accent" onClick={() => void load(before)}>{t('messages.older')}</button>}
      {!loading && !messages.length && <p className="text-app-muted">{t('messages.begin')}</p>}
      {messages.map(message => <MessageBubble key={message.id} message={message} userId={user?.user_id ?? 0} busy={busy} onVisible={onVisible} onReact={() => {
        if (busy) return
        setBusy(true)
        api.reactToMessage(id, message.id, !message.reactions.some(r => r.user_id === user?.user_id)).then(updated => {
          if (alive.current) { mutation.current++; setMessages(rows => rows.map(m => m.id === updated.id ? updated : m)) }
        }).catch(() => { if (alive.current) setError(true) }).finally(() => { if (alive.current) setBusy(false) })
      }} />)}<div ref={end} />
    </div>
    <form className="message-composer border-t border-app p-3" onSubmit={async e => {
      e.preventDefault()
      if (!body.body.trim() || busy) return
      const payload = mentionPayload(body), value = JSON.stringify(payload)
      if (sendKey.current?.value !== value) sendKey.current = { value, key: crypto.randomUUID() }
      const sending = sendKey.current
      savePendingSend(user?.user_id, id, sending)
      setBusy(true)
      try {
        const message = await api.sendMessage(id, { ...payload, client_id: sending.key })
        completePendingSend(user?.user_id, id, sending)
        if (!alive.current) return
        mutation.current++; setMessages(rows => [...rows.filter(m => m.id !== message.id), message].sort((a,b) => a.id-b.id))
        changeBody(emptyMentionValue()); sendKey.current = null; setError(false)
        requestAnimationFrame(() => end.current?.scrollIntoView({ block: 'end' }))
      } catch { if (alive.current) setError(true) }
      finally { if (alive.current) setBusy(false) }
    }}><label htmlFor="direct-message" className="mb-2 block text-sm text-app-muted">{t('messages.compose')}</label><div className="flex gap-2"><MentionComposer id="direct-message" placeholder={t('messages.placeholder')} value={body} onChange={changeBody} disabled={busy} /><button type="submit" aria-label={t('messages.send')} disabled={busy || !body.body.trim()} className="px-3"><Send size={20} /></button></div><p className="mt-2 text-xs text-app-muted">{t('messages.reactionHint')}</p></form>
  </section>
}

export default function Messages() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const { conversationId } = useParams()
  const id = Number(conversationId)
  const navigate = useNavigate()
  const [items, setItems] = useState<Conversation[]>([])
  const [before, setBefore] = useState<string | null>(null)
  const [error, setError] = useState(false)
  const [loading, setLoading] = useState(true)
  const [choose, setChoose] = useState(false)
  const [starting, setStarting] = useState(false)
  const [retry, setRetry] = useState(0)
  const inboxInitialized = useRef(false)
  useEffect(() => {
    let alive = true, pending = false
    const load = async () => {
      if (pending) return; pending = true
      try { const page = await api.listConversations(); if (alive) {
        setItems(previous => [...new Map([...previous, ...page.items].map(c => [c.id, c])).values()].sort((a,b) => (b.updated_at ?? '').localeCompare(a.updated_at ?? '') || b.id-a.id))
        if (!inboxInitialized.current) { setBefore(page.next_before); inboxInitialized.current = true }
        setError(false)
      } }
      catch { if (alive) setError(true) }
      finally { pending = false; if (alive) setLoading(false) }
    }
    void load()
    const timer = setInterval(() => { if (document.visibilityState === 'visible') void load() }, 5000)
    return () => { alive = false; clearInterval(timer) }
  }, [retry, id])
  return <div className={`messages-page mx-auto max-w-6xl p-4 text-app-text sm:p-6 ${id > 0 ? 'messages-page-thread' : ''}`}><div className="messages-heading mb-5 flex items-center justify-between"><h1 className="text-2xl font-semibold">{t('messages.title')}</h1><button className="flex items-center gap-2 border border-app px-3 py-2" onClick={() => setChoose(v => !v)} aria-expanded={choose}><Plus size={18} />{t('messages.new')}</button></div>
    {choose && <div className="mb-4 max-w-lg rounded-xl border border-app bg-app-panel p-4"><MemberPicker disabled={starting} onSelect={async member => {
      setStarting(true)
      try { const c = await api.startConversation(member.user_id); setChoose(false); navigate(`/messages/${c.id}`); setRetry(n => n + 1) }
      catch { setError(true) } finally { setStarting(false) }
    }} /></div>}
    {error && <p role="alert">{t('messages.error')} <button onClick={() => setRetry(n => n + 1)}>{t('common.retry')}</button></p>}
    <div className="messages-grid grid gap-5 md:grid-cols-[280px_1fr]">
      <aside className={id ? 'hidden md:block' : ''} aria-label={t('messages.inbox')}>
        {loading && <p role="status">{t('common.loading')}</p>}
        {!loading && !items.length && <p className="p-4 text-app-muted">{t('messages.empty')}</p>}
        {items.map(c => <Link key={c.id} to={`/messages/${c.id}`} className={`mb-2 block rounded-xl border border-app p-3 ${c.id === id ? 'bg-app-panel-elevated' : 'bg-app-panel'}`}><strong>{c.members.filter(m => m.user_id !== user?.user_id).map(m => m.display_name).join(', ')}</strong>{!!c.unread_count && <span className="ml-2 rounded-full bg-app-accent px-2 text-app-bg">{c.unread_count}</span>}<p className="mt-1 truncate text-sm text-app-muted">{c.latest?.body || (c.latest?.dive ? t('messages.diveCard') : t('messages.begin'))}</p></Link>)}
        {before && <button onClick={async () => { try { const page = await api.listConversations(before); setItems(rows => [...new Map([...rows, ...page.items].map(c => [c.id,c])).values()]); setBefore(page.next_before) } catch { setError(true) } }}>{t('messages.more')}</button>}
      </aside>
      {Number.isSafeInteger(id) && id > 0 ? <Thread key={`${user?.user_id}:${id}`} id={id} /> : <p className="hidden p-6 text-app-muted md:block">{t('messages.choose')}</p>}
    </div>
  </div>
}
