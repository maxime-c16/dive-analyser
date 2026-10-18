import { useEffect, useState } from 'react'
import { Link, useLocation, useParams, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { CalendarDays, ChevronLeft, Pencil } from 'lucide-react'
import {
  getUserProfile,
  getUserActivity,
  type MemberProfile as MemberProfileData,
  type ActivityItem,
} from '../services/activityApi'
import { activityIcon } from '../components/activity/ActivityFeed'
import MemberLink from '../components/activity/MemberLink'
import MemberAvatar from '../components/MemberAvatar'
import ProfileDiveGrid from '../components/ProfileDiveGrid'
import ProfileMessageButton from '../components/messages/ProfileMessageButton'
import ProfileEditor from '../components/ProfileEditor'
import AchievementsPanel from '../components/achievements/AchievementsPanel'
import { appLanguage } from '../utils/dateLocale'

const PAGE_SIZE = 30
const PROFILE_TABS = ['dives', 'activity', 'achievements'] as const
type ProfileTab = (typeof PROFILE_TABS)[number]

// On another member's profile every row is their action: always show the
// member's name with a third-person phrase.
function ActorPhrase({ item }: { item: ActivityItem }) {
  const { t } = useTranslation()
  const nameNode = item.actor.user_id
    ? <MemberLink userId={item.actor.user_id} className="font-semibold text-app-accent hover:underline">{item.actor.display_name}</MemberLink>
    : <span className="font-semibold">{item.actor.display_name}</span>
  return <>{nameNode} {t(`profile.trail.${item.kind}`)}</>
}

function ClipLink({ item }: { item: ActivityItem }) {
  return (
    // scope=all: the library defaults admins to their own bindings, which
    // would silently discard clips the interaction points at.
    <Link to={`/dives?clip=${item.dive.id}&scope=all`} className="text-app-muted underline underline-offset-2 hover:text-app-accent">
      {item.dive.dive_code}{item.dive.height ? ` · ${item.dive.height}` : ''}
      {item.dive.diver_name ? ` · ${item.dive.diver_name}` : ''}
    </Link>
  )
}

function ProfileHead({ profile, editing, onEdit }: { profile: MemberProfileData; editing: boolean; onEdit: () => void }) {
  const { t } = useTranslation()
  // A diver binding that only repeats the member's own name adds nothing.
  const own = new Set([profile.display_name, profile.handle ?? ''].map(value => value.trim().toLowerCase()))
  const otherDivers = profile.divers.filter(diver => !own.has(diver.display_name.trim().toLowerCase()))
  return (
    <header className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-3 border-b border-app pb-4">
      <MemberAvatar member={profile} large />
      <div className="min-w-0 flex-1 basis-56">
        <h1 className="truncate text-2xl font-semibold tracking-tight text-app-text">{profile.display_name}</h1>
        {profile.handle && <p className="mt-0.5 text-sm text-app-accent">@{profile.handle}</p>}
        {profile.bio && <p className="mt-2 max-w-xl whitespace-pre-wrap break-words text-sm text-app-text">{profile.bio}</p>}
        <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-app-muted">
          {profile.joined_at && (
            <span className="inline-flex items-center gap-1.5">
              <CalendarDays className="h-3.5 w-3.5" aria-hidden />
              <time dateTime={profile.joined_at}>{t('profile.memberSince', { date: new Date(profile.joined_at).toLocaleDateString(appLanguage(), { year: 'numeric', month: 'long' }) })}</time>
            </span>
          )}
          {otherDivers.length > 0 && <span>{t('profile.diverOf')} {otherDivers.map(diver => diver.display_name).join(', ')}</span>}
        </p>
      </div>
      <div className="flex shrink-0 items-start">
        {profile.is_self
          ? <button type="button" className="touch-target inline-flex items-center justify-center gap-2 whitespace-nowrap border border-app bg-app-panel px-4 text-sm font-medium text-app-text hover:border-app-strong" onClick={onEdit} aria-expanded={editing}><Pencil className="h-4 w-4" aria-hidden />{t('community.edit')}</button>
          : <ProfileMessageButton userId={profile.user_id} />}
      </div>
    </header>
  )
}

/** Vertical timeline: one rail, day headings, per-event times. */
function ActivityTimeline({ items }: { items: ActivityItem[] }) {
  const { t } = useTranslation()
  const language = appLanguage()
  const groups = new Map<string, ActivityItem[]>()
  for (const item of items) {
    const stamp = item.created_at ? new Date(item.created_at) : null
    const dayKey = stamp ? stamp.toDateString() : '—'
    groups.set(dayKey, [...(groups.get(dayKey) ?? []), item])
  }
  const dayLabel = (dayKey: string) => {
    if (dayKey === '—') return ''
    const today = new Date().toDateString()
    if (dayKey === today) return t('profile.today')
    const yesterday = new Date(Date.now() - 86400000).toDateString()
    if (dayKey === yesterday) return t('profile.yesterday')
    return new Date(dayKey).toLocaleDateString(language, { weekday: 'long', day: 'numeric', month: 'long' })
  }
  const clock = (item: ActivityItem) =>
    item.created_at
      ? new Date(item.created_at).toLocaleTimeString(language, { hour: '2-digit', minute: '2-digit' })
      : ''

  return (
    /* Rail geometry: every node (day dot, event icon) is centered on the
       x=8px rail through the same translate-x-1/2 helper, so alignment
       cannot drift between nodes. */
    <ol className="relative">
      {[...groups.entries()].map(([day, rows]) => (
        <li key={day} className="relative pb-8 last:pb-0">
          <span aria-hidden className="absolute left-[8px] top-3 bottom-0 w-px -translate-x-1/2 bg-[var(--app-border)]" />
          <span
            aria-hidden
            className="absolute left-[8px] top-0 z-10 h-4 w-4 -translate-x-1/2 rounded-full border-2 border-app-panel bg-app-accent"
          />
          <p className="pl-10 text-xs font-semibold uppercase tracking-[0.14em] text-app-muted">
            {dayLabel(day)}
          </p>
          <ul className="mt-3 space-y-5 pl-10">
            {rows.map(item => {
              const Icon = activityIcon(item)
              return (
                <li key={item.key} className="relative flex items-start gap-3">
                  <span
                    aria-hidden
                    className="absolute left-[-42px] top-[3px] z-10 flex h-5 w-5 items-center justify-center rounded-full border border-app bg-app-panel text-app-muted"
                  >
                    <Icon className="h-3 w-3" />
                  </span>
                  <span
                    aria-hidden
                    className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-app-panel-elevated text-sm font-bold text-app-accent ring-1 ring-app"
                  >
                    {item.actor.display_name.trim()[0]?.toUpperCase() ?? '?'}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm leading-6 text-app-text">
                      <ActorPhrase item={item} />{' '}
                      <ClipLink item={item} />
                    </p>
                    {item.comment?.body && (
                      <p className="mt-1 border-l-2 border-app-accent/50 pl-3 text-sm leading-6 text-app-muted">
                        {item.comment.body}
                      </p>
                    )}
                  </div>
                  <time dateTime={item.created_at ?? undefined} className="shrink-0 pt-1 text-xs text-app-muted">
                    {clock(item)}
                  </time>
                </li>
              )
            })}
          </ul>
        </li>
      ))}
    </ol>
  )
}

export default function MemberProfile() {
  const { userId } = useParams()
  const { t } = useTranslation()
  const [searchParams] = useSearchParams()
  const location = useLocation()
  const requestedTab = PROFILE_TABS.find(value => value === searchParams.get('tab')) ?? 'dives'
  const [tab, setTab] = useState<ProfileTab>(requestedTab)
  // Following a ?tab= link while already on this profile (e.g. the unlock
  // toast) must open that tab; location.key changes on every navigation.
  const tabParam = searchParams.get('tab')
  useEffect(() => {
    const next = PROFILE_TABS.find(value => value === tabParam)
    if (next) setTab(next)
  }, [tabParam, location.key])
  const [editing, setEditing] = useState(false)
  const [retry, setRetry] = useState(0)
  const [profile, setProfile] = useState<MemberProfileData | null>(null)
  const [notFound, setNotFound] = useState(false)
  const [items, setItems] = useState<ActivityItem[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!userId) return
    let alive = true
    setTab(requestedTab)
    setEditing(false)
    setProfile(null)
    setNotFound(false)
    setError('')
    setItems([])
    setCursor(null)
    setLoaded(false)
    getUserProfile(Number(userId))
      .then(data => {
        if (!alive) return
        setProfile(data)
        return getUserActivity(Number(userId), { limit: PAGE_SIZE })
      })
      .then(page => {
        if (!alive || !page) return
        setItems(page.items)
        setCursor(page.next_before)
        setLoaded(true)
      })
      .catch((err: Error & { status?: number }) => {
        if (!alive) return
        if (err.status === 404) setNotFound(true)
        else setError(t('profile.errorLoad'))
        setLoaded(true)
      })
    return () => {
      alive = false
    }
  }, [userId, t, retry])

  const loadOlder = () => {
    if (!cursor || loadingMore || !userId) return
    setLoadingMore(true)
    getUserActivity(Number(userId), { before: cursor, limit: PAGE_SIZE })
      .then(page => {
        setItems(previous => [...previous, ...page.items])
        setCursor(page.next_before)
      })
      .catch(() => setError(t('account.activity.errorLoad')))
      .finally(() => setLoadingMore(false))
  }

  if (notFound) {
    return (
      <div className="mx-auto mt-10 max-w-lg py-10 text-center">
        <h1 className="text-2xl font-semibold text-app-text">{t('profile.notFoundTitle')}</h1>
        <Link to="/dives" className="touch-target mt-6 inline-flex items-center gap-2 border border-app-accent bg-app-panel px-4 text-sm text-app-accent">
          {t('notFound.backToLibrary')}
        </Link>
      </div>
    )
  }
  if (!profile) {
    if (error) return <p role="alert" className="py-8 text-sm text-red-400">{error} <button onClick={() => setRetry(value => value + 1)} className="underline">{t('common.retry')}</button></p>
    return <p role="status" className="py-8 text-sm text-app-muted">{t('common.loadingPage')}</p>
  }

  return (
    <div className="mx-auto max-w-4xl">
      <Link to="/community" className="touch-target mb-1 inline-flex items-center gap-1 text-sm text-app-accent hover:underline"><ChevronLeft className="h-4 w-4" aria-hidden />{t('community.back')}</Link>
      <ProfileHead profile={profile} editing={editing} onEdit={() => setEditing(value => !value)} />
      {editing && <ProfileEditor profile={profile} onChange={identity => setProfile(previous => previous ? { ...previous, ...identity } : previous)} onClose={() => setEditing(false)} />}
      <div className="mb-5 flex border-b border-app" role="tablist" aria-label={t('community.profileSections')}>
        {PROFILE_TABS.map(value => <button key={value} role="tab" id={`profile-tab-${value}`} aria-selected={tab === value} tabIndex={tab === value ? 0 : -1} onKeyDown={event => {
          if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
          event.preventDefault()
          const index = PROFILE_TABS.indexOf(value)
          const next = event.key === 'Home' ? PROFILE_TABS[0]
            : event.key === 'End' ? PROFILE_TABS[PROFILE_TABS.length - 1]
            : PROFILE_TABS[(index + (event.key === 'ArrowRight' ? 1 : -1) + PROFILE_TABS.length) % PROFILE_TABS.length]
          setTab(next)
          document.getElementById(`profile-tab-${next}`)?.focus()
        }} aria-controls={`profile-panel-${value}`} className={`touch-target flex-1 border-b-2 px-4 ${tab === value ? 'border-app-accent text-app-accent' : 'border-transparent text-app-muted'}`} onClick={() => setTab(value)}>{t(`community.${value}`)}</button>)}
      </div>
      {tab === 'dives' && <div role="tabpanel" id="profile-panel-dives" aria-labelledby="profile-tab-dives"><ProfileDiveGrid key={profile.user_id} userId={profile.user_id} /></div>}
      {tab === 'achievements' && (
        <div role="tabpanel" id="profile-panel-achievements" aria-labelledby="profile-tab-achievements" className="border border-app bg-app-panel p-4 sm:p-6">
          <AchievementsPanel key={profile.user_id} userId={profile.user_id} isSelf={profile.is_self} />
        </div>
      )}
      <div hidden={tab !== 'activity'} role="tabpanel" id="profile-panel-activity" aria-labelledby="profile-tab-activity">
      <div className="border border-app bg-app-panel p-4 sm:p-6">
        {error && items.length === 0 ? (
          <p role="alert" className="text-sm text-red-400">{error}</p>
        ) : !loaded && items.length === 0 ? (
          <p role="status" className="text-sm text-app-muted">{t('account.activity.loading')}</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-app-muted">{t('profile.emptyActivity')}</p>
        ) : (
          <>
            <ActivityTimeline items={items} />
            {cursor && (
              <button
                type="button"
                onClick={loadOlder}
                disabled={loadingMore}
                className="touch-target mt-5 border border-app bg-app-panel-elevated px-4 py-2 text-sm font-medium text-app-text disabled:opacity-60"
              >
                {loadingMore ? t('account.activity.loading') : t('account.activity.loadOlder')}
              </button>
            )}
          </>
        )}
      </div>
      </div>
    </div>
  )
}
