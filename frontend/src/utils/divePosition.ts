/**
 * The letter remains part of the canonical FINA dive code and API contract.
 * Keep it for filtering, but never make people translate it in the UI.
 */
export const DIVE_POSITION_NAMES = {
  A: 'Straight',
  B: 'Pike',
  C: 'Tuck',
  D: 'Free',
} as const

export type DivePositionCode = keyof typeof DIVE_POSITION_NAMES

const NAME_TO_CODE: Record<string, DivePositionCode> = Object.fromEntries(
  Object.entries(DIVE_POSITION_NAMES).map(([code, name]) => [name.toLowerCase(), code as DivePositionCode]),
) as Record<string, DivePositionCode>

export function divePositionCode(position?: string | null, diveCode?: string | null): DivePositionCode | null {
  // The final canonical-code letter is the authoritative source. The stored
  // field is only a compatibility fallback for incomplete legacy records.
  const canonicalMatch = diveCode?.trim().toUpperCase().match(/^\d{3,4}([ABCD])$/)
  if (canonicalMatch) return canonicalMatch[1] as DivePositionCode

  const normalized = position?.trim().toUpperCase()
  if (normalized && normalized in DIVE_POSITION_NAMES) return normalized as DivePositionCode
  return position ? NAME_TO_CODE[position.trim().toLowerCase()] || null : null
}

export function divePositionName(position?: string | null, diveCode?: string | null) {
  const code = divePositionCode(position, diveCode)
  return code ? DIVE_POSITION_NAMES[code] : 'Unknown position'
}

