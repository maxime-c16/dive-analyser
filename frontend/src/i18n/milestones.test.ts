import { afterEach, describe, expect, it } from 'vitest'
import i18n from './index'
import { milestoneDisplay } from './milestones'

describe('milestoneDisplay (French)', () => {
  afterEach(async () => { await i18n.changeLanguage('en') })

  it('names the dive in the narrative while keeping the code', async () => {
    await i18n.changeLanguage('fr')
    const display = milestoneDisplay({
      type: 'first_success', dive_code: '101B', height: '3m',
      title: 'First successful 101B', narrative: 'x', failures_before: 0, attempts_before: 0,
    })
    expect(display.narrative).toContain('101B (plongeon en avant carpé)')
  })

  it('shows the bare code when the code has no known name', async () => {
    await i18n.changeLanguage('fr')
    const display = milestoneDisplay({
      type: 'first_success', dive_code: '999X', height: '3m',
      title: 't', narrative: 'x', failures_before: 0, attempts_before: 0,
    })
    expect(display.narrative).toContain('999X')
    expect(display.narrative).not.toContain('999X (')
  })

  it('keeps backend English copy in English', () => {
    const display = milestoneDisplay({
      type: 'first_success', dive_code: '101B', height: '3m',
      title: 'First successful 101B', narrative: 'Backend narrative', failures_before: 0,
    })
    expect(display).toEqual({ title: 'First successful 101B', narrative: 'Backend narrative' })
  })
})
