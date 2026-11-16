import type { TFunction } from 'i18next'

export function techniqueImpact(t: TFunction, affected: number, explicit: number) {
  return `${t('technique.affectedDives', { count: affected })} · ${t('technique.preservedTags', { count: explicit })}`
}
