import { expect, it } from 'vitest'
import { nameSearchCodes } from './diveNameSearch'
it('intersects before applying the candidate cap, independently of word order', () => {
  const first = nameSearchCodes('somersaults back tuck')
  const reverse = nameSearchCodes('back tuck somersaults')
  expect(first.status).toBe('match')
  expect(first.codes).toContain('203C')
  expect(new Set(first.codes)).toEqual(new Set(reverse.codes))
  expect(first.codes.length).toBe(new Set(first.codes).size)
})
