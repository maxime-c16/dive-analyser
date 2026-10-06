/**
 * The position letter remains part of the canonical FINA dive code and API
 * contract. Keep it for filtering, but never make people translate it in
 * the UI: names follow World Aquatics terminology
 * (A straight/droit, B pike/carpé, C tuck/groupé, D free/libre) rendered in
 * the active i18next language.
 */
import i18n from '../i18n'

export type DivePositionCode = 'A' | 'B' | 'C' | 'D'

export const DIVE_POSITION_CODES: DivePositionCode[] = ['A', 'B', 'C', 'D']

const POSITION_KEY: Record<DivePositionCode, string> = {
  A: 'jargon.positions.A',
  B: 'jargon.positions.B',
  C: 'jargon.positions.C',
  D: 'jargon.positions.D',
}

const CANONICAL_NAMES: Record<DivePositionCode, string> = {
  A: 'Straight',
  B: 'Pike',
  C: 'Tuck',
  D: 'Free',
}

/** English canonical names double as the backend compatibility fallback. */
const CODE_FROM_NAME: Record<string, DivePositionCode> = Object.fromEntries(
  Object.entries(CANONICAL_NAMES).map(([code, name]) => [name.toLowerCase(), code as DivePositionCode]),
)

export function divePositionCode(position?: string | null, diveCode?: string | null): DivePositionCode | null {
  // The final canonical-code letter is the authoritative source. The stored
  // field is only a compatibility fallback for incomplete legacy records.
  const canonicalMatch = diveCode?.trim().toUpperCase().match(/^\d{3,4}([ABCD])$/)
  if (canonicalMatch) return canonicalMatch[1] as DivePositionCode

  const normalized = position?.trim().toUpperCase()
  if (normalized && (DIVE_POSITION_CODES as string[]).includes(normalized)) return normalized as DivePositionCode
  return position ? CODE_FROM_NAME[position.trim().toLowerCase()] || null : null
}

export function divePositionName(position?: string | null, diveCode?: string | null) {
  const code = divePositionCode(position, diveCode)
  return code ? i18n.t(POSITION_KEY[code]) : i18n.t('jargon.unknownPosition')
}
