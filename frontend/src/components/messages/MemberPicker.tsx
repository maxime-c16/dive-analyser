import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../contexts/AuthContext'
import { searchMembers, type MemberIdentity } from '../../services/communityApi'
import MemberAvatar from '../MemberAvatar'
export default function MemberPicker({ onSelect, disabled }: { onSelect: (member: MemberIdentity) => void; disabled?: boolean }) {
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
  return <div className="space-y-2">
    <label className="block text-sm">{t('messages.recipient')}<input className="mt-2 w-full border border-app bg-app-panel px-3 py-2" value={query} disabled={disabled} onChange={e => setQuery(e.target.value)} placeholder={t('community.search')} /></label>
    {loading && <p role="status">{t('common.loading')}</p>}
    {error && <p role="alert">{t('community.error')} <button type="button" onClick={() => setRetry(n => n + 1)}>{t('common.retry')}</button></p>}
    {!loading && !error && !items.length && <p>{t('community.empty')}</p>}
    <div className="max-h-64 overflow-y-auto">{items.map(member => <button type="button" key={member.user_id} disabled={disabled} className="flex w-full items-center gap-3 border-b border-app p-3 text-left hover:bg-app-panel-elevated" onClick={() => onSelect(member)}><MemberAvatar member={member} /><span><strong>{member.display_name}</strong>{member.handle && <span className="block text-sm text-app-muted">@{member.handle}</span>}</span></button>)}</div>
  </div>
}
