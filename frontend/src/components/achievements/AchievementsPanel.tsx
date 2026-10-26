import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import './achievements.css'
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
import { ACHIEVEMENT_CATEGORIES, achievementArt, achievementIcon, isKnownAchievement } from './achievementCatalog'

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
  const share = total ? unlockedCount / total : 0
  return (
    <div className="ach">
      <div className="ach-summary" data-testid="achievements-summary">
        <span className="ach-ring" style={{ '--p': share } as CSSProperties} aria-hidden="true"><b>{unlockedCount}</b></span>
        <span>{t('achievements.summary', { unlocked: unlockedCount, total })}</span>
      </div>
      {grouped.map((group, groupIndex) => (
        <section key={group.category} aria-labelledby={`achievements-${group.category}`} className="ach-group">
          <h3 id={`achievements-${group.category}`}>{t(`achievements.categories.${group.category}`)}</h3>
          <ul className="ach-grid">
            {group.items.map((card, index) => {
              const title = t(`achievements.items.${card.key}.title`)
              const art = achievementArt(card.key)
              const Icon = achievementIcon(card.key)
              return (
                <li key={card.key} data-unlocked={card.unlocked} className={`ach-card${card.unlocked ? ' is-unlocked' : ''}`} style={{ '--i': groupIndex * 4 + index } as CSSProperties}>
                  <span className="ach-art" aria-hidden="true">
                    {art ? <>
                      <img src={art} alt="" loading="lazy" decoding="async" width={160} height={200} />
                      {card.unlocked && <span className="ach-sheen" style={{ WebkitMaskImage: `url(${art})`, maskImage: `url(${art})` }} />}
                    </> : <Icon className="h-8 w-8" />}
                    {!card.unlocked && <span className="ach-lock"><Lock size={14} /></span>}
                  </span>
                  <p className="ach-title">{title}{!card.unlocked && <span className="sr-only"> — {t('achievements.locked')}</span>}</p>
                  <p className="ach-desc">{t(`achievements.items.${card.key}.description`)}</p>
                  {card.unlocked && card.unlockedAt && <p className="ach-date">{new Date(card.unlockedAt).toLocaleDateString(language, { day: 'numeric', month: 'short', year: 'numeric' })}</p>}
                  {!card.unlocked && card.target > 1 && <span className="ach-progress" role="progressbar" aria-label={title} aria-valuemin={0} aria-valuemax={card.target} aria-valuenow={card.progress}>
                    <i style={{ width: `${Math.min(100, (card.progress / card.target) * 100)}%` }} /><small>{card.progress}/{card.target}</small>
                  </span>}
                </li>
              )
            })}
          </ul>
        </section>
      ))}
    </div>
  )
}
