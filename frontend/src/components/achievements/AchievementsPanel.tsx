import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Lock } from 'lucide-react'
import {
  getMemberAchievements,
  getMyAchievements,
  markAchievementsSeen,
  type AchievementCategory,
} from '../../services/achievementsApi'
import { appLanguage } from '../../utils/dateLocale'
import PageLoading from '../PageLoading'
import { ACHIEVEMENT_CATEGORIES, achievementIcon, isKnownAchievement } from './achievementCatalog'

type Card = {
  key: string
  category: AchievementCategory
  unlocked: boolean
  unlockedAt: string | null
  target: number
  progress: number
}

/**
 * Own profile: the whole catalogue, locked entries greyed with progress.
 * Someone else's profile: only what they unlocked (locked entries and
 * progress stay private).
 */
export default function AchievementsPanel({ userId, isSelf }: { userId: number; isSelf: boolean }) {
  const { t } = useTranslation()
  const [cards, setCards] = useState<Card[] | null>(null)
  const [total, setTotal] = useState(0)
  const [error, setError] = useState(false)
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    let alive = true
    setCards(null)
    setError(false)
    const load = isSelf
      ? getMyAchievements().then(data => {
          // Opening the list counts as seeing every unlock.
          if (data.items.some(item => item.unlocked && !item.seen)) void markAchievementsSeen().catch(() => {})
          return {
            total: data.total,
            cards: data.items.map(item => ({
              key: item.key, category: item.category, unlocked: item.unlocked, unlockedAt: item.unlocked_at,
              target: item.target, progress: item.progress,
            })),
          }
        })
      : getMemberAchievements(userId).then(data => ({
          total: data.total,
          cards: data.items.map(item => ({
            key: item.key, category: item.category, unlocked: true, unlockedAt: item.unlocked_at, target: 1, progress: 1,
          })),
        }))
    load
      .then(result => {
        if (!alive) return
        setCards(result.cards.filter(card => isKnownAchievement(card.key)))
        setTotal(result.total)
      })
      .catch(() => alive && setError(true))
    return () => {
      alive = false
    }
  }, [userId, isSelf, retry])

  const grouped = useMemo(
    () => ACHIEVEMENT_CATEGORIES
      .map(category => ({ category, items: (cards ?? []).filter(card => card.category === category) }))
      .filter(group => group.items.length > 0),
    [cards],
  )

  if (error) {
    return (
      <p role="alert" className="text-sm text-red-400">
        {t('achievements.errorLoad')}{' '}
        <button type="button" onClick={() => setRetry(value => value + 1)} className="underline">{t('common.retry')}</button>
      </p>
    )
  }
  if (!cards) return <PageLoading message={t('achievements.loading')} />

  const unlockedCount = cards.filter(card => card.unlocked).length
  if (!isSelf && unlockedCount === 0) return <p className="text-sm text-app-muted">{t('achievements.emptyOther')}</p>

  const language = appLanguage()
  return (
    <div>
      <p className="mb-4 text-sm text-app-muted" data-testid="achievements-summary">
        {t('achievements.summary', { unlocked: unlockedCount, total })}
      </p>
      <div className="space-y-6">
        {grouped.map(group => (
          <section key={group.category} aria-labelledby={`achievements-${group.category}`}>
            <h3 id={`achievements-${group.category}`} className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-app-muted">
              {t(`achievements.categories.${group.category}`)}
            </h3>
            <ul className="grid gap-3 sm:grid-cols-2">
              {group.items.map(card => {
                const Icon = card.unlocked ? achievementIcon(card.key) : Lock
                const title = t(`achievements.items.${card.key}.title`)
                return (
                  <li key={card.key} data-unlocked={card.unlocked} className={`flex items-start gap-3 border p-3 ${card.unlocked ? 'border-app-accent bg-app-panel' : 'border-app bg-app-panel opacity-60'}`}>
                    <span aria-hidden className={`flex h-10 w-10 shrink-0 items-center justify-center ${card.unlocked ? 'bg-app-accent-soft text-app-accent' : 'bg-app-panel-elevated text-app-muted'}`}>
                      <Icon className="h-5 w-5" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-semibold text-app-text">
                        {title}
                        {!card.unlocked && <span className="sr-only"> — {t('achievements.locked')}</span>}
                      </p>
                      <p className="mt-0.5 text-sm text-app-muted">{t(`achievements.items.${card.key}.description`)}</p>
                      {card.unlocked && card.unlockedAt && (
                        <p className="mt-1 text-xs text-app-muted">
                          {t('achievements.unlockedOn', { date: new Date(card.unlockedAt).toLocaleDateString(language) })}
                        </p>
                      )}
                      {!card.unlocked && card.target > 1 && (
                        <div className="mt-2 flex items-center gap-2">
                          <progress className="h-1.5 flex-1" max={card.target} value={card.progress} aria-label={title} />
                          <span className="text-xs text-app-muted">{card.progress}/{card.target}</span>
                        </div>
                      )}
                    </div>
                  </li>
                )
              })}
            </ul>
          </section>
        ))}
      </div>
    </div>
  )
}
