import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { X } from 'lucide-react'
import { useAuth } from '../../contexts/AuthContext'
import {
  ACHIEVEMENTS_CHECK_EVENT,
  getUnseenAchievements,
  markAchievementsSeen,
} from '../../services/achievementsApi'
import { achievementIcon, isKnownAchievement } from './achievementCatalog'

const VISIBLE_MS = 7000
const GROUP_SIZE = 3

function videoPlaying(): boolean {
  try {
    return Array.from(document.querySelectorAll('video')).some(video => !video.paused)
  } catch {
    return false
  }
}

/**
 * Celebrates unlocks with a transient toast. Unlocks are recorded server-side
 * by the member's own actions (and by other members' likes/comments on their
 * dives), so this only asks the server what is still unseen: on load, on
 * focus, every minute, and shortly after any successful write (see
 * installAchievementProbe). Keys are marked seen as soon as they are queued so
 * a reload or a second tab never replays them. Scheduled polls skip a tick
 * while a clip plays, like the notification badge.
 */
export default function AchievementToaster() {
  const { user } = useAuth()
  return user ? <AccountToaster key={user.user_id} userId={user.user_id} /> : null
}

function AccountToaster({ userId }: { userId: number }) {
  const { t } = useTranslation()
  const [queue, setQueue] = useState<string[]>([])
  const [current, setCurrent] = useState<string[] | null>(null)
  const queued = useRef(new Set<string>())

  const check = useCallback(async (scheduled: boolean) => {
    if (scheduled && (document.visibilityState === 'hidden' || videoPlaying())) return
    try {
      const { items } = await getUnseenAchievements()
      const keys = items.map(item => item.key).filter(key => isKnownAchievement(key) && !queued.current.has(key))
      if (!keys.length) return
      keys.forEach(key => queued.current.add(key))
      setQueue(previous => [...previous, ...keys])
      await markAchievementsSeen(keys)
    } catch {
      // Celebration is best-effort: stay quiet and retry on the next trigger.
    }
  }, [])

  useEffect(() => {
    void check(true)
    const scheduled = () => void check(true)
    const requested = () => void check(false)
    const timer = window.setInterval(scheduled, 60_000)
    window.addEventListener('focus', scheduled)
    window.addEventListener(ACHIEVEMENTS_CHECK_EVENT, requested)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('focus', scheduled)
      window.removeEventListener(ACHIEVEMENTS_CHECK_EVENT, requested)
    }
  }, [check])

  useEffect(() => {
    if (current || queue.length === 0) return
    setCurrent(queue.slice(0, GROUP_SIZE))
    setQueue(queue.slice(GROUP_SIZE))
  }, [current, queue])

  useEffect(() => {
    if (!current) return
    const timer = window.setTimeout(() => setCurrent(null), VISIBLE_MS)
    return () => window.clearTimeout(timer)
  }, [current])

  if (!current) return null
  const single = current.length === 1
  const Icon = achievementIcon(current[0])
  return (
    <div className="pointer-events-none fixed bottom-20 right-4 z-50 md:bottom-6 md:right-6">
      <div role="status" aria-live="polite" className="pointer-events-auto flex w-[min(22rem,calc(100vw-2rem))] items-start gap-3 border border-app-accent bg-app-panel p-4 shadow-lg">
        <span aria-hidden className="flex h-10 w-10 shrink-0 items-center justify-center bg-app-accent-soft text-app-accent">
          <Icon className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-app-accent">
            {single ? t('achievements.unlocked') : t('achievements.unlockedMany', { count: current.length })}
          </p>
          {single ? (
            <>
              <p className="mt-1 text-sm font-semibold text-app-text">{t(`achievements.items.${current[0]}.title`)}</p>
              <p className="mt-0.5 text-sm text-app-muted">{t(`achievements.items.${current[0]}.description`)}</p>
            </>
          ) : (
            <ul className="mt-1 space-y-0.5 text-sm text-app-text">
              {current.map(key => <li key={key} className="font-semibold">{t(`achievements.items.${key}.title`)}</li>)}
            </ul>
          )}
          <Link to={`/users/${userId}?tab=achievements`} onClick={() => setCurrent(null)} className="mt-2 inline-block text-sm text-app-accent hover:underline">
            {t('achievements.view')}
          </Link>
        </div>
        <button type="button" onClick={() => setCurrent(null)} aria-label={t('achievements.dismiss')} className="touch-target -m-2 flex items-center justify-center p-2 text-app-muted hover:text-app-text">
          <X className="h-4 w-4" aria-hidden />
        </button>
      </div>
    </div>
  )
}
