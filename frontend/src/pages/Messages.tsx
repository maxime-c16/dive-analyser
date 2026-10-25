import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, Check, LogOut, Play, Plus, Send, Users, X } from 'lucide-react'
import ConversationAvatar from '../components/messages/ConversationAvatar'
import type { MemberIdentity } from '../services/communityApi'
import { format, isToday, isYesterday, differenceInCalendarDays } from 'date-fns'
import MemberAvatar from '../components/MemberAvatar'
import { appLocale } from '../utils/dateLocale'
import '../components/messages/messages.css'
import { useAuth } from '../contexts/AuthContext'
import * as api from '../services/messagesApi'
import type { Conversation, Message } from '../services/messagesApi'
import MemberPicker from '../components/messages/MemberPicker'
import MessageBubble from '../components/messages/MessageBubble'
import MentionComposer from '../components/mentions/MentionComposer'
import { readMessageDraft, saveMessageDraft, readPendingSend, savePendingSend, completePendingSend, discardPendingSend } from '../navigation/messageDraft'
import PageLoading from '../components/PageLoading'
import { useMobileViewport, useBottomAction } from '../navigation/useMobileNavigation'
import { useMessagesUnread } from '../components/MessagesUnread'
import '../navigation/messagesMobile.css'
import { emptyMentionValue, mentionPayload } from '../components/mentions/mentionValue'
import { MobileShellActions } from '../navigation/mobileShellActions'

const GROUP_GAP_MS = 5 * 60_000
const TITLE_MAX = 60
/** Other members besides yourself; mirrors backend MAX_GROUP_MEMBERS - 1. */
const GROUP_MAX_OTHERS = 15
/** A group's chosen name, else its members' names. */
const nameOf = (c: Pick<Conversation, 'title'> | null | undefined, peers: MemberIdentity[]) => c?.title || peers.map(m => m.display_name).join(', ')

/**
 * The part of the page the software keyboard leaves visible, refreshed on every
 * visualViewport resize/scroll (Safari's offsetTop is only trusted fresh from
 * those events). Used only while typing on phones.
 */
function useVisibleBox(active: boolean) {
  const read = () => ({ top: window.visualViewport?.offsetTop ?? 0, height: window.visualViewport?.height ?? window.innerHeight })
  const [box, setBox] = useState(read)
  useEffect(() => {
    const viewport = window.visualViewport
    if (!active || !viewport) return
    const update = () => setBox(read())
    update()
    viewport.addEventListener('resize', update); viewport.addEventListener('scroll', update)
    return () => { viewport.removeEventListener('resize', update); viewport.removeEventListener('scroll', update) }
  }, [active])
  return box
}
const dayOf = (iso: string) => new Date(iso).toDateString()

/** Inbox time: hour today, "yesterday", weekday this week, then a short date. */
function inboxTime(iso: string | undefined, yesterday: string) {
  if (!iso) return ''
  const date = new Date(iso)
  if (isToday(date)) return format(date, 'HH:mm')
  if (isYesterday(date)) return yesterday
  if (differenceInCalendarDays(new Date(), date) < 7) return format(date, 'EEE', { locale: appLocale() }).replace('.', '')
  return format(date, 'd MMM', { locale: appLocale() }).replace('.', '')
}

