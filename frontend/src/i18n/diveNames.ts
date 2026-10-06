/**
 * World Aquatics (FINA) dive-code naming, localized.
 *
 * Codes are never translated — `5231D` is `5231D` in every language and in
 * the API. This module reconstructs each code's markup and renders the human
 * dive name, mirroring the semantics of backend/app/services/fina_validator.py
 * and world_aquatics_dd.py (FFN French edition of the World Aquatics Diving
 * Rules, 2022-2025 Appendices):
 *
 *   groups 1-4: [GROUP][FLYING][UNITS][POSITION] — the second digit is 1 only
 *               for flying dives; UNITS counts half-somersaults
 *               (1 = dive, 3 = 1½ somersaults, 5 = 2½ somersaults…).
 *   group 5:    [5][DIRECTION][UNITS][TWISTS][POSITION] — DIRECTION mirrors
 *               the groups (1 front, 2 back, 3 reverse, 4 inward); TWISTS
 *               counts half-twists (1 = ½ twist, 2 = 1 twist…).
 *   group 6:    [6][DIRECTION][UNITS][POSITION] (optionally with a twist digit
 *               before the position); armstand dives are platform-only.
 *
 * French naming follows the FFN French edition / Plongeon Canada usage:
 *   101A → "Plongeon en avant droit"
 *   203C → "Saut périlleux et demi arrière groupé"
 *   302B → "Saut périlleux renversé carpé"
 *   401C → "Plongeon retourné groupé"
 *   5132D → "Saut périlleux et demi avant avec une vrille en position libre"
 *   624C → "Plongeon en équilibre avec double saut périlleux arrière groupé"
 * Flying dives are rendered with "pris au vol".
 *
 * English naming follows the World Aquatics DD-table wording:
 *   101B → "Forward dive pike"
 *   203C → "Back 1½ somersaults tuck"
 *   113B → "Forward flying 1½ somersaults pike"
 *   5132D → "Forward 1½ somersaults 1 twist free"
 *   624C → "Armstand back double somersaults tuck"
 */

export type DivePosition = 'A' | 'B' | 'C' | 'D'

export type DiveParts = {
  group: 1 | 2 | 3 | 4 | 5 | 6
  direction: 0 | 1 | 2 | 3 | 4 | 5
  flying: boolean
  rotations: number // half-somersault units, 1-8
  twists: number // half-twist units, 0-8
  position: DivePosition
}

const STANDARD_RE = /^([1-4])([01])([1-8])([ABCD])$/
const TWISTING_RE = /^5([1-4])([1-8])([1-8])([ABCD])$/
// Armstand codes are exactly four characters (backend fina_validator): a
// fifth twist digit is not defined, so such codes stay unparsed (rendered
// raw) rather than being silently named as a different dive.
const ARMSTAND_RE = /^6([0-5])([1-8])([ABCD])$/

/** Parses FINA codes; returns null for anything the reference doesn't define. */
export function parseDiveCode(code?: string | null): DiveParts | null {
  if (!code) return null
  const codeStr = code.trim().toUpperCase()

  const standard = STANDARD_RE.exec(codeStr)
  if (standard) {
    const group = Number(standard[1]) as 1 | 2 | 3 | 4
    return {
      group,
      direction: group, // groups 1-4 mirror their direction digit
      flying: standard[2] === '1',
      rotations: Number(standard[3]),
      twists: 0,
      position: standard[4] as DivePosition,
    }
  }
  const twisting = TWISTING_RE.exec(codeStr)
  if (twisting) {
    return {
      group: 5,
      direction: Number(twisting[1]) as 1 | 2 | 3 | 4,
      flying: false,
      rotations: Number(twisting[2]),
      twists: Number(twisting[3]),
      position: twisting[4] as DivePosition,
    }
  }
  const armstand = ARMSTAND_RE.exec(codeStr)
  if (armstand) {
    const dirDigit = Number(armstand[1])
    return {
      group: 6,
      direction: dirDigit as 0 | 1 | 2 | 3 | 4 | 5,
      flying: false,
      rotations: Number(armstand[2]),
      twists: 0,
      position: armstand[3] as DivePosition,
    }
  }
  return null
}

const ENGLISH_ROTATIONS: Record<number, string> = {
  1: 'dive',
  2: 'somersault',
  3: '1½ somersaults',
  4: 'double somersault',
  5: '2½ somersaults',
  6: 'triple somersault',
  7: '3½ somersaults',
  8: 'quadruple somersault',
}

const FRENCH_ROTATIONS: Record<number, string> = {
  1: 'plongeon',
  2: 'saut périlleux',
  3: 'saut périlleux et demi',
  4: 'double saut périlleux',
  5: 'double saut périlleux et demi',
  6: 'triple saut périlleux',
  7: 'triple saut périlleux et demi',
  8: 'quadruple saut périlleux',
}

