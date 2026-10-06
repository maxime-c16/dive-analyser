import { afterEach, describe, expect, it } from 'vitest'
import i18n from '../i18n'
import fr from '../i18n/locales/fr'
import { confidenceLevelLabel, signalLabel } from './personalValue'

describe('personal value labels', () => {
  afterEach(async () => { await i18n.changeLanguage('en') })

  it('localizes API display names, component keys and confidence levels', async () => {
    await i18n.changeLanguage('fr')
    expect(signalLabel('Same-dive result')).toBe(fr.pdv.signals.sameDiveResult)
    expect(signalLabel('same_dive_relative')).toBe(fr.pdv.signals.sameDiveResult)
    expect(signalLabel('Breakthrough')).toBe(fr.pdv.signals.breakthrough)
    expect(confidenceLevelLabel('high')).toBe(fr.pdv.levels.high)
  })

  it('passes unknown values through and falls back when empty', () => {
    expect(signalLabel('Mystery')).toBe('Mystery')
    expect(signalLabel(null, 'Emerging')).toBe('Emerging')
    expect(confidenceLevelLabel('weird')).toBe('weird')
  })
})
