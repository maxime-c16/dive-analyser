export type LanguageCode = 'system' | 'en' | 'fr'

export const PREFS_KEY = 'dive-analyser.prefs.v1'

type PrefsBlob = { language?: unknown } & Record<string, unknown>

/**
 * The language lives inside the same `dive-analyser.prefs.v1` blob as the
 * notification prefs in Account.tsx, so there is one prefs surface:
 * a corrupted blob falls back to defaults rather than throwing.
 */
export function readStoredLanguage(): LanguageCode {
  try {
    const raw = localStorage.getItem(PREFS_KEY)
    if (!raw) return 'system'
    const parsed = JSON.parse(raw) as PrefsBlob
    if (parsed.language === 'en' || parsed.language === 'fr' || parsed.language === 'system') {
      return parsed.language
    }
  } catch {
    // Corrupt blob: fall through to the system default.
  }
  return 'system'
}

export function writeStoredLanguage(language: LanguageCode) {
  try {
    const raw = localStorage.getItem(PREFS_KEY)
    const parsed = raw ? (JSON.parse(raw) as PrefsBlob) : {}
    localStorage.setItem(PREFS_KEY, JSON.stringify({ ...parsed, language }))
  } catch {
    // Private browsing etc: the choice simply doesn't persist.
  }
}
