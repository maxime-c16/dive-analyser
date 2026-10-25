import { useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Heart, Play } from 'lucide-react'
import type { Message } from '../../services/messagesApi'
import MentionText from '../mentions/MentionText'
import MemberAvatar from '../MemberAvatar'
import type { MemberIdentity } from '../../services/communityApi'

/**
 * One message. Consecutive messages from the same sender form a group: only
 * the last one shows its time, and only your newest message shows its
 * delivery state. Double tap reacts; the heart button stays reachable by
 * keyboard and shows on hover.
 */
export default function MessageBubble({ message, userId, onReact, onVisible, busy, first = true, last = true, status, fresh = false, sender }: {
  message: Message; userId: number; onReact: () => void; onVisible: (id: number, visible: boolean) => void; busy: boolean
  first?: boolean; last?: boolean; status?: string | null; fresh?: boolean
  /** In groups: who sent it (name on the first bubble, avatar beside the last). */
  sender?: MemberIdentity | null
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
  const count = message.reactions.length
  const time = new Date(message.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return <article ref={ref} aria-label={mine ? t('messages.yourMessage') : t('messages.receivedMessage')}
    className={`msg-item ${mine ? 'is-mine' : 'is-theirs'}${first ? ' is-first' : ''}${last ? ' is-last' : ''}${fresh ? ' is-fresh' : ''}${sender !== undefined ? ' in-group' : ''}`}
    onPointerUp={e => {
      if (e.target instanceof Element && e.target.closest('a,button')) return
      const now = Date.now()
      if (now - tap.current < 300 && !busy) { onReact(); tap.current = 0 } else tap.current = now
    }}>
    {sender !== undefined && !mine && first && <p className="msg-sender">{sender?.display_name ?? t('messages.formerMember')}</p>}
    {sender !== undefined && !mine && last && <span className="msg-sender-avatar" aria-hidden="true">{sender ? <MemberAvatar member={sender} size={28} /> : null}</span>}
    <div className="msg-bubble-row">
      <div className={`msg-bubble${message.dive && !message.body ? ' is-media' : ''}`}>
        {message.body && <p className="msg-text"><MentionText body={message.body} mentions={message.mentions} /></p>}
        {message.dive && (message.dive.available
          ? <Link to={`/dives?clip=${message.dive.id}&scope=all`} className="msg-dive" aria-label={`${t('messages.watch')} · ${message.dive.dive_code} · ${message.dive.height}`}>
              <span className="msg-dive-thumb">
                {message.dive.poster_url && <img src={message.dive.poster_url} alt="" loading="lazy" decoding="async" />}
                <span className="msg-dive-play" aria-hidden="true"><Play size={18} fill="currentColor" /></span>
              </span>
              <span className="msg-dive-cap"><b>{message.dive.dive_code}</b><span>{message.dive.height}</span></span>
            </Link>
          : <p className="msg-dive-gone">{t('messages.diveUnavailable')}</p>)}
        {count > 0 && <span className="msg-reaction" aria-hidden="true"><Heart size={11} fill="currentColor" />{count > 1 ? count : ''}</span>}
      </div>
      <button type="button" className={`msg-react${reacted ? ' is-on' : ''}`} disabled={busy} aria-label={t('messages.react')} aria-pressed={reacted} onClick={onReact}>
        <Heart size={15} fill={reacted ? 'currentColor' : 'none'} />
      </button>
    </div>
    {(last || status) && <div className="msg-meta">
      {last && <time dateTime={message.created_at}>{time}</time>}
      {status && <span>{status}</span>}
    </div>}
  </article>
}
