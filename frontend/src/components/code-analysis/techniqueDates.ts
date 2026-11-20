export function techniqueTimestamp(value: string) {
  return Date.parse(/(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : `${value}Z`)
}

// History compares the full PostgreSQL timestamp before using the dive ID.
// Keep the sub-millisecond part separate from the chart's numeric coordinate.
export function techniqueHistoryOrder(value: string, id: number) {
  const fraction = value.match(/\.(\d+)(?:Z|[+-]\d\d:\d\d)?$/)?.[1] ?? ''
  return { at: techniqueTimestamp(value), microseconds: Number(fraction.slice(3, 6).padEnd(3, '0')), id }
}

export function compareTechniqueHistoryOrder(a: ReturnType<typeof techniqueHistoryOrder>, b: ReturnType<typeof techniqueHistoryOrder>) {
  return a.at - b.at || a.microseconds - b.microseconds || a.id - b.id
}

export function techniqueDate(value: string, language: string) {
  const date = new Date(techniqueTimestamp(value))
  if (!Number.isFinite(date.getTime())) return '—'
  return new Intl.DateTimeFormat(language.startsWith('fr') ? 'fr-FR' : 'en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(date)
}

export function techniqueInputDate(date: Date, timezone: string) {
  try {
    const parts = new Intl.DateTimeFormat('sv-SE', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(date)
    const part = (type: string) => parts.find(p => p.type === type)?.value
    return `${part('year')}-${part('month')}-${part('day')}T${part('hour')}:${part('minute')}`
  } catch { return date.toISOString().slice(0, 16) }
}

export function techniqueDateTime(value: string, language: string) {
  const date = new Date(techniqueTimestamp(value))
  if (!Number.isFinite(date.getTime())) return '—'
  const clock = new Intl.DateTimeFormat(language.startsWith('fr') ? 'fr-FR' : 'en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC', hourCycle: 'h23' }).format(date)
  return `${techniqueDate(value, language)} · ${clock}`
}
