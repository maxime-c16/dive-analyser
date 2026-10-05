/**
 * Milestones arrive from the backend with English `title`/`narrative` text
 * plus structured context (type, dive_code, height, counters). Rather than
 * persisting per-locale server text, we reconstruct localized equivalents
 * from the structure; English keeps the backend copy. Keys map to the
 * milestone families in backend/app/services/milestones.py.
 */
import i18n from './index'
import { type ResolvedLanguage } from './index'
import { diveCodeName } from './diveNames'

type MilestoneLike = {
  type: string
  dive_code?: string | null
  height?: string | null
  title: string
  narrative: string
  attempts_before?: number
  failures_before?: number
  days_since_last?: number
  streak_length?: number
}

type Interpolated = {
  code: string
  height: string
  name: string
  attempts: number
  failures: number
  days: number
  streak: number
}

function interpolate(milestone: MilestoneLike): Interpolated {
  return {
    code: milestone.dive_code || '',
    height: milestone.height || '',
    name: milestone.dive_code ? diveCodeName(milestone.dive_code, i18n.language as ResolvedLanguage) : '',
    attempts: milestone.attempts_before ?? 0,
    failures: milestone.failures_before ?? 0,
    days: milestone.days_since_last ?? 0,
    streak: milestone.streak_length ?? 0,
  }
}

function titleFor(milestone: MilestoneLike, values: Interpolated): string {
  const key = `milestones.${milestone.type}.title`
  return i18n.t(key, { defaultValue: '', interpolation: { prefix: '{', suffix: '}' } })
    .replace(/\{(\w+)\}/g, (_, name) => String((values as Record<string, unknown>)[name] ?? ''))
}

function narrativeFor(milestone: MilestoneLike, values: Interpolated): string {
  const base = i18n.t(`milestones.${milestone.type}.narrative`, {
    defaultValue: '',
    interpolation: { prefix: '{', suffix: '}' },
  }).replace(/\{(\w+)\}/g, (_, name) => String((values as Record<string, unknown>)[name] ?? ''))

  // Family-specific endnotes mirror the backend's conditional tails.
  let tail = ''
  if (milestone.type === 'first_success' && values.failures > 0) {
    tail = ' ' + i18n.t('milestones.afterFailures', { count: values.failures })
  }
  if (milestone.type === 'first_perfect') {
    tail = values.attempts === 0
      ? ' ' + i18n.t('milestones.firstTryPerfect')
      : ' ' + i18n.t('milestones.masteryAfter', { count: values.attempts })
  }
  if (milestone.type === 'redemption') {
    tail = values.days === 0
      ? ' ' + i18n.t('milestones.sameDay')
      : ' ' + i18n.t('milestones.daysLater', { count: values.days })
  }
  if (milestone.type === 'comeback') {
    tail = ''
  }
  if (milestone.type === 'avoided_dive_attempted') {
    tail = ''
  }
  return `${base}${tail}`.trim()
}

type MilestoneDisplay = { title: string; narrative: string }

/**
 * Localized title + narrative when running in French; otherwise the
 * backend English copy stands. Falls back to the backend text whenever the
 * milestone family has no reconstruction yet.
 */
export function milestoneDisplay(milestone: MilestoneLike): MilestoneDisplay {
  if (i18n.language === 'fr') {
    const values = interpolate(milestone)
    const title = titleFor(milestone, values)
    const narrative = narrativeFor(milestone, values)
    if (title && narrative) return { title, narrative }
  }
  return { title: milestone.title, narrative: milestone.narrative }
}
