/** One decimal, in the reader's language (6,5 in French). */
export function points(value: number, locale: string, signed = false): string {
  const text = Math.abs(value).toLocaleString(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 })
  return !signed ? (value < 0 ? `−${text}` : text) : value > 0 ? `+${text}` : value < 0 ? `−${text}` : '='
}

export function scoreNumber(value: number | null | undefined, locale: string): string {
  return value == null ? '—' : points(value, locale)
}
