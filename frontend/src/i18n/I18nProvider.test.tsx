import { act, render, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import i18n from './index'
import { I18nProvider } from './I18nProvider'
import { writeStoredLanguage } from './prefs'

function setNavigatorLanguage(language: string) {
  vi.spyOn(window.navigator, 'language', 'get').mockReturnValue(language)
}

describe('I18nProvider device language', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
    void i18n.changeLanguage('en')
  })

  it('follows a device language change while "system" is selected', async () => {
    setNavigatorLanguage('en-US')
    writeStoredLanguage('system')
    render(<I18nProvider><span /></I18nProvider>)
    expect(i18n.language).toBe('en')

    setNavigatorLanguage('fr-FR')
    act(() => { window.dispatchEvent(new Event('languagechange')) })
    await waitFor(() => expect(i18n.language).toBe('fr'))
    expect(document.documentElement.lang).toBe('fr')
  })

  it('ignores device language changes for an explicit selection', () => {
    setNavigatorLanguage('en-US')
    writeStoredLanguage('en')
    render(<I18nProvider><span /></I18nProvider>)

    setNavigatorLanguage('fr-FR')
    act(() => { window.dispatchEvent(new Event('languagechange')) })
    expect(i18n.language).toBe('en')
  })
})
