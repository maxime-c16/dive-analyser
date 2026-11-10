import { expect,it } from 'vitest'
import i18n from '../../i18n'
import { techniqueImpact } from './techniqueText'
it('pluralizes dives and preserved tags independently in English and French',()=>{
 expect(techniqueImpact(i18n.getFixedT('en'),1,2)).toBe('1 dive in this interval · 2 existing tags kept')
 expect(techniqueImpact(i18n.getFixedT('en'),2,1)).toBe('2 dives in this interval · 1 existing tag kept')
 expect(techniqueImpact(i18n.getFixedT('fr'),1,2)).toBe('1 plongeon dans cet intervalle · 2 identifications conservées')
})
