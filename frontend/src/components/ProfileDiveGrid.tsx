import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { getProfileDives, type ProfileDive } from '../services/communityApi'
import { LibraryCardGrid } from './LibraryCards'
import PageLoading from './PageLoading'
import MediaThumbnail from './MediaThumbnail'
import type { Attempt } from '../utils/attemptPresentation'

/** Profile grid rows as Library attempts: the same portrait cards, score badge and day sections. */
function asAttempt(dive: ProfileDive): Attempt {
  return {
    id: dive.id, dive_code: dive.dive_code, height: dive.height, dive_datetime: dive.dive_datetime,
    performance: dive.performance ?? '', phase1_performance: dive.phase1_performance ?? null, phase2_performance: dive.phase2_performance ?? null,
    thumb_url: dive.poster_url, video_uuid: null,
  } as unknown as Attempt
}

export default function ProfileDiveGrid({ userId }: { userId: number }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
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
  const attempts = useMemo(() => dives.map(asAttempt), [dives])
  const byId = useMemo(() => new Map(dives.map(dive => [dive.id, dive])), [dives])
  return <section aria-label={t('community.dives')}>
    <LibraryCardGrid attempts={attempts} onOpen={attempt => navigate(`/dives?clip=${attempt.id}&scope=all`)}
      // Poster, else a ready local web preview: never a B2 original from a tile.
      thumbnail={attempt => <MediaThumbnail posterUrl={byId.get(attempt.id)?.poster_url} playbackUrl={byId.get(attempt.id)?.playback_url} />} />
    {loading && dives.length === 0 && <PageLoading />}
    {loading && dives.length > 0 && <p role="status" className="cm-empty">{t('common.loading')}</p>}
    {error && <p role="alert" className="cm-alert">{t('community.divesError')} <button type="button" onClick={() => { if (cursor) void more(); else setRetry(previous => previous + 1) }}>{t('common.retry')}</button></p>}
    {!loading && !error && dives.length === 0 && <p className="cm-empty">{t('community.noDives')}</p>}
    {cursor && <div style={{ display: 'grid', marginTop: 16 }}><button type="button" onClick={() => void more()} disabled={loading} className="ca-pill cm-more">{t('community.moreDives')}</button></div>}
  </section>
}
