/**
 * Personal note ("note perso") on the 0-10 athlete scale. Mirrors
 * backend/app/services/performance_scoring.py; backend/tests/test_scoring_contract.py
 * fails if the two drift. Contract: docs/SCORING.md.
 */
export const ATHLETE_SCORE_10: Record<string, number> = {
  F: 0,
  B: 2,
  M: 4.5,
  G: 7,
  P: 10,
}

export const PHASE1_WEIGHT = 0.45
export const PHASE2_WEIGHT = 0.55

/** Lowest score of each letter band (midpoints between letters): a score maps to its nearest letter. */
export const GRADE_FLOORS = {
  P: 8.5,
  G: 5.75,
  M: 3.25,
  B: 1,
  F: 0,
} as const

export type Grade = keyof typeof GRADE_FLOORS

/** Nearest letter for a 0-10 score. Letters, colours and success all derive from it. */
export function gradeForScore(score: number): Grade {
  if (score >= GRADE_FLOORS.P - 1e-9) return 'P'
  if (score >= GRADE_FLOORS.G - 1e-9) return 'G'
  if (score >= GRADE_FLOORS.M - 1e-9) return 'M'
  if (score >= GRADE_FLOORS.B - 1e-9) return 'B'
  return 'F'
}

export function athleteScore10(performance?: string | null): number {
  if (!performance) return 0
  return ATHLETE_SCORE_10[performance.toUpperCase()] ?? 0
}

export function phaseScore10(phase1?: string | null, phase2?: string | null): number | null {
  if (!phase1 || !phase2) return null
  return athleteScore10(phase1) * PHASE1_WEIGHT + athleteScore10(phase2) * PHASE2_WEIGHT
}

export function performanceScore10(
  performance?: string | null,
  phase1?: string | null,
  phase2?: string | null,
): number {
  return phaseScore10(phase1, phase2) ?? athleteScore10(performance)
}

/** "Réussite": landed at M or better. */
export function isSuccessfulPerformance(performance?: string | null): boolean {
  return performance === 'M' || performance === 'G' || performance === 'P'
}

export function performanceColor(score: number): string {
  if (score >= GRADE_FLOORS.G) return 'text-green-400'
  if (score >= GRADE_FLOORS.M) return 'text-amber-400'
  return 'text-red-400'
}

export function performanceBorder(score: number): string {
  if (score >= GRADE_FLOORS.G) return 'border-green-500/50'
  if (score >= GRADE_FLOORS.M) return 'border-amber-500/50'
  return 'border-red-500/50'
}

export function performanceBarColor(score: number): string {
  if (score >= GRADE_FLOORS.G) return 'bg-green-500'
  if (score >= GRADE_FLOORS.M) return 'bg-amber-500'
  return 'bg-red-500'
}
