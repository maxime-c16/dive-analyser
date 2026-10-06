import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Heart, MessageSquare, ThumbsUp, Film } from 'lucide-react'
import { ActivityItem } from '../../services/activityApi'
import { appLanguage } from '../../utils/dateLocale'
import MemberLink from './MemberLink'

export function activityIcon(item: ActivityItem) {
  if (item.kind === 'comment') return MessageSquare
  if (item.kind === 'comment_like') return ThumbsUp
  return Heart
}

function relativeDate(value: string | null, language: string): string {
  if (!value) return ''
  const date = new Date(value)
  const diff = Date.now() - date.getTime()
  const day = 24 * 60 * 60 * 1000
  if (diff >= 0 && diff < day) {
    return new Intl.RelativeTimeFormat(language, { numeric: 'auto' }).format(-Math.round(diff / (60 * 60 * 1000)), 'hour')
  }
  return date.toLocaleDateString(language)
}

function Avatar({ name }: { name: string }) {
  const letter = (name.trim()[0] || '?').toUpperCase()
  return (
    <span
      aria-hidden
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-app-panel-elevated text-sm font-bold text-app-accent ring-1 ring-app"
    >
      {letter}
    </span>
  )
}

/**
 * One merged-feed row. The actor name links to their profile only for
 * account holders — guests stay plain text by design.
 */
export function ActivityRow({ item, condensed = false }: { item: ActivityItem; condensed?: boolean }) {
  const { t } = useTranslation()
  const language = appLanguage()
  const Icon = activityIcon(item)
  // scope=all: the library defaults admins to their own bindings, which would
  // silently discard clips the interaction points at.
  const clipHref = `/dives?clip=${item.dive.id}&scope=all`
  const actorNode = item.actor.user_id
    ? <MemberLink userId={item.actor.user_id} className="font-semibold text-app-accent hover:underline">{item.actor.display_name}</MemberLink>
    : <span className="font-semibold text-app-text">{item.actor.display_name}</span>

  const phrase = item.direction === 'received'
    ? t(`account.activity.trail.${item.direction}.${item.kind}`)
    : t(`account.activity.trail.${item.direction}.${item.kind}`)

  return (
    <li className="flex items-start gap-3 py-3">
      <span aria-hidden className="mt-5 flex h-7 w-7 shrink-0 items-center justify-center border border-app bg-app-panel-elevated text-app-muted">
        <Icon className="h-3.5 w-3.5" />
      </span>
      <Avatar name={item.actor.display_name} />
      <div className="min-w-0 flex-1">
        <p className="text-sm leading-6 text-app-text">
          {item.direction === 'received' ? <>{actorNode} {phrase}</> : <>{phrase}</>}
          {item.dive && (
            <>
              {' '}
              <Link to={clipHref} className="inline-flex items-center gap-1 text-app-muted underline underline-offset-2 hover:text-app-accent">
                <Film className="h-3.5 w-3.5" aria-hidden />
                {item.dive.dive_code}{item.dive.height ? ` · ${item.dive.height}` : ''}
                {item.dive.diver_name ? ` · ${item.dive.diver_name}` : ''}
              </Link>
            </>
          )}
          <time dateTime={item.created_at ?? undefined} className="ml-2 text-xs text-app-muted">
            {relativeDate(item.created_at, language)}
          </time>
        </p>
        {item.comment?.body && !condensed && (
          <p className="mt-0.5 border-l-2 border-app pl-2 text-sm text-app-muted line-clamp-2">{item.comment.body}</p>
        )}
      </div>
    </li>
  )
}

export function ActivityList({
  items,
  error,
  hasMore,
  loadingMore,
  onLoadMore,
  condensed = false,
  emptyKey = 'account.activity.empty',
}: {
  items: ActivityItem[]
  error: string
  hasMore: boolean
  loadingMore: boolean
  onLoadMore: () => void
  condensed?: boolean
  emptyKey?: string
}) {
  const { t } = useTranslation()
  if (error) {
    return <p role="alert" className="text-sm text-red-400">{error}</p>
  }
  if (items.length === 0) {
    return <p className="text-sm text-app-muted">{t(emptyKey)}</p>
  }
  return (
    <>
      <ul className="divide-y divide-[var(--app-border)]">
        {items.map(item => <ActivityRow key={item.key} item={item} condensed={condensed} />)}
      </ul>
      {hasMore && (
        <button
          type="button"
          onClick={onLoadMore}
          disabled={loadingMore}
          className="touch-target mt-3 border border-app bg-app-panel-elevated px-4 py-2 text-sm font-medium text-app-text disabled:opacity-60"
        >
          {loadingMore ? t('account.activity.loading') : t('account.activity.loadOlder')}
        </button>
      )}
    </>
  )
}
