import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import i18n, { applyLanguage, type LanguageCode, type ResolvedLanguage } from './index'
import { PREFS_KEY, readStoredLanguage, writeStoredLanguage } from './prefs'

/**
 * Languages we ship. `system` follows navigator.language (fr* -> fr).
 */
export const LANGUAGES: Array<{ value: LanguageCode; label: string; labelKey?: string }> = [
  { value: 'system', label: 'Language of the device', labelKey: 'settings.languageSystemOption' },
  { value: 'en', label: 'English' },
  { value: 'fr', label: 'Français' }
]

function resolve(stored: LanguageCode): ResolvedLanguage {
  if (stored === 'en' || stored === 'fr') return stored
  const nav = typeof navigator !== 'undefined' ? navigator.language : 'en'
  return nav && nav.toLowerCase().startsWith('fr') ? 'fr' : 'en'
}

type I18nContextValue = {
  language: LanguageCode
  resolvedLanguage: ResolvedLanguage
  setLanguage: (language: LanguageCode) => void
}

const I18nContext = createContext<I18nContextValue | null>(null)

export function I18nProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<LanguageCode>(() => {
    const stored = readStoredLanguage()
    applyLanguage(stored)
    return stored
  })
  const [resolved, setResolved] = useState<ResolvedLanguage>(() => resolve(readStoredLanguage()))

  useEffect(() => {
    const sync = () => {
      const stored = readStoredLanguage()
      setLanguageState(stored)
      setResolved(resolve(stored))
      applyLanguage(stored)
    }
    // Cross-tab sync: storage events don't fire in the writing tab, so this
    // listener never fights the local setLanguage. Filter on the prefs key —
    // library cache and What's-new keys change often and must not re-render
    // the whole tree.
    window.addEventListener('storage', sync)
    return () => window.removeEventListener('storage', sync)
  }, [])

  const setLanguage = useCallback((next: LanguageCode) => {
    writeStoredLanguage(next)
    setLanguageState(next)
    const nextResolved = resolve(next)
    setResolved(nextResolved)
    applyLanguage(next)
  }, [])

  const value = useMemo(
    () => ({ language, resolvedLanguage: resolved, setLanguage }),
    [language, resolved, setLanguage],
  )

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useLang(): I18nContextValue {
  const ctx = useContext(I18nContext)
  if (!ctx) throw new Error('useLang must be used within I18nProvider')
  return ctx
}
