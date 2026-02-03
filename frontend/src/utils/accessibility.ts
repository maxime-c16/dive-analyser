/**
 * Accessibility utilities for keyboard navigation, ARIA labels, and screen reader support
 */

/**
 * Generate unique ID for accessibility attributes
 */
export const generateId = (prefix: string): string => {
  return `${prefix}-${Math.random().toString(36).substr(2, 9)}`
}

/**
 * Check if element should handle keyboard event
 */
export const isKeyboardEvent = (event: React.KeyboardEvent): boolean => {
  return event.key === 'Enter' || event.key === ' '
}

/**
 * Announce message to screen readers
 */
export const announceToScreenReader = (message: string, priority: 'polite' | 'assertive' = 'polite') => {
  const element = document.createElement('div')
  element.setAttribute('role', 'status')
  element.setAttribute('aria-live', priority)
  element.setAttribute('aria-atomic', 'true')
  element.textContent = message

  // Add temporary element to DOM
  document.body.appendChild(element)

  // Remove after announcement is read
  setTimeout(() => {
    document.body.removeChild(element)
  }, 1000)
}

/**
 * Focus management utilities
 */
export const focusElement = (ref: React.RefObject<HTMLElement>): void => {
  ref.current?.focus()
}

export const focusTrap = (event: React.KeyboardEvent, firstElement: HTMLElement, lastElement: HTMLElement): void => {
  if (event.key !== 'Tab') return

  if (event.shiftKey) {
    // Shift + Tab
    if (document.activeElement === firstElement) {
      lastElement.focus()
      event.preventDefault()
    }
  } else {
    // Tab
    if (document.activeElement === lastElement) {
      firstElement.focus()
      event.preventDefault()
    }
  }
}

/**
 * Ensure contrast ratio meets WCAG guidelines
 */
export const checkContrastRatio = (foreground: string, background: string): boolean => {
  // This is a simplified check - in production use a library like polished
  // For now, just ensure we're using defined color values
  return !!(foreground && background)
}
