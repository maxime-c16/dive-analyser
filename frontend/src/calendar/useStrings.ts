import { useTranslation } from "react-i18next";
import { strings, type Strings } from "./strings";

export function useCalendarStrings(): { t: Strings; lang: "fr" | "en" } {
  const { i18n } = useTranslation();
  const lang = i18n.resolvedLanguage?.startsWith("fr") ? "fr" : "en";
  return { t: strings[lang], lang };
}

export interface CalendarContext {
  me: import("./api").MyClub[];
  calendars: import("./api").CalendarInfo[];
  refresh: () => void;
}

/**
 * Props for form action buttons. On touch devices the shell hides the bottom
 * navigation while a text field has focus and restores it on blur. A tap on
 * a button would first blur the field, re-show the navigation and shift the
 * layout before the click lands, losing the first tap. Suppressing the
 * focus change on press keeps the layout stable until the click is handled;
 * keyboard activation is unaffected and the shell policy is unchanged.
 */
export const keepFocusOnPress = {
  onPointerDown: (e: { preventDefault: () => void }) => e.preventDefault(),
  onMouseDown: (e: { preventDefault: () => void }) => e.preventDefault(),
};
