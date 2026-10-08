import { useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Heart } from 'lucide-react'
import type { Message } from '../../services/messagesApi'
import MentionText from '../mentions/MentionText'
export default function MessageBubble({ message, userId, onReact, onVisible, busy }: {
  message: Message; userId: number; onReact: () => void; onVisible: (id: number, visible: boolean) => void; busy: boolean
}) {
  const { t } = useTranslation()
  const ref = useRef<HTMLElement>(null)
  const tap = useRef(0)
  const mine = message.sender_id === userId
  const reacted = message.reactions.some(r => r.user_id === userId)
  useEffect(() => {
    if (mine || !ref.current) return
    const observer = new IntersectionObserver(entries => onVisible(message.id, entries[0].intersectionRatio >= 0.6), { threshold: [0, 0.6] })
    observer.observe(ref.current)
    return () => { observer.disconnect(); onVisible(message.id, false) }
  }, [message.id, mine, onVisible])
  const read = message.receipts.length > 0 && message.receipts.every(r => r.read_at)
  const delivered = message.receipts.length > 0 && message.receipts.every(r => r.delivered_at)
  const readAt = read ? message.receipts.map(r => r.read_at!).sort()[message.receipts.length - 1] : null
  return <article ref={ref} aria-label={mine ? t('messages.yourMessage') : t('messages.receivedMessage')} className={`w-fit max-w-[88%] rounded-2xl border border-app p-3 ${mine ? 'ml-auto bg-app-panel-elevated' : 'mr-auto bg-app-panel'}`}
    onPointerUp={e => {
      if (e.target instanceof Element && e.target.closest('a,button')) return
      const now = Date.now()
      if (now - tap.current < 300 && !busy) { onReact(); tap.current = 0 } else tap.current = now
    }}>
    {message.body && <p className="whitespace-pre-wrap break-words text-sm"><MentionText body={message.body} mentions={message.mentions} /></p>}
    {message.dive && (message.dive.available ? <Link to={`/dives?clip=${message.dive.id}&scope=all`} className="mt-2 block min-w-[180px] max-w-[280px] overflow-hidden rounded-xl border border-app">
      {message.dive.poster_url && <img src={message.dive.poster_url} alt="" className="h-40 w-full object-cover" />}
      <span className="block p-2 text-sm font-semibold">{message.dive.dive_code} · {message.dive.height} · {t('messages.watch')}</span>
    </Link> : <p className="mt-2 text-sm text-app-muted">{t('messages.diveUnavailable')}</p>)}
    <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-app-muted">
      <time dateTime={message.created_at}>{new Date(message.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time>
      {mine && <span>{readAt ? t('messages.readAt', { time: new Date(readAt).toLocaleString() }) : t(delivered ? 'messages.delivered' : 'messages.sent')}</span>}
      <button type="button" disabled={busy} aria-label={t('messages.react')} aria-pressed={reacted} onClick={onReact} className="ml-auto flex items-center gap-1 p-1"><Heart size={14} fill={reacted ? 'currentColor' : 'none'} />{message.reactions.length || ''}</button>
    </div>
  </article>
}
