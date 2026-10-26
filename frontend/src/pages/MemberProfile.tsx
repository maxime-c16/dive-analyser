import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { format, parseISO } from 'date-fns'
import { ArrowLeft, Heart, Layers, MessageCircle, Pencil } from 'lucide-react'
import {
  getUserProfile,
  getUserActivity,
  type MemberProfile as MemberProfileData,
  type ActivityItem,
} from '../services/activityApi'
import { getMemberCodes } from '../services/communityApi'
import MemberAvatar from '../components/MemberAvatar'
import MemberLink from '../components/activity/MemberLink'
import ProfileDiveGrid from '../components/ProfileDiveGrid'
import ProfileMessageButton from '../components/messages/ProfileMessageButton'
import ProfileEditor from '../components/ProfileEditor'
import AchievementsPanel from '../components/achievements/AchievementsPanel'
import CodeCards, { type CodeSort } from '../components/code-analysis/CodeCards'
import { CountUp, Segmented } from '../components/code-analysis/parts'
import PageLoading from '../components/PageLoading'
import { MobileShellActions } from '../navigation/mobileShellActions'
import { appLocale } from '../utils/dateLocale'
import type { CodeSummary } from '../services/codeSummariesApi'
import '../components/code-analysis/codeAnalysis.css'
import '../components/community/community.css'

const PAGE_SIZE = 30
/** Compact age for a stat tile: "3 h", "18 j", "2 mois", "1 an". */
/** Time since `iso` as a number and a short unit, so the number lines up with the other KPIs. */
function shortAgo(iso: string, t: (key: string, options?: Record<string, unknown>) => string) {
  const hours = (Date.now() - Date.parse(iso)) / 3_600_000
  const days = Math.round(hours / 24)
  const [count, unit] = hours < 24 ? [Math.max(1, Math.round(hours)), 'hours'] : days < 45 ? [days, 'days'] : days < 365 ? [Math.round(days / 30), 'months'] : [Math.round(days / 365), 'years']
  return { count, unit: t(`profile.ago.${unit}`, { count }) }
}
const PROFILE_TABS = ['dives', 'codes', 'activity', 'achievements'] as const
type ProfileTab = (typeof PROFILE_TABS)[number]
type MemberCodes = Awaited<ReturnType<typeof getMemberCodes>>

const ACTIVITY_ICONS = { dive_like: Heart, comment: MessageCircle, comment_like: Heart } as const

/** Day-grouped feed of the member's likes and comments, with real avatars. */
function ActivityTimeline({ items }: { items: ActivityItem[] }) {
  const { t } = useTranslation()
  const groups = new Map<string, ActivityItem[]>()
  for (const item of items) {
    const key = item.created_at ? new Date(item.created_at).toDateString() : '—'
    groups.set(key, [...(groups.get(key) ?? []), item])
  }
  const label = (key: string) => {
    if (key === '—') return ''
    if (key === new Date().toDateString()) return t('profile.today')
    if (key === new Date(Date.now() - 86_400_000).toDateString()) return t('profile.yesterday')
    return format(new Date(key), 'EEEE d MMMM', { locale: appLocale() })
  }
  return <ol className="cm-timeline">
    {[...groups.entries()].map(([day, rows], groupIndex) => <li key={day} className="cm-day ca-pop" style={{ '--i': groupIndex } as CSSProperties}>
      <p>{label(day)}</p>
      {rows.map(item => {
        const Icon = ACTIVITY_ICONS[item.kind] ?? Heart
        return <div key={item.key} className="cm-event">
          <MemberAvatar member={item.actor} size={36} />
          <div className="cm-event-body">
            <span className="cm-event-icon" aria-hidden="true"><Icon size={11} /></span>
            {item.actor.user_id ? <MemberLink userId={item.actor.user_id} className="font-semibold">{item.actor.display_name}</MemberLink> : <b>{item.actor.display_name}</b>}
            {' '}{t(`profile.trail.${item.kind}`)}{' '}
            <Link to={`/dives?clip=${item.dive.id}&scope=all`}>{item.dive.dive_code}{item.dive.height ? ` · ${item.dive.height}` : ''}{item.dive.diver_name ? ` · ${item.dive.diver_name}` : ''}</Link>
            {item.comment?.body && <blockquote>{item.comment.body}</blockquote>}
          </div>
          <time dateTime={item.created_at ?? undefined}>{item.created_at ? format(new Date(item.created_at), 'HH:mm') : ''}</time>
        </div>
      })}
    </li>)}
  </ol>
}

