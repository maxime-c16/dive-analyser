import { describe, expect, it } from 'vitest'
import { diveCodeName, parseDiveCode } from './diveNames'

describe('parseDiveCode', () => {
  it('parses standard codes', () => {
    expect(parseDiveCode('101B')).toEqual({ group: 1, direction: 1, flying: false, rotations: 1, twists: 0, position: 'B' })
    expect(parseDiveCode('113b')).toEqual({ group: 1, direction: 1, flying: true, rotations: 3, twists: 0, position: 'B' })
    expect(parseDiveCode('5231D')).toEqual({ group: 5, direction: 2, flying: false, rotations: 3, twists: 1, position: 'D' })
    expect(parseDiveCode('624C')).toEqual({ group: 6, direction: 2, flying: false, rotations: 4, twists: 0, position: 'C' })
    expect(parseDiveCode('901B')).toBeNull()
    expect(parseDiveCode('')).toBeNull()
    expect(parseDiveCode(null)).toBeNull()
  })
})

describe('diveCodeName English', () => {
  it('uses FINA wording', () => {
    expect(diveCodeName('101B', 'en')).toBe('Forward dive pike')
    expect(diveCodeName('203C', 'en')).toBe('Back 1½ somersaults tuck')
    expect(diveCodeName('113B', 'en')).toBe('Forward flying 1½ somersaults pike')
    expect(diveCodeName('5132D', 'en')).toBe('Forward 1½ somersaults 1 twist free')
    expect(diveCodeName('5231D', 'en')).toBe('Back 1½ somersaults ½ twist free')
    expect(diveCodeName('624C', 'en')).toBe('Armstand back double somersault tuck')
    expect(diveCodeName('612B', 'en')).toBe('Armstand forward somersault pike')
    expect(diveCodeName('306C', 'en')).toBe('Reverse triple somersault tuck')
  })
  it('keeps unrecognized codes raw', () => {
    expect(diveCodeName('999X', 'en')).toBe('999X')
  })
})


describe('diveCodeName armstand codes', () => {
  it('keeps armstand directions without a defined name raw', () => {
    // The backend validator accepts directions 0-5; only 1-4 have names.
    for (const code of ['601A', '651A', '652C']) {
      expect(parseDiveCode(code)).toBeNull()
      expect(diveCodeName(code, 'en')).toBe(code)
      expect(diveCodeName(code, 'fr')).toBe(code)
    }
  })

  it('keeps five-character armstand codes raw', () => {
    // The backend validator accepts only four-character group-6 codes.
    for (const code of ['6103B', '6121D', '6121B']) {
      expect(parseDiveCode(code)).toBeNull()
      expect(diveCodeName(code, 'en')).toBe(code)
      expect(diveCodeName(code, 'fr')).toBe(code)
    }
  })
})

describe('diveCodeName French (FINA/FFN jargon)', () => {
  it('renders canonical French names', () => {
    expect(diveCodeName('101B', 'fr')).toBe('Plongeon en avant carpé')
    expect(diveCodeName('101A', 'fr')).toBe('Plongeon en avant droit')
    expect(diveCodeName('302B', 'fr')).toBe('Saut périlleux renversé carpé')
    expect(diveCodeName('401C', 'fr')).toBe('Plongeon retourné groupé')
    expect(diveCodeName('303B', 'fr')).toBe('Saut périlleux et demi renversé carpé')
    expect(diveCodeName('205C', 'fr')).toBe('Double saut périlleux et demi arrière groupé')
    expect(diveCodeName('5132D', 'fr')).toBe('Saut périlleux et demi avant avec une vrille en position libre')
    expect(diveCodeName('5231D', 'fr')).toBe('Saut périlleux et demi arrière avec une demi-vrille en position libre')
    expect(diveCodeName('624C', 'fr')).toBe('Plongeon en équilibre double saut périlleux arrière groupé')
    expect(diveCodeName('612B', 'fr')).toBe('Plongeon en équilibre saut périlleux avant carpé')
  })
  it('renders flying dives with the FFN "pris au vol" form', () => {
    expect(diveCodeName('113B', 'fr')).toBe('Saut périlleux et demi avant carpé pris au vol')
  })
})