function Thread({ id, onLeave }: { id: number; onLeave: (id: number) => void }) {
  const { user } = useAuth()
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [menu, setMenu] = useState(false)
  const [titleDraft, setTitleDraft] = useState<string | null>(null)
  const [conversation, setConversation] = useState<Conversation | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [before, setBefore] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [busy, setBusy] = useState(false)
  const [body, setBody] = useState(() => readMessageDraft(user?.user_id, id))
  const viewport = useMobileViewport()
  useBottomAction(viewport.width < 768)
  const phone = viewport.width < 768
  const typing = phone && viewport.editing
  const visibleBox = useVisibleBox(typing)
  const changeBody = (value: ReturnType<typeof emptyMentionValue>) => { if (!value.body) { sendKey.current = null; discardPendingSend(user?.user_id, id) } setBody(value); saveMessageDraft(user?.user_id, id, value) }
  const [retry, setRetry] = useState(0)
  const alive = useRef(true)
  const visible = useRef(new Set<number>())
  const received = useRef(new Set<number>())
  const read = useRef(new Set<number>())
  const pendingRead = useRef(false)
  const pendingLoad = useRef(false)
  const initialized = useRef(false)
  // Messages newer than the first load arrive with a small animation.
  const baseline = useRef<number | null>(null)
  const mutation = useRef(0)
  const sendKey = useRef<{ value: string; key: string } | null>(readPendingSend(user?.user_id, id))
  const thread = useRef<HTMLElement>(null)
  const [top, setTop] = useState(0)
  useLayoutEffect(() => {
    if (viewport.width >= 768 || !thread.current) return
    window.scrollTo({ top: 0, behavior: 'instant' })
    const measure = () => { if (thread.current) setTop(thread.current.getBoundingClientRect().top + window.scrollY) }
    measure()
    // The mobile shell bar can mount after this thread (arriving from the inbox) and push it down.
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure)
    observer?.observe(document.body)
    return () => observer?.disconnect()
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
  const { refresh: refreshUnread } = useMessagesUnread()
  const markVisibleRead = useCallback(async () => {
    if (!alive.current || pendingRead.current || document.visibilityState !== 'visible' || !document.hasFocus()) return
    const ids = [...visible.current].filter(i => !read.current.has(i)).slice(0, 50)
    if (!ids.length) return
    pendingRead.current = true
    try { await api.acknowledgeMessages(id, ids, true); ids.forEach(i => read.current.add(i)); refreshUnread() }
    catch { /* Retry on visibility, focus or next poll; never fabricate a receipt. */ }
    finally { pendingRead.current = false }
    // An observer may discover another visible message while this batch is in flight.
    if (alive.current && ids.every(i => read.current.has(i))) queueMicrotask(() => { void markVisibleRead() })
  }, [id, refreshUnread])
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
      if (!initialized.current) baseline.current = page.items.reduce((max, m) => Math.max(max, m.id), 0)
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
  const me = user?.user_id ?? 0
  const group = conversation?.kind === 'group'
  const byId = new Map(conversation?.members.map(m => [m.user_id, m]) ?? [])
  const lastMine = [...messages].reverse().find(m => m.sender_id === me)
  const statusOf = (message: Message) => {
    const read = message.receipts.length > 0 && message.receipts.every(r => r.read_at)
    const delivered = message.receipts.length > 0 && message.receipts.every(r => r.delivered_at)
    const readers = message.receipts.filter(r => r.read_at).length
    if (group && readers > 0 && !read) return t('messages.readBy', { count: readers })
    if (read) return t('messages.readShort', { time: format(new Date(message.receipts.map(r => r.read_at!).sort()[message.receipts.length - 1]), 'HH:mm') })
    return t(delivered ? 'messages.delivered' : 'messages.sent')
  }
  const dayLabel = (iso: string) => {
    const date = new Date(iso)
    return isToday(date) ? t('messages.today') : isYesterday(date) ? t('messages.yesterday') : format(date, 'EEEE d MMMM', { locale: appLocale() })
  }
  const react = (message: Message) => {
    if (busy) return
    setBusy(true)
    api.reactToMessage(id, message.id, !message.reactions.some(r => r.user_id === user?.user_id)).then(updated => {
      if (alive.current) { mutation.current++; setMessages(rows => rows.map(m => m.id === updated.id ? updated : m)) }
    }).catch(() => { if (alive.current) setError(true) }).finally(() => { if (alive.current) setBusy(false) })
  }
  // While typing on a phone the conversation is pinned to what the keyboard leaves visible: header on top, input right above the keys.
  const pinned = typing ? { position: 'fixed', left: 0, right: 0, top: visibleBox.top, height: visibleBox.height, zIndex: 45 } as React.CSSProperties : {}
  return <section ref={thread} className={`message-thread msg-thread${typing ? ' is-typing' : ''}`} style={{ '--message-viewport-height': `${viewport.height}px`, '--message-top': `${top}px`, ...pinned } as React.CSSProperties}>
    <header className="msg-thread-head">
      <Link to="/messages" className="msg-icon-btn msg-back" aria-label={t('messages.title')}><ArrowLeft size={18} /></Link>
      {group
        ? <div className="msg-menu msg-group-head">
            <button type="button" className="msg-peer" aria-expanded={menu} aria-haspopup="dialog" onClick={() => setMenu(v => !v)}>
              <ConversationAvatar peers={peers} size={phone ? 36 : 40} />
              <span className="msg-peer-name"><b>{nameOf(conversation, peers)}</b><small>{t('messages.members', { count: peers.length + 1 })}</small></span>
            </button>
            {menu && <div className="msg-menu-pop msg-group-pop" role="dialog" aria-label={t('messages.groupOptions')}>
              <form className="msg-title-edit" onSubmit={async e => {
                e.preventDefault()
                const next = (titleDraft ?? conversation?.title ?? '').trim()
                if (next === (conversation?.title ?? '')) { setTitleDraft(null); return }
                try { const saved = await api.renameGroup(id, next); if (alive.current) { setConversation(c => c && { ...c, title: saved.title }); setTitleDraft(null) } }
                catch { if (alive.current) setError(true) }
              }}>
                <label htmlFor="group-title" className="msg-group-pop-title">{t('messages.groupName')}</label>
                <div className="msg-title-row">
                  <input id="group-title" maxLength={TITLE_MAX} value={titleDraft ?? conversation?.title ?? ''} placeholder={peers.map(m => m.display_name).join(', ')} onChange={e => setTitleDraft(e.target.value)} />
                  {titleDraft !== null && titleDraft.trim() !== (conversation?.title ?? '') && <button type="submit" className="msg-title-save" aria-label={t('messages.saveName')}><Check size={16} /></button>}
                </div>
              </form>
              <p className="msg-group-pop-title">{t('messages.members', { count: peers.length + 1 })}</p>
              {peers.map(m => <Link key={m.user_id} to={`/users/${m.user_id}`} className="msg-group-member"><MemberAvatar member={m} size={32} /><b>{m.display_name}</b></Link>)}
              <button type="button" className="msg-leave" disabled={busy} onClick={async () => {
                if (!window.confirm(t('messages.leaveConfirm'))) return
                setBusy(true)
                try { await api.leaveConversation(id); onLeave(id); navigate('/messages') } catch { if (alive.current) setError(true) } finally { if (alive.current) { setBusy(false); setMenu(false) } }
              }}><LogOut size={16} />{t('messages.leave')}</button>
            </div>}
          </div>
        : peers.map(m => <Link key={m.user_id} to={`/users/${m.user_id}`} className="msg-peer">
            <MemberAvatar member={m} size={phone ? 36 : 40} />
            <span className="msg-peer-name"><b>{m.display_name}</b>{m.handle && <small>@{m.handle}</small>}</span>
          </Link>)}
      {/* Phones: this row replaces the tab title, so it carries the shell actions like every tab heading. */}
      {phone && <MobileShellActions />}
    </header>
    {error && <p role="alert" className="msg-alert">{t('messages.error')} <button type="button" onClick={() => setRetry(n => n + 1)}>{t('common.retry')}</button></p>}
    <div className="message-history msg-history" aria-label={t('messages.conversation')}>
      {loading && messages.length === 0 && <div className="grid min-h-[30vh] place-items-center"><PageLoading /></div>}
      {before && <button type="button" disabled={loading || busy} className="msg-older" onClick={() => void load(before)}>{t('messages.older')}</button>}
      {!loading && !messages.length && <div className="msg-empty-thread">
        {peers[0] && <MemberAvatar member={peers[0]} size={72} />}
        <p>{t('messages.begin')}</p>
      </div>}
      {messages.map((message, index) => {
        const previous = messages[index - 1], next = messages[index + 1]
        const newDay = !previous || dayOf(previous.created_at) !== dayOf(message.created_at)
        const joins = (a?: Message, b?: Message) => Boolean(a && b && a.sender_id === b.sender_id && dayOf(a.created_at) === dayOf(b.created_at)
          && Math.abs(Date.parse(b.created_at) - Date.parse(a.created_at)) < GROUP_GAP_MS)
        return <React.Fragment key={message.id}>
          {newDay && <div className="msg-day" role="separator"><span>{dayLabel(message.created_at)}</span></div>}
          <MessageBubble message={message} userId={me} busy={busy} onVisible={onVisible} onReact={() => react(message)}
            first={newDay || !joins(previous, message)} last={!joins(message, next)}
            status={message === lastMine ? statusOf(message) : null}
            fresh={baseline.current != null && message.id > baseline.current}
            sender={group ? (message.sender_id != null ? byId.get(message.sender_id) ?? null : null) : undefined} />
        </React.Fragment>
      })}<div ref={end} />
    </div>
    <form className="message-composer msg-composer" onSubmit={async e => {
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
    }}>
      <label htmlFor="direct-message" className="sr-only">{t('messages.compose')}</label>
      <MentionComposer id="direct-message" placeholder={t('messages.placeholderShort')} value={body} onChange={changeBody} disabled={busy} />
      <button type="submit" className="msg-send" aria-label={t('messages.send')} disabled={busy || !body.body.trim()}><Send size={18} /></button>
    </form>
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
  const [groupMode, setGroupMode] = useState(false)
  const [picked, setPicked] = useState<MemberIdentity[]>([])
  const [groupTitle, setGroupTitle] = useState('')
  const [starting, setStarting] = useState(false)
  const [retry, setRetry] = useState(0)
  const { refresh: refreshUnread } = useMessagesUnread()
  const phone = useMobileViewport().width < 768
  const visible = useVisibleBox(choose && phone)
  // Leaving the inbox re-syncs the nav badge with the receipts just written.
  useEffect(() => () => refreshUnread(), [refreshUnread])
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
  const me = user?.user_id
  const startWith = async (member: { user_id: number }) => {
    setStarting(true)
    try { const c = await api.startConversation(member.user_id); closeSheet(); navigate(`/messages/${c.id}`); setRetry(n => n + 1) }
    catch { setError(true) } finally { setStarting(false) }
  }
  const createGroup = async () => {
    if (picked.length < 2 || picked.length > GROUP_MAX_OTHERS || starting) return
    setStarting(true)
    try { const c = await api.startGroup(picked.map(m => m.user_id), groupTitle.trim()); closeSheet(); navigate(`/messages/${c.id}`); setRetry(n => n + 1) }
    catch { setError(true) } finally { setStarting(false) }
  }
  const closeSheet = () => { setChoose(false); setGroupMode(false); setPicked([]); setGroupTitle('') }
  const toggle = (member: MemberIdentity) => setPicked(rows => rows.some(m => m.user_id === member.user_id) ? rows.filter(m => m.user_id !== member.user_id) : rows.length >= GROUP_MAX_OTHERS ? rows : [...rows, member])
  // Leaving a group removes it from the API inbox, so drop it from local state too:
  // the refresh only merges returned rows and would otherwise keep the dead row clickable.
  const removeConversation = useCallback((cid: number) => setItems(rows => rows.filter(c => c.id !== cid)), [])
  return <div className={`messages-page msg-page ${id > 0 ? 'messages-page-thread' : ''}`}>
    <div className="messages-heading msg-head">
      <h1>{t('messages.title')}</h1>
      <button type="button" className="msg-new-btn" onClick={() => choose ? closeSheet() : setChoose(true)} aria-expanded={choose} aria-label={t('messages.new')}><Plus size={18} /><span>{t('messages.newShort')}</span></button>
      {(!(id > 0) || !phone) && <MobileShellActions />}
      {choose && <>
        <div className="msg-sheet-backdrop" onClick={closeSheet} aria-hidden="true" />
        <div className="msg-sheet" role="dialog" style={phone ? { bottom: `${Math.max(0, window.innerHeight - visible.top - visible.height)}px`, maxHeight: `${Math.max(240, visible.height - 24)}px` } : undefined} aria-label={t(groupMode ? 'messages.newGroup' : 'messages.new')} onKeyDown={e => { if (e.key === 'Escape') closeSheet() }}>
          <div className="msg-sheet-head">
            {groupMode && <button type="button" className="msg-icon-btn" aria-label={t('common.back')} onClick={() => { setGroupMode(false); setPicked([]) }}><ArrowLeft size={18} /></button>}
            <b>{t(groupMode ? 'messages.newGroup' : 'messages.new')}</b>
            {groupMode
              ? <button type="button" className="msg-new-btn msg-create" disabled={picked.length < 2 || picked.length > GROUP_MAX_OTHERS || starting} onClick={() => void createGroup()}
                  aria-label={picked.length < 2 ? t('messages.pickTwo') : t('messages.createGroup', { count: picked.length + 1 })}>{t('messages.create')}{picked.length >= 2 && <span className="msg-create-count">{picked.length + 1}</span>}</button>
              : <button type="button" className="msg-icon-btn" aria-label={t('common.close')} onClick={closeSheet}><X size={18} /></button>}
          </div>
          {!groupMode && <button type="button" className="msg-mode" onClick={() => setGroupMode(true)}><span className="msg-mode-icon"><Users size={20} /></span><b>{t('messages.newGroup')}</b></button>}
          {groupMode && <label className="msg-search msg-name-field"><span className="sr-only">{t('messages.groupName')}</span>
            <input value={groupTitle} maxLength={TITLE_MAX} onChange={e => setGroupTitle(e.target.value)} placeholder={t('messages.groupNamePlaceholder')} />
          </label>}
          {groupMode && picked.length > 0 && <div className="msg-chips">{picked.map(m => <button key={m.user_id} type="button" className="msg-chip" onClick={() => toggle(m)} aria-label={t('messages.removeMember', { name: m.display_name })}>
            <MemberAvatar member={m} size={28} />{m.display_name}<X size={14} />
          </button>)}</div>}
          <MemberPicker key={groupMode ? 'group' : 'direct'} disabled={starting} autoFocus selected={groupMode ? picked.map(m => m.user_id) : undefined}
            onSelect={member => groupMode ? toggle(member) : void startWith(member)} />
          {groupMode && picked.length < 2 && <p className="msg-hint">{t('messages.pickTwo')}</p>}
          {groupMode && picked.length >= GROUP_MAX_OTHERS && <p className="msg-hint">{t('messages.groupFull', { count: GROUP_MAX_OTHERS + 1 })}</p>}
        </div>
      </>}
    </div>
    {error && <p role="alert" className="msg-alert">{t('messages.error')} <button type="button" onClick={() => setRetry(n => n + 1)}>{t('common.retry')}</button></p>}
    <div className="messages-grid msg-grid">
      <aside className={`msg-inbox${id ? ' is-behind' : ''}`} aria-label={t('messages.inbox')}>
        {loading && items.length === 0 && <div className="grid min-h-[30vh] place-items-center"><PageLoading /></div>}
        {!loading && !items.length && <div className="msg-empty">
          <p>{t('messages.empty')}</p>
          <button type="button" className="msg-new-btn" onClick={() => setChoose(true)}><Plus size={18} /><span>{t('messages.newShort')}</span></button>
        </div>}
        {items.map((c, index) => {
          const peers = c.members.filter(m => m.user_id !== me)
          const latest = c.latest
          const preview = latest?.body || (latest?.dive ? [latest.dive.dive_code, latest.dive.height].filter(Boolean).join(' · ') || t('messages.diveCard') : t('messages.begin'))
          const unread = c.unread_count ?? 0
          return <Link key={c.id} to={`/messages/${c.id}`} className={`msg-row${c.id === id ? ' is-active' : ''}${unread ? ' is-unread' : ''}`} style={{ '--i': Math.min(index, 12) } as React.CSSProperties}
            aria-current={c.id === id ? 'page' : undefined}>
            <ConversationAvatar peers={peers} size={52} />
            <span className="msg-row-main">
              <span className="msg-row-top"><b>{nameOf(c, peers)}</b><time dateTime={c.updated_at}>{inboxTime(latest?.created_at ?? c.updated_at, t('messages.yesterday'))}</time></span>
              <span className="msg-row-bottom">
                <span className="msg-row-preview">{latest && latest.sender_id === me && <span className="msg-row-you">{t('messages.you')} </span>}{latest && c.kind === 'group' && latest.sender_id !== me && <span className="msg-row-you">{c.members.find(m => m.user_id === latest.sender_id)?.display_name ?? ''} : </span>}{latest?.dive && <Play size={12} fill="currentColor" aria-hidden="true" className="msg-row-dive" />}{preview}</span>
                {unread > 0 && <span className="msg-badge" aria-label={t('messages.unread', { count: unread })}>{unread}</span>}
              </span>
            </span>
          </Link>
        })}
        {before && <button type="button" className="msg-older" onClick={async () => { try { const page = await api.listConversations(before); setItems(rows => [...new Map([...rows, ...page.items].map(c => [c.id,c])).values()]); setBefore(page.next_before) } catch { setError(true) } }}>{t('messages.more')}</button>}
      </aside>
      {Number.isSafeInteger(id) && id > 0 ? <Thread key={`${user?.user_id}:${id}`} id={id} onLeave={removeConversation} /> : <div className="msg-pane-empty"><p>{t('messages.choose')}</p></div>}
    </div>
  </div>
}
