import { expect, it } from 'vitest'
import { nameSearchCodes } from '../utils/diveNameSearch'
it('probe2', () => {
  const r = nameSearchCodes('arriere')
  console.log('ARRIERE_FR status', r.status, 'n', r.codes.length, '.has203C', r.codes.includes('203C'), 'has201A', r.codes.includes('201A'), 'has303C', r.codes.includes('303C'))
  const f = nameSearchCodes('arriere groupé')
  console.log('ARRIERE_TUCK_FR', f.status, f.codes.length, f.codes.slice(0, 12).join(','))
  const pl = nameSearchCodes('plongeon')
  console.log('PLONGEON', pl.status, pl.codes.length, pl.codes.includes('101A'))
  expect(true).toBe(true)
})
