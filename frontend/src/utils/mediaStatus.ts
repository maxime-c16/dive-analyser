import i18n from '../i18n'

/**
 * Media and rendition statuses are canonical API identifiers
 * (`waiting_for_mac`, `ready`…). Render them through the catalog; an
 * unlisted status shows its identifier with underscores removed.
 */
export function mediaStatusLabel(status: string): string {
  return i18n.exists(`mediaStatus.${status}`) ? i18n.t(`mediaStatus.${status}`) : status.replace(/_/g, ' ')
}