export default function MemberProfile() {
  const { userId } = useParams()
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const location = useLocation()
  const tab: ProfileTab = PROFILE_TABS.find(value => value === searchParams.get('tab')) ?? 'dives'
  const setTab = (next: ProfileTab) => setSearchParams(next === 'dives' ? {} : { tab: next }, { replace: true, preventScrollReset: true })
  // Tabs only change the URL query: panels stay mounted once opened, so switching back is instant.
  const [visited, setVisited] = useState<{ user?: string; tabs: Set<ProfileTab> }>(() => ({ user: userId, tabs: new Set([tab]) }))
  useEffect(() => setVisited(previous => previous.user === userId ? (previous.tabs.has(tab) ? previous : { user: userId, tabs: new Set(previous.tabs).add(tab) }) : { user: userId, tabs: new Set([tab]) }), [userId, tab])
  const opened = visited.user === userId ? visited.tabs : new Set([tab])
  const [editing, setEditing] = useState(false)
  const [retry, setRetry] = useState(0)
  const [profile, setProfile] = useState<MemberProfileData | null>(null)
  const [codes, setCodes] = useState<MemberCodes | null>(null)
  const [codeSort, setCodeSort] = useState<CodeSort>('recent')
  const [notFound, setNotFound] = useState(false)
  const [items, setItems] = useState<ActivityItem[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!userId) return
    let alive = true
    setEditing(false); setProfile(null); setCodes(null); setNotFound(false); setError('')
    setItems([]); setCursor(null); setLoaded(false)
    getUserProfile(Number(userId))
      .then(data => {
        if (!alive) return
        setProfile(data)
        getMemberCodes(Number(userId)).then(result => { if (alive) setCodes(result) }).catch(() => undefined)
        return getUserActivity(Number(userId), { limit: PAGE_SIZE })
      })
      .then(page => {
        if (!alive || !page) return
        setItems(page.items); setCursor(page.next_before); setLoaded(true)
      })
      .catch((err: Error & { status?: number }) => {
        if (!alive) return
        if (err.status === 404) setNotFound(true)
        else setError(t('profile.errorLoad'))
        setLoaded(true)
      })
    return () => { alive = false }
  }, [userId, t, retry])

  const loadOlder = () => {
    if (!cursor || loadingMore || !userId) return
    setLoadingMore(true)
    getUserActivity(Number(userId), { before: cursor, limit: PAGE_SIZE })
      .then(page => { setItems(previous => [...previous, ...page.items]); setCursor(page.next_before) })
      .catch(() => setError(t('account.activity.errorLoad')))
      .finally(() => setLoadingMore(false))
  }

  const analysable = useMemo<CodeSummary[]>(() => (codes?.codes ?? []).filter(code => code.analytics), [codes])
  const weeks = codes?.activity?.weeks ?? []
  const weekMax = Math.max(1, ...weeks.map(week => week.attempt_count))

  if (notFound) return <div className="ca cm-profile"><div className="ca-note">{t('profile.notFoundTitle')} <Link className="ca-btn" to="/community">{t('community.back')}</Link></div></div>
  if (!profile) {
    if (error) return <p role="alert" className="cm-alert">{error} <button type="button" onClick={() => setRetry(value => value + 1)}>{t('common.retry')}</button></p>
    return <PageLoading />
  }

  // A diver binding that only repeats the member's own name adds nothing.
  const own = new Set([profile.display_name, profile.handle ?? ''].map(value => value.trim().toLowerCase()))
  const otherDivers = profile.divers.filter(diver => !own.has(diver.display_name.trim().toLowerCase()))
  const diverId = profile.is_self ? undefined : profile.divers[0]?.diver_id
  const totals = codes?.totals
  const last = totals?.last_attempt_at ? shortAgo(totals.last_attempt_at, t) : null

  return <div className="ca cm-profile ca-arrive">
    <div className="cm-head">
      <button type="button" className="ca-back" onClick={() => location.key !== 'default' ? navigate(-1) : navigate('/community')}><ArrowLeft className="h-4 w-4" aria-hidden="true" />{t('community.back')}</button>
      <span className="cm-head-fill" />
      <MobileShellActions />
    </div>

    <header className="cm-hero">
      <MemberAvatar member={profile} size={96} />
      <div style={{ minWidth: 0 }}>
        <h1>{profile.display_name}</h1>
        {profile.handle && <p className="cm-hero-handle">@{profile.handle}</p>}
        <div className="cm-facts">
          {profile.joined_at && <span className="ca-fact">{t('profile.memberSince', { date: format(parseISO(profile.joined_at), 'MMMM yyyy', { locale: appLocale() }) })}</span>}
          {otherDivers.length > 0 && <span className="ca-fact">{t('profile.diverOf')} {otherDivers.map(diver => diver.display_name === diver.display_name.toUpperCase() ? diver.display_name.toLowerCase().replace(/(^|[\s'-])\p{L}/gu, letter => letter.toUpperCase()) : diver.display_name).join(', ')}</span>}
        </div>
      </div>
      {profile.bio && <p className="cm-hero-bio">{profile.bio}</p>}
      <div className="cm-actions">
        {profile.is_self
          ? <>
              <button type="button" className="cm-btn" onClick={() => setEditing(value => !value)} aria-expanded={editing}><Pencil size={16} aria-hidden="true" />{t('community.edit')}</button>
              <Link to="/series" className="cm-btn"><Layers size={16} aria-hidden="true" />{t('series.mySeries')}</Link>
            </>
          : <ProfileMessageButton userId={profile.user_id} className="cm-btn is-primary" />}
      </div>
    </header>
    {editing && <ProfileEditor profile={profile} onChange={identity => setProfile(previous => previous ? { ...previous, ...identity } : previous)} onClose={() => setEditing(false)} />}

    {totals && totals.attempt_count > 0 && <section className="ca-panel" aria-label={t('profile.stats')}>
      <dl className="ca-kpis" style={{ margin: 0 }}>
        <div className="ca-kpi"><dt>{t('profile.kpi.dives')}</dt><dd><CountUp value={totals.attempt_count} digits={0} /></dd></div>
        <div className="ca-kpi"><dt>{t('profile.kpi.codes')}</dt><dd><CountUp value={codes!.codes.length} digits={0} /></dd></div>
        <div className="ca-kpi"><dt>{t('profile.kpi.sessions')}</dt><dd><CountUp value={totals.session_count} digits={0} /></dd></div>
        <div className="ca-kpi"><dt>{t('profile.kpi.last')}</dt><dd>{last ? <><CountUp value={last.count} digits={0} /><small className="ca-kpi-unit">{last.unit}</small></> : '—'}</dd></div>
      </dl>
      {weeks.length > 0 && <>
        <div className="cm-weeks" aria-label={t('profile.weeksAria', { count: weeks.length })}>
          {weeks.map((week, index) => <i key={week.start} className={week.attempt_count ? '' : 'is-empty'} title={`${week.start} · ${week.attempt_count}`}
            style={{ height: `${Math.max(4, (week.attempt_count / weekMax) * 100)}%`, '--i': index } as CSSProperties} />)}
        </div>
        <div className="cm-weeks-legend"><span>{format(parseISO(weeks[0].start), 'MMM yy', { locale: appLocale() })}</span><span>{t('profile.thisWeek')}</span></div>
      </>}
    </section>}

    <Segmented label={t('community.profileSections')} value={tab} onChange={setTab}
      options={PROFILE_TABS.map(value => [value, t(`community.${value}`)] as const)} />

    {PROFILE_TABS.filter(key => key === tab || opened.has(key)).map(key => <div key={key} className="cm-tabpanel" role="tabpanel" aria-label={t(`community.${key}`)} hidden={key !== tab}>
      {key === 'dives' && <ProfileDiveGrid key={profile.user_id} userId={profile.user_id} />}
      {key === 'codes' && (codes === null ? <div className="ca-skeleton" style={{ height: 240 }} />
        : analysable.length ? <CodeCards codes={analysable} sort={codeSort} onSort={setCodeSort} diverId={diverId}
            onOpenClip={id => navigate(`/dives?clip=${id}&scope=all`)} />
        : <p className="cm-empty">{t('community.noDives')}</p>)}
      {key === 'activity' && <section className="ca-panel">
        {error && items.length === 0 ? <p role="alert" className="cm-alert">{error}</p>
          : !loaded && items.length === 0 ? <PageLoading message={t('account.activity.loading')} />
          : items.length === 0 ? <p className="cm-empty">{t('profile.emptyActivity')}</p>
          : <>
              <ActivityTimeline items={items} />
              {cursor && <button type="button" className="ca-pill cm-more" onClick={loadOlder} disabled={loadingMore}>{loadingMore ? t('account.activity.loading') : t('account.activity.loadOlder')}</button>}
            </>}
      </section>}
      {key === 'achievements' && <section className="ca-panel"><AchievementsPanel key={profile.user_id} userId={profile.user_id} isSelf={profile.is_self} /></section>}
    </div>)}
  </div>
}
