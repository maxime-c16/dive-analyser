/** Pure statistics for one dive code's attempts (all scores on the 0-10 athlete scale). */

export function quantile(values: number[], p: number): number | null {
  if (!values.length) return null
  const sorted = [...values].sort((a, b) => a - b)
  const index = (sorted.length - 1) * p
  const lo = Math.floor(index), hi = Math.ceil(index)
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (index - lo)
}
export const median = (values: number[]) => quantile(values, 0.5)
export const mean = (values: number[]) => values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null

export function rolling(values: number[], window: number, p = 0.5): number[] {
  return values.map((_, index) => quantile(values.slice(Math.max(0, index - window + 1), index + 1), p) as number)
}

/** Smoothing window that keeps short histories readable and long ones calm. */
export function smoothingWindow(count: number, bySession = false): number {
  return bySession ? 3 : Math.max(7, Math.min(15, Math.round(count / 10)))
}

export type Extreme = { index: number; kind: 'peak' | 'valley'; value: number }

/**
 * The two clearest peaks and valleys of a smoothed series: a point is kept
 * when it is the local max/min of its neighbourhood and stands at least one
 * point above/below it, and kept points are spread apart.
 */
export function extremes(smoothed: number[]): Extreme[] {
  const n = smoothed.length
  if (n < 12) return []
  const gap = Math.max(4, Math.round(n / 8))
  const found: Extreme[] = []
  for (let i = 1; i < n - 1; i++) {
    const value = smoothed[i]
    if (smoothed[i - 1] === value) continue
    // A plateau counts once, marked at its middle; prominence is required on both sides
    // so the edge of a plateau next to a peak is not reported as a valley.
    let end = i
    while (end + 1 < n && smoothed[end + 1] === value) end++
    if (end === n - 1) continue
    const left = smoothed.slice(Math.max(0, i - gap), i), right = smoothed.slice(end + 1, Math.min(n, end + 1 + gap))
    const index = Math.round((i + end) / 2)
    if (value > Math.max(...left, ...right) - 1e-9 && value - Math.min(...left) >= 1 && value - Math.min(...right) >= 1) found.push({ index, kind: 'peak', value })
    if (value < Math.min(...left, ...right) + 1e-9 && Math.max(...left) - value >= 1 && Math.max(...right) - value >= 1) found.push({ index, kind: 'valley', value })
  }
  const pick = (kind: Extreme['kind']) => found.filter(item => item.kind === kind)
    .sort((a, b) => kind === 'peak' ? b.value - a.value : a.value - b.value)
    .reduce<Extreme[]>((kept, item) => kept.length < 2 && kept.every(other => Math.abs(other.index - item.index) >= gap) ? [...kept, item] : kept, [])
  return [...pick('peak'), ...pick('valley')].sort((a, b) => a.index - b.index)
}

/** Rating band for a 0-10 score, matching the Library rating colours. */
export function scoreBand(score: number): 'P' | 'G' | 'M' | 'B' | 'F' {
  return score >= 8.5 ? 'P' : score >= 5.75 ? 'G' : score >= 3.25 ? 'M' : score >= 1 ? 'B' : 'F'
}

export const DAY_MS = 86_400_000

/** Median of the last six weeks against the four and a half months before, like the code cards. */
export function recentTrend<T>(items: T[], score: (item: T) => number, date: (item: T) => number, now = Date.now()): number | null {
  const recent = items.filter(item => now - date(item) <= 42 * DAY_MS).map(score)
  const baseline = items.filter(item => now - date(item) > 42 * DAY_MS && now - date(item) <= 182 * DAY_MS).map(score)
  if (recent.length < 4 || baseline.length < 4) return null
  return (median(recent) as number) - (median(baseline) as number)
}

/** One decimal, rounded half up like the backend, so cards, charts and pages show the same value. */
export function fmtScore(value: number | null | undefined): string {
  return value == null || Number.isNaN(value) ? '—' : (Math.round(value * 10 + 1e-6) / 10).toFixed(1)
}