const ENGLISH_TWISTS: Record<number, string> = {
  1: '½ twist',
  2: '1 twist',
  3: '1½ twists',
  4: '2 twists',
  5: '2½ twists',
  6: '3 twists',
  7: '3½ twists',
  8: '4 twists',
}

const FRENCH_TWISTS: Record<number, string> = {
  1: 'une demi-vrille',
  2: 'une vrille',
  3: 'une vrille et demie',
  4: 'deux vrilles',
  5: 'deux vrilles et demie',
  6: 'trois vrilles',
  7: 'trois vrilles et demie',
  8: 'quatre vrilles',
}

const FRENCH_TWISTING_DIRECTIONS: Record<number, string> = {
  1: 'avant',
  2: 'arrière',
  3: 'renversé',
  4: 'retourné',
}

const TWISTING_DIRECTIONS_ENGLISH = ['Forward', 'Back', 'Reverse', 'Inward'] as const

const FRENCH_ARMSTAND_DIRECTIONS: Record<number, string> = {
  1: 'avant',
  2: 'arrière',
  3: 'renversé',
  4: 'retourné',
}

const FRENCH_PARTICIPLES: Record<DivePosition, string> = {
  A: 'droit',
  B: 'carpé',
  C: 'groupé',
  D: 'libre',
}

const ENGLISH_POSITIONS: Record<DivePosition, string> = {
  A: 'straight',
  B: 'pike',
  C: 'tuck',
  D: 'free',
}

export type DiveLanguage = 'en' | 'fr'

function capitalize(text: string): string {
  return text ? text[0].toUpperCase() + text.slice(1) : text
}

function englishName(parts: DiveParts): string {
  const rotation = ENGLISH_ROTATIONS[parts.rotations] ?? ''
  const position = ENGLISH_POSITIONS[parts.position]
  const flying = parts.flying ? 'flying' : ''
  const twists = parts.twists > 0 ? (ENGLISH_TWISTS[parts.twists] ?? '') : ''

  if (parts.group === 6) {
    const dirWord = ['', 'forward', 'back', 'reverse', 'inward'][parts.direction] ?? ''
    return capitalize(['armstand', dirWord, rotation, twists, position].filter(Boolean).join(' '))
  }

  const direction = ['forward', 'back', 'reverse', 'inward'][parts.group - 1] ?? ''
  if (parts.group === 5) {
    const twistingDirection = TWISTING_DIRECTIONS_ENGLISH[parts.direction - 1] ?? ''
    return capitalize([twistingDirection, rotation, twists, position].filter(Boolean).join(' '))
  }
  return capitalize([direction, flying, rotation, twists, position].filter(Boolean).join(' '))
}

function frenchName(parts: DiveParts): string {
  const rotation = FRENCH_ROTATIONS[parts.rotations] ?? ''
  const twistPhrase =
    parts.twists > 0 ? 'avec ' + (FRENCH_TWISTS[parts.twists] ?? '') : ''

  if (parts.group === 6) {
    // "Plongeon en équilibre avec double saut périlleux arrière groupé" (624C)
    const direction = FRENCH_ARMSTAND_DIRECTIONS[parts.direction] ?? ''
    const location = parts.position === 'D' ? 'en position libre' : FRENCH_PARTICIPLES[parts.position]
    return capitalize(
      ['plongeon en équilibre', rotation, direction, twistPhrase, location]
        .filter(Boolean)
        .join(' ')
        .replace(' avec avec', ' avec'),
    )
  }

  // Groups 1-5: the rotation word carries the motion noun; the direction
  // adjective mirrors the group (or the twisting direction digit in group 5).
  // Wikipedia/FFN style: 101 = "Plongeon en avant", but 103 = "Saut
  // périlleux et demi avant"; groups 2-5 use plain direction adjectives.
  const directionIndex = parts.group === 5 ? parts.direction : parts.group
  const directionWord =
    directionIndex === 1
      ? parts.rotations === 1
        ? 'en avant'
        : 'avant'
      : ['arrière', 'renversé', 'retourné'][directionIndex - 2] ?? ''
  const location =
    parts.position === 'D'
      ? parts.twists > 0
        ? 'en position libre'
        : 'libre'
      : FRENCH_PARTICIPLES[parts.position]
  const flyingPhrase = parts.flying ? 'pris au vol' : ''
  return capitalize(
    [rotation, directionWord, twistPhrase, location, flyingPhrase]
      .filter(Boolean)
      .join(' '),
  )
}

/**
 * Localized, human dive name from a FINA code. Returns the raw code itself
 * when the structure isn't recognized, keeping unknown codes visible.
 */
export function diveCodeName(code: string, lang: DiveLanguage): string {
  const parts = parseDiveCode(code)
  if (!parts) return code
  return lang === 'fr' ? frenchName(parts) : englishName(parts)
}
