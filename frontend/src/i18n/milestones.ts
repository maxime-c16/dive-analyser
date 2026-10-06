/**
 * Milestones arrive from the backend with English `title`/`narrative` text
 * plus structured context (type, dive_code, height, counters). Rather than
 * persisting per-locale server text, we reconstruct localized equivalents
 * from the structure; English keeps the backend copy. Keys map to the
 * milestone families in backend/app/services/milestones.py.
 *
 * Some sources (sync WebSocket events) carry only type/title/narrative —
 * no dive_code, height or counters. A reconstruction without its context
 * would lie with zero values, so those fall back to the backend text.
 */
import i18n from './index'
import { diveCodeName } from './diveNames'

export type MilestoneLike = {
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

/** Types whose reconstruction reads a numeric counter or day gap. */
const COUNTER_TYPES = new Set([
  'first_attempt', 'first_success', 'first_perfect', 'first_from_height',
  'breakthrough', 'redemption', 'comeback', 'avoided_dive_attempted',
  'success_streak', 'perfect_streak', 'consistency_achieved',
  'new_height_conquered', 'training_streak', 'personal_best',
])

type Interpolated = {
  code: string
  height: string
  name: string
  /** Code followed by its localized name, e.g. `101B (plongeon en avant carpé)`. */
  codeLabel: string
  attempts: number
  failures: number
  days: number
  streak: number
}

function interpolate(milestone: MilestoneLike): Interpolated {
  const code = milestone.dive_code || ''
  const name = code ? diveCodeName(code, i18n.language as 'en' | 'fr') : ''
  // diveCodeName returns the raw code for unrecognized codes: don't repeat it.
  const named = name && name !== code.trim().toUpperCase() && name !== code
  return {
    code,
    height: milestone.height || '',
    name,
    codeLabel: named ? `${code} (${name.charAt(0).toLocaleLowerCase(i18n.language)}${name.slice(1)})` : code,
    attempts: milestone.attempts_before ?? 0,
    failures: milestone.failures_before ?? 0,
    days: milestone.days_since_last ?? 0,
    streak: milestone.streak_length ?? 0,
  }
}

/**
 * True when the payload carries the context the reconstruction needs:
 * a dive code and — for count-bearing types — at least one counter field.
 */
function hasReconstructionContext(milestone: MilestoneLike): boolean {
  if (!milestone.dive_code && !milestone.height) return false
  if (COUNTER_TYPES.has(milestone.type)) {
    return milestone.attempts_before != null || milestone.failures_before != null ||
      milestone.days_since_last != null || milestone.streak_length != null
  }
  return true
}

function titleFor(milestone: MilestoneLike, values: Interpolated): string {
  return i18n.t(`milestones.${milestone.type}.title`, {
    defaultValue: '',
    ...values,
  })
}

function narrativeFor(milestone: MilestoneLike, values: Interpolated): string {
  const base = i18n.t(`milestones.${milestone.type}.narrative`, {
    defaultValue: '',
    ...values,
  })

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
  return `${base}${tail}`.trim()
}

type MilestoneDisplay = { title: string; narrative: string }

/**
 * Localized title + narrative when running in French and the payload
 * carries enough context; otherwise the backend English copy stands.
 */
export function milestoneDisplay(milestone: MilestoneLike): MilestoneDisplay {
  if (i18n.language === 'fr' && hasReconstructionContext(milestone)) {
    const values = interpolate(milestone)
    const title = titleFor(milestone, values)
    const narrative = narrativeFor(milestone, values)
    if (title && narrative) return { title, narrative }
  }
  return { title: milestone.title, narrative: milestone.narrative }
}
