import { describe, expect, it } from 'vitest'
import en from './locales/en'
import fr from './locales/fr'

/**
 * Key parity: every key present in the English locale must exist in the
 * French locale (and vice versa). New user-visible keys must add both.
 * Paths are handled as step arrays because leaf keys contain dots
 * (e.g. height "7.5m") and must not be split on '.'.
 */
type Tree = Record<string, unknown>

function flatten(node: Tree, base: string[] = []): string[][] {
  return Object.entries(node).flatMap(([key, value]) =>
    typeof value === 'object' && value !== null
      ? flatten(value as Tree, [...base, key])
      : [[...base, key]],
  )
}

function resolve(tree: unknown, path: string[]): unknown {
  return path.reduce<unknown>((node, key) =>
    typeof node === 'object' && node !== null ? (node as Tree)[key] : undefined, tree)
}

const pathToKey = (path: string[]) => path.join('\u0000')

describe('locale key parity', () => {
  it('en and fr expose exactly the same keys', () => {
    const enKeys = flatten(en as unknown as Tree).map(pathToKey).sort()
    const frKeys = flatten(fr as unknown as Tree).map(pathToKey).sort()
    const missingInFr = enKeys.filter(key => !frKeys.includes(key))
    const missingInEn = frKeys.filter(key => !enKeys.includes(key))
    expect(missingInFr.map(k => k.split('\u0000').join('.')), 'defined in en but missing in fr').toEqual([])
    expect(missingInEn.map(k => k.split('\u0000').join('.')), 'defined in fr but missing in en').toEqual([])
  })

  it('values are non-empty strings for both locales', () => {
    for (const [name, tree] of [['en', en], ['fr', fr]] as const) {
      for (const path of flatten(tree as unknown as Tree)) {
        const value = resolve(tree, path)
        expect(value, `${name}:${path.join('.')}`).toBeTypeOf('string')
        expect(value, `${name}:${path.join('.')}`).not.toBe('')
      }
    }
  })
})
