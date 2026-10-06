import i18next from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from './locales/en'
import fr from './locales/fr'
import { readStoredLanguage } from './prefs'

export type LanguageCode = 'system' | 'en' | 'fr'
export type ResolvedLanguage = 'en' | 'fr'

const PUBLISHED: ResolvedLanguage[] = ['en', 'fr']

export function resolvePreferredLanguage(stored: string | null, navigatorLanguage: string | undefined): ResolvedLanguage {
  if (stored === 'en' || stored === 'fr') return stored
  const nav = (navigatorLanguage || 'en').toLowerCase()
  if (PUBLISHED.some(tag => nav === tag || nav.startsWith(`${tag}-`))) {
    return PUBLISHED.find(tag => nav === tag || nav.startsWith(`${tag}-`)) as ResolvedLanguage
  }
  return 'en'
}

export function resolveLanguage(stored: string | null, navigatorLanguage?: string): ResolvedLanguage {
  if (stored === 'system' || stored === null || stored === undefined) {
    return resolvePreferredLanguage(null, navigatorLanguage)
  }
  return resolvePreferredLanguage(stored, navigatorLanguage)
}

if (!i18next.isInitialized) {
  void i18next.use(initReactI18next).init({
    resources: { en: { translation: en }, fr: { translation: fr } },
    lng: resolveLanguage(readStoredLanguage(), typeof navigator !== 'undefined' ? navigator.language : undefined),
    fallbackLng: 'en',
    interpolation: { escapeValue: false },
    returnEmptyString: false,
  })
}

export default i18next

export async function changeLanguage(next: 'en' | 'fr') {
  await i18next.changeLanguage(next)
  if (typeof document !== 'undefined') {
    document.documentElement.lang = next
  }
}

export function applyLanguage(
  stored: LanguageCode,
  navigatorLanguage: string | undefined = typeof navigator !== 'undefined' ? navigator.language : undefined,
) {
  const resolved = resolveLanguage(stored, navigatorLanguage)
  if (i18next.language !== resolved) {
    void i18next.changeLanguage(resolved)
  }
  if (typeof document !== 'undefined') {
    document.documentElement.lang = resolved
  }
  return resolved
}
