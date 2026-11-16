import { describe, expect, it } from 'vitest'
import { ATHLETE_SCORE_10, GRADE_FLOORS, gradeForScore, performanceColor, phaseScore10 } from './performanceScoring'

const LETTERS = ['F', 'B', 'M', 'G', 'P'] as const

describe('personal note bands (docs/SCORING.md)', () => {
  it('maps each letter score to its own letter', () => {
    expect(LETTERS.map(letter => gradeForScore(ATHLETE_SCORE_10[letter]))).toEqual(LETTERS)
  })

  it('gives two-phase dives the band of their weighted score', () => {
    expect(gradeForScore(phaseScore10('G', 'P') as number)).toBe('P')
    expect(gradeForScore(phaseScore10('P', 'M') as number)).toBe('G')
    expect(gradeForScore(phaseScore10('P', 'G') as number)).toBe('G')
  })

  it('colours a score by the same band as its letter', () => {
    expect(performanceColor(GRADE_FLOORS.G)).toBe('text-green-400')
    expect(performanceColor(GRADE_FLOORS.M)).toBe('text-amber-400')
    expect(performanceColor(GRADE_FLOORS.M - 0.01)).toBe('text-red-400')
  })
})
