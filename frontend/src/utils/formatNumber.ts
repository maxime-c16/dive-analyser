import i18n from '../i18n'

/**
 * Fixed decimals in the reader's language ("4,80" in French). Use for every
 * number a person reads; keep `toFixed` for SVG paths and CSS values.
 * Returns '' for a missing value so `fmtNum(x, 1) || '—'` reads naturally.
 */
export function fmtNum(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return ''
  return value.toLocaleString(i18n.language || 'fr', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
    useGrouping: false,
  })
}
