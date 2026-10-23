import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Search, User } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { searchMembers, type MemberSummary } from '../services/communityApi'
import { appLanguage } from '../utils/dateLocale'
import MemberAvatar from '../components/MemberAvatar'
import PageLoading from '../components/PageLoading'
import { MobileShellActions } from '../navigation/mobileShellActions'

export default function Community() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const [params, setParams] = useSearchParams()
  const q = params.get('q') ?? ''
  const [members, setMembers] = useState<MemberSummary[]>([])
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
    <header className="mb-4 flex items-center justify-between gap-3">
      <h1 className="min-w-0 text-3xl font-semibold tracking-tight text-app-text sm:text-4xl">{t('community.title')}</h1>
      <MobileShellActions />
      {user && <Link className="touch-target max-lg:hidden inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap border border-app bg-app-panel px-4 text-sm font-medium text-app-text hover:border-app-strong" to={`/users/${user.user_id}`}><User className="h-4 w-4" aria-hidden />{t('community.myProfile')}</Link>}
    </header>
    <label className="relative mb-4 block">
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-app-muted" aria-hidden />
      <span className="sr-only">{t('community.search')}</span>
      <input type="search" maxLength={120} value={q} onChange={event => setParams(event.target.value ? { q: event.target.value } : {}, { replace: true })} placeholder={t('community.search')} className="app-input h-11 w-full !pl-10 pr-4 text-sm" />
    </label>
    {error && <p role="alert" className="mb-4 text-red-400">{t('community.error')} <button className="underline" onClick={() => { if (after) void more(); else setRetry(value => value + 1) }}>{t('common.retry')}</button></p>}
    <ul className="grid gap-2 sm:grid-cols-2">
      {members.map(member => <li key={member.user_id}><Link to={`/users/${member.user_id}`} className="flex h-full items-center gap-3 border border-app bg-app-panel p-3 transition-colors hover:border-app-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-app-accent">
        <MemberAvatar member={member} size={44} /><div className="min-w-0"><p className="truncate font-semibold text-app-text">{member.display_name}{member.handle && <span className="ml-2 text-sm font-normal text-app-accent">@{member.handle}</span>}</p>{member.accessible_dive_count !== undefined && <p className="mt-1 flex flex-wrap gap-x-2 text-sm text-app-muted">
          <span>{member.accessible_dive_count > 0 ? t('community.sharedDives', { count: member.accessible_dive_count }) : t('community.noSharedDives')}</span>
          {member.accessible_dive_count > 0 && member.latest_dive_at && <span>{t('community.latestDive')} <time dateTime={member.latest_dive_at}>{new Date(member.latest_dive_at).toLocaleDateString(appLanguage(), { day: 'numeric', month: 'short', year: 'numeric' })}</time></span>}
        </p>}{member.bio && <p className="mt-0.5 line-clamp-1 break-words text-sm text-app-muted">{member.bio}</p>}</div>
      </Link></li>)}
    </ul>
    {loading && members.length === 0 && <PageLoading />}
    {!loading && !error && members.length === 0 && <p className="py-6 text-app-muted">{t('community.empty')}</p>}
    {after && <button disabled={loading} onClick={() => void more()} className="touch-target mt-4 border border-app bg-app-panel px-4 text-sm font-medium text-app-text hover:border-app-strong disabled:opacity-50">{t('community.more')}</button>}
  </div>
}
