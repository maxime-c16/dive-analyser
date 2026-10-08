import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Search } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { searchMembers, type MemberIdentity } from '../services/communityApi'
import MemberAvatar from '../components/MemberAvatar'

export default function Community() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const [params, setParams] = useSearchParams()
  const q = params.get('q') ?? ''
  const [members, setMembers] = useState<MemberIdentity[]>([])
  const [after, setAfter] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const generation = useRef(0)
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    const current = ++generation.current
    const controller = new AbortController()
    setMembers([]); setAfter(null); setLoading(true); setError(false)
    const timer = window.setTimeout(() => {
      searchMembers(q, undefined, controller.signal).then(page => {
        if (current !== generation.current) return
        setMembers(page.items); setAfter(page.next_after)
      }).catch(() => { if (!controller.signal.aborted) setError(true) })
        .finally(() => { if (current === generation.current && !controller.signal.aborted) setLoading(false) })
    }, 250)
    return () => { controller.abort(); window.clearTimeout(timer); generation.current++ }
  }, [q, retry])

  async function more() {
    if (!after || loading) return
    const current = generation.current
    setLoading(true); setError(false)
    try {
      const page = await searchMembers(q, after)
      if (current !== generation.current) return
      setMembers(previous => [...previous, ...page.items]); setAfter(page.next_after)
    } catch { if (current === generation.current) setError(true) }
    finally { if (current === generation.current) setLoading(false) }
  }

  return <div className="mx-auto max-w-4xl">
    <header className="mb-6 flex items-start justify-between gap-4">
      <div><h1 className="text-3xl font-semibold text-app-text">{t('community.title')}</h1><p className="mt-2 text-sm text-app-muted">{t('community.subtitle')}</p></div>
      {user && <Link className="touch-target shrink-0 border border-app px-3 py-2 text-sm text-app-accent" to={`/users/${user.user_id}`}>{t('community.myProfile')}</Link>}
    </header>
    <label className="mb-6 flex items-center gap-3 border border-app bg-app-panel p-3 text-app-muted">
      <Search className="h-5 w-5" aria-hidden />
      <span className="sr-only">{t('community.search')}</span>
      <input type="search" maxLength={120} value={q} onChange={event => setParams(event.target.value ? { q: event.target.value } : {}, { replace: true })} placeholder={t('community.search')} className="min-w-0 flex-1 bg-transparent text-app-text outline-none" />
    </label>
    {error && <p role="alert" className="mb-4 text-red-400">{t('community.error')} <button className="underline" onClick={() => { if (after) void more(); else setRetry(value => value + 1) }}>{t('common.retry')}</button></p>}
    <ul className="grid gap-3 sm:grid-cols-2">
      {members.map(member => <li key={member.user_id}><Link to={`/users/${member.user_id}`} className="flex h-full items-start gap-3 border border-app bg-app-panel p-4 transition-colors hover:border-app-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-app-accent">
        <MemberAvatar member={member} /><div className="min-w-0"><p className="truncate font-semibold text-app-text">{member.display_name}</p>{member.handle && <p className="text-sm text-app-accent">@{member.handle}</p>}{member.bio && <p className="mt-2 line-clamp-2 break-words text-sm text-app-muted">{member.bio}</p>}</div>
      </Link></li>)}
    </ul>
    {loading && <p role="status" className="py-6 text-sm text-app-muted">{t('common.loading')}</p>}
    {!loading && !error && members.length === 0 && <p className="py-6 text-app-muted">{t('community.empty')}</p>}
    {after && <button disabled={loading} onClick={() => void more()} className="touch-target mt-6 border border-app px-4 text-app-text disabled:opacity-50">{t('community.more')}</button>}
  </div>
}
