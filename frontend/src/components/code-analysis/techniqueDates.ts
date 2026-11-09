export function techniqueDate(value: string, language: string) {
  const date = new Date(/(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : `${value}Z`)
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
  const date = new Date(/(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : `${value}Z`)
  if (!Number.isFinite(date.getTime())) return '—'
  const clock = new Intl.DateTimeFormat(language.startsWith('fr') ? 'fr-FR' : 'en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC', hourCycle: 'h23' }).format(date)
  return `${techniqueDate(value, language)} · ${clock}`
}
