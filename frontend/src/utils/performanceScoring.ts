export const ATHLETE_SCORE_10: Record<string, number> = {
  F: 0,
  B: 2,
  M: 4.5,
  G: 7,
  P: 10,
}

export const PHASE1_WEIGHT = 0.45
export const PHASE2_WEIGHT = 0.55

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

export function isSuccessfulPerformance(performance?: string | null): boolean {
  return performance === 'M' || performance === 'G' || performance === 'P'
}

export function performanceColor(score: number): string {
  if (score >= 7) return 'text-green-400'
  if (score >= 4.5) return 'text-amber-400'
  return 'text-red-400'
}

export function performanceBorder(score: number): string {
  if (score >= 7) return 'border-green-500/50'
  if (score >= 5.5) return 'border-amber-500/50'
  if (score >= 4.5) return 'border-app'
  return 'border-red-500/50'
}

export function performanceBarColor(score: number): string {
  if (score >= 7) return 'bg-green-500'
  if (score >= 4.5) return 'bg-amber-500'
  return 'bg-red-500'
}
