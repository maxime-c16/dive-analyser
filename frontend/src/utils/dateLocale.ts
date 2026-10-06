/**
 * date-fns renders month/weekday names through a `locale` option (English
 * by default). Callers pass `appLocale()` so dates follow the active UI
 * language instead of staying English.
 */
import { enUS, fr } from 'date-fns/locale'
import i18n from '../i18n'

export function appLocale(): typeof enUS {
  return i18n.language === 'fr' ? fr : enUS
}

/** Intl.DateTimeFormat language tag for the active UI language. */
export function appLanguage(): string {
  return i18n.language
}
