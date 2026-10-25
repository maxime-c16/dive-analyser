import { describe, expect, it } from 'vitest'
import { DAY_MS, extremes, median, quantile, recentTrend, rolling, scoreBand, smoothingWindow } from './codeStats'

describe('codeStats', () => {
  it('computes quantiles and rolling medians', () => {
    expect(median([1, 9, 5])).toBe(5)
    expect(quantile([0, 10], 0.25)).toBe(2.5)
    expect(median([])).toBeNull()
    expect(rolling([2, 4, 6, 8], 2)).toEqual([2, 3, 5, 7])
  })

  it('keeps short histories smooth enough and long ones calm', () => {
    expect(smoothingWindow(20)).toBe(7)
    expect(smoothingWindow(400)).toBe(15)
    expect(smoothingWindow(400, true)).toBe(3)
  })

  it('labels at most two clear, separated peaks and valleys', () => {
    const series = [...Array(10).fill(4), ...Array(6).fill(7), ...Array(10).fill(4), ...Array(6).fill(2), ...Array(10).fill(4)]
    const marks = extremes(series)
    expect(marks.map(mark => [mark.kind, mark.value])).toEqual([['peak', 7], ['valley', 2]])
    expect(extremes(Array(30).fill(5))).toEqual([])
    expect(extremes([1, 9, 1])).toEqual([])
  })

  it('compares the last six weeks with the months before, only with enough attempts', () => {
    const now = Date.UTC(2026, 9, 25)
    const at = (days: number, score: number) => ({ when: now - days * DAY_MS, score })
    const items = [at(100, 4), at(101, 4), at(102, 4), at(103, 4), at(1, 7), at(2, 7), at(3, 7), at(4, 7)]
    expect(recentTrend(items, item => item.score, item => item.when, now)).toBe(3)
    expect(recentTrend(items.slice(0, 6), item => item.score, item => item.when, now)).toBeNull()
  })

  it('maps scores to the Library rating colours', () => {
    expect([10, 7, 4.5, 2, 0].map(scoreBand)).toEqual(['P', 'G', 'M', 'B', 'F'])
  })
})
