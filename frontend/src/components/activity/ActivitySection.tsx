import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ActivityList } from './ActivityFeed'
import { getMyActivity, type ActivityItem, type ActivityPage } from '../../services/activityApi'
import PageLoading from '../PageLoading'

export type ActivityTab = 'all' | 'received' | 'sent'

const PAGE_SIZE = 30

/**
 * Personal activity history: interactions on my dives, and my own actions.
 * Cursor-paged ("load older"); switching tabs resets the feed.
 */
export function useMyActivity(tab: ActivityTab) {
  const [items, setItems] = useState<ActivityItem[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)

  useEffect(() => {
    let alive = true
    setItems([])
    setCursor(null)
    setLoaded(false)
    setBusy(true)
    setError(false)
    getMyActivity({ direction: tab, limit: PAGE_SIZE })
      .then((page: ActivityPage) => {
        if (!alive) return
        setItems(page.items)
        setCursor(page.next_before)
        setLoaded(true)
      })
      .catch(() => {
        if (alive) setError(true)
      })
      .finally(() => {
        if (alive) setBusy(false)
      })
    return () => {
      alive = false
    }
  }, [tab])

  const loadOlder = () => {
    if (!cursor || busy) return
    setBusy(true)
    getMyActivity({ direction: tab, before: cursor, limit: PAGE_SIZE })
      .then(page => {
        setItems(previous => [...previous, ...page.items])
        setCursor(page.next_before)
      })
      .catch(() => setError(true))
      .finally(() => setBusy(false))
  }

  return { items, loaded, busy, error, cursor, loadOlder }
}

export default function ActivitySection() {
  const { t } = useTranslation()
  const [tab, setTab] = useState<ActivityTab>('all')
  const { items, loaded, busy, error, cursor, loadOlder } = useMyActivity(tab)

  const tabs: { id: ActivityTab; labelKey: string }[] = [
    { id: 'all', labelKey: 'account.activity.tabs.all' },
    { id: 'received', labelKey: 'account.activity.tabs.received' },
    { id: 'sent', labelKey: 'account.activity.tabs.sent' },
  ]

  return (
    <section aria-label={t('account.activity.title')} className="border border-app bg-app-panel p-5">
      <h2 className="flex items-center gap-2 font-semibold text-app-text">{t('account.activity.title')}</h2>
      <p className="mt-1 text-sm text-app-muted">{t('account.activity.subtitle')}</p>

      <div className="mt-3 flex flex-wrap gap-2" role="radiogroup" aria-label={t('account.activity.tabsAria')}>
        {tabs.map(option => {
          const selected = tab === option.id
          return (
            <button
              key={option.id}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => setTab(option.id)}
              className={`touch-target border px-3 py-2 text-sm font-medium transition-colors ${
                selected
                  ? 'border-app-accent bg-app-accent/10 text-app-accent'
                  : 'border-app bg-app-panel-elevated text-app-muted hover:text-app-text'
              }`}
            >
              {t(option.labelKey)}
            </button>
          )
        })}
      </div>

      <div aria-live="polite" className="mt-3">
        {!loaded && !error ? (
          <PageLoading message={t('account.activity.loading')} />
        ) : (
          <ActivityList
            items={items}
            error={error ? t('account.activity.errorLoad') : ''}
            hasMore={!!cursor}
            loadingMore={busy}
            onLoadMore={loadOlder}
          />
        )}
      </div>
    </section>
  )
}
