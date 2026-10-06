import i18n from '../i18n'

/**
 * The API emits canonical identifiers: component keys (`same_dive_relative`),
 * `primary_signal` display names ("Same-dive result") and confidence levels
 * (`high`). Map them to localized labels at render time; unknown values pass
 * through unchanged.
 */
const SIGNAL_KEYS: Record<string, string> = {
  technical: 'technical',
  Technical: 'technical',
  same_dive_relative: 'sameDiveResult',
  'Same-dive result': 'sameDiveResult',
  breakthrough: 'breakthrough',
  Breakthrough: 'breakthrough',
  progression: 'progression',
  Progression: 'progression',
  consistency: 'consistency',
  Consistency: 'consistency',
  novelty: 'novelty',
  Novelty: 'novelty',
}

export function signalLabel(key: string | null | undefined, fallback = ''): string {
  if (!key) return fallback
  const suffix = SIGNAL_KEYS[key]
  return suffix ? i18n.t(`pdv.signals.${suffix}`) : key
}

export function confidenceLevelLabel(level: string): string {
  return i18n.exists(`pdv.levels.${level}`) ? i18n.t(`pdv.levels.${level}`) : level
}
