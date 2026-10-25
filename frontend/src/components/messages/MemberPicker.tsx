import { useEffect, useState, type CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, Search } from 'lucide-react'
import { useAuth } from '../../contexts/AuthContext'
import { searchMembers, type MemberIdentity } from '../../services/communityApi'
import MemberAvatar from '../MemberAvatar'
import './messages.css'

/** Search members; with `selected`, rows toggle (group creation) instead of picking one. */
export default function MemberPicker({ onSelect, disabled, autoFocus = false, selected }: { onSelect: (member: MemberIdentity) => void; disabled?: boolean; autoFocus?: boolean; selected?: number[] }) {
  const { t } = useTranslation()
  const { user } = useAuth()
  const [query, setQuery] = useState('')
  const [items, setItems] = useState<MemberIdentity[]>([])
  const [error, setError] = useState(false)
  const [loading, setLoading] = useState(false)
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setItems([]); setError(false)
    const timer = setTimeout(() => { searchMembers(query, undefined, controller.signal).then(page => {
      if (!controller.signal.aborted) setItems(page.items.filter(m => m.user_id !== user?.user_id))
    }).catch(() => { if (!controller.signal.aborted) setError(true) }).finally(() => { if (!controller.signal.aborted) setLoading(false) }) }, 180)
    return () => { clearTimeout(timer); controller.abort() }
  }, [query, user?.user_id, retry])
  return <div className="msg-pick">
    <label className="msg-search">
      <Search size={16} aria-hidden="true" />
      <span className="sr-only">{t('messages.recipient')}</span>
      <input value={query} disabled={disabled} autoFocus={autoFocus} onChange={e => setQuery(e.target.value)} placeholder={t('community.search')} />
    </label>
    {error && <p role="alert" className="msg-alert">{t('community.error')} <button type="button" onClick={() => setRetry(n => n + 1)}>{t('common.retry')}</button></p>}
    <div className="msg-pick-list">
      {loading && <div role="status" aria-label={t('common.loading')}>{[0, 1, 2].map(index => <div key={index} className="msg-pick-skeleton" />)}</div>}
      {!loading && !error && !items.length && <p className="msg-pick-empty">{t('community.empty')}</p>}
      {items.map((member, index) => <button type="button" key={member.user_id} disabled={disabled} className="msg-pick-row" style={{ '--i': Math.min(index, 10) } as CSSProperties} aria-pressed={selected ? selected.includes(member.user_id) : undefined} onClick={() => onSelect(member)}>
        <MemberAvatar member={member} size={44} />
        <span className="msg-pick-name"><b>{member.display_name}</b>{member.handle && <small>@{member.handle}</small>}</span>
        {selected && <span className="msg-pick-check" aria-hidden="true">{selected.includes(member.user_id) && <Check size={14} strokeWidth={3} />}</span>}
      </button>)}
    </div>
  </div>
}
