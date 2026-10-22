import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Film, Lock, Play } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { getProfileDives, type ProfileDive } from '../services/communityApi'
import PageLoading from './PageLoading'
import { appLanguage } from '../utils/dateLocale'
import MediaThumbnail from './MediaThumbnail'

function Tile({ dive }: { dive: ProfileDive }) {
  const { t } = useTranslation()
  const hasMedia = Boolean(dive.poster_url || dive.playback_url)
  const text = hasMedia ? 'text-white' : 'text-app-text'
  return <Link to={`/dives?clip=${dive.id}&scope=all`} aria-label={t('community.openDive', { code: dive.dive_code, height: dive.height })} className="group relative block aspect-video overflow-hidden border border-app bg-app-panel-elevated focus-visible:outline focus-visible:outline-2 focus-visible:outline-app-accent">
    <MediaThumbnail posterUrl={dive.poster_url} playbackUrl={dive.playback_url} />
    <span className="absolute right-2 top-2 flex gap-1 text-white">{hasMedia ? <Play className="h-4 w-4 fill-current drop-shadow" aria-hidden /> : <Film className="h-4 w-4 text-app-muted" aria-hidden />}{dive.visibility === 'private' && <Lock className={`h-4 w-4 ${hasMedia ? 'drop-shadow' : 'text-app-muted'}`} aria-label={t('community.privateDive')} />}</span>
    <span className={`absolute inset-x-0 bottom-0 px-2 pb-2 pt-6 ${text} ${hasMedia ? 'bg-gradient-to-t from-black/90 to-transparent' : ''} sm:px-3 sm:pb-3`}><span className="block font-mono text-sm font-semibold sm:text-base">{dive.dive_code} · {dive.height}</span><time dateTime={dive.dive_datetime} className={`mt-0.5 block text-xs ${hasMedia ? 'text-white/80' : 'text-app-muted'}`}>{new Date(dive.dive_datetime).toLocaleDateString(appLanguage())}</time></span>
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
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">{dives.map(dive => <Tile key={dive.id} dive={dive} />)}</div>
    {loading && dives.length === 0 && <PageLoading />}
    {loading && dives.length > 0 && <p role="status" className="py-6 text-sm text-app-muted">{t('common.loading')}</p>}
    {error && <p role="alert" className="py-6 text-sm text-red-400">{t('community.divesError')} <button className="underline" onClick={() => { if (cursor) void more(); else setRetry(previous => previous + 1) }}>{t('common.retry')}</button></p>}
    {!loading && !error && dives.length === 0 && <p className="border border-app bg-app-panel p-8 text-center text-app-muted">{t('community.noDives')}</p>}
    {cursor && <button onClick={() => void more()} disabled={loading} className="touch-target mt-5 border border-app bg-app-panel px-4 text-sm font-medium text-app-text hover:border-app-strong disabled:opacity-50">{t('community.moreDives')}</button>}
  </section>
}
