import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Film, Lock, Play } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { getProfileDives, type ProfileDive } from '../services/communityApi'
import { appLanguage } from '../utils/dateLocale'

function Tile({ dive }: { dive: ProfileDive }) {
  const { t } = useTranslation()
  const [failed, setFailed] = useState(false)
  return <Link to={`/dives?clip=${dive.id}&scope=all`} aria-label={t('community.openDive', { code: dive.dive_code, height: dive.height })} className="group relative block aspect-square overflow-hidden bg-app-panel-elevated focus-visible:outline focus-visible:outline-2 focus-visible:outline-app-accent">
    {dive.poster_url && !failed
      ? <img src={dive.poster_url} alt="" loading="lazy" onError={() => setFailed(true)} className="h-full w-full object-cover transition-transform group-hover:scale-105" />
      : <span className="absolute inset-0 flex items-center justify-center text-app-muted"><Film className="h-8 w-8 opacity-40 sm:h-12 sm:w-12" aria-hidden /></span>}
    <span className="absolute right-2 top-2 flex gap-1 text-white"><Play className="h-4 w-4 fill-current drop-shadow" aria-hidden />{dive.visibility === 'private' && <Lock className="h-4 w-4 drop-shadow" aria-label={t('community.privateDive')} />}</span>
    <span className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/90 to-transparent px-2 pb-2 pt-8 text-white sm:px-3 sm:pb-3"><span className="block text-xs font-semibold sm:text-base">{dive.dive_code} · {dive.height}</span><time dateTime={dive.dive_datetime} className="mt-1 hidden text-xs text-white/80 sm:block">{new Date(dive.dive_datetime).toLocaleDateString(appLanguage())}</time></span>
  </Link>
}

export default function ProfileDiveGrid({ userId }: { userId: number }) {
  const { t } = useTranslation()
  const [dives, setDives] = useState<ProfileDive[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const generation = useRef(0)
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const current = ++generation.current
    setDives([]); setCursor(null); setLoading(true); setError(false)
    getProfileDives(userId).then(page => {
      if (current !== generation.current) return
      setDives(page.items); setCursor(page.next_before)
    }).catch(() => { if (current === generation.current) setError(true) })
      .finally(() => { if (current === generation.current) setLoading(false) })
    return () => { generation.current++ }
  }, [userId, retry])
  async function more() {
    if (!cursor || loading) return
    const current = generation.current
    setLoading(true); setError(false)
    try {
      const page = await getProfileDives(userId, cursor)
      if (current !== generation.current) return
      setDives(previous => [...previous, ...page.items]); setCursor(page.next_before)
    } catch { if (current === generation.current) setError(true) }
    finally { if (current === generation.current) setLoading(false) }
  }
  return <section aria-label={t('community.dives')}>
    <p className="mb-3 text-xs text-app-muted">{t('community.latest')}</p>
    <div className="grid grid-cols-3 gap-1 sm:gap-2">{dives.map(dive => <Tile key={dive.id} dive={dive} />)}</div>
    {loading && <p role="status" className="py-6 text-sm text-app-muted">{t('common.loading')}</p>}
    {error && <p role="alert" className="py-6 text-sm text-red-400">{t('community.divesError')} <button className="underline" onClick={() => { if (cursor) void more(); else setRetry(previous => previous + 1) }}>{t('common.retry')}</button></p>}
    {!loading && !error && dives.length === 0 && <p className="border border-app bg-app-panel p-8 text-center text-app-muted">{t('community.noDives')}</p>}
    {cursor && <button onClick={() => void more()} disabled={loading} className="touch-target mt-5 border border-app px-4 text-app-text disabled:opacity-50">{t('community.moreDives')}</button>}
  </section>
}
